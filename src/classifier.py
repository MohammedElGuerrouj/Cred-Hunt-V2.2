import math
from llm_client import call_llm
from prompt_builder import build_prompt, get_system
from dataset_schema import derive_is_credentials, normalize_status

VALID_STATUSES = {"REAL", "FALSE_POSITIVE", "REVIEW"}


def shannon_entropy(s: str) -> float:
    """Quick entropy check — low entropy = likely placeholder."""
    if not s:
        return 0.0
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((f / n) * math.log2(f / n) for f in freq.values())


def _confidence_to_status(confidence: float) -> str:
    """Fallback only: derive a status from confidence when the LLM omitted it."""
    if confidence >= 0.85:
        return "REAL"
    if confidence >= 0.50:
        return "REVIEW"
    return "FALSE_POSITIVE"


def classify(detection: dict, test_mode: bool = False, model: str | None = None) -> dict:
    match = detection.get("matched_value", "")

    # Pre-filter: very low entropy strings are almost always placeholders.
    if shannon_entropy(match) < 2.5:
        return {
            **detection,
            "is_credentials": 0,
            "status": "FALSE_POSITIVE",
            "confidence": 0.95,
            "reasoning": "Low entropy — likely placeholder",
            "evidence": ["entropy < 2.5"],
            "indicators": ["entropy < 2.5"],
            "agent_trace": {
                "strategy": "deterministic_prefilter",
                "checks": ["entropy"],
                "tool_calls": [],
                "model": model or "prefilter",
            },
            "json_valid": True,
            "skipped_llm": True,
        }

    prompt = build_prompt(detection)
    result = call_llm(prompt, get_system(), test_mode=test_mode, model=model)

    # Trust the model's explicit status when it's valid; only fall back to
    # confidence-based bucketing if the model failed to return one.
    raw_status = normalize_status(result.get("status"))
    if raw_status in VALID_STATUSES:
        status = raw_status
    else:
        status = _confidence_to_status(float(result.get("confidence", 0.5)))

    # Don't let the spread operator overwrite our reconciled status.
    merged = {**detection, **result}
    merged["status"] = status
    merged["is_credentials"] = int(result.get("is_credentials", derive_is_credentials(status)))
    merged.setdefault("evidence", result.get("indicators", []))
    merged.setdefault("indicators", merged["evidence"])
    merged.setdefault(
        "agent_trace",
        {"strategy": "direct_json", "checks": ["context", "value", "path"], "tool_calls": [], "model": model},
    )
    merged.setdefault("json_valid", result.get("json_valid", True))
    return merged


def classify_batch(detections: list, test_mode: bool = False, model: str | None = None) -> list:
    return [classify(d, test_mode=test_mode, model=model) for d in detections]
