# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

CRED-HUUNT v2 is an agentic credential triage and benchmarking system. It parses two source synthetic datasets (`.crdownload` Python-literal tuples) into a merged JSONL corpus, augments false positives, trains a binary `is_credentials` LoRA adapter, and benchmarks local Ollama SLMs across reasoning strategies. Authoritative docs live in `docs_v2/` — start with `docs_v2/README.md` (doc map), `docs_v2/RUNBOOK.md` (commands), `docs_v2/ARCHITECTURE.md` (layering).

## Common commands

Install deps:
```powershell
pip install -r requirements.txt
```

Build the v2 merged + augmented dataset (creates `data/merged_dataset.jsonl`, splits, CSVs, augmentation report):
```powershell
python scripts/process_synthetic_training_data.py --target both --augment-fp 3
```

Run the runtime classifier on a detections JSON (Ollama must be serving at `http://localhost:11434`):
```powershell
python src/main.py -i <detections.json> -o data/output_report.json [--model qwen2.5-coder:3b] [--test]
```
`--test` uses the heuristic `_fake_response` in `src/llm_client.py` — no Ollama needed.

Benchmark matrix (model × reasoning strategy):
```powershell
python scripts/benchmark_models.py --models qwen2.5-coder:3b granite3.3:2b llama3.2:3b `
  --strategies direct_json few_shot self_consistency cot_distilled react_triage `
  --test data/test_data_binary.jsonl `
  --output results/benchmark_matrix.jsonl --summary results/benchmark_summary.json
```

LoRA training (GPU recommended, binary target):
```powershell
python scripts/lora_fine_tune.py --model qwen2.5-coder:3b --epochs 3 --batch-size 4 `
  --learning-rate 5e-4 --gpu --target both `
  --train data/training_data_binary.jsonl --val data/val_data_binary.jsonl
```

Evaluate a held-out split (base model or LoRA adapter):
```powershell
python scripts/evaluate_model_performance.py --base-model Qwen/Qwen2.5-Coder-3B `
  --test data/test_data.jsonl --no-adapter --report data/evaluation_base.json
```

Smoke-test models without the benchmark harness:
```powershell
python scripts/test_trained_model.py --models qwen2.5-coder:3b granite3.3:2b llama3.2:3b
```

There is no test suite, linter config, or pre-commit setup in this repo.

## Architecture

Three layers — keep them separate:

1. **Runtime classifier** (`src/`) — turns a detection JSON record into a v2 decision object.
   - `main.py` → `classifier.py` → `prompt_builder.py` + `llm_client.py` → `aggregator.py`.
   - `classifier.classify` short-circuits with a deterministic prefilter when `shannon_entropy(matched_value) < 2.5` (marks as FALSE_POSITIVE with `agent_trace.strategy = "deterministic_prefilter"`). Only then does it call the LLM.
   - `llm_client.normalize_llm_result` is the single normalization point — every code path (real Ollama, test mode, error fallback, benchmark strategies) must funnel responses through it so the v2 contract holds: `{is_credentials, status, confidence, reasoning, evidence, indicators, agent_trace, json_valid}`.
   - The classifier trusts the model's `status` if it's in `{REAL, FALSE_POSITIVE, REVIEW}`; only falls back to confidence-bucketing when the model omitted it. Don't reintroduce confidence-from-status coupling.

2. **Dataset/feature layer** (`src/dataset_schema.py`, `scripts/process_synthetic_training_data.py`, `scripts/augment_false_positives.py`, `scripts/distill_rationales.py`).
   - `dataset_schema.make_record` is the canonical record constructor; `derive_is_credentials` and `normalize_status` are the canonical mappers from status text to labels — prefer them over ad-hoc string compares (note: `aggregator.py` and `benchmark_models.py` still compare `status == "REAL"` directly in places, which is fine for read-only reporting but should not spread).
   - Two entropy implementations exist: `src/classifier.shannon_entropy` runs at inference (the `< 2.5` prefilter), `src/dataset_schema.compute_entropy` runs at dataset build. Keep behavior aligned if you touch either.
   - Splits are **group-aware by `source_context_hash`**: every record sharing a context goes to the same split. Do not split flat — that leaks context across train/val/test.
   - `cot_distilled` training labels: `scripts/distill_rationales.py` emits a JSONL of teacher rationales; `process_synthetic_training_data.py --rationales <path>` splices them into the training labels in place of `_default_reasoning`.
   - Source `.crdownload` files in `data/` are read-only inputs. All generated JSONL / CSV / reports under `data/` and `results/` are gitignored — regenerate, don't commit.

3. **Benchmark/reasoning layer** (`scripts/benchmark_models.py`, `scripts/reasoning_runner.py`, `scripts/react_tools.py`).
   - `reasoning_runner.run_strategy` is the strategy abstraction (`direct_json`, `few_shot`, `self_consistency`, `cot_distilled`, `react_triage`, plus back-compat `tool_assisted`). Add new strategies here, not in the runtime classifier.
   - `self_consistency` is **gated**: it runs a cheap T=0 call first and only escalates to N samples at T=0.3 when `0.4 <= confidence <= 0.6` or `status == REVIEW`. The benchmark records an `escalation_rate` per (model, strategy) cell.
   - `react_triage` is the **iterative ReAct loop** (`_run_react_iterative`): the model emits `{thought, action, args}` or `{thought, final}` JSON; the runner dispatches against `react_tools.TOOL_REGISTRY` and feeds observations back for up to `REACT_MAX_STEPS=3` turns, with a forced `direct_json` fallback if the loop derails. Tools must stay **read-only and deterministic**.
   - Benchmark output is JSONL of per-record rows; the summary aggregates by `(model, strategy)` and reports binary F1, hard-negative recall, JSON/schema validity, evidence grounding score, avg/p95/p99 latency, escalation rate.

## Import & path conventions

- `src/` is **not** a package — modules import each other flat (`from classifier import ...`). Scripts under `scripts/` add `ROOT/src` and `ROOT/scripts` to `sys.path` themselves. New scripts that need shared code should follow the same `sys.path.insert(0, str(ROOT / "src"))` pattern at the top.
- The CLI `python src/main.py ...` works because Python prepends `src/` to `sys.path` when running a file from there. Do not convert these to package imports without also updating the scripts.

## v2 output contract (non-negotiable)

Every model response — runtime, training labels, benchmark — must serialize to:
```json
{"is_credentials":0|1,"status":"REAL|FALSE_POSITIVE|REVIEW","confidence":0.0-1.0,
 "reasoning":"...","evidence":[...],
 "agent_trace":{"strategy":"...","checks":[...],"tool_calls":[...],"model":"..."}}
```
The training prompt format in `prompt_builder.build_prompt` and the inference prompt are intentionally byte-identical — keep them in sync if you change either.

## Ollama dependency

Runtime classifier and benchmark scripts call Ollama at `http://localhost:11434/api/generate`. Pull the three primary benchmark models before running:
```powershell
ollama pull qwen2.5-coder:3b
ollama pull granite3.3:2b
ollama pull llama3.2:3b
ollama serve
```
For dev without Ollama, pass `--test` to `src/main.py` (heuristic responses) — but benchmark/eval scripts have no offline mode.
