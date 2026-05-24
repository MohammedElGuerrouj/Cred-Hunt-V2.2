# Architecture

CRED-HUUNT v2 separates credential detection into three layers:

1. Dataset and feature layer.
2. Agentic classification layer.
3. Benchmark and evaluation layer.

The current repository already has a working classification path. The v2 architecture keeps that path and adds stronger data contracts, agent traceability, and benchmark orchestration.

## Current Pipeline

```text
input detections JSON
-> src/main.py
-> src/classifier.py
-> src/prompt_builder.py
-> src/llm_client.py
-> src/aggregator.py
-> output report JSON
```

## Current Components

| Component | File | Responsibility |
|---|---|---|
| CLI runner | [../src/main.py](../src/main.py) | Loads detections, runs batch classification, writes grouped report |
| Classifier | [../src/classifier.py](../src/classifier.py) | Applies entropy pre-filter, builds prompt, normalizes LLM status |
| Prompt builder | [../src/prompt_builder.py](../src/prompt_builder.py) | Defines system prompt, few-shot examples, prompt/completion format |
| LLM client | [../src/llm_client.py](../src/llm_client.py) | Calls Ollama and parses JSON-ish responses safely |
| Aggregator | [../src/aggregator.py](../src/aggregator.py) | Groups results by owner and file |
| Training processor | [../scripts/process_synthetic_training_data.py](../scripts/process_synthetic_training_data.py) | Parses pre-classified synthetic datasets and emits train/val/test JSONL |
| LoRA trainer | [../scripts/lora_fine_tune.py](../scripts/lora_fine_tune.py) | Fine-tunes a causal LM with LoRA adapters |
| Evaluator | [../scripts/evaluate_model_performance.py](../scripts/evaluate_model_performance.py) | Evaluates held-out JSONL split and reports multiclass metrics |

## Target v2 Pipeline

```text
source datasets
-> parse true_positive + false_positive
-> augment false positives
-> merge into one JSONL corpus
-> group-aware train/val/test split
-> build prompt/completion pairs
-> train or run selected model
-> apply selected reasoning strategy
-> emit credential decision + evidence + agent_trace
-> aggregate by owner/file/secret hash
-> benchmark model x reasoning matrix
```

## Target Agentic Flow

```text
Observe
-> read detection, file path, matched value, source, nearby context

Extract
-> entropy, length, placeholder indicators, key names, nearby username/host, path signals

Reason
-> direct_json, few_shot, self_consistency, cot_distilled, react_triage

Act
-> optional read-only checks: entropy, placeholder, git blame, fixture/test path, repeated secret grouping

Decide
-> is_credentials, status, confidence

Explain
-> short reasoning, evidence list, agent_trace metadata

Aggregate
-> owner/file summaries, duplicate secret clusters, review queues
```

## Data Boundaries

| Boundary | Contract |
|---|---|
| Source datasets | Existing `.crdownload` Python-like tuple files remain read-only |
| Unified corpus | `data/merged_dataset.jsonl` is the v2 source of truth after parsing and augmentation |
| Training JSONL | `data/training_data_binary.jsonl`, `data/val_data_binary.jsonl`, `data/test_data_binary.jsonl` contain prompt/completion records |
| Evaluation reports | JSON reports under `data/` or `results/`, never mixed with source datasets |
| Human inspection | CSV files are flat inspection exports only, not training inputs |

## Target Output Contract

Every production model response should parse as JSON and include both binary and analyst-facing fields:

```json
{
  "is_credentials": 0,
  "status": "FALSE_POSITIVE",
  "confidence": 0.91,
  "reasoning": "The value is a password reset URL in documentation, not a secret value.",
  "evidence": ["documentation path", "reset URL", "no assignment to secret variable"],
  "agent_trace": {
    "strategy": "direct_json",
    "checks": ["placeholder", "context", "file_path"],
    "tool_calls": []
  }
}
```

## v2 Modules

| Module | Purpose |
|---|---|
| `src/dataset_schema.py` | Shared schema and `is_credentials` derivation |
| `scripts/augment_false_positives.py` | False-positive augmentation generators |
| `scripts/benchmark_models.py` | Runs model x reasoning benchmark matrix |
| `scripts/reasoning_runner.py` | Strategy abstraction for direct/few-shot/self-consistency/distilled/ReAct |
| `scripts/react_tools.py` | Read-only agent tool registry |
| `scripts/distill_rationales.py` | Future teacher rationale generation for distilled reasoning |
| `scripts/tot_investigator.py` | Future repo-scale Tree-of-Thoughts triage |
| `scripts/got_aggregator.py` | Future cross-file Graph-of-Thoughts aggregation |

## Current Implementation Notes

1. The training processor emits v2 records with `is_credentials`, `status`, prompt/completion JSONL, and augmentation metadata.
2. Train/val/test splitting is group-aware by `source_context_hash` to avoid context leakage.
3. The LLM client accepts a model parameter for benchmark and runtime runs while retaining a default model.
4. Benchmarking is handled by [../scripts/benchmark_models.py](../scripts/benchmark_models.py); legacy batch/demo scanners were removed from the minimal v2 tree.
5. The evaluator reports binary metrics, multiclass metrics, JSON validity, latency, and distractor slices. Evidence-grounding scoring is still a future enhancement.

## Design Principles

- Prefer JSONL for datasets and benchmark results.
- Keep source datasets immutable.
- Keep prompts and training prompts byte-identical where possible.
- Separate decision labels from explanations.
- Expose grounded evidence, not raw free-form hidden reasoning, as the production transparency mechanism.
- Benchmark models and reasoning strategies independently.
