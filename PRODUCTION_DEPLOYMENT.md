# Production Deployment

This document covers running CRED-HUUNT v2 at scale beyond the developer-workflow `docs_v2/RUNBOOK.md`. Topics: topology, model serving, throughput sizing, observability, failure modes, capacity planning, and rollout strategy.

Pair this with [SECURITY.md](SECURITY.md), [THREAT_MODEL.md](THREAT_MODEL.md), and [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md).

## Architecture

### Reference topology

```
   ┌──────────────────────────────────────────────────┐
   │ Orchestration layer (your CI / scheduler)        │
   │  • partitions input batches                      │
   │  • applies tenant routing                        │
   │  • applies retention + deletion                  │
   └────────────────┬─────────────────────────────────┘
                    │ detection JSON batches
                    ▼
   ┌──────────────────────────────────────────────────┐
   │ CRED-HUUNT worker pool                           │
   │  • src/main.py invoked per batch                 │
   │  • or scripts/benchmark_models.py for offline    │
   │  • horizontally scalable                         │
   └────────────────┬─────────────────────────────────┘
                    │ Ollama /api/generate
                    ▼
   ┌──────────────────────────────────────────────────┐
   │ Ollama model server (GPU)                        │
   │  • pinned model digests (not tags)               │
   │  • mounted from internal registry                │
   │  • dedicated network namespace                   │
   └──────────────────────────────────────────────────┘
                    │
                    ▼
   ┌──────────────────────────────────────────────────┐
   │ Output sink                                      │
   │  • C3-classified storage (see DATA_GOVERNANCE)   │
   │  • metrics emitter (Prometheus, OTLP)            │
   │  • audit log (append-only)                       │
   └──────────────────────────────────────────────────┘
```

### Component placement

| Component | Where it runs | Critical settings |
|---|---|---|
| Worker (`src/main.py`) | CPU-only is fine for the orchestration; LoRA inference needs GPU | Set `OMP_NUM_THREADS` to match CPU allocation |
| Ollama | Dedicated GPU node; one process per GPU | `OLLAMA_HOST=127.0.0.1:11434`, `OLLAMA_NUM_PARALLEL` matched to model + VRAM |
| LoRA-tuned student (optional) | Same GPU node as base; loaded via `peft.PeftModel.from_pretrained` | Pin adapter version in deployment manifest |
| Orchestrator | Existing CI/CD or workflow engine (Airflow, Argo, Temporal) | Owns retention, tenancy, retries |

## Model Serving

### Pull and pin

Production must pin by **digest**, not tag. Tags float; an attacker who controls the registry can republish a malicious model under the same tag (see [THREAT_MODEL.md §T-2](THREAT_MODEL.md)).

```bash
# Pull once, capture the digest
ollama pull qwen2.5-coder:3b
ollama show qwen2.5-coder:3b --modelfile | grep -i digest

# Reference by digest in your deployment manifest
# e.g., qwen2.5-coder@sha256:<digest>
```

Mirror to an internal registry. The Ollama server in production should not be reachable to the public Ollama Hub.

### Model warmup

First call to a freshly-loaded model can take 5–15 seconds while weights move into VRAM. Warm at startup:

```bash
curl -s http://localhost:11434/api/generate -d '{
  "model": "qwen2.5-coder:3b",
  "prompt": "warmup",
  "stream": false,
  "options": {"num_predict": 1}
}' > /dev/null
```

Run this for every model the worker is configured to use. Block the worker from accepting traffic until warmup succeeds.

### Memory sizing

Approximate VRAM needs (FP16, no LoRA):

| Model | Approx. VRAM | Notes |
|---|---|---|
| `qwen2.5-coder:3b` | ~6 GB | Comfortable on consumer 8 GB GPUs |
| `granite3.3:2b` | ~5 GB | Comfortable on consumer 8 GB GPUs |
| `llama3.2:3b` | ~7 GB | Borderline on 8 GB; comfortable on 12 GB |
| LoRA adapter | +~200 MB | Negligible incremental cost |

