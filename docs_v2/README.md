# CRED-HUUNT docs_v2

CRED-HUUNT v2 is an agentic AI credential triage and benchmarking system. The project is moving from a single credential classifier toward an agent that reads context, extracts evidence, applies one or more reasoning strategies, decides whether a value is a credential, and reports an analyst-friendly explanation.

The v2 work keeps the current scanner/classifier pipeline, but adds a stronger dataset contract, binary `is_credentials` target, false-positive augmentation, model benchmarking, and agentic reasoning modes.

## Documentation Map

| File | Purpose |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Current pipeline and v2 target architecture |
| [AGENTIC_AI_DESIGN.md](AGENTIC_AI_DESIGN.md) | Agent loop, output contract, trace/evidence design |
| [DATASET_FORMAT.md](DATASET_FORMAT.md) | Dataset formats and unified JSONL schema |
| [DATA_AUGMENTATION.md](DATA_AUGMENTATION.md) | False-positive augmentation and hard-negative generation |
| [AXA_SYNTHETIC_DATASET.md](AXA_SYNTHETIC_DATASET.md) | AXA Group synthetic dataset generator — languages, credential types, carriers |
| [TRAINING_PIPELINE.md](TRAINING_PIPELINE.md) | Data processing, LoRA training, model creation, validation |
| [REASONING_STRATEGIES.md](REASONING_STRATEGIES.md) | Direct, few-shot, self-consistency, distilled CoT, ReAct, ToT/GoT |
| [MODEL_SELECTION.md](MODEL_SELECTION.md) | Small language models selected for benchmarking |
| [BENCHMARK_DESIGN.md](BENCHMARK_DESIGN.md) | 3-model x reasoning-strategy benchmark matrix |
| [EVALUATION_METRICS.md](EVALUATION_METRICS.md) | Accuracy, F1, JSON validity, latency, evidence quality |
| [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) | Phased implementation plan and known gaps |
| [RUNBOOK.md](RUNBOOK.md) | Commands for data prep, training, evaluation, benchmarking |

## Core v2 Decisions

1. Treat CRED-HUUNT as an agentic credential triage system, not only a text classifier.
2. Keep source datasets read-only: `data/true_positive.crdownload` and `data/false_positive.crdownload`.
3. Merge both sources into one shuffled JSONL corpus: `data/merged_dataset.jsonl`.
4. Add binary `is_credentials` while preserving `status`.
5. Expand false positives with 3x augmentation to teach context-aware rejection.
6. Benchmark three primary SLMs (family-diverse, ~2-3B class):
   - `qwen2.5-coder:3b` (Alibaba, code-tuned)
   - `granite3.3:2b` (IBM, agentic/JSON-disciplined)
   - `llama3.2:3b` (Meta, general-purpose challenger)
7. Benchmark five reasoning strategies:
   - `direct_json`
   - `few_shot`
   - `self_consistency`
   - `cot_distilled`
   - `react_triage`
8. Use Tree-of-Thoughts and Graph-of-Thoughts later for repo-scale triage, not the first per-detection classifier.

## Target Agent Output

The agent should return machine-parseable JSON with analyst-facing evidence. Raw hidden/free-form chain-of-thought should not be the production contract.

```json
{
  "is_credentials": 1,
  "status": "REAL",
  "confidence": 0.94,
  "reasoning": "The value is assigned to DB_PASS near a username and host, and it is not a placeholder.",
  "evidence": [
    "password-like key: DB_PASS",
    "near username and host",
    "non-placeholder value",
    "high entropy"
  ],
  "agent_trace": {
    "strategy": "few_shot_self_consistency",
    "checks": ["entropy", "placeholder", "context", "file_path"],
    "tool_calls": []
  }
}
```

## Current Implementation Anchors

| Area | Current file |
|---|---|
| CLI entry point | [../src/main.py](../src/main.py) |
| Classification orchestration | [../src/classifier.py](../src/classifier.py) |
| Ollama client | [../src/llm_client.py](../src/llm_client.py) |
| Prompt construction | [../src/prompt_builder.py](../src/prompt_builder.py) |
| Report aggregation | [../src/aggregator.py](../src/aggregator.py) |
| Dataset processing | [../scripts/process_synthetic_training_data.py](../scripts/process_synthetic_training_data.py) |
| LoRA training | [../scripts/lora_fine_tune.py](../scripts/lora_fine_tune.py) |
| Evaluation | [../scripts/evaluate_model_performance.py](../scripts/evaluate_model_performance.py) |
| Sample model tests | [../scripts/test_trained_model.py](../scripts/test_trained_model.py) |

## Implementation Status

The v2 MVP is implemented in the repository:

- Runtime: v2 prompt contract, Ollama client normalization, classifier output fields, and aggregation summaries.
- Dataset: merged JSONL corpus, false-positive augmentation, binary target, group-aware train/val/test splits, and inspection/report artifacts.
- Benchmarking: model x reasoning-strategy runner, reasoning strategy abstraction, and read-only ReAct-style tools.
- Training/evaluation: LoRA script flags for v2 splits, binary-oriented evaluator, and non-interactive model smoke tests.

Future work remains for rationale distillation and repo-scale Tree-of-Thoughts / Graph-of-Thoughts investigation.
