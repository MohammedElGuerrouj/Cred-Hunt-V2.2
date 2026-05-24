# Training Pipeline

The v2 training pipeline converts read-only source datasets into a merged augmented JSONL corpus, then trains or benchmarks models against the same prompt contract used at inference.

## Current Pipeline

Current script:

```text
scripts/process_synthetic_training_data.py
```

Current outputs:

```text
data/synthetic_training_dataset.json
data/training_data.jsonl
data/val_data.jsonl
data/test_data.jsonl
data/training_data.csv
data/instruction_tuning_dataset.json
```

Current training script:

```text
scripts/lora_fine_tune.py
```

Current evaluator:

```text
scripts/evaluate_model_performance.py
```

## v2 Pipeline

```text
true_positive.crdownload + false_positive.crdownload
-> parse + normalize
-> augment false positives
-> merge into data/merged_dataset.jsonl
-> group-aware split
-> build prompt/completion JSONL
-> train LoRA or run Ollama benchmark
-> evaluate binary + multiclass + evidence metrics
```

## Step 1: Parse And Merge

Command:

```bash
python scripts/process_synthetic_training_data.py --target both --augment-fp 3
```

Expected new artifacts:

```text
data/merged_dataset.jsonl
data/training_data_binary.jsonl
data/val_data_binary.jsonl
data/test_data_binary.jsonl
data/training_data_augmented.csv
data/augmentation_report.json
```

The `--target` and `--augment-fp` flags are implemented in the v2 processor.

## Step 2: Prompt Contract

Training and inference must use the same prompt shape from [../src/prompt_builder.py](../src/prompt_builder.py).

Target completion shape:

```json
{
  "is_credentials": 1,
  "status": "REAL",
  "confidence": 0.98,
  "reasoning": "Pre-classified as real credential from source dataset.",
  "evidence": ["source:true_positive", "password-like assignment"]
}
```

Training formatter:

```python
def format_training_text_binary(detection: dict, label: dict) -> dict:
    ...
```

Keep the existing `format_training_text` for backward compatibility.

## Step 3: LoRA Fine-Tuning

Primary LoRA target:

```bash
python scripts/lora_fine_tune.py \
  --model qwen2.5-coder:3b \
  --epochs 3 \
  --batch-size 4 \
  --learning-rate 5e-4 \
  --gpu \
  --target both
```

The default [../scripts/lora_fine_tune.py](../scripts/lora_fine_tune.py) v2 inputs are:

```text
data/training_data_binary.jsonl
data/val_data_binary.jsonl
```

The script also accepts explicit split and target flags:

```text
--train data/training_data_binary.jsonl
--val data/val_data_binary.jsonl
--target binary|multiclass|both
```

## Step 4: Ollama Model Creation

After LoRA training:

```bash
ollama create credentials-detector-lora -f Modelfile.credentials-detector
```

The Modelfile system prompt should require:

```json
{
  "is_credentials": 0,
  "status": "FALSE_POSITIVE",
  "confidence": 0.0,
  "reasoning": "brief analyst-facing reason",
  "evidence": ["grounded", "signals"],
  "agent_trace": {
    "strategy": "direct_json"
  }
}
```

## Step 5: Evaluation

Base model evaluation:

```bash
python scripts/evaluate_model_performance.py \
  --base-model Qwen/Qwen2.5-1.5B \
  --test data/test_data_binary.jsonl \
  --no-adapter \
  --report data/evaluation_base_qwen15.json
```

LoRA evaluation:

```bash
python scripts/evaluate_model_performance.py \
  --base-model Qwen/Qwen2.5-1.5B \
  --adapter ./lora-credentials-detector \
  --test data/test_data_binary.jsonl \
  --report data/evaluation_lora_qwen15.json
```

v2 evaluator additions:

- parse `is_credentials`
- binary precision, recall, F1
- multiclass confusion matrix
- JSON validity rate
- latency per sample
- metrics by `distractor_type`
- hard-negative recall
- evidence grounding score

## Step 6: Benchmark Multiple Ollama Models

Command:

```bash
python scripts/benchmark_models.py \
  --models qwen2.5-coder:3b granite3.3:2b llama3.2:3b \
  --strategies direct_json few_shot self_consistency \
  --test data/test_data_binary.jsonl \
  --output results/benchmark_matrix.jsonl
```

The benchmark script is implemented and supports `--test-mode` for smoke validation without Ollama.

## Training Success Gates

| Gate | Target |
|---|---:|
| JSON validity | >= 99% |
| Binary F1 | >= 0.93 |
| REAL recall | >= 0.93 |
| FALSE_POSITIVE precision | >= 0.93 |
| Hard-negative recall | >= 0.85 |
| Context leakage | 0 shared `source_context_hash` across splits |

## Troubleshooting

| Issue | Action |
|---|---|
| GPU out of memory | reduce `--batch-size` or use gradient accumulation |
| Low REAL recall | reduce FP dominance or add class weights |
| Too many false positives | increase hard negatives and context-token distractors |
| JSON parse failures | lower temperature, stricter system prompt, shorter completion schema |
| Overfitting | check group-aware split and reduce epochs |
| Slow inference | use direct/few-shot only; reserve self-consistency for borderline cases |