For a single-GPU node serving all three: target 16 GB VRAM minimum, 24 GB recommended.

For high-throughput deployments: one model per node, scale node count to match the strategy mix.

## Throughput Sizing

Per-record latency (from benchmark observations on RTX 4090, reference numbers):

| Strategy | Median latency | p95 latency | LLM calls per record |
|---|---|---|---|
| `direct_json` | ~0.3 s | ~0.6 s | 1 |
| `few_shot` | ~0.3 s | ~0.6 s | 1 |
| `self_consistency` (no escalation) | ~0.3 s | ~0.6 s | 1 |
| `self_consistency` (escalated) | ~1.5 s | ~3.0 s | 5 |
| `cot_distilled` | ~0.4 s | ~0.7 s | 1 |
| `react_triage` (iterative, terminates at step 1) | ~0.4 s | ~0.8 s | 1 |
| `react_triage` (full 3-step loop) | ~1.2 s | ~2.5 s | up to 3 |

Numbers above are illustrative; actual values depend on model, prompt length, and hardware. Always benchmark on the target hardware before sizing.

**Capacity planning rule of thumb:** for a single Ollama instance with one 3B model on a single GPU, expect ~3–5 inferences/sec sustained. To scan 1M detections/day with `direct_json`: ~12 inferences/sec sustained → 3–4 GPU instances.

### Batch vs streaming

The current pipeline is batch-oriented. `src/main.py` reads the full detection JSON at once. For streaming use:

- Wrap the per-record call (`classifier.classify`) in a queue consumer.
- Apply a per-worker concurrency limit matching `OLLAMA_NUM_PARALLEL`.
- Honor backpressure when Ollama returns 429-equivalent errors (the current LLM client treats all errors as `REVIEW` fallback — adjust if you need explicit backpressure).

## Observability

### Metrics to emit

Per inference (worker-side):

- `cred_huunt_inference_latency_ms{model,strategy}` — histogram
- `cred_huunt_inference_total{model,strategy,status,is_credentials}` — counter
- `cred_huunt_json_invalid_total{model,strategy}` — counter (the model failed to return parseable JSON)
- `cred_huunt_schema_invalid_total{model,strategy}` — counter (parseable JSON but missing required fields)
- `cred_huunt_escalation_total{model}` — counter (self_consistency escalations)
- `cred_huunt_react_steps{model}` — histogram (iterations before terminal answer)
- `cred_huunt_react_fallback_total{model}` — counter (ReAct loop derailed → forced direct_json fallback)

Per Ollama node:

- GPU utilization
- VRAM headroom
- Queue depth (Ollama exposes this via its own metrics)

Per batch:

- Batch size and duration
- Output report write success
- Storage class compliance (was the output written to a C3-classified path?)

### Logs

- **Worker logs:** structured JSON. Include `record_id`, `model`, `strategy`, decision, latency. **Never** include `matched_value` or full `context`.
- **Ollama logs:** retain locally per data-residency rules; do not forward to a central aggregator without operator review.
- **Audit log:** append-only, signed. Captures the provenance bundle from [DATA_GOVERNANCE.md §Audit Trail](DATA_GOVERNANCE.md).

### Tracing

OpenTelemetry traces should span: orchestrator → worker → Ollama → output sink. Use the existing record_id as the trace's primary correlation key.

## Failure Modes

| Mode | Symptom | Mitigation |
|---|---|---|
| Ollama crash / OOM | Worker sees connection refused, falls back to `REVIEW` | Liveness probe restarts Ollama; orchestrator marks batch for retry |
| Model returns invalid JSON | `json_validity_rate` drops; `_fake_response`-style fallback path is **not** triggered (test_mode only); real path returns `REVIEW` with `confidence=0.5` | Alert on json_validity_rate < 0.95 sustained; consider switching default strategy |
| Iterative ReAct doesn't terminate | `react_fallback_total` increments; `agent_trace.terminated == "fallback_direct_json"` | Alert on fallback rate > 10%; investigate prompt drift or model regression |
| LoRA adapter loaded against wrong base model | High `json_invalid_total`, low F1 | Pin both base model and adapter version together; reject startup if mismatched |
| Context-leakage hits a real-world dataset | Train/val/test groups overlap; metrics look better than reality | Re-run `_assert_no_group_leakage` in `process_synthetic_training_data.py`; treat any leak as a release-blocking defect |
| Tenant data crosses partition | A C3 output appears in another tenant's storage | Orchestrator bug; preserve C3 contents, audit, page on-call |

