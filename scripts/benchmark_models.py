#!/usr/bin/env python3
"""Benchmark local Ollama models across CRED-HUUNT reasoning strategies."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

from reasoning_runner import run_strategy

REQUIRED_SCHEMA_FIELDS = {"is_credentials", "status", "confidence", "reasoning", "evidence", "agent_trace"}
VALID_STATUSES = {"REAL", "FALSE_POSITIVE", "REVIEW"}
GROUNDED_PREFIXES = ("source:", "distractor:", "near ", "high entropy", "low entropy", "no ", "placeholder", "documentation")


def record_grounding_text(record: Dict[str, Any]) -> str:
    """Concatenate fields that evidence strings can legitimately point to."""
    parts = [
        record.get("context", "") or "",
        record.get("password", "") or "",
        record.get("matched_value", "") or "",
        record.get("file_path", "") or "",
        record.get("prompt", "") or "",
    ]
    return " ".join(parts).lower()


def schema_valid(result: Dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    if not REQUIRED_SCHEMA_FIELDS.issubset(result.keys()):
        return False
    if result.get("status") not in VALID_STATUSES:
        return False
    if not isinstance(result.get("evidence"), list):
        return False
    if not isinstance(result.get("agent_trace"), dict):
        return False
    try:
        conf = float(result.get("confidence", -1))
    except (TypeError, ValueError):
        return False
    return 0.0 <= conf <= 1.0 and int(result.get("is_credentials", -1)) in (0, 1)


def evidence_grounding_score(evidence: List[str], grounding_text: str) -> float:
    """Fraction of evidence items that map to either the grounding text or a known grounded prefix."""
    if not evidence:
        return 0.0
    grounded = 0
    for item in evidence:
        s = str(item).lower().strip()
        if not s:
            continue
        if any(s.startswith(prefix) for prefix in GROUNDED_PREFIXES):
            grounded += 1
            continue
        # Token-level check: at least one non-trivial word from evidence appears in grounding text.
        tokens = [t for t in re.split(r"[\s,:;]+", s) if len(t) >= 3]
        if any(tok in grounding_text for tok in tokens):
            grounded += 1
    return grounded / len(evidence)


def percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = min(len(sorted_vals) - 1, int(round((q / 100.0) * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def expected_is_credentials(record: Dict[str, Any]) -> int:
    if "is_credentials" in record:
        return int(record["is_credentials"])
    status = record.get("status") or ""
    return 1 if str(status).upper() == "REAL" else 0


def compute_binary_metrics(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    tp = sum(1 for row in rows if row["expected_is_credentials"] == 1 and row["predicted_is_credentials"] == 1)
    tn = sum(1 for row in rows if row["expected_is_credentials"] == 0 and row["predicted_is_credentials"] == 0)
    fp = sum(1 for row in rows if row["expected_is_credentials"] == 0 and row["predicted_is_credentials"] == 1)
    fn = sum(1 for row in rows if row["expected_is_credentials"] == 1 and row["predicted_is_credentials"] == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(rows) if rows else 0.0
    return {"accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1, "tp": tp, "tn": tn, "fp": fp, "fn": fn}


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["model"], row["strategy"])].append(row)

    runs = []
    for (model, strategy), items in sorted(grouped.items()):
        binary = compute_binary_metrics(items)
        hard_items = [item for item in items if item.get("distractor_type") == "hard_negative"]
        hard_metrics = compute_binary_metrics(hard_items) if hard_items else {"recall": None}
        latencies = [item["latency_ms"] for item in items]
        escalation_flags = [item.get("escalated") for item in items if item.get("escalated") is not None]
        escalation_rate = (sum(1 for flag in escalation_flags if flag) / len(escalation_flags)) if escalation_flags else None
        runs.append(
            {
                "model": model,
                "strategy": strategy,
                "n": len(items),
                "binary_precision": binary["precision"],
                "binary_recall": binary["recall"],
                "binary_f1": binary["f1"],
                "accuracy": binary["accuracy"],
                "hard_negative_recall": hard_metrics.get("recall"),
                "json_validity_rate": sum(1 for item in items if item["json_valid"]) / len(items),
                "schema_validity_rate": sum(1 for item in items if item.get("schema_valid")) / len(items),
                "evidence_grounding_score": (
                    sum(item.get("evidence_grounding", 0.0) for item in items) / len(items)
                ),
                "avg_latency_ms": statistics.mean(latencies),
                "p95_latency_ms": percentile(latencies, 95),
                "p99_latency_ms": percentile(latencies, 99),
                "review_rate": sum(1 for item in items if item.get("predicted_status") == "REVIEW") / len(items),
                "escalation_rate": escalation_rate,
                "confusion": Counter((item["expected_is_credentials"], item["predicted_is_credentials"]) for item in items),
            }
        )
    return {"runs": runs}


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark CRED-HUUNT models and reasoning strategies.")
    parser.add_argument("--models", nargs="+", default=["qwen2.5-coder:3b", "granite3.3:2b", "llama3.2:3b"])
    parser.add_argument("--strategies", nargs="+", default=["direct_json", "few_shot", "self_consistency"])
    parser.add_argument("--test", default="data/test_data_binary.jsonl")
    parser.add_argument("--output", default="results/benchmark_matrix.jsonl")
    parser.add_argument("--summary", default="results/benchmark_summary.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--test-mode", action="store_true", help="Use deterministic fake LLM responses for smoke tests.")
    args = parser.parse_args()

    records = load_jsonl(Path(args.test))
    if args.limit:
        records = records[: args.limit]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []

    with open(output_path, "w", encoding="utf-8") as handle:
        for model in args.models:
            for strategy in args.strategies:
                print(f"Benchmarking model={model} strategy={strategy} records={len(records)}")
                for index, record in enumerate(records, 1):
                    start = time.perf_counter()
                    result = run_strategy(record, model=model, strategy=strategy, test_mode=args.test_mode)
                    latency_ms = (time.perf_counter() - start) * 1000
                    expected_binary = expected_is_credentials(record)
                    grounding_text = record_grounding_text(record)
                    evidence_list = result.get("evidence", []) if isinstance(result.get("evidence"), list) else []
                    agent_trace = result.get("agent_trace") or {}
                    row = {
                        "record_id": record.get("record_id", str(index)),
                        "model": model,
                        "strategy": strategy,
                        "expected_is_credentials": expected_binary,
                        "predicted_is_credentials": int(result.get("is_credentials", 0)),
                        "expected_status": record.get("status"),
                        "predicted_status": result.get("status"),
                        "confidence": result.get("confidence", 0.5),
                        "json_valid": bool(result.get("json_valid", True)),
                        "schema_valid": schema_valid(result),
                        "evidence_grounding": evidence_grounding_score(evidence_list, grounding_text),
                        "latency_ms": latency_ms,
                        "distractor_type": record.get("distractor_type"),
                        "reasoning": result.get("reasoning", ""),
                        "evidence": evidence_list,
                        "agent_trace": agent_trace,
                        "escalated": agent_trace.get("escalated") if isinstance(agent_trace, dict) else None,
                    }
                    rows.append(row)
                    serializable = dict(row)
                    handle.write(json.dumps(serializable, ensure_ascii=False) + "\n")
                    if index % 100 == 0:
                        print(f"  {index}/{len(records)}")

    summary = summarize(rows)
    for run in summary["runs"]:
        run["confusion"] = {f"{key[0]}->{key[1]}": value for key, value in run["confusion"].items()}
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print(f"Benchmark rows written to {output_path}")
    print(f"Summary written to {summary_path}")


if __name__ == "__main__":
    main()
