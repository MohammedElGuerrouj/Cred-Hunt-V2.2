#!/usr/bin/env python3
"""Reasoning strategy runner for local Ollama credential benchmarks."""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))
from llm_client import call_llm, normalize_llm_result, parse_json_safely  # noqa: E402
from prompt_builder import build_prompt, get_react_system, get_system  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from react_tools import TOOL_REGISTRY, run_basic_tools  # noqa: E402

REACT_MAX_STEPS = 3


def record_to_detection(record: Dict[str, Any]) -> Dict[str, Any]:
    if "prompt" in record and "context" not in record:
        return _prompt_to_detection(record["prompt"])
    return {
        "file_path": record.get("file_path", "synthetic/training_sample"),
        "source": record.get("source_file", record.get("source", "benchmark")),
        "pattern_name": record.get("pattern_name", "PASSWORD"),
        "matched_value": record.get("password") if record.get("password") is not None else "None",
        "context": record.get("context", ""),
    }


def _prompt_to_detection(prompt: str) -> Dict[str, Any]:
    file_match = re.search(r"File:\s*(.*?)\s*\|", prompt)
    source_match = re.search(r"Source:\s*(.*?)\n", prompt)
    pattern_match = re.search(r"Pattern:\s*(.*?)\s*\|", prompt)
    match_match = re.search(r"Match:\s*(.*?)\nContext:", prompt, re.DOTALL)
    context_match = re.search(r"Context:\n(.*)", prompt, re.DOTALL)
    return {
        "file_path": file_match.group(1).strip() if file_match else "synthetic/training_sample",
        "source": source_match.group(1).strip() if source_match else "benchmark",
        "pattern_name": pattern_match.group(1).strip() if pattern_match else "PASSWORD",
        "matched_value": match_match.group(1).strip() if match_match else "None",
        "context": context_match.group(1).strip() if context_match else "",
    }


def build_strategy_prompt(detection: Dict[str, Any], strategy: str, tool_summary: Optional[Dict[str, Any]] = None) -> str:
    base = build_prompt(detection)
    if strategy == "direct_json":
        return base
    if strategy == "few_shot":
        return base + "\n\nUse the examples from the system prompt and return only the required JSON."
    if strategy == "cot_distilled":
        return base + "\n\nReturn concise analyst-facing reasoning and evidence. Do not output hidden chain-of-thought."
    if strategy == "tool_assisted":
        return base + "\n\nRead-only tool results:\n" + json.dumps(tool_summary or {}, ensure_ascii=False)
    if strategy == "react_triage":
        return base + "\n\nBegin the ReAct loop. Emit one JSON object per turn."
    return base


BORDERLINE_LOWER = 0.4
BORDERLINE_UPPER = 0.6


def run_strategy(
    record: Dict[str, Any],
    *,
    model: str,
    strategy: str,
    samples: int = 5,
    temperature: float = 0.0,
    test_mode: bool = False,
) -> Dict[str, Any]:
    detection = record_to_detection(record)
    if strategy == "self_consistency":
        return _run_self_consistency(detection, model=model, samples=samples, test_mode=test_mode)
    if strategy == "react_triage":
        return _run_react_iterative(detection, model=model, test_mode=test_mode)

    tool_summary = None
    if strategy == "tool_assisted":
        tool_summary = run_basic_tools(detection.get("matched_value"), detection.get("context", ""), detection.get("file_path", ""))

    prompt = build_strategy_prompt(detection, strategy, tool_summary)
    raw = call_llm(
        prompt,
        get_system(),
        test_mode=test_mode,
        model=model,
        temperature=temperature,
        return_raw=True,
    )
    result = normalize_llm_result(raw.get("parsed", raw), strategy=strategy, model=model)
    result["raw_response"] = raw.get("raw_response")
    if tool_summary:
        result.setdefault("agent_trace", {})["tool_calls"] = tool_summary["tool_calls"]
    return result


def _needs_escalation(result: Dict[str, Any]) -> bool:
    """Self-consistency gate: borderline confidence or REVIEW status."""
    confidence = float(result.get("confidence", 0.5))
    status = str(result.get("status", "REVIEW")).upper()
    if status == "REVIEW":
        return True
    return BORDERLINE_LOWER <= confidence <= BORDERLINE_UPPER


