#!/usr/bin/env python3
"""Evaluate CRED-HUUNT v2 model outputs on a held-out JSONL split."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

LABELS = ["REAL", "FALSE_POSITIVE", "REVIEW"]
REQUIRED_SCHEMA_FIELDS = {"is_credentials", "status", "confidence", "reasoning", "evidence", "agent_trace"}
GROUNDED_PREFIXES = ("source:", "distractor:", "near ", "high entropy", "low entropy", "no ", "placeholder", "documentation")


def schema_valid(parsed: Dict[str, Any]) -> bool:
    if not isinstance(parsed, dict):
        return False
    if not REQUIRED_SCHEMA_FIELDS.issubset(parsed.keys()):
        return False
    if str(parsed.get("status", "")).upper() not in LABELS:
        return False
    if not isinstance(parsed.get("evidence"), list):
        return False
    if not isinstance(parsed.get("agent_trace"), dict):
        return False
    try:
        conf = float(parsed.get("confidence", -1))
    except (TypeError, ValueError):
        return False
    return 0.0 <= conf <= 1.0 and int(parsed.get("is_credentials", -1)) in (0, 1)


def evidence_grounding_score(evidence: List[str], grounding_text: str) -> float:
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


def parse_completion_json(text: str) -> Tuple[Dict[str, Any], bool]:
    if not text:
        return {}, False
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}, isinstance(obj, dict)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
            return obj if isinstance(obj, dict) else {}, isinstance(obj, dict)
        except json.JSONDecodeError:
            continue
    return {}, False


def extract_status(text: str) -> str:
    parsed, valid = parse_completion_json(text)
    if valid and str(parsed.get("status", "")).upper() in LABELS:
        return str(parsed["status"]).upper()
    match = re.search(r'"status"\s*:\s*"([A-Z_]+)"', text)
    if match and match.group(1) in LABELS:
        return match.group(1)
    for label in LABELS:
        if label in text.upper():
            return label
    return "REVIEW"


def expected_status(record: Dict[str, Any]) -> str:
    if "status" in record:
        return str(record["status"]).upper()
    return extract_status(record.get("completion", ""))


def expected_binary(record: Dict[str, Any]) -> int:
    if "is_credentials" in record:
        return int(record["is_credentials"])
    parsed, valid = parse_completion_json(record.get("completion", ""))
    if valid and "is_credentials" in parsed:
        return int(parsed["is_credentials"])
    return 1 if expected_status(record) == "REAL" else 0


def predicted_binary(text: str, status: str) -> int:
    parsed, valid = parse_completion_json(text)
    if valid and "is_credentials" in parsed:
        return int(bool(parsed["is_credentials"]))
    return 1 if status == "REAL" else 0


def predict(model, tokenizer, prompt: str, device, max_new_tokens: int = 160) -> str:
    import torch

    inputs = tokenizer(prompt + "\n", return_tensors="pt").to(device)
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = output[0, inputs["input_ids"].shape[1] :]
    return tokenizer.decode(generated, skip_special_tokens=True)


def compute_binary_metrics(y_true: List[int], y_pred: List[int]) -> Dict[str, float]:
    tp = sum(1 for true, pred in zip(y_true, y_pred) if true == 1 and pred == 1)
    tn = sum(1 for true, pred in zip(y_true, y_pred) if true == 0 and pred == 0)
    fp = sum(1 for true, pred in zip(y_true, y_pred) if true == 0 and pred == 1)
    fn = sum(1 for true, pred in zip(y_true, y_pred) if true == 1 and pred == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(y_true) if y_true else 0.0
    return {"accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1, "tp": tp, "tn": tn, "fp": fp, "fn": fn}


def compute_multiclass_metrics(y_true: List[str], y_pred: List[str]) -> Dict[str, Any]:
    confusion = {label: Counter() for label in LABELS}
    for true, pred in zip(y_true, y_pred):
        confusion.setdefault(true, Counter())[pred] += 1

    per_class = {}
    for label in LABELS:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in LABELS if other != label)
        fn = sum(confusion[label][other] for other in LABELS if other != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"support": sum(confusion[label].values()), "precision": precision, "recall": recall, "f1": f1}
    macro_f1 = sum(item["f1"] for item in per_class.values()) / len(LABELS)
    accuracy = sum(1 for true, pred in zip(y_true, y_pred) if true == pred) / len(y_true) if y_true else 0.0
    return {"accuracy": accuracy, "macro_f1": macro_f1, "per_class": per_class, "confusion": {key: dict(value) for key, value in confusion.items()}}


def slice_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_distractor: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_distractor[row.get("distractor_type") or "original"].append(row)
    return {
        key: compute_binary_metrics([item["expected_binary"] for item in items], [item["predicted_binary"] for item in items])
        for key, items in by_distractor.items()
    }


def print_report(metrics: Dict[str, Any]) -> None:
    print("\n" + "=" * 70)
    print("CRED-HUUNT V2 EVALUATION REPORT")
    print("=" * 70)
    print(f"Examples: {metrics['n']}")
    binary = metrics["binary"]
    print(f"Binary F1: {binary['f1'] * 100:.2f}%")
    print(f"Binary precision: {binary['precision'] * 100:.2f}%")
    print(f"Binary recall: {binary['recall'] * 100:.2f}%")
    print(f"JSON validity: {metrics['json_validity_rate'] * 100:.2f}%")
    print(f"Schema validity: {metrics['schema_validity_rate'] * 100:.2f}%")
    print(f"Evidence grounding: {metrics['evidence_grounding_score'] * 100:.2f}%")
    print(f"Average latency: {metrics['avg_latency_ms']:.1f} ms (p95={metrics['p95_latency_ms']:.1f} p99={metrics['p99_latency_ms']:.1f})")
    print("\nMulticlass:")
    print(f"Accuracy: {metrics['multiclass']['accuracy'] * 100:.2f}%")
    print(f"Macro F1: {metrics['multiclass']['macro_f1'] * 100:.2f}%")
    print("\nDistractor slices:")
    for name, values in metrics["slices"].items():
        print(f"  {name}: n={values['tp'] + values['tn'] + values['fp'] + values['fn']} f1={values['f1'] * 100:.2f}% recall={values['recall'] * 100:.2f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a base model or LoRA adapter on CRED-HUUNT JSONL data.")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-Coder-3B")
    parser.add_argument("--adapter", default="./lora-credentials-detector")
    parser.add_argument("--test", default="data/test_data_binary.jsonl")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--report", default="data/evaluation_report.json")
    parser.add_argument("--no-adapter", action="store_true")
    args = parser.parse_args()

    test_path = Path(args.test)
    if not test_path.exists():
        print(f"Test file not found: {test_path}")
        print("Run: python scripts/process_synthetic_training_data.py")
        return

    records = load_jsonl(test_path)
    if args.limit:
        records = records[: args.limit]
    print(f"Loaded {len(records)} examples from {test_path}")

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        device_map="auto" if device == "cuda" else None,
        trust_remote_code=True,
    )

    if not args.no_adapter and Path(args.adapter).exists():
        from peft import PeftModel

        print(f"Attaching LoRA adapter: {args.adapter}")
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    rows: List[Dict[str, Any]] = []
    for index, record in enumerate(records, 1):
        start = time.perf_counter()
        raw = predict(model, tokenizer, record["prompt"], device)
        latency_ms = (time.perf_counter() - start) * 1000
        parsed, json_valid = parse_completion_json(raw)
        status = extract_status(raw)
        evidence_list = parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else []
        grounding_text = (record.get("prompt", "") or "").lower()
        row = {
            "record_id": record.get("record_id", str(index)),
            "expected_status": expected_status(record),
            "predicted_status": status,
            "expected_binary": expected_binary(record),
            "predicted_binary": predicted_binary(raw, status),
            "json_valid": json_valid,
            "schema_valid": schema_valid(parsed),
            "evidence_grounding": evidence_grounding_score(evidence_list, grounding_text),
            "latency_ms": latency_ms,
            "distractor_type": record.get("distractor_type"),
            "raw_response": raw,
            "parsed_response": parsed,
        }
        rows.append(row)
        if index % 25 == 0 or index == len(records):
            print(f"  {index}/{len(records)} processed")

    y_true_binary = [row["expected_binary"] for row in rows]
    y_pred_binary = [row["predicted_binary"] for row in rows]
    y_true_status = [row["expected_status"] for row in rows]
    y_pred_status = [row["predicted_status"] for row in rows]

    latencies = [row["latency_ms"] for row in rows]
    metrics = {
        "n": len(rows),
        "binary": compute_binary_metrics(y_true_binary, y_pred_binary),
        "multiclass": compute_multiclass_metrics(y_true_status, y_pred_status),
        "json_validity_rate": sum(1 for row in rows if row["json_valid"]) / len(rows) if rows else 0.0,
        "schema_validity_rate": sum(1 for row in rows if row.get("schema_valid")) / len(rows) if rows else 0.0,
        "evidence_grounding_score": (
            sum(row.get("evidence_grounding", 0.0) for row in rows) / len(rows) if rows else 0.0
        ),
        "avg_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "p95_latency_ms": percentile(latencies, 95),
        "p99_latency_ms": percentile(latencies, 99),
        "slices": slice_metrics(rows),
        "rows": rows,
    }
    print_report(metrics)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=2)
    print(f"Report written to: {report_path}")


if __name__ == "__main__":
    main()