## Capacity and Reliability Targets

Recommended SLOs for an internal deployment scanning developer commits:

| SLO | Target | Notes |
|---|---|---|
| Inference availability | 99.5% monthly | Per worker pool, not per Ollama node |
| Median latency | < 600 ms | For `few_shot` strategy |
| p95 latency | < 1.5 s | For `few_shot` strategy |
| JSON validity | ≥ 0.99 | If below, fall back to direct_json |
| Schema validity | ≥ 0.98 | Stricter than JSON validity |
| Hard-negative recall | ≥ 0.85 | Drives FP rate; gate releases on this |
| Binary recall (REAL class) | ≥ 0.93 | Drives miss rate; **never relax this without sign-off** |

Latency SLOs do **not** apply to forensic / `react_triage` strategies, which are explicitly slower and intended for offline analyst workflows.

## Rollout Strategy

### Promoting a new model version

1. Pull the candidate, capture digest.
2. Run `scripts/test_trained_model.py` smoke test (deterministic 7-case set) — must pass at 100%.
3. Run benchmark on test split with the current production strategy mix. Compare against the previous-version summary.
4. Hold the candidate at canary for **at least 24 hours** scanning ≥ 1% of live traffic.
5. Compare canary vs production metrics: binary F1, hard_negative_recall, json_validity_rate, p95 latency. Block if any metric regresses > 2 percentage points.
6. Roll out incrementally: 1% → 10% → 50% → 100% with a 4-hour soak between steps.
7. Keep the previous model warm for 7 days to enable rollback.

### Promoting a new prompt version

`src/prompt_builder.SYSTEM_PROMPT` and `FEW_SHOTS` are the contract. Any change is a versioned change.

1. Add a `prompt_version` constant alongside the prompt.
2. Run the full benchmark matrix with the new prompt against the existing models.
3. Apply the same canary + soak protocol as above.
4. Record the prompt_version in the provenance bundle.

### Promoting a new strategy

A new strategy in `scripts/reasoning_runner.py`:

1. Add the strategy with documentation in [`docs_v2/REASONING_STRATEGIES.md`](docs_v2/REASONING_STRATEGIES.md).
2. Benchmark all 3 primary models with the new strategy alongside the current 5.
3. Update [`docs_v2/BENCHMARK_DESIGN.md`](docs_v2/BENCHMARK_DESIGN.md) matrix table.
4. Pin escalation behavior, max-steps, temperature defaults in the deployment manifest.

## Disaster Recovery

| Failure | Recovery |
|---|---|
| Model artifact corruption | Restore from internal registry; verify SHA-256 digest |
| Dataset corruption | Re-run `scripts/process_synthetic_training_data.py` from versioned `data/*.crdownload` |
| LoRA adapter loss | Re-train from `data/training_data_binary.jsonl` (or rationale-augmented variant) — preserve the training command in the model card |
| C3 output loss | Per organizational secret-incident policy; the codebase has no recovery path |

## Cost Considerations

The system is designed to be self-hosted on commodity GPUs. Approximate operating cost (illustrative):

- 1 × consumer GPU (8–12 GB VRAM): suitable for one 3B model, ~3–5 inferences/sec.
- 1 × workstation GPU (24 GB VRAM): can host all three models or a 7B model with adapter; ~10 inferences/sec across models.
- Datacenter GPUs (A10, L4, A100): substantially higher throughput; only worth it for scan-on-every-commit at large organizations.

A LoRA-tuned 3B student on a workstation GPU can typically meet the F1 / latency targets above without datacenter hardware. See [ROADMAP.md](ROADMAP.md) for the cost/quality bet.