def _run_self_consistency(detection: Dict[str, Any], *, model: str, samples: int, test_mode: bool) -> Dict[str, Any]:
    """Gated self-consistency: cheap call first; escalate to N samples only on borderline cases."""
    first_raw = call_llm(
        build_strategy_prompt(detection, "few_shot"),
        get_system(),
        test_mode=test_mode,
        model=model,
        temperature=0.0,
        return_raw=True,
    )
    first = normalize_llm_result(first_raw.get("parsed", first_raw), strategy="self_consistency", model=model)

    if not _needs_escalation(first):
        first.setdefault("agent_trace", {})
        first["agent_trace"]["escalated"] = False
        first["agent_trace"]["strategy"] = "self_consistency"
        first["agent_trace"]["samples"] = 1
        first["raw_response"] = first_raw.get("raw_response")
        return first

    votes: List[int] = [int(first.get("is_credentials", 0))]
    statuses: List[str] = [first.get("status", "REVIEW")]
    confidences: List[float] = [float(first.get("confidence", 0.5))]
    raw_samples: List[Dict[str, Any]] = [first]
    for _ in range(samples - 1):
        raw = call_llm(
            build_strategy_prompt(detection, "few_shot"),
            get_system(),
            test_mode=test_mode,
            model=model,
            temperature=0.3,
            return_raw=True,
        )
        parsed = normalize_llm_result(raw.get("parsed", raw), strategy="self_consistency_sample", model=model)
        votes.append(int(parsed.get("is_credentials", 0)))
        statuses.append(parsed.get("status", "REVIEW"))
        confidences.append(float(parsed.get("confidence", 0.5)))
        raw_samples.append(parsed)

    positive_votes = sum(votes)
    predicted_is_credentials = 1 if positive_votes > samples / 2 else 0
    if predicted_is_credentials:
        status = "REAL"
    else:
        non_real = [status for status in statuses if status != "REAL"]
        status = max(set(non_real or ["FALSE_POSITIVE"]), key=(non_real or ["FALSE_POSITIVE"]).count)
    confidence = statistics.mean(confidences) if confidences else 0.5
    return normalize_llm_result(
        {
            "is_credentials": predicted_is_credentials,
            "status": status,
            "confidence": confidence,
            "reasoning": "Majority vote from self-consistency samples after borderline gate triggered.",
            "evidence": ["self-consistency majority vote"],
            "agent_trace": {
                "strategy": "self_consistency",
                "escalated": True,
                "samples": samples,
                "votes": {"is_credentials_1": positive_votes, "is_credentials_0": samples - positive_votes},
                "sample_statuses": statuses,
            },
            "raw_samples": raw_samples,
        },
        strategy="self_consistency",
        model=model,
    )


def _parse_react_turn(text: str) -> Dict[str, Any]:
    """Parse one ReAct turn. Returns a dict that may contain 'action'/'args' or 'final'."""
    parsed, _ = parse_json_safely(text or "")
    return parsed if isinstance(parsed, dict) else {}


def _run_react_iterative(
    detection: Dict[str, Any],
    *,
    model: str,
    test_mode: bool,
    max_steps: int = REACT_MAX_STEPS,
) -> Dict[str, Any]:
    """Iterative ReAct loop: model emits thought/action, runner executes tool, feeds observation back."""
    system = get_react_system()
    transcript: List[Dict[str, Any]] = []
    tool_calls: List[Dict[str, Any]] = []
    seen_hashes: set = set()
    current_prompt = build_strategy_prompt(detection, "react_triage")

    for step in range(max_steps):
        raw = call_llm(
            current_prompt,
            system,
            test_mode=test_mode,
            model=model,
            temperature=0.0,
            return_raw=True,
        )
        raw_text = raw.get("raw_response", "") or ""
        turn = _parse_react_turn(raw_text)
        transcript.append({"step": step, "raw": raw_text, "parsed": turn})

        if "final" in turn and isinstance(turn["final"], dict):
            final_obj = dict(turn["final"])
            agent_trace = final_obj.get("agent_trace") or {}
            if not isinstance(agent_trace, dict):
                agent_trace = {}
            agent_trace["strategy"] = "react_triage"
            agent_trace["tool_calls"] = tool_calls
            agent_trace["steps"] = step + 1
            agent_trace["terminated"] = "final"
            final_obj["agent_trace"] = agent_trace
            result = normalize_llm_result(final_obj, strategy="react_triage", model=model)
            result["raw_response"] = raw_text
            result["react_transcript"] = transcript
            return result

        action = turn.get("action")
        args = turn.get("args") if isinstance(turn.get("args"), dict) else {}
        if action in TOOL_REGISTRY:
            if action == "duplicate_secret_check":
                args = {**args, "_seen_hashes": seen_hashes}
            observation = TOOL_REGISTRY[action](detection, args)
            tool_calls.append({"tool": action, "args": {k: v for k, v in args.items() if not k.startswith("_")}, "observation": observation})
            if action == "duplicate_secret_check" and observation.get("value_hash"):
                seen_hashes.add(observation["value_hash"])
            current_prompt = (
                build_strategy_prompt(detection, "react_triage")
                + "\n\nPrevious actions:\n"
                + json.dumps(tool_calls, ensure_ascii=False)
                + "\n\nEmit the next JSON object (another action, or the final answer)."
            )
            continue

        # Unparseable turn or unknown action: break out and fall back.
        break

    # Fallback: forced direct_json call if iterations exhausted or model derailed.
    fallback_raw = call_llm(
        build_prompt(detection),
        get_system(),
        test_mode=test_mode,
        model=model,
        temperature=0.0,
        return_raw=True,
    )
    fallback = normalize_llm_result(fallback_raw.get("parsed", fallback_raw), strategy="react_triage", model=model)
    fallback.setdefault("agent_trace", {})
    fallback["agent_trace"]["tool_calls"] = tool_calls
    fallback["agent_trace"]["steps"] = len(transcript)
    fallback["agent_trace"]["terminated"] = "fallback_direct_json"
    fallback["raw_response"] = fallback_raw.get("raw_response")
    fallback["react_transcript"] = transcript
    return fallback
