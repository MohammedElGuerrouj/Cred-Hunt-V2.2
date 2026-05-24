# ADR-0003: Iterative ReAct Loop with TOOL_REGISTRY

## Status

Accepted. May 2026.

## Context

The previous `react_triage` strategy was misnamed. It ran four deterministic tools (`entropy_check`, `placeholder_check`, `context_signal_check`, `file_path_check`) once before the LLM call, serialized their results into the prompt, and made a single LLM call. The model never decided which tools to use; the model never saw observations; the model never had a chance to act on intermediate results. This is "tool-augmented single-shot prompting," not the canonical ReAct loop (Yao et al., 2022) where reasoning and acting interleave.

Three problems with the previous design:

1. **Honesty.** Naming a strategy `react_triage` when it does not implement ReAct is misleading to the operator and to anyone reading the benchmark.
2. **Inflexibility.** Adding a tool meant editing the runner's hardcoded tool list. Every new tool was a code change in two places.
3. **Lost benefit.** The May 2026 literature review (Sifting the Noise, arXiv 2601.22952) found that iterative ReAct agents have the lowest false-positive rate among compared LLM strategies. The single-shot variant captures none of that benefit because the model cannot revise its understanding based on tool output.

## Decision

Implement a real iterative ReAct loop in `scripts/reasoning_runner.py:_run_react_iterative`. Per-turn protocol:

- The model emits exactly one JSON object on each turn. Either:
  - `{"thought": "...", "action": "<tool_name>", "args": {...}}` — the runner executes the named tool and feeds back `{"observation": <tool_result>}` in the next turn.
  - `{"thought": "...", "final": {<v2 decision object>}}` — terminal answer.
- Loop runs up to `REACT_MAX_STEPS = 3` iterations.
- If the model emits an unrecognized action or unparseable JSON, the loop terminates and the runner falls back to a forced `direct_json` call. `agent_trace.terminated == "fallback_direct_json"` records this.

Tool dispatch via `scripts/react_tools.py:TOOL_REGISTRY`:

```python
TOOL_REGISTRY: Dict[str, Callable[[Dict, Dict], Dict]] = {
    "entropy_check": ...,
    "placeholder_check": ...,
    "context_signal_check": ...,
    "file_path_check": ...,
    "duplicate_secret_check": ...,
}
```

Adding a tool means adding one function and one registry entry. The runner does not change.

The system prompt addendum (`src/prompt_builder.REACT_SYSTEM_ADDENDUM`) explains the turn schema and lists the available tools.

The previous single-shot behavior is preserved as a separate strategy `tool_assisted`. It still works, it is still benchmarkable, but it no longer pretends to be ReAct.

## Consequences

### Positive

- Naming matches behavior.
- Adding a tool is a one-line change in `react_tools.py` plus a doc update.
- The iterative loop can produce a different verdict from the single-shot variant — measurable in the benchmark by comparing `react_triage` vs `tool_assisted` on the same model.
- The model can short-circuit (emit `final` on step 1) when it has enough information from the input alone, so the median latency is close to `direct_json` for easy cases.
- Forced fallback prevents the loop from hanging or returning malformed output.

### Negative

- Worst-case latency is up to 3× a single LLM call. For high-volume scanning this would be prohibitive — `react_triage` is therefore positioned as a forensic / borderline-case strategy in `docs_v2/REASONING_STRATEGIES.md`, not a default.
- Smaller models (2-3B) may not follow the action/observation/final protocol cleanly. The fallback handles this gracefully but the benchmark may show high `terminated == "fallback_direct_json"` rates for some models. This is itself informative — it tells us which models can play the agent role.
- The system prompt is now strategy-dependent. Maintenance burden is higher than a single prompt.

### Neutral

- The current tools are read-only and deterministic; the loop adds no I/O surface. [THREAT_MODEL.md §T-7](../../THREAT_MODEL.md) tracks this invariant and gates any future I/O-capable tool behind a security review.

## Implementation

- `scripts/reasoning_runner.py:_run_react_iterative` — new function.
- `scripts/reasoning_runner.py:run_strategy` — dispatches `react_triage` to the new function and `tool_assisted` to the old single-shot path.
- `scripts/react_tools.py:TOOL_REGISTRY` — new dict; `duplicate_secret_check` added.
- `src/prompt_builder.py:REACT_SYSTEM_ADDENDUM`, `get_react_system()` — new.
- `docs_v2/REASONING_STRATEGIES.md` — updated `react_triage` section, added `tool_assisted` note.

## Reversal criteria

This decision should be revisited if:

- The benchmark shows that small models (2-3B) cannot follow the action/observation/final protocol at acceptable rates (e.g., `terminated == "fallback_direct_json"` exceeds 50% on all three primary models). In that case, fall back to `tool_assisted` as the primary tool-augmented strategy and reserve iterative ReAct for the upper-bound model only.
- A future tool requires multi-step coordination (e.g., a planner that calls `context_signal_check` then conditionally `duplicate_secret_check`). Recourse: add an explicit `plan` action type rather than expecting the model to plan via free-text thoughts.

## References

- Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models", 2022.
- arXiv 2601.22952, "Sifting the Noise: A Comparative Study of LLM Agents in Vulnerability False Positive Filtering" — finds ReAct agents have the lowest FP rate.
- [`docs_v2/REASONING_STRATEGIES.md`](../REASONING_STRATEGIES.md) §react_triage.
- [`THREAT_MODEL.md §T-7`](../../THREAT_MODEL.md).
