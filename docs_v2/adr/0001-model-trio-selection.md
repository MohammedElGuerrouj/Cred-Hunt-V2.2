# ADR-0001: Family-Diverse Primary Model Trio

## Status

Accepted. May 2026.

## Context

CRED-HUUNT v2 benchmarks small language models on credential triage. The earlier trio — `qwen2.5:1.5b`, `qwen2.5-coder:3b`, `granite3.3:2b` — paired two same-family Qwen variants (general 1.5b + coder 3b) with a single cross-family challenger (granite 2b). This design measured intra-family scaling (1.5b vs 3b inside Qwen2.5) but not architectural lessons across families.

The May 2026 literature review found:

- No published benchmark of models ≤7B on secret detection — including arXiv 2504.18784 (the closest analog, which evaluates 7-8B models on `SecretBench`). The 2-3B class is unmapped territory.
- Industry rankings (BentoML, PromptQuorum, InsiderLLM) consistently rate `qwen2.5-coder` and the Llama-3.2 family near the top in the small-model code-understanding tier, with Granite as a viable third option for instruction-following / JSON discipline.
- IBM Granite-3.3 documentation explicitly markets the model for classification, extraction, and "controllable thinking" — properties relevant to our JSON-contract output.

We need a trio that:

1. Holds parameter count roughly constant (2–3B) so size is not a confound.
2. Spans three different training families so architecture and training-recipe variance is visible in results.
3. Each model is justifiable on its own merits, not present as filler.

## Decision

Adopt the primary trio:

| Model | Family | Rationale |
|---|---|---|
| `qwen2.5-coder:3b` | Alibaba Qwen2.5-Coder | Code/config specialist; widely-cited strongest small code model |
| `granite3.3:2b` | IBM Granite 3.3 | Designed for classification and instruction-following; JSON discipline |
| `llama3.2:3b` | Meta Llama 3.2 | General-purpose challenger; different family from the above two; tests whether code-tuning is paying off |

Retire `qwen2.5:1.5b` from the primary tier. It remains available via `--models qwen2.5:1.5b` for ablation but is no longer a default.

## Consequences

### Positive

- The benchmark matrix now answers "which *family* of small model is best for credential triage?" rather than only "does code-tuning beat the smaller-same-family general model?"
- Llama 3.2 brings a different training pipeline (post-trained for instruction-following on Meta's data) to the comparison.
- We can publish results in three directions: code-tuned, agentic-tuned, general-tuned.

### Negative

- Three different families means three different prompt sensitivities. Some prompting strategies that work well for Qwen may degrade Granite or Llama.
- We lose the apples-to-apples 1.5b vs 3b same-family comparison.
- VRAM headroom needs to fit the largest of the three (Llama 3.2 3b ≈ 7 GB FP16) on the benchmark host.

### Neutral / open

- The literature does not predict a winner. The benchmark will decide.
- The Llama 3.2 Community License is not Apache 2.0; downstream redistribution requires acknowledgement. Operators must review licensing for their use case.

## Implementation

- Defaults updated in `scripts/benchmark_models.py`, `scripts/test_trained_model.py`, `scripts/lora_fine_tune.py`, `src/llm_client.py`, `scripts/evaluate_model_performance.py` (`--base-model` → `Qwen/Qwen2.5-Coder-3B`).
- Documentation swept in `docs_v2/MODEL_SELECTION.md`, `docs_v2/BENCHMARK_DESIGN.md`, `docs_v2/RUNBOOK.md`, `docs_v2/IMPLEMENTATION_ROADMAP.md`, `docs_v2/TRAINING_PIPELINE.md`, `docs_v2/README.md`, `CLAUDE.md`.

## Reversal criteria

This decision should be revisited if the benchmark shows any of:

- `granite3.3:2b` is strictly dominated (no metric strictly better than the other two) — swap for `phi-3.5-mini` or `qwen3:4b`.
- `llama3.2:3b` is strictly dominated — swap for `gemma2:2b`.
- The 2-3B size class is uniformly below the F1 / hard_negative_recall gates — promote a 7-8B model to the primary tier and demote the trio to "small-model ablation".

## References

- [`docs_v2/MODEL_SELECTION.md`](../MODEL_SELECTION.md)
- arXiv 2504.18784 — Secret Breach Detection in Source Code with LLMs
- Qwen2.5-Coder Technical Report (arXiv 2409.12186)
