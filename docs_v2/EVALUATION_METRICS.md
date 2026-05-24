# Evaluation Metrics

CRED-HUUNT v2 must evaluate more than classification accuracy. The system is agentic, so the benchmark must track labels, JSON validity, explanation quality, latency, and evidence grounding.

## Core Binary Metrics

The main production target is:

```text
is_credentials: 0|1
```

Required metrics:

| Metric | Meaning |
|---|---|
| precision | Of predicted credentials, how many were real |
| recall | Of real credentials, how many were found |
| F1 | Harmonic mean of precision and recall |
| false-positive rate | FP predictions among true negatives |
| false-negative rate | missed real credentials |
| balanced accuracy | handles class imbalance |

Primary gate:

```text
binary_f1 >= 0.93
```

## Multiclass Metrics

Keep `status` because analysts need richer triage.

Labels:

```text
REAL
FALSE_POSITIVE
REVIEW
```

Report:

- multiclass accuracy
- macro F1
- per-class precision/recall/F1
- confusion matrix
- REVIEW rate

## Hard-Negative Metrics

Hard negatives are the most important false-positive slice.

Report binary recall for:

```text
distractor_type = hard_negative
distractor_type = high_entropy_non_secret
distractor_type = context_token
```

Target:

```text
hard_negative_recall >= 0.85 for is_credentials = 0
```

Interpretation: the model should reject real-looking values in non-credential contexts.

## JSON Validity

The pipeline depends on parseable output.

Track:

| Metric | Meaning |
|---|---|
| `json_validity_rate` | percentage of responses that parse as JSON |
| `schema_validity_rate` | percentage containing required fields |
| `repair_rate` | percentage requiring JSON repair |
| `fallback_review_rate` | percentage forced to REVIEW due to parse failure |

Target:

```text
json_validity_rate >= 0.99
schema_validity_rate >= 0.98
```

## Evidence Grounding

Agentic AI output must explain decisions with evidence grounded in input context.

Simple score from 0 to 1:

```text
1.0 = every evidence item maps to context/value/path/features
0.5 = mixed grounded and generic evidence
0.0 = ungrounded or hallucinated evidence
```

Automated checks:

- evidence mentions key names found in context
- evidence mentions file/path class found in record
- evidence mentions entropy/length only if computed
- evidence does not invent tools that were not called
- evidence does not cite unavailable files or lines

Target:

```text
evidence_grounding_score >= 0.90
```

## Reasoning Quality

Reasoning should be short, useful, and consistent with the label.

Score dimensions:

| Dimension | Check |
|---|---|
| consistency | reasoning agrees with `is_credentials` and `status` |
| specificity | cites context-specific signals |
| brevity | concise enough for analyst review |
| non-hallucination | does not invent evidence |
| actionability | helps decide whether to rotate/review/ignore |

Do not require raw chain-of-thought for production scoring.

## Latency Metrics

Track:

```text
latency_ms_per_detection
p50_latency_ms
p95_latency_ms
p99_latency_ms
tokens_prompt
tokens_completion
model_load_time_if_measured
```

Reasoning strategy cost multiplier:

```text
cost_multiplier = avg_latency(strategy) / avg_latency(direct_json)
```

Self-consistency should show its cost clearly because it runs multiple samples.

## Agent Tool Metrics

For `react_triage` and later ToT/GoT modes:

- tool calls per detection
- tool error rate
- average tool latency
- percentage of decisions changed after tools
- percentage of REVIEW cases resolved by tools

## Dataset Slice Metrics

Report metrics by:

```text
status
is_credentials
distractor_type
source_file
pattern_name
file_path_class
entropy_bucket
length_bucket
has_username_nearby
has_host_nearby
```

Recommended entropy buckets:

```text
<2.0
2.0-3.0
3.0-4.0
>=4.0
```

## Benchmark Summary Table

Each model-strategy pair should produce:

| Field | Type |
|---|---|
| `model` | string |
| `strategy` | string |
| `n` | int |
| `binary_precision` | float |
| `binary_recall` | float |
| `binary_f1` | float |
| `macro_f1` | float |
| `hard_negative_recall` | float |
| `json_validity_rate` | float |
| `schema_validity_rate` | float |
| `evidence_grounding_score` | float |
| `avg_latency_ms` | float |
| `p95_latency_ms` | float |
| `review_rate` | float |

## Pass/Fail Gates

Minimum before promoting a model/strategy:

```text
binary_f1 >= 0.93
json_validity_rate >= 0.99
hard_negative_recall >= 0.85
evidence_grounding_score >= 0.90
p95_latency_ms within production budget
```

If no model passes all gates, pick the best F1/latency tradeoff and route low-confidence cases to analyst review.
