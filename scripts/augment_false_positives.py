#!/usr/bin/env python3
"""False-positive augmentation helpers for CRED-HUUNT v2."""

from __future__ import annotations

import random
import re
import string
import uuid
from typing import Dict, Iterable, List, Optional

PLACEHOLDERS = [
    "your_password",
    "<PASSWORD>",
    "****",
    "xxxxxxxx",
    "changeme",
    "P@ssw0rd",
    "REDACTED",
    "PASSWORD_HERE",
    "***hidden***",
]

DICTIONARY_WORDS = [
    "password",
    "secret",
    "token",
    "admin",
    "temporary",
    "credential",
    "example",
    "sample",
    "reset",
    "policy",
]

TOKEN_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+"),
    re.compile(r"\b(?:INC|RITM|CHG)\d+\b", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9_-]+\\[A-Z0-9._-]+\b"),
    re.compile(r"\b\d{4}[-/.]\d{2}[-/.]\d{2}\b"),
    re.compile(r"\b\d{2}[-/.]\d{2}[-/.]\d{4}\b"),
    re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\b", re.IGNORECASE),
]


def _clone_with_password(record: Dict, password: Optional[str], distractor_type: str, suffix: str) -> Dict:
    clone = dict(record)
    parent_id = record["record_id"]
    clone.update(
        {
            "record_id": f"{parent_id}-aug-{suffix}",
            "password": password,
            "status": "FALSE_POSITIVE",
            "is_credentials": 0,
            "distractor_type": distractor_type,
            "augmentation_parent_id": parent_id,
        }
    )
    return clone


def gen_none(rng: random.Random) -> Optional[str]:
    return rng.choice([None, "", "None", "null"])


def gen_placeholder(rng: random.Random) -> str:
    return rng.choice(PLACEHOLDERS)


def gen_context_token(context: str, rng: random.Random) -> Optional[str]:
    candidates: List[str] = []
    for pattern in TOKEN_PATTERNS:
        candidates.extend(match.group(0) for match in pattern.finditer(context or ""))
    if not candidates:
        return None
    return rng.choice(candidates)


def gen_dictionary_word(rng: random.Random) -> str:
    return rng.choice(DICTIONARY_WORDS)


def gen_high_entropy_non_secret(rng: random.Random) -> str:
    choice = rng.choice(["uuid", "sha1", "sha256"])
    if choice == "uuid":
        return str(uuid.UUID(int=rng.getrandbits(128)))
    alphabet = string.hexdigits.lower()[:16]
    size = 40 if choice == "sha1" else 64
    return "".join(rng.choice(alphabet) for _ in range(size))


def gen_hard_negative(true_passwords: List[str], rng: random.Random) -> str:
    if true_passwords:
        return rng.choice(true_passwords)
    return gen_high_entropy_non_secret(rng)


def augment_false_positive(record: Dict, true_passwords: List[str], rng: random.Random) -> List[Dict]:
    """Return three tiered augmented variants for one false-positive record."""
    variants: List[Dict] = []

    if rng.random() < 0.5:
        variants.append(_clone_with_password(record, gen_none(rng), "none_literal", "none"))
    else:
        variants.append(_clone_with_password(record, gen_placeholder(rng), "placeholder", "placeholder"))

    context_token = gen_context_token(record.get("context", ""), rng)
    if context_token and rng.random() < 0.7:
        variants.append(_clone_with_password(record, context_token, "context_token", "context-token"))
    else:
        variants.append(_clone_with_password(record, gen_dictionary_word(rng), "dictionary_word", "dictionary"))

    if rng.random() < 0.5:
        variants.append(_clone_with_password(record, gen_high_entropy_non_secret(rng), "high_entropy_non_secret", "high-entropy"))
    else:
        variants.append(_clone_with_password(record, gen_hard_negative(true_passwords, rng), "hard_negative", "hard-negative"))

    return variants


def augment_false_positives(records: Iterable[Dict], true_passwords: List[str], seed: int = 42) -> List[Dict]:
    rng = random.Random(seed)
    augmented: List[Dict] = []
    for record in records:
        augmented.extend(augment_false_positive(record, true_passwords, rng))
    return augmented
