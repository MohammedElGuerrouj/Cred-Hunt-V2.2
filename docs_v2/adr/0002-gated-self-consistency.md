# ADR-0002: Gate `self_consistency` on Borderline Confidence

## Status

Accepted. May 2026.

## Context

Self-consistency (Wang et al., 2022) is documented as a strategy in `docs_v2/REASONING_STRATEGIES.md` and `docs_v2/RUNBOOK.md`. Both docs specify the strategy should only fire on borderline cases — `0.4 <= confidence <= 0.6` or `status == REVIEW`. Production hot-paths should use the cheaper `direct_json` or `few_shot`.

The previous implementation in `scripts/reasoning_runner.py:_run_self_consistency` ignored the gate. It always ran N samples at temperature 0.3, regardless of how confident a cheap deterministic call would have been. Consequences:

- **5× latency cost** on every record where the strategy was selected.
- Benchmark numbers for `self_consistency` overstated quality at the expense of cost: comparing it to `direct_json` on F1 alone made it look attractive while hiding the latency tax.
- The agent_trace contained no flag indicating whether sampling actually changed the verdict, so post-hoc analysis was impossible.

The May 2026 literature review (Sifting the Noise, arXiv 2601.22952) confirmed the routing pattern: agentic / sampling strategies should be applied selectively to borderline cases, not by default.

## Decision

Implement gated self-consistency:

1. Run one call at `temperature = 0.0` with the `few_shot` prompt (same prompt the un-gated path used).
2. If the result is **not borderline** (confidence outside `[0.4, 0.6]` AND status is not `REVIEW`), return that result. Record `agent_trace.escalated = False`, `agent_trace.samples = 1`.
3. If the result **is** borderline, run N–1 additional samples at `temperature = 0.3`, majority-vote on `is_credentials`, derive status by mode of non-REAL labels when negative. Record `agent_trace.escalated = True`, `agent_trace.samples = N`, the per-sample statuses, and the vote counts.

`N = 5` by default (`scripts/reasoning_runner.py:run_strategy` `samples=5`).

The benchmark summary reports `escalation_rate` per `(model, strategy)` cell so latency cost is visible at-a-glance.

## Consequences

### Positive

- Latency cost is now proportional to the fraction of borderline cases, not 100% of inputs.
- The `self_consistency` row in the benchmark is now an honest measurement of its targeted use case rather than an inflated one.
- `escalation_rate` is itself a useful metric: high rates indicate a base model that is confidently wrong less often (which is good) or unconfident in general (which is bad — investigate calibration).
- Aligns the code with the documented design in `docs_v2/AGENTIC_AI_DESIGN.md` and `docs_v2/RUNBOOK.md`.

### Negative

- A model that is *overconfidently wrong* never triggers escalation. The gate trusts the model's reported confidence; a poorly-calibrated model gets a free pass on the cheap call. Mitigation: confidence calibration is now a meta-metric to watch.
- The strategy is more complex than the previous unconditional sampling loop. The complexity is justified by the latency win.

### Neutral

- Random seeding for the escalation samples is not pinned per-record — different runs will produce different votes on the same borderline input. This is acceptable for benchmarks but worth noting in any production audit.

## Implementation

Code:

- `scripts/reasoning_runner.py:_run_self_consistency` — rewritten.
- `scripts/reasoning_runner.py:_needs_escalation` — gate function.
- `scripts/reasoning_runner.py:BORDERLINE_LOWER, BORDERLINE_UPPER` — gate thresholds.
- `scripts/benchmark_models.py:summarize` — adds `escalation_rate` field.

Tests:

- `scripts/test_trained_model.py` covers the schema contract end-to-end.
- Smoke benchmark on a 3-record dataset confirms non-null `escalation_rate` only for `self_consistency`.

## Reversal criteria

This decision should be revisited if:

- The benchmark shows that gated self-consistency degrades F1 vs un-gated by >1 point — the cheap first call is misleading the gate. Recourse: adjust thresholds or escalate on additional signals (e.g., high-risk file path).
- A future production deployment needs deterministic per-record sampling. Recourse: thread a per-record seed through `_run_self_consistency`.

## References

- Wang et al., "Self-Consistency Improves Chain of Thought Reasoning in Language Models", 2022.
- arXiv 2601.22952, "Sifting the Noise: A Comparative Study of LLM Agents in Vulnerability False Positive Filtering".
- [`docs_v2/RUNBOOK.md`](../RUNBOOK.md) §12.
- [`docs_v2/AGENTIC_AI_DESIGN.md`](../AGENTIC_AI_DESIGN.md).
