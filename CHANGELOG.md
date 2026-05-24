# Changelog

All notable changes to CRED-HUUNT v2 are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Family-diverse primary model trio: `qwen2.5-coder:3b`, `granite3.3:2b`, `llama3.2:3b`. Retired `qwen2.5:1.5b` from the primary tier. Decision recorded in [`docs_v2/adr/0001-model-trio-selection.md`](docs_v2/adr/0001-model-trio-selection.md).
- Gated `self_consistency` strategy: cheap first call at temperature 0, escalation to N=5 samples only when `0.4 <= confidence <= 0.6` or `status == REVIEW`. New `agent_trace.escalated` flag; new `escalation_rate` field in benchmark summary. Decision recorded in [`docs_v2/adr/0002-gated-self-consistency.md`](docs_v2/adr/0002-gated-self-consistency.md).
- Iterative ReAct loop (`react_triage`): replaces single-shot tool injection with a proper Yao-et-al-style loop (thought → action → observation → final) up to `REACT_MAX_STEPS = 3`. Forced `direct_json` fallback on derailment. New `TOOL_REGISTRY` in `scripts/react_tools.py` for tool dispatch. The single-shot variant is preserved as `tool_assisted` for back-compat. Decision recorded in [`docs_v2/adr/0003-iterative-react-loop.md`](docs_v2/adr/0003-iterative-react-loop.md).
- New ReAct tool: `duplicate_secret_check` — detects repeated `matched_value`s within a run via truncated SHA-256.
- Honest `cot_distilled` pipeline: new `scripts/distill_rationales.py` generates teacher rationales (default teacher `qwen2.5-coder:7b`). New `--rationales` flag on `scripts/process_synthetic_training_data.py` splices teacher rationales into training labels in place of the deterministic default reasoning.
- New evaluation metrics across `scripts/benchmark_models.py` and `scripts/evaluate_model_performance.py`:
  - `schema_validity_rate` — fraction of model outputs satisfying the full v2 contract (all required fields with valid types).
  - `evidence_grounding_score` — heuristic 0–1 score for how grounded evidence strings are in the input.
  - `p95_latency_ms`, `p99_latency_ms` — tail latency.
  - `escalation_rate` — only meaningful for `self_consistency`.
- New enterprise documentation: [SECURITY.md](SECURITY.md), [MODEL_CARD.md](MODEL_CARD.md), [THREAT_MODEL.md](THREAT_MODEL.md), [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md), [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md), [CONTRIBUTING.md](CONTRIBUTING.md), [ROADMAP.md](ROADMAP.md), [CHANGELOG.md](CHANGELOG.md), and ADRs under `docs_v2/adr/`.

### Changed

- `src/llm_client.MODEL` default is now `qwen2.5-coder:3b` (was `qwen2.5:1.5b`).
- `scripts/lora_fine_tune.py` `--model` default is now `qwen2.5-coder:3b` (was `qwen2.5:1.5b`).
- `scripts/evaluate_model_performance.py` `--base-model` default is now `Qwen/Qwen2.5-Coder-3B` (was `Qwen/Qwen2.5-1.5B`).
- `scripts/test_trained_model.py` `--models` default is now the new primary trio.
- `_run_self_consistency` no longer runs the full N-sample loop unconditionally; it gates on borderline confidence per the design in `docs_v2/RUNBOOK.md` §12 and `docs_v2/AGENTIC_AI_DESIGN.md`.
- `react_triage` strategy is now the iterative loop; the previous single-shot behavior is available under the new strategy name `tool_assisted`.
- ReAct mode uses `prompt_builder.get_react_system()` (system prompt + addendum describing the per-turn JSON protocol). Base `SYSTEM_PROMPT` and `FEW_SHOTS` are unchanged.

### Deferred

- Tree-of-Thoughts (`scripts/tot_investigator.py`) — out of scope until benchmark results justify it. See [`docs_v2/adr/0004-defer-tot-got.md`](docs_v2/adr/0004-defer-tot-got.md).
- Graph-of-Thoughts (`scripts/got_aggregator.py`) — requires repo-scale data not present in the synthetic corpus. Same ADR.
- `git_blame_check` ReAct tool — synthetic dataset has no git context.

### Security

- New [THREAT_MODEL.md](THREAT_MODEL.md) enumerates nine threats (T-1 prompt injection, T-2 model poisoning, T-3 evasion, T-4 trace exfiltration, T-5 DoS, T-6 repudiation, T-7 ReAct tool elevation, T-8 training-data poisoning, T-9 Ollama spoofing) and current vs planned mitigations.
- New [SECURITY.md](SECURITY.md) defines disclosure SLA, in-scope / out-of-scope, and dependency hygiene.
- ReAct tool registry preserves the "read-only and deterministic" invariant. Adding any I/O-capable tool is now a documented review event.

### Documentation

- `CLAUDE.md` updated: model trio, gated self_consistency, iterative ReAct, dual entropy implementations, softened "only places that map status" claim.
- `docs_v2/MODEL_SELECTION.md`, `docs_v2/BENCHMARK_DESIGN.md`, `docs_v2/RUNBOOK.md`, `docs_v2/IMPLEMENTATION_ROADMAP.md`, `docs_v2/TRAINING_PIPELINE.md`, `docs_v2/README.md`: model trio references swept.
- `docs_v2/REASONING_STRATEGIES.md`: rewrote `react_triage` (iterative + TOOL_REGISTRY) and `cot_distilled` (honest two-piece pipeline) sections.

---

This is the inaugural entry. There are no earlier versions of this changelog; for change history before this point, see the git log.

[Unreleased]: https://example.com/compare/HEAD
