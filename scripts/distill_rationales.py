#!/usr/bin/env python3
"""Generate teacher rationales for CRED-HUUNT v2 records.

For each prompt/completion pair in an input JSONL (e.g. data/training_data_binary.jsonl),
call a stronger Ollama model and ask it to produce a concise analyst-facing rationale
plus a short evidence list. The teacher receives the same prompt the student sees and is
told the ground-truth label so the rationale is consistent with that label.

Outputs a JSONL with one record per input line:
    {"record_id": "...", "is_credentials": 0|1, "status": "...",
     "reasoning": "<teacher rationale>", "evidence": ["...", ...]}

Use scripts/process_synthetic_training_data.py --rationales <output.jsonl> to splice
these rationales into the training labels.

Teacher options (Ollama tags):
    qwen2.5-coder:7b   recommended for code/config context
    qwen2.5:7b         general
    granite3.3:8b      IBM agentic
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llm_client import call_llm, parse_json_safely  # noqa: E402

TEACHER_SYSTEM = """You are an expert security analyst writing training rationales for a credential-detection model.

You will be shown a detection record (file path, pattern, matched value, surrounding context) AND the ground-truth label (is_credentials, status). Your job: produce a short, analyst-facing rationale that explains WHY the ground-truth label is correct, plus a small list of concrete evidence strings grounded in the input.

Rules:
- Be specific to THIS record. No boilerplate.
- Reasoning must be 1-2 sentences, plain English, no chain-of-thought.
- Evidence is a list of 2-5 short signals you can point to in the context, value, or path (e.g. "password-like key DB_PASS", "reset URL", "AKIA prefix", "high entropy", "documentation path", "placeholder term YOUR_").
- Do NOT contradict the ground-truth label.
- Output ONLY valid JSON of the form: {"reasoning":"...","evidence":["...","..."]}
"""


def build_teacher_prompt(record: Dict[str, Any]) -> str:
    student_prompt = record.get("prompt", "")
    status = record.get("status", "REVIEW")
    is_credentials = record.get("is_credentials")
    distractor = record.get("distractor_type") or "original"
    return (
        f"{student_prompt}\n\n"
        f"Ground-truth label:\n"
        f"  is_credentials = {is_credentials}\n"
        f"  status = {status}\n"
        f"  distractor_type = {distractor}\n\n"
        "Produce the JSON rationale now."
    )


def load_done_ids(path: Path) -> set:
    if not path.exists():
        return set()
    ids: set = set()
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = entry.get("record_id")
            if rid:
                ids.add(rid)
    return ids


def distill_one(record: Dict[str, Any], teacher: str, test_mode: bool, timeout: int) -> Optional[Dict[str, Any]]:
    prompt = build_teacher_prompt(record)
    raw = call_llm(
        prompt,
        TEACHER_SYSTEM,
        test_mode=test_mode,
        model=teacher,
        temperature=0.2,
        timeout=timeout,
        return_raw=True,
    )
    raw_text = raw.get("raw_response", "") if isinstance(raw, dict) else ""
    parsed, ok = parse_json_safely(raw_text) if raw_text else ({}, False)
    if not ok:
        # In test_mode call_llm returns a normalized v2 object; salvage its reasoning/evidence.
        candidate = raw.get("parsed") if isinstance(raw, dict) else None
        if isinstance(candidate, dict) and (candidate.get("reasoning") or candidate.get("evidence")):
            parsed = candidate
            ok = True
    if not ok:
        return None

    reasoning = parsed.get("reasoning")
    evidence = parsed.get("evidence")
    if not isinstance(reasoning, str) or not reasoning.strip():
        return None
    if not isinstance(evidence, list):
        evidence = [str(evidence)] if evidence else []
    return {
        "record_id": record.get("record_id"),
        "is_credentials": record.get("is_credentials"),
        "status": record.get("status"),
        "reasoning": reasoning.strip(),
        "evidence": [str(item) for item in evidence][:5],
        "teacher": teacher,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate teacher rationales for cot_distilled training.")
    parser.add_argument("--teacher", default="qwen2.5-coder:7b", help="Ollama tag for the teacher model.")
    parser.add_argument("--input", required=True, help="Input JSONL (training_data_binary.jsonl or similar).")
    parser.add_argument("--output", required=True, help="Output JSONL of rationales.")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on number of records.")
    parser.add_argument("--resume", action="store_true", help="Skip record_ids already present in output.")
    parser.add_argument("--test-mode", action="store_true", help="Use the LLM client's heuristic fake response.")
    parser.add_argument("--timeout", type=int, default=120, help="Per-call Ollama timeout in seconds.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    done_ids = load_done_ids(output_path) if args.resume else set()
    mode = "a" if args.resume and output_path.exists() else "w"

    processed = 0
    skipped = 0
    failed = 0
    with open(input_path, "r", encoding="utf-8") as src, open(output_path, mode, encoding="utf-8") as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            rid = record.get("record_id")
            if rid in done_ids:
                skipped += 1
                continue
            if args.limit and processed >= args.limit:
                break
            result = distill_one(record, teacher=args.teacher, test_mode=args.test_mode, timeout=args.timeout)
            if result is None:
                failed += 1
                continue
            dst.write(json.dumps(result, ensure_ascii=False) + "\n")
            dst.flush()
            processed += 1
            if processed % 25 == 0:
                print(f"  processed={processed} skipped={skipped} failed={failed}")

    print(f"Done. processed={processed} skipped={skipped} failed={failed} -> {output_path}")


if __name__ == "__main__":
    main()
