# Runbook

This runbook contains practical commands for the implemented v2 workflow and notes the remaining future-only items separately.

## 1. Prepare Ollama Models

Primary benchmark models:

```bash
ollama pull qwen2.5-coder:3b
ollama pull granite3.3:2b
ollama pull llama3.2:3b
```

Optional extended models:

```bash
ollama pull phi4-mini:3.8b
ollama pull deepseek-r1:1.5b
ollama pull smollm2:1.7b
```

Optional upper-bound models:

```bash
ollama pull qwen2.5:7b
ollama pull qwen2.5-coder:7b
ollama pull granite3.3:8b
```

Start Ollama if needed:

```bash
ollama serve
```

## 2. Data Processing Command

Full v2 dataset build:

```bash
python scripts/process_synthetic_training_data.py --target both --augment-fp 3
```

Expected outputs:

```text
data/merged_dataset.jsonl
data/synthetic_training_dataset.json
data/training_data.jsonl
data/val_data.jsonl
data/test_data.jsonl
data/training_data_binary.jsonl
data/val_data_binary.jsonl
data/test_data_binary.jsonl
data/training_data.csv
data/training_data_augmented.csv
data/instruction_tuning_dataset.json
data/augmentation_report.json
```

### 2a. AXA synthetic dataset workflow

Generate a high-realism AXA Group corpus (10 languages, ~24 credential types,
16 carriers) and build training data from it. See
[AXA_SYNTHETIC_DATASET.md](AXA_SYNTHETIC_DATASET.md) for the design.

```bash
# Generate (deterministic; writes to data/synthetic, never overwrites data/)
python scripts/generate_axa_synthetic.py --out-dir data/synthetic --seed 42

# Build the v2 training corpus from the generated source files
python scripts/process_synthetic_training_data.py --target both --augment-fp 3 \
  --data-dir data/synthetic \
  --source-tp data/synthetic/true_positive.crdownload \
  --source-fp data/synthetic/false_positive.crdownload \
  --source-review data/synthetic/review.crdownload
```

The `--source-tp / --source-fp / --source-review` flags override the hardcoded
`data/*.crdownload` names; `--source-review` adds the `REVIEW` class (omit it
for a strictly binary corpus).

The processor writes its JSONL/CSV artifacts into `--data-dir`, so the training
and benchmark scripts must be pointed at `data/synthetic/` explicitly (they
default to `data/`):

```bash
# Train on the AXA synthetic corpus
python scripts/lora_fine_tune.py --model qwen2.5-coder:3b --gpu --target both \
  --train data/synthetic/training_data_binary.jsonl \
  --val   data/synthetic/val_data_binary.jsonl

# Benchmark / evaluate on its held-out split
python scripts/benchmark_models.py --test data/synthetic/test_data_binary.jsonl \
  --output results/axa_matrix.jsonl --summary results/axa_summary.json
python scripts/evaluate_model_performance.py --base-model Qwen/Qwen2.5-Coder-3B \
  --test data/synthetic/test_data_binary.jsonl --no-adapter \
  --report data/synthetic/evaluation_base.json
```

## 4. Inspect Augmented Data

After v2 processing:

```bash
python -m json.tool data/augmentation_report.json
```

Manual CSV inspection:

```bash
python - <<'PY'
import csv
from collections import Counter
with open('data/training_data_augmented.csv', newline='', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))
print('rows:', len(rows))
print(Counter(r.get('distractor_type') for r in rows))
print(Counter(r.get('status') for r in rows))
PY
```

On Windows PowerShell, if heredoc syntax is inconvenient, use a short script file or inspect the CSV in VS Code.

## 5. LoRA Training Command

Default v2 command:

```bash
python scripts/lora_fine_tune.py \
  --model qwen2.5-coder:3b \
  --epochs 3 \
  --batch-size 4 \
  --learning-rate 5e-4 \
  --gpu \
  --target both \
  --train data/training_data_binary.jsonl \
  --val data/val_data_binary.jsonl
```

## 7. Create Ollama LoRA Model

```bash
ollama create credentials-detector-lora -f Modelfile.credentials-detector
```

Verify:

```bash
ollama list
ollama show credentials-detector-lora
```

## 8. Evaluation Command

Base model only:

```bash
python scripts/evaluate_model_performance.py \
  --base-model Qwen/Qwen2.5-Coder-3B \
  --test data/test_data.jsonl \
  --no-adapter \
  --report data/evaluation_base.json
```

LoRA adapter:

```bash
python scripts/evaluate_model_performance.py \
  --base-model Qwen/Qwen2.5-Coder-3B \
  --adapter ./lora-credentials-detector \
  --test data/test_data.jsonl \
  --report data/evaluation_lora.json
```

## 9. v2 Benchmark Command

```bash
python scripts/benchmark_models.py \
  --models qwen2.5-coder:3b granite3.3:2b llama3.2:3b \
  --strategies direct_json few_shot self_consistency cot_distilled react_triage \
  --test data/test_data_binary.jsonl \
  --output results/benchmark_matrix.jsonl \
  --summary results/benchmark_summary.json
```

Recommended first run:

```bash
python scripts/benchmark_models.py \
  --models qwen2.5-coder:3b granite3.3:2b llama3.2:3b \
  --strategies direct_json few_shot self_consistency \
  --test data/test_data_binary.jsonl \
  --limit 500 \
  --output results/benchmark_smoke.jsonl
```

## 10. Sample Model Test

```bash
python scripts/test_trained_model.py \
  --models qwen2.5-coder:3b granite3.3:2b llama3.2:3b
```

## 11. Success Checklist

Before trusting a benchmark:

- `data/merged_dataset.jsonl` exists.
- Train/val/test are group-aware split by source context.
- No source context hash is shared across splits.
- All records have `is_credentials`.
- All model responses are parsed with JSON validity tracked.
- Benchmark stores model, strategy, prompt version, latency, and raw response.
- Reports include binary F1 and hard-negative recall.

## 12. Recommended First Production Candidate

Start with:

```text
qwen2.5-coder:3b + few_shot
```

Use self-consistency only for borderline cases:

```text
0.4 <= confidence <= 0.6
```

After LoRA is available, compare against:

```text
credentials-detector-lora + direct_json
credentials-detector-lora + few_shot
```
