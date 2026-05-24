# CRED-HUUNT v2

CRED-HUUNT v2 is an agentic AI credential triage and benchmarking project. It builds a merged credential dataset, augments false positives, trains/evaluates a binary `is_credentials` model contract, and benchmarks local models across reasoning strategies.

Start here:

- [docs_v2/README.md](docs_v2/README.md) for the documentation map.
- [docs_v2/RUNBOOK.md](docs_v2/RUNBOOK.md) for runnable commands.
- [docs_v2/TRAINING_PIPELINE.md](docs_v2/TRAINING_PIPELINE.md) for data processing and LoRA training.
- [notebooks/kaggle_train_eval_pipeline.ipynb](notebooks/kaggle_train_eval_pipeline.ipynb) to train and evaluate LoRA adapters on Kaggle.

Minimal project layout:

```text
docs_v2/       v2 architecture, training, benchmark, and runbook docs
src/           runtime classifier and schema code
scripts/       dataset, training, evaluation, and benchmark scripts
data/          tracked source datasets plus ignored generated artifacts
notebooks/     Kaggle training/evaluation notebooks
```

The source `.crdownload` files are tracked. Generated JSONL/CSV datasets, benchmark outputs, local model weights, and Kaggle packaging files are intentionally ignored. Regenerate artifacts with:

```powershell
python scripts/process_synthetic_training_data.py --target both --augment-fp 3
```