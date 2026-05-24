# Contributing to CRED-HUUNT v2

Thanks for considering a contribution. This document covers how to set up a development environment, how the code is organized, what review will check for, and the higher-bar process for changes that touch the model, the prompt, the dataset, or the threat model.

## Development setup

```bash
git clone <your-fork>
cd Cred_Hunt_v2-main
python -m venv .venv
.venv/Scripts/activate     # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Pull the primary benchmark models locally (~12 GB total):

```bash
ollama pull qwen2.5-coder:3b
ollama pull granite3.3:2b
ollama pull llama3.2:3b
```

Quick offline smoke test (no Ollama required):

```bash
python scripts/test_trained_model.py --test-mode
```

If that exits clean and prints accuracy per model, your environment is ready.

## Code organization

Three layers — read [`CLAUDE.md`](CLAUDE.md) for the architectural overview. Briefly:

| Layer | Files | Add code here when... |
|---|---|---|
| Runtime classifier | `src/` | Touching the per-detection inference path |
| Dataset / feature | `src/dataset_schema.py`, `scripts/process_synthetic_training_data.py`, `scripts/augment_false_positives.py`, `scripts/distill_rationales.py` | Adding records, augmentations, training labels |
| Benchmark / reasoning | `scripts/benchmark_models.py`, `scripts/reasoning_runner.py`, `scripts/react_tools.py` | Adding a strategy, a tool, or a metric |

`src/` is not a Python package — modules import flat (`from classifier import ...`). Scripts manipulate `sys.path` themselves. Do not refactor to package imports without also updating every script.

## Code style

- Python 3.10+.
- Type hints on public functions. Use `from __future__ import annotations` for forward references.
- 4-space indentation, double quotes for strings.
- No `eval`, no `exec`, no `shell=True`. Ever. See [SECURITY.md](SECURITY.md).
- Reuse existing helpers: `normalize_llm_result`, `parse_json_safely`, `normalize_status`, `derive_is_credentials`, `context_hash`. Don't reinvent.

## Review checklist

Every change should pass:

1. `python -c "import ast; ast.parse(open('<file>').read())"` parses cleanly.
2. The smoke command above still passes.
3. No new `requirements.txt` entries without justification in the PR description.
4. No new network calls outside of Ollama loopback.
5. No new file I/O from `scripts/react_tools.py` without a [THREAT_MODEL.md §T-7](THREAT_MODEL.md) review.
6. No commit of any `data/*.jsonl`, `data/*.json`, `data/*.csv`, or `results/**` — they are all gitignored for a reason.
7. Docs touched: if you changed the strategy list, update `docs_v2/REASONING_STRATEGIES.md`, `docs_v2/BENCHMARK_DESIGN.md`, and `CLAUDE.md`.
8. Provenance: if you changed the prompt, `src/llm_client.MODEL`, or the LoRA adapter contract, note it in [CHANGELOG.md](CHANGELOG.md).

## Higher-bar changes

Some change classes require additional review beyond a normal PR. The list is short and intentional.

### Adding a reasoning strategy

A new strategy goes in `scripts/reasoning_runner.py`. Required artifacts in the PR:

- A dispatch branch in `build_strategy_prompt` and `run_strategy`.
- A docstring explaining what the strategy does, when it's worth its latency cost, and what `agent_trace` fields it emits.
- An entry in `docs_v2/REASONING_STRATEGIES.md` with the same content.
- A row in the matrix in `docs_v2/BENCHMARK_DESIGN.md`.
- A test_mode smoke run (the one in this README) that exercises the new strategy.
- A benchmark run on the test split — paste the per-cell metrics in the PR description.

### Adding a ReAct tool

A new tool goes in `scripts/react_tools.py`. Required:

- Function returning `{"tool": "<name>", "status": "ok", ...}` — no exceptions raised.
- Entry in `TOOL_REGISTRY`.
- Mention in `prompt_builder.REACT_SYSTEM_ADDENDUM`.
- **Read-only and deterministic.** If the tool needs I/O (filesystem, network, git), it requires:
  - Updates to [THREAT_MODEL.md §T-7](THREAT_MODEL.md).
  - Sandboxing / arg validation in the tool itself.
  - Security review sign-off.
- Documentation in `docs_v2/REASONING_STRATEGIES.md` under the `react_triage` table.

### Adding a model to the primary trio

Required:

- An ADR (`docs_v2/adr/000N-add-<model>.md`) — see existing ADRs for format.
- Updates to defaults in `scripts/benchmark_models.py`, `scripts/test_trained_model.py`, optionally `src/llm_client.py`.
- Updates to `docs_v2/MODEL_SELECTION.md`, `docs_v2/BENCHMARK_DESIGN.md`, `docs_v2/RUNBOOK.md`, `CLAUDE.md`.
- A benchmark run on the test split with the new model alongside the current trio — paste the comparison in the PR.
- Update [MODEL_CARD.md](MODEL_CARD.md) primary-models table.

### Changing the system prompt or few-shots

`src/prompt_builder.py` is the production contract. Any change requires:

- A `prompt_version` bump (define the constant if missing).
- A full benchmark run for at least one model showing the new prompt does not regress `binary_f1`, `hard_negative_recall`, or `json_validity_rate`.
- [CHANGELOG.md](CHANGELOG.md) entry with the previous and new prompt_version.
- Update [`docs_v2/REASONING_STRATEGIES.md`](docs_v2/REASONING_STRATEGIES.md) if the change affects the strategy semantics.

### Changing dataset processing

Touching `scripts/process_synthetic_training_data.py`, `scripts/augment_false_positives.py`, or `src/dataset_schema.py`:

- Run the full processor (`python scripts/process_synthetic_training_data.py --target both --augment-fp 3`) and confirm `_assert_no_group_leakage` does not fire.
- Compare `data/augmentation_report.json` against the previous run — distractor distribution should be intentional, not accidental.
- If a distractor type is added or removed, update `docs_v2/DATA_AUGMENTATION.md` and `docs_v2/EVALUATION_METRICS.md`.

### Changing the threat model or data classes

Any change to [THREAT_MODEL.md](THREAT_MODEL.md), [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md), or [SECURITY.md](SECURITY.md):

- Requires explicit security-reviewer approval.
- Backwards-incompatible changes to a data class trigger a major-version bump in [CHANGELOG.md](CHANGELOG.md).

## Testing

The project has no automated test suite. Quality is enforced via:

- `scripts/test_trained_model.py` — 7-case deterministic smoke test against the expected schema. Pass rate per model is recorded.
- `scripts/benchmark_models.py --test-mode` — exercises every strategy path end-to-end with the heuristic fake LLM.
- The full benchmark — primary regression detector.

Contributions that introduce a real test framework (`pytest`, hypothesis, coverage) are welcome and should be discussed in an issue first.

## Commit and PR conventions

- One concern per commit. A model swap and a metric addition are two PRs.
- Imperative subject line, ≤72 chars: `Add duplicate_secret_check tool to ReAct registry`.
- Body explains the *why* — the *what* is in the diff.
- Reference related ADRs, threat-model sections, or research papers in the body.
- If the change is operator-visible (new flag, new metric, new default), include a CHANGELOG.md entry.

## Signing off

Before opening a PR, confirm you have read:

- [SECURITY.md](SECURITY.md) — what you can and can't change without security review.
- [THREAT_MODEL.md](THREAT_MODEL.md) — what threats the codebase is defending against.
- [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md) — never commit C3 data.
- [MODEL_CARD.md](MODEL_CARD.md) — the responsible-AI contract.

If you maintain a fork, also adopt the model card and threat model for your variant — they are not vacuous boilerplate.

## Getting help

Open a draft PR early. Tag the maintainers listed in the project README. Questions about prompt engineering, model selection, or benchmark methodology are welcome — these are research-grade decisions and discussion is encouraged.
