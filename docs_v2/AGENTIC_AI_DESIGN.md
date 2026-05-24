# Agentic AI Design

CRED-HUUNT v2 should behave like an agentic AI credential triage system. The classifier is one component inside a larger loop that observes context, extracts evidence, reasons with a selected strategy, optionally uses tools, decides, explains, and aggregates results.

## Agent Goal

Given a detected value and its context, decide whether the value is a real credential.

The agent must answer:

1. Is this a credential? `is_credentials: 0|1`
2. What is the analyst-facing status? `REAL`, `FALSE_POSITIVE`, or `REVIEW`
3. How confident is the decision?
4. Which evidence supports the decision?
5. Which reasoning strategy and checks were used?

## Agent Loop

```text
Observe -> Extract -> Reason -> Act -> Decide -> Explain -> Aggregate
```

| Step | Meaning | Example |
|---|---|---|
| Observe | Read detection, matched value, file path, nearby context | `DB_PASS=...`, `.env`, host/user nearby |
| Extract | Convert raw context into structured features | entropy, key name, path type, placeholder flags |
| Reason | Apply the selected strategy | direct JSON, few-shot, self-consistency, distilled CoT, ReAct |
| Act | Optionally call read-only tools/checks | entropy check, git blame, fixture path check |
| Decide | Emit machine labels | `is_credentials`, `status`, `confidence` |
| Explain | Emit short reasoning and evidence | analyst-readable summary, not raw hidden thought |
| Aggregate | Group and prioritize findings | owner/file/secret hash clusters |

## Input Contract

The agent consumes normalized detection objects. Existing scanner outputs should be adapted to this shape.

```json
{
  "file_path": "config/service.env",
  "owner": "team-x",
  "source": "scanner",
  "pattern_name": "PASSWORD",
  "matched_value": "example-value-redacted",
  "match_line_number": 42,
  "context": "DB_USER=svc_app\nDB_PASS=example-value-redacted\nDB_HOST=10.0.0.4"
}
```

## Output Contract

The agent returns parseable JSON. This is the production contract.

```json
{
  "is_credentials": 1,
  "status": "REAL",
  "confidence": 0.94,
  "reasoning": "The value is assigned to a password variable near service username and host fields.",
  "evidence": [
    "password-like key: DB_PASS",
    "near username and host",
    "non-placeholder value",
    "high entropy"
  ],
  "agent_trace": {
    "strategy": "few_shot_self_consistency",
    "checks": ["entropy", "placeholder", "context", "file_path"],
    "tool_calls": [],
    "model": "qwen2.5-coder:3b"
  }
}
```

## Thinking And Reasoning Policy

The project needs transparency, but production should not depend on raw free-form hidden chain-of-thought. The preferred approach is:

- Use internal reasoning strategies to improve decisions.
- Expose short analyst-facing `reasoning`.
- Expose concrete `evidence`.
- Expose `agent_trace` metadata showing which checks and strategy ran.
- For distilled CoT training, store rationale traces in offline training artifacts, not as the default production response.

Recommended public fields:

| Field | Exposed | Purpose |
|---|---|---|
| `reasoning` | Yes | Short explanation for analysts |
| `evidence` | Yes | Grounded facts used by the decision |
| `agent_trace` | Yes | Strategy/check metadata for audit |
| `thoughts` | No by default | Optional offline distillation artifact only |

## Agent Modes

| Mode | Strategy | Use case |
|---|---|---|
| `fast` | `direct_json` | High-volume scans where latency matters |
| `balanced` | `few_shot` | Default production triage |
| `borderline` | `self_consistency` | Confidence around 0.4 to 0.6 or status `REVIEW` |
| `forensic` | `react_triage` | Expensive review with read-only tools |
| `repo_scale` | ToT/GoT | Multi-file correlation and investigation |

## Read-Only Tool Registry

The first ReAct implementation should only use safe, deterministic, read-only tools.

| Tool | Input | Output |
|---|---|---|
| `entropy_check` | value | entropy, length, character classes |
| `placeholder_check` | value | placeholder flags and matched terms |
| `context_signal_check` | context | nearby keys, username, host, URL, docs/reset signals |
| `file_path_check` | file path | prod/test/docs/source/config classification |
| `pattern_check` | pattern name, value | pattern family and expected format |
| `duplicate_secret_check` | secret hash | count and locations |
| `git_blame_check` | file path, line | author/date metadata for forensic mode |
| `fixture_check` | file path, context | likely test fixture/demo/sample indicators |

## Decision Logic

The model remains the main judge, but deterministic checks should guide or override obvious cases.

Examples:

- Very low entropy + placeholder term -> `FALSE_POSITIVE`.
- Password-like key + service context + non-placeholder -> likely `REAL`.
- Docs path + reset URL -> `FALSE_POSITIVE`.
- Source code assignment with low entropy but no placeholder -> `REVIEW`.
- Real-looking value in false-positive context -> hard negative; model must use context.

## Failure Handling

| Failure | Response |
|---|---|
| Invalid JSON | Retry once with strict JSON repair prompt, then return `REVIEW` |
| Missing `is_credentials` | Derive from `status` only if valid, else `REVIEW` |
| Low confidence | Route to self-consistency or analyst review |
| Tool error | Keep classification, record tool error in `agent_trace` |
| Model timeout | Return `REVIEW` with timeout reason |

## Audit Requirements

Every benchmark and production run should preserve:

- model name
- reasoning strategy
- prompt template version
- dataset split
- source record id
- decision JSON
- latency
- JSON validity
- optional tool-call trace

This is necessary for model comparison, regression testing, and analyst trust.
