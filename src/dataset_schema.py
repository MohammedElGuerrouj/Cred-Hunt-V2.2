"""Shared dataset and classifier schema helpers for CRED-HUUNT v2."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from typing import Any, Dict, Iterable, Optional

VALID_STATUSES = {"REAL", "FALSE_POSITIVE", "REVIEW"}


def compute_entropy(value: Optional[str]) -> float:
    """Compute Shannon entropy per character for a string value."""
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def compute_features(value: Optional[str]) -> Dict[str, Any]:
    """Return deterministic string features used by training and agent evidence."""
    text = value or ""
    return {
        "entropy": compute_entropy(text),
        "length": len(text),
        "has_special": any(not char.isalnum() for char in text),
        "has_upper": any(char.isupper() for char in text),
        "has_lower": any(char.islower() for char in text),
        "has_digit": any(char.isdigit() for char in text),
    }


def derive_is_credentials(status: str) -> int:
    """Derive the binary target from the analyst-facing status."""
    normalized = normalize_status(status)
    return 1 if normalized == "REAL" else 0


def normalize_status(status: Any) -> str:
    """Normalize status text to the project labels."""
    normalized = str(status or "REVIEW").upper().strip().replace(" ", "_")
    return normalized if normalized in VALID_STATUSES else "REVIEW"


def context_hash(context: str) -> str:
    """Stable group key for leakage-safe splitting."""
    digest = hashlib.sha256((context or "").encode("utf-8", errors="ignore")).hexdigest()
    return f"sha256:{digest}"


def make_record(
    *,
    record_id: str,
    source_file: str,
    source_index: int,
    context: str,
    username: Optional[str],
    password: Optional[str],
    status: str,
    distractor_type: Optional[str] = None,
    source_context_hash: Optional[str] = None,
    augmentation_parent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a normalized merged dataset record."""
    normalized_status = normalize_status(status)
    return {
        "record_id": record_id,
        "source_file": source_file,
        "source_index": source_index,
        "context": context or "",
        "username": username or None,
        "password": password if password not in {"", "None", "null", "NULL"} else None,
        "status": normalized_status,
        "is_credentials": derive_is_credentials(normalized_status),
        "distractor_type": distractor_type,
        "source_context_hash": source_context_hash or context_hash(context or ""),
        "augmentation_parent_id": augmentation_parent_id,
        "features": compute_features(password),
    }


def record_to_detection(record: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt a merged dataset record to the runtime detection prompt schema."""
    context = record.get("context") or ""
    username = record.get("username")
    if username and f"username={username}" not in context:
        context = f"username={username}\n{context}"
    return {
        "file_path": record.get("file_path", "synthetic/training_sample"),
        "source": record.get("source_file", "synthetic_dataset"),
        "pattern_name": record.get("pattern_name", "PASSWORD"),
        "matched_value": record.get("password") if record.get("password") is not None else "None",
        "context": context,
    }


def build_label(record: Dict[str, Any], reasoning: Optional[str] = None) -> Dict[str, Any]:
    """Build the supervised completion payload for a normalized record."""
    status = normalize_status(record.get("status"))
    distractor_type = record.get("distractor_type")
    evidence = [f"source:{record.get('source_file', 'unknown')}"]
    if distractor_type:
        evidence.append(f"distractor:{distractor_type}")
    if record.get("username"):
        evidence.append("near username")
    features = record.get("features") or compute_features(record.get("password"))
    if features.get("entropy", 0.0) >= 3.5:
        evidence.append("high entropy")
    return {
        "is_credentials": derive_is_credentials(status),
        "status": status,
        "confidence": 0.98 if status == "REAL" else 0.95,
        "reasoning": reasoning or _default_reasoning(status, distractor_type),
        "evidence": evidence,
        "agent_trace": {
            "strategy": "supervised_label",
            "checks": ["source_label", "features", "context"],
            "tool_calls": [],
        },
    }


def _default_reasoning(status: str, distractor_type: Optional[str]) -> str:
    if status == "REAL":
        return "Pre-classified as a real credential in the source dataset."
    if distractor_type:
        return f"Pre-classified as a false positive with {distractor_type} augmentation."
    return "Pre-classified as a false positive in the source dataset."


def deduplicate_records(records: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Deduplicate merged records while preserving input order."""
    seen = set()
    deduped = []
    for record in records:
        key = (
            record.get("source_context_hash"),
            record.get("password"),
            record.get("status"),
            record.get("distractor_type"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped
