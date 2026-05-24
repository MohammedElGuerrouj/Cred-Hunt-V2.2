# Implementation Roadmap

This roadmap turns the docs_v2 design into code changes. It is ordered so each phase produces a verifiable artifact.

## Phase 0: Baseline Audit

Goal: confirm current behavior before v2 changes.

Tasks:

1. Run current data processor.
2. Run current evaluator on existing test split.
3. Record baseline metrics for `qwen2.5-coder:3b` and existing `credentials-detector` if available.
4. Note current JSON validity and latency.

Commands:

```bash
python scripts/process_synthetic_training_data.py
python scripts/evaluate_model_performance.py --no-adapter --report data/evaluation_baseline.json
```

Deliverable:

```text
data/evaluation_baseline.json
```

## Phase 1: Dataset Schema And Merge

Goal: create one unified source-of-truth dataset.

Add:

```text
src/dataset_schema.py
```

Update:

```text
scripts/process_synthetic_training_data.py
```

Outputs:

```text
data/merged_dataset.jsonl
data/training_data_binary.jsonl
data/val_data_binary.jsonl
data/test_data_binary.jsonl
```

Acceptance checks:

- every record has `is_credentials`
- source records include `source_file` and `source_index`
- TP and FP are shuffled into one merged corpus
- group-aware split has no context leakage

## Phase 2: False-Positive Augmentation

Goal: make the model context-aware.

Add:

```text
scripts/augment_false_positives.py
```

Generators:

```text
none_literal
placeholder
context_token
dictionary_word
high_entropy_non_secret
hard_negative
```

Outputs:

```text
data/augmentation_report.json
data/training_data_augmented.csv
```

Acceptance checks:

- 3 augmented variants per FP context where possible
- hard negatives remain `is_credentials: 0`
- counts by distractor type are reported
- manual sample confirms correct labels

## Phase 3: Prompt And Agent Output Contract

Goal: make model output parseable and agentic.

Update:

```text
src/prompt_builder.py
src/llm_client.py
src/classifier.py
src/aggregator.py
```

Changes:

- add `is_credentials` to output schema
- add `evidence`
- add `agent_trace`
- keep short `reasoning`
- add safe fallback for missing fields

Acceptance checks:

- current tests still return valid JSON
- `is_credentials` is consistent with `status`
- aggregator includes binary counts

## Phase 4: LoRA Training Update

Goal: train on the binary + status completion contract.

Update:

```text
scripts/lora_fine_tune.py
```

Add flags:

```text
--target binary|multiclass|both
--train data/training_data_binary.jsonl
--val data/val_data_binary.jsonl
```

Acceptance checks:

- training runs with existing Qwen2.5-1.5B path
- adapter is saved
- validation loss is logged
- binary metrics can be computed after training

## Phase 5: Evaluation Update

Goal: measure what matters for agentic credential triage.

Update:

```text
scripts/evaluate_model_performance.py
```

Add metrics:

```text
binary precision/recall/F1
JSON validity
schema validity
hard-negative recall
latency
distractor-type slices
evidence grounding score
```

Acceptance checks:

- report includes binary and multiclass sections
- report can evaluate base model and LoRA adapter
- invalid JSON is counted explicitly

## Phase 6: Benchmark Runner

Goal: compare SLMs and reasoning strategies.

Add:

```text
scripts/benchmark_models.py
scripts/reasoning_runner.py
```

First benchmark:

```text
models: qwen2.5-coder:3b, granite3.3:2b, llama3.2:3b
strategies: direct_json, few_shot, self_consistency
```

Full benchmark:

```text
models: primary 3
strategies: direct_json, few_shot, self_consistency, cot_distilled, react_triage
```

Acceptance checks:

- one JSONL row per record/model/strategy
- summary JSON is generated
- latency and JSON validity are tracked

## Phase 7: Agentic Tools

Goal: support ReAct-style forensic triage.

Add:

```text
scripts/react_tools.py
scripts/react_agent.py
```

Initial tools:

```text
entropy_check
placeholder_check
context_signal_check
file_path_check
duplicate_secret_check
fixture_check
git_blame_check
```

Acceptance checks:

- tools are read-only
- tool calls are recorded in `agent_trace`
- tool errors do not crash classification

## Phase 8: Rationale Distillation

Goal: improve small models without exposing raw chain-of-thought in production.

Add:

```text
scripts/distill_rationales.py
```

Outputs:

```text
data/merged_dataset_with_rationales.jsonl
data/training_data_rationale_distilled.jsonl
```

Acceptance checks:

- rationales are short and grounded
- student model improves hard-negative recall or REVIEW handling
- production output remains short reasoning + evidence

## Phase 9: Repo-Scale ToT/GoT

Goal: investigate cross-file and multi-hypothesis findings.

Add later:

```text
scripts/tot_investigator.py
scripts/got_aggregator.py
```

Use for:

- repeated secret clusters
- high-risk findings
- unresolved REVIEW cases
- repo-scale context correlation

Acceptance checks:

- not used in first-pass high-volume scanning
- output feeds analyst review queues
- graph/branch traces are stored separately from simple classification output

## Priority Order

Recommended build order:

1. Phase 1 dataset schema and merge
2. Phase 2 augmentation
3. Phase 3 output contract
4. Phase 5 evaluation metrics
5. Phase 6 benchmark runner for direct/few-shot/self-consistency
6. Phase 4 LoRA training update
7. Phase 7 ReAct tools
8. Phase 8 rationale distillation
9. Phase 9 ToT/GoT

Evaluation can be updated before LoRA because it is needed to compare all models fairly.

## Definition Of Done For v2 MVP

The v2 MVP is done when:

- `data/merged_dataset.jsonl` exists and includes TP + FP + augmented FP.
- `is_credentials` is present throughout training and evaluation.
- Group-aware split prevents context leakage.
- Three models are benchmarked across at least three strategies.
- Reports include binary F1, JSON validity, latency, and hard-negative recall.
- Agent output includes short reasoning, evidence, and agent_trace.
- The best model/strategy is selected with a documented tradeoff.
