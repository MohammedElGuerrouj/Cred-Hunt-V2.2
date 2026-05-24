#!/usr/bin/env python3
"""Read-only deterministic tools for agentic credential triage."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))
from dataset_schema import compute_features  # noqa: E402

PLACEHOLDER_TERMS = [
    "your_",
    "example",
    "sample",
    "demo",
    "dummy",
    "fake",
    "changeme",
    "placeholder",
    "password123",
    "xxxx",
    "redacted",
]


def entropy_check(value: Optional[str]) -> Dict[str, Any]:
    features = compute_features(value)
    return {"tool": "entropy_check", "status": "ok", "features": features}


def placeholder_check(value: Optional[str]) -> Dict[str, Any]:
    lowered = (value or "").lower()
    matched = [term for term in PLACEHOLDER_TERMS if term in lowered]
    return {"tool": "placeholder_check", "status": "ok", "matched_terms": matched, "is_placeholder": bool(matched)}


def context_signal_check(context: str) -> Dict[str, Any]:
    text = context or ""
    signals = {
        "has_password_key": bool(re.search(r"\b(pass|password|pwd|secret|token|key)\b", text, re.IGNORECASE)),
        "has_username": bool(re.search(r"\b(user|username|login|account|cuenta|correo|utenza)\b", text, re.IGNORECASE)),
        "has_host": bool(re.search(r"\b(host|url|server|db_host)\b", text, re.IGNORECASE)),
        "has_reset_language": bool(re.search(r"reset|recover|policy|expired|change password", text, re.IGNORECASE)),
        "has_ticket": bool(re.search(r"\b(?:INC|RITM|CHG)\d+\b", text, re.IGNORECASE)),
        "has_url": bool(re.search(r"https?://", text, re.IGNORECASE)),
    }
    return {"tool": "context_signal_check", "status": "ok", "signals": signals}


def file_path_check(file_path: str) -> Dict[str, Any]:
    path = (file_path or "").lower().replace("\\", "/")
    path_class = "source"
    if any(part in path for part in ["test", "tests", "fixture", "sample", "dummy"]):
        path_class = "test_fixture"
    elif any(part in path for part in ["readme", "docs", "documentation"]):
        path_class = "documentation"
    elif any(part in path for part in ["prod", ".env", "config", "settings", "deploy", "workflow"]):
        path_class = "config"
    return {"tool": "file_path_check", "status": "ok", "path_class": path_class}


def duplicate_secret_check(value: Optional[str], seen_hashes: Optional[set] = None) -> Dict[str, Any]:
    """Check if value's hash was seen earlier in this run. Hashes are sha256 truncated to 16 chars."""
    if not value:
        return {"tool": "duplicate_secret_check", "status": "ok", "value_hash": None, "is_duplicate": False}
    digest = hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]
    is_dup = bool(seen_hashes and digest in seen_hashes)
    return {"tool": "duplicate_secret_check", "status": "ok", "value_hash": digest, "is_duplicate": is_dup}


# Tool dispatch registry — runner uses this to map model-emitted action names to functions.
# Each entry adapts a (detection, args) tuple to the underlying check.
def _dispatch_entropy(detection: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    return entropy_check(args.get("value", detection.get("matched_value")))


def _dispatch_placeholder(detection: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    return placeholder_check(args.get("value", detection.get("matched_value")))


def _dispatch_context_signal(detection: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    return context_signal_check(args.get("context", detection.get("context", "")))


def _dispatch_file_path(detection: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    return file_path_check(args.get("file_path", detection.get("file_path", "")))


def _dispatch_duplicate(detection: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    seen = args.get("_seen_hashes") if isinstance(args, dict) else None
    return duplicate_secret_check(args.get("value", detection.get("matched_value")), seen_hashes=seen)


TOOL_REGISTRY: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = {
    "entropy_check": _dispatch_entropy,
    "placeholder_check": _dispatch_placeholder,
    "context_signal_check": _dispatch_context_signal,
    "file_path_check": _dispatch_file_path,
    "duplicate_secret_check": _dispatch_duplicate,
}


def run_basic_tools(value: Optional[str], context: str, file_path: str) -> Dict[str, Any]:
    """Single-shot batch used by the back-compat `tool_assisted` strategy."""
    calls = [
        entropy_check(value),
        placeholder_check(value),
        context_signal_check(context),
        file_path_check(file_path),
    ]
    return {"tool_calls": calls}
