# ADR-0004: Defer Tree-of-Thoughts and Graph-of-Thoughts

## Status

Accepted. May 2026.

## Context

`docs_v2/REASONING_STRATEGIES.md` documents Tree-of-Thoughts (ToT) and Graph-of-Thoughts (GoT) as future strategies. Placeholder scripts (`scripts/tot_investigator.py`, `scripts/got_aggregator.py`) are mentioned in [`docs_v2/ARCHITECTURE.md`](../ARCHITECTURE.md). Neither exists on disk and neither is scheduled for the current benchmark cycle.

We need an explicit, durable record of why these strategies are deferred — not abandoned — so future contributors do not re-litigate the decision.

The May 2026 literature review found:

- ToT used in hierarchical CWE vulnerability classification (smart contracts and code analysis) but not in published secret-detection work.
- GoT and graph-based approaches (Code Property Graph, GraphSAGE, hierarchical attention graph CNN) used for vulnerability detection on cross-file program structure — not per-detection triage.
- No paper benchmarks ToT or GoT against simpler strategies on a credential-classification dataset comparable to ours.

The cost structure also matters. Both are expensive at inference time. ToT typically fans out 5–10× more LLM calls per detection than a single strategy. GoT requires a graph-construction pass before reasoning begins.

## Decision

**Defer both** until the current benchmark cycle has results. Specifically:

- **ToT** is deferred until the 3-model × 5-strategy matrix shows a recall ceiling on the `REVIEW` class or on `hard_negative` distractors that the existing strategies cannot close. The motivating signal would be: `react_triage` `hard_negative_recall < 0.85` on all three primary models, with no clear winner among them.
- **GoT** is deferred until the project integrates a real repo-scale dataset (not the current per-detection synthetic corpus). The motivating signal would be: an internal or public corpus with cross-file relationships (same `secret_hash` in multiple files, same `owner` for multiple findings) becomes available.

When ToT is implemented, it will be **routed**, not default: invoked only when the routing layer (`docs_v2/BENCHMARK_DESIGN.md §Routing Benchmark`) classifies a finding as both borderline and high-risk.

When GoT is implemented, it will operate as a **post-processing aggregator** consuming benchmark JSONL, not as a strategy in `scripts/reasoning_runner.py`. It returns cluster-level verdicts, not per-record verdicts.

## Consequences

### Positive

- The benchmark cycle focuses on strategies whose cost / benefit is known. Five strategies × three models is already 15 cells; adding two speculative strategies would inflate the matrix and the runtime budget without clear payoff.
- Forces a measurement-driven decision later: ToT only ships if the matrix shows existing strategies cannot solve borderline cases. GoT only ships if a real dataset justifies the engineering.
- Avoids implementing GoT-style reasoning on a synthetic dataset that has no real cross-file structure — the result would be misleading.

### Negative

- The repository carries documented-but-unimplemented strategies, which is a known maintenance smell. We accept this because the docs document our *plan*, not a promise that the code is complete.
- A contributor expecting ToT or GoT will need to read this ADR to understand why those scripts are absent.

### Neutral

- The `tot_investigator.py` and `got_aggregator.py` filenames are reserved for the eventual implementations. Do not reuse them for unrelated scripts.

## Implementation

- No code change. This ADR is the artifact.
- [`docs_v2/REASONING_STRATEGIES.md`](../REASONING_STRATEGIES.md) §tree_of_thoughts and §graph_of_thoughts already mark these as future. Link this ADR from those sections in the next docs sweep.
- [ROADMAP.md](../../ROADMAP.md) §10 and §11 carry the implementation plan.

## Reversal criteria

Implement ToT when:

- The benchmark matrix shows `react_triage` `hard_negative_recall < 0.85` for all three primary models AND no model dominates on borderline cases.
- We have engineering budget for a routed strategy that adds 5–10× latency to <10% of detections.

Implement GoT when:

- A real (non-synthetic) repo-scale dataset is integrated, with `owner` / `commit_sha` / cross-file relationships present.
- The deployment use case explicitly benefits from cluster-level review queues (i.e., the analyst workflow groups findings).

## References

- Yao et al., "Tree of Thoughts: Deliberate Problem Solving with Large Language Models", 2023.
- Besta et al., "Graph of Thoughts: Solving Elaborate Problems with Large Language Models", 2024.
- [`docs_v2/REASONING_STRATEGIES.md`](../REASONING_STRATEGIES.md) §tree_of_thoughts, §graph_of_thoughts.
- [ROADMAP.md](../../ROADMAP.md) §10–§11.
