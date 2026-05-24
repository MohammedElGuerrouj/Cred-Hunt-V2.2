# Reasoning Strategies

CRED-HUUNT v2 should benchmark reasoning as a configurable strategy, separate from model choice. This lets the project answer two different questions:

1. Which model is best?
2. Which reasoning strategy is worth its latency cost?

## Strategy Summary

| Strategy | Cost | Agentic level | Best use |
|---|---:|---:|---|
| `direct_json` | Lowest | Low | Fast baseline and production high-volume scans |
| `few_shot` | Low | Medium | Default classifier with examples |
| `self_consistency` | Medium | Medium | Borderline confidence cases |
| `cot_distilled` | Medium training cost, low inference cost | Medium-high | Hard negatives and REVIEW cases |
| `react_triage` | High | High | Forensic review with read-only tools |
| `tree_of_thoughts` | Very high | High | Future repo-scale branch exploration |
| `graph_of_thoughts` | Very high | High | Future cross-file correlation |

The first benchmark should include:

```text
direct_json
few_shot
self_consistency
cot_distilled
react_triage
```

ToT and GoT should be designed now but implemented later.

## direct_json

The simplest strategy: ask the model to emit strict JSON with no few-shot examples beyond the system contract.

Target output:

```json
{
  "is_credentials": 0,
  "status": "FALSE_POSITIVE",
  "confidence": 0.91,
  "reasoning": "Short explanation.",
  "evidence": ["grounded signal"]
}
```

Use for:

- baseline metrics
- high-volume scans
- LoRA models trained on the exact prompt shape

Measure:

- JSON validity
- binary F1
- latency
- false-positive reduction

## few_shot

Uses representative examples inside the prompt. The current [../src/prompt_builder.py](../src/prompt_builder.py) already has static `FEW_SHOTS`.

v2 improvements:

- add examples with `is_credentials`
- include hard-negative examples
- include context-token false positives
- include reset URL/policy/documentation examples
- optionally choose dynamic few-shot examples by similarity

Use for:

- default production mode before LoRA
- evaluating whether context examples reduce false positives

## self_consistency

Runs the same detection multiple times and majority-votes the result.

Recommended settings:

```text
samples: 3 or 5
temperature: 0.2 to 0.4
vote key: is_credentials
fallback tie-break: average confidence, then REVIEW
```

Use only when:

```text
0.4 <= confidence <= 0.6
status == REVIEW
JSON output is valid but evidence is weak
```

Do not use for every detection unless latency is acceptable.

Output should record:

```json
{
  "agent_trace": {
    "strategy": "self_consistency",
    "samples": 5,
    "votes": {"is_credentials_1": 2, "is_credentials_0": 3}
  }
}
```

## cot_distilled

This is not raw chain-of-thought as production output. It is an offline training strategy implemented in two pieces:

1. `scripts/distill_rationales.py` — call a stronger teacher with the student prompt + ground-truth label, emit `{record_id, reasoning, evidence}` JSONL.
2. `scripts/process_synthetic_training_data.py --rationales <path>` — splice those rationales into the training labels, replacing `_default_reasoning`. The result is `data/training_data_binary.jsonl` with teacher-grade `reasoning` and `evidence` per record.
3. Fine-tune the smaller student on the rationale-augmented split with `scripts/lora_fine_tune.py`.
4. In production, the student emits the same v2 contract (`reasoning`, `evidence`, `agent_trace`) — no hidden CoT.

**Honest benchmarking note.** Running `cot_distilled` as a benchmark strategy against a *base* (un-distilled) model only measures the effect of the prompt suffix `"Return concise analyst-facing reasoning..."`. The strategy only meaningfully differs from `direct_json` once a student has been trained on the rationale-augmented split.

Teacher options:

```text
qwen2.5-coder:7b   # recommended for code/config context
qwen2.5:7b         # general
granite3.3:8b      # IBM agentic
phi4-mini:3.8b     # smaller fallback
```

Use for:

- hard negatives
- REVIEW examples
- cases where context must override entropy

Evaluation must check that rationales are grounded in the input context.

## react_triage

ReAct mode lets the agent reason and use read-only tools. This is a slower forensic path, not the default per-line scanner.

The strategy is implemented as an **iterative loop** (Yao et al. style) in `scripts/reasoning_runner.py:_run_react_iterative`. On each turn the model emits ONE JSON object:

- Tool call: `{"thought":"...","action":"<tool_name>","args":{...}}` — the runner executes the named tool and feeds back `{"observation": <tool_result>}` for the next turn.
- Final answer: `{"thought":"...","final":{<full v2 decision object>}}`.

The loop runs at most `REACT_MAX_STEPS` (default 3) iterations. If the model never emits a `final`, the runner falls back to a forced `direct_json` call and records `terminated = "fallback_direct_json"` in `agent_trace`.

Read-only tools (registered in `scripts/react_tools.py:TOOL_REGISTRY`):

| Tool | Purpose | Status |
|---|---|---|
| `entropy_check` | Shannon entropy and character class features | implemented |
| `placeholder_check` | Detect placeholders and masked values | implemented |
| `context_signal_check` | Key names, URLs, users, hosts, reset, tickets | implemented |
| `file_path_check` | Classify path as source/test_fixture/documentation/config | implemented |
| `duplicate_secret_check` | Detect values seen earlier in the same run | implemented |
| `fixture_check` | Partly subsumed by `file_path_check`'s `test_fixture` class | deferred |
| `git_blame_check` | Optional forensic metadata | deferred (no git context in synthetic data) |

Adding a tool means dropping a function into `react_tools.py` and a dispatch entry into `TOOL_REGISTRY` — the runner does not need to be touched.

### tool_assisted (back-compat)

For comparison, the original single-shot variant is preserved as the `tool_assisted` strategy: all four base tools run once, results are stuffed into the prompt as a JSON blob, model produces a single JSON answer. Cheaper, less honest about the "agentic" framing.

Production output should include tool traces:

```json
{
  "agent_trace": {
    "strategy": "react_triage",
    "tool_calls": [
      {"tool": "entropy_check", "status": "ok"},
      {"tool": "file_path_check", "status": "ok"}
    ]
  }
}
```

## tree_of_thoughts

Tree-of-Thoughts is a later repo-scale strategy. It is useful when one detection has several plausible hypotheses.

Example hypotheses:

```text
REAL
FALSE_POSITIVE
TEST_ONLY
ROTATED
DOCUMENTATION_EXAMPLE
```

A ToT controller can expand each hypothesis with extra context, score branches, and keep the most likely decision path.

Future script:

```text
scripts/tot_investigator.py
```

Use only for:

- high-risk findings
- unresolved REVIEW cases
- multi-file investigations

## graph_of_thoughts

Graph-of-Thoughts is a later cross-file correlation strategy.

Build graph nodes:

```text
detection
secret_hash
file
owner
pattern
context_cluster
```

Build edges:

```text
same secret hash
same owner
same file family
same pattern
same commit/author
same service context
```

Then reason over clusters instead of isolated detections.

Future script:

```text
scripts/got_aggregator.py
```

Use for:

- repeated secret triage
- deciding whether one leaked value appears across multiple repos
- grouping analyst review queues

## Recommended Adoption Order

1. `direct_json`
2. `few_shot`
3. `self_consistency`
4. `cot_distilled`
5. `react_triage`
6. `tree_of_thoughts`
7. `graph_of_thoughts`

## Strategy Metrics

Every strategy should report:

- binary F1
- hard-negative recall
- JSON validity
- average latency
- average tokens generated
- cost multiplier relative to `direct_json`
- evidence grounding score
- percentage routed to REVIEW
