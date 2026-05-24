"""Prompt construction for the credential classifier."""

from __future__ import annotations

import json
from typing import Any, Dict

SYSTEM_PROMPT = """You are an agentic AI security credential classifier.
Read the detected value, file path, source, pattern, and surrounding context.
Decide whether the value is a real credential.

Labels:
- REAL: actual secret/token/password/key granting system access, not meant to be public.
- FALSE_POSITIVE: placeholder, reset URL, policy mention, documentation example, test value, masked string, dummy value, ticket ID, date, host, or non-secret context.
- REVIEW: ambiguous case where neither REAL nor FALSE_POSITIVE is clearly correct.

Respond ONLY with valid JSON. No text outside the JSON object.
Required format: {"is_credentials":0|1,"status":"REAL"|"FALSE_POSITIVE"|"REVIEW","confidence":0.0-1.0,"reasoning":"brief analyst-facing explanation","evidence":["grounded signals"],"agent_trace":{"strategy":"direct_json","checks":["context","value","path"],"tool_calls":[]}}

Do not output hidden chain-of-thought. Use concise reasoning and concrete evidence grounded in the input."""

FEW_SHOTS = [
    {
        "role": "user",
        "content": """File: config/prod.env | Source: scanner
Pattern: PASSWORD | Match: NexusAutumn48!@#
Context:
DB_USER=svc_orders
DB_PASS=NexusAutumn48!@#
DB_HOST=10.0.0.8""",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "is_credentials": 1,
                "status": "REAL",
                "confidence": 0.96,
                "reasoning": "The value is assigned to a password key near a service username and host.",
                "evidence": ["password-like key", "near username", "near host", "non-placeholder value"],
                "agent_trace": {"strategy": "few_shot", "checks": ["context", "value", "path"], "tool_calls": []},
            }
        ),
    },
    {
        "role": "user",
        "content": """File: README.md | Source: scanner
Pattern: API_KEY | Match: YOUR_API_KEY_HERE
Context:
Replace YOUR_API_KEY_HERE with your actual key.""",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "is_credentials": 0,
                "status": "FALSE_POSITIVE",
                "confidence": 0.98,
                "reasoning": "The value is an explicit placeholder in documentation.",
                "evidence": ["documentation path", "uppercase placeholder", "replacement instruction"],
                "agent_trace": {"strategy": "few_shot", "checks": ["placeholder", "context", "path"], "tool_calls": []},
            }
        ),
    },
    {
        "role": "user",
        "content": """File: security/password-reset.md | Source: scanner
Pattern: PASSWORD | Match: 550e8400-e29b-41d4-a716-446655440000
Context:
password reset requested by user@example.com on 2025-01-12""",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "is_credentials": 0,
                "status": "FALSE_POSITIVE",
                "confidence": 0.93,
                "reasoning": "The value appears in a password reset event, not a credential assignment.",
                "evidence": ["reset context", "event/documentation language", "no secret assignment"],
                "agent_trace": {"strategy": "few_shot", "checks": ["context", "value", "path"], "tool_calls": []},
            }
        ),
    },
    {
        "role": "user",
        "content": """File: src/auth.js | Source: scanner
Pattern: TOKEN | Match: abc123def456
Context:
const token = 'abc123def456';
authenticate(token);""",
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "is_credentials": 0,
                "status": "REVIEW",
                "confidence": 0.62,
                "reasoning": "The value is low entropy but appears in source code as a token, so it needs review.",
                "evidence": ["source code context", "token variable", "low entropy"],
                "agent_trace": {"strategy": "few_shot", "checks": ["context", "entropy", "path"], "tool_calls": []},
            }
        ),
    },
]


def build_prompt(detection: Dict[str, Any]) -> str:
    return f"""File: {detection['file_path']} | Source: {detection.get('source', 'unknown')}
Pattern: {detection['pattern_name']} | Match: {detection['matched_value']}
Context:
{detection['context']}"""


def build_messages(detection: Dict[str, Any]) -> list[Dict[str, str]]:
    """Full chat-style message list including system prompt and few-shot examples."""
    return (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + FEW_SHOTS
        + [{"role": "user", "content": build_prompt(detection)}]
    )


def get_system() -> str:
    return SYSTEM_PROMPT


REACT_SYSTEM_ADDENDUM = """

ReAct mode: instead of returning the final JSON immediately, you may call read-only tools to gather evidence first.

On every turn, emit exactly ONE JSON object, one of:
1. Tool call: {"thought":"why I need this","action":"<tool_name>","args":{...}}
2. Final answer: {"thought":"summary","final":{"is_credentials":0|1,"status":"REAL|FALSE_POSITIVE|REVIEW","confidence":0.0-1.0,"reasoning":"...","evidence":[...],"agent_trace":{"strategy":"react_triage","checks":[...],"tool_calls":[]}}}

Available tools (all read-only, deterministic, no I/O):
- entropy_check(value): Shannon entropy and character class features
- placeholder_check(value): detect placeholder/masked terms
- context_signal_check(context): password/username/host/reset/ticket/url signals
- file_path_check(file_path): classify path as source/test_fixture/documentation/config
- duplicate_secret_check(value): has this exact value been seen earlier in this run

The runner will execute the tool and feed the result back as {"observation": <tool_result>}. After at most a few tool calls, return the final JSON. Do not invent observations."""


def get_react_system() -> str:
    return SYSTEM_PROMPT + REACT_SYSTEM_ADDENDUM


def format_training_text_binary(detection: Dict[str, Any], label: Dict[str, Any]) -> Dict[str, str]:
    """Return v2 prompt/completion pair with binary and agentic fields."""
    completion = json.dumps(
        {
            "is_credentials": int(label.get("is_credentials", 1 if label.get("status") == "REAL" else 0)),
            "status": label["status"],
            "confidence": label.get("confidence", 0.95),
            "reasoning": label.get("reasoning", ""),
            "evidence": label.get("evidence", label.get("indicators", [])),
            "agent_trace": label.get(
                "agent_trace",
                {"strategy": "supervised_label", "checks": ["source_label"], "tool_calls": []},
            ),
        },
        ensure_ascii=False,
    )
    return {"prompt": build_prompt(detection), "completion": completion}


def format_training_text(detection: Dict[str, Any], label: Dict[str, Any]) -> Dict[str, str]:
    """Backward-compatible formatter; emits the v2 JSON contract."""
    return format_training_text_binary(detection, label)
