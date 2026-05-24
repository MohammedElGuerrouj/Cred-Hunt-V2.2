# Benchmark Design

The v2 benchmark compares model choice and reasoning strategy independently.

Primary benchmark:

```text
3 models x 5 reasoning strategies
```

## Primary Models

```text
qwen2.5-coder:3b
granite3.3:2b
llama3.2:3b
```

## Primary Reasoning Strategies

```text
direct_json
few_shot
self_consistency
cot_distilled
react_triage
```

## Benchmark Matrix

| Model | direct_json | few_shot | self_consistency | cot_distilled | react_triage |
|---|---|---|---|---|---|
| `qwen2.5-coder:3b` | yes | yes | yes (gated) | yes | yes (iterative) |
| `granite3.3:2b` | yes | yes | yes (gated) | yes | yes (iterative) |
| `llama3.2:3b` | yes | yes | yes (gated) | yes | yes (iterative) |

Notes:
- `self_consistency` is gated on borderline confidence (0.4–0.6) or `status == REVIEW`. The benchmark reports an `escalation_rate` per cell.
- `cot_distilled` requires the rationale-augmented training split (`scripts/distill_rationales.py`); without it, the cell collapses to a prompt-suffix variant of `direct_json`.
- `react_triage` is the iterative ReAct loop (thought → action → observation → final). The single-shot tool-injection variant is preserved under `tool_assisted` for back-compat.

Recommended first smoke test:

```text
3 models x 3 strategies: direct_json, few_shot, self_consistency
limit: 500 examples
```

Full benchmark:

```text
3 models x 5 strategies
full test split
```

## Extended Model Matrix

Optional models:

```text
phi4-mini:3.8b
deepseek-r1:1.5b
smollm2:1.7b
```

Upper-bound models:

```text
qwen2.5:7b
qwen2.5-coder:7b
granite3.3:8b
```

## Dataset

Use:

```text
data/test_data_binary.jsonl
```

Every benchmark record should include:

```json
{
  "record_id": "...",
  "prompt": "...",
  "status": "FALSE_POSITIVE",
  "is_credentials": 0,
  "distractor_type": "hard_negative",
  "source_context_hash": "sha256:..."
}
```

## Benchmark Output

Line-oriented output:

```text
results/benchmark_matrix.jsonl
```

Each result line:

```json
{
  "run_id": "2026-05-18-qwen-coder-few-shot",
  "record_id": "fp-001-aug-hard-negative",
  "model": "qwen2.5-coder:3b",
  "strategy": "few_shot",
  "expected_is_credentials": 0,
  "predicted_is_credentials": 0,
  "expected_status": "FALSE_POSITIVE",
  "predicted_status": "FALSE_POSITIVE",
  "confidence": 0.88,
  "json_valid": true,
  "latency_ms": 620,
  "tokens_prompt": 420,
  "tokens_completion": 75,
  "distractor_type": "hard_negative",
  "reasoning": "Short explanation.",
  "evidence": ["reset context", "no assignment"],
  "agent_trace": {"strategy": "few_shot"}
}
```

Summary output:

```text
results/benchmark_summary.json
```

Summary shape:

```json
{
  "runs": [
    {
      "model": "qwen2.5-coder:3b",
      "strategy": "few_shot",
      "binary_f1": 0.94,
      "precision": 0.95,
      "recall": 0.93,
      "hard_negative_recall": 0.88,
      "json_validity_rate": 0.995,
      "avg_latency_ms": 640
    }
  ]
}
```

## Benchmark Command

```bash
python scripts/benchmark_models.py \
  --models qwen2.5-coder:3b granite3.3:2b llama3.2:3b \
  --strategies direct_json few_shot self_consistency cot_distilled react_triage \
  --test data/test_data_binary.jsonl \
  --output results/benchmark_matrix.jsonl \
  --summary results/benchmark_summary.json
```

## Fairness Rules

1. Use the same test split for every model and strategy.
2. Use fixed random seed for self-consistency sampling order.
3. Record prompt template version.
4. Record model temperature and options.
5. Keep response parsing identical across models.
6. Count invalid JSON as a benchmark failure.
7. Report latency separately from quality.
8. Report metrics by `distractor_type`, not only aggregate F1.

## Routing Benchmark

Production likely should not use one strategy for every case. Add a routing benchmark after individual strategy benchmarks.

Recommended routing policy:

```text
if direct/few_shot confidence >= 0.85:
    accept
elif 0.4 <= confidence <= 0.6 or status == REVIEW:
    run self_consistency
elif high-risk path or hard-negative signals:
    run react_triage
else:
    analyst review
```

Routing metrics:

- quality vs latency
- percentage of detections escalated
- false-positive reduction
- analyst review volume

## Expected Outcomes

Hypothesis before LoRA:

```text
qwen2.5-coder:3b + few_shot + self_consistency-on-borderline
```

Hypothesis after LoRA:

```text
credentials-detector-lora + direct_json or few_shot
```

## Minimum Viable Benchmark

Implement first:

```text
models: qwen2.5-coder:3b, granite3.3:2b, llama3.2:3b
strategies: direct_json, few_shot, self_consistency
samples: 500
metrics: binary F1, JSON validity, latency, hard-negative recall
```

Then expand to full matrix.
