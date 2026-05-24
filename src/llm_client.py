"""Ollama client and response normalization for CRED-HUUNT v2."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests

from dataset_schema import derive_is_credentials, normalize_status

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5-coder:3b"


def call_llm(
    prompt: str,
    system: str,
    test_mode: bool = False,
    *,
    model: Optional[str] = None,
    temperature: float = 0.0,
    timeout: int = 120,
    return_raw: bool = False,
) -> Dict[str, Any]:
    """Call Ollama and return a normalized v2 decision object."""
    selected_model = model or MODEL
    if test_mode:
        parsed = _fake_response(prompt, selected_model)
        return {"parsed": parsed, "raw_response": json.dumps(parsed), "json_valid": True} if return_raw else parsed

    payload = {
        "model": selected_model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": 4096,
            "num_thread": 4,
        },
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        response.raise_for_status()
        raw_text = response.json().get("response", "")
        parsed, json_valid = parse_json_safely(raw_text)
        normalized = normalize_llm_result(parsed, strategy="direct_json", model=selected_model, json_valid=json_valid)
        if return_raw:
            return {"parsed": normalized, "raw_response": raw_text, "json_valid": json_valid}
        return normalized
    except Exception as exc:
        fallback = normalize_llm_result(
            {
                "status": "REVIEW",
                "confidence": 0.5,
                "reasoning": f"LLM error: {exc}",
                "evidence": ["llm_error"],
            },
            strategy="direct_json",
            model=selected_model,
            json_valid=False,
        )
        if return_raw:
            return {"parsed": fallback, "raw_response": "", "json_valid": False}
        return fallback


def parse_json_safely(text: str) -> tuple[Dict[str, Any], bool]:
    """Parse a JSON object from model text, allowing surrounding text."""
    if not text:
        return {}, False
    try:
        return json.loads(text), True
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
            if isinstance(obj, dict):
                return obj, True
        except json.JSONDecodeError:
            continue
    return {}, False


def normalize_llm_result(
    result: Dict[str, Any],
    *,
    strategy: str,
    model: str,
    json_valid: bool = True,
) -> Dict[str, Any]:
    """Ensure every response matches the v2 classifier contract."""
    status = normalize_status(result.get("status"))
    if "is_credentials" in result:
        is_credentials = 1 if int(bool(result.get("is_credentials"))) else 0
        if status == "REVIEW" and is_credentials == 1:
            status = "REAL"
    else:
        is_credentials = derive_is_credentials(status)

    confidence = result.get("confidence", 0.5)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    evidence = result.get("evidence", result.get("indicators", []))
    if isinstance(evidence, str):
        evidence = [evidence]
    if not isinstance(evidence, list):
        evidence = []

    agent_trace = result.get("agent_trace") or {}
    if not isinstance(agent_trace, dict):
        agent_trace = {}
    agent_trace.setdefault("strategy", strategy)
    agent_trace.setdefault("checks", [])
    agent_trace.setdefault("tool_calls", [])
    agent_trace.setdefault("model", model)

    return {
        "is_credentials": is_credentials,
        "status": status,
        "confidence": confidence,
        "reasoning": str(result.get("reasoning") or "No reasoning provided."),
        "evidence": evidence,
        "indicators": evidence,
        "agent_trace": agent_trace,
        "json_valid": json_valid,
    }


def _fake_response(prompt: str, model: str) -> Dict[str, Any]:
    matched_value = ""
    if "Match: " in prompt:
        start = prompt.find("Match: ") + len("Match: ")
        end = prompt.find("\n", start)
        matched_value = prompt[start:end if end != -1 else None].strip()
    lower_prompt = prompt.lower()
    lower_value = matched_value.lower()

    placeholder_terms = ["test", "example", "placeholder", "your_", "replace", "demo", "sample", "xxx", "changeme", "password123", "none", "null"]
    reset_terms = ["reset", "recover", "policy", "expired", "password help", "password update"]
    if any(term in lower_value for term in placeholder_terms) or any(term in lower_prompt for term in reset_terms):
        return normalize_llm_result(
            {
                "is_credentials": 0,
                "status": "FALSE_POSITIVE",
                "confidence": 0.9,
                "reasoning": "Contains placeholder or password reset/policy indicators.",
                "evidence": ["placeholder_or_reset_context"],
            },
            strategy="test_mode",
            model=model,
        )

    if (
        (len(matched_value) > 20 and any(char in matched_value for char in "!@#$%^&*"))
        or "bearer " in lower_prompt
        or matched_value.startswith("AKIA")
        or (matched_value.count("-") >= 4 and len(matched_value) > 30)
    ):
        return normalize_llm_result(
            {
                "is_credentials": 1,
                "status": "REAL",
                "confidence": 0.85,
                "reasoning": "Value appears credential-like based on format and context.",
                "evidence": ["credential_format"],
            },
            strategy="test_mode",
            model=model,
        )

    return normalize_llm_result(
        {
            "is_credentials": 0,
            "status": "REVIEW",
            "confidence": 0.6,
            "reasoning": "Uncertain classification.",
            "evidence": ["ambiguous"],
        },
        strategy="test_mode",
        model=model,
    )
