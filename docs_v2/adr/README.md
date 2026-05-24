# Architecture Decision Records

This directory holds Architecture Decision Records (ADRs) for CRED-HUUNT v2 — short documents that capture a single load-bearing technical decision, the context that drove it, and the consequences.

ADRs follow the [Michael Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions). Each file is self-contained and immutable once accepted: if a decision is later reversed, write a new ADR that supersedes the old one rather than editing history.

## Status values

| Status | Meaning |
|---|---|
| Proposed | Drafted, awaiting review |
| Accepted | Approved and in effect |
| Deprecated | No longer in effect but not yet superseded |
| Superseded by ADR-NNNN | Replaced by a newer decision |

## Index

| ID | Title | Status |
|---|---|---|
| [0001](0001-model-trio-selection.md) | Family-diverse primary model trio | Accepted |
| [0002](0002-gated-self-consistency.md) | Gate `self_consistency` on borderline confidence | Accepted |
| [0003](0003-iterative-react-loop.md) | Iterative ReAct loop with TOOL_REGISTRY | Accepted |
| [0004](0004-defer-tot-got.md) | Defer Tree-of-Thoughts and Graph-of-Thoughts | Accepted |

## Filename convention

`NNNN-kebab-case-title.md` where `NNNN` is a zero-padded, monotonically increasing integer. Do not reuse numbers, even for deleted ADRs.

## When to write an ADR

Write one when you make a decision that:

- Changes a default that consumers depend on (model, strategy, prompt, dataset shape).
- Adds a layer to the threat model.
- Forecloses a future option (e.g., "we will not support multi-tenant input mixing").
- Trades clarity for performance, or vice versa, in a way that future maintainers will need to understand.

Do **not** write one for:

- Routine refactors.
- Bug fixes that restore a documented behavior.
- Anything fully captured by a code comment near the affected lines.
