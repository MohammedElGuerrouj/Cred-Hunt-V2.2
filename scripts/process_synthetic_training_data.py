#!/usr/bin/env python3
"""Build the CRED-HUUNT v2 merged, augmented training dataset."""

from __future__ import annotations

import argparse
import ast
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dataset_schema import (  # noqa: E402
    build_label,
    compute_features,
    context_hash,
    deduplicate_records,
    make_record,
    record_to_detection,
)
from prompt_builder import format_training_text_binary  # noqa: E402
from augment_false_positives import augment_false_positives  # noqa: E402

MAX_CONTEXT_CHARS = 600
RANDOM_SEED = 42

DATASET_PATTERN = re.compile(
    r'\(\s*"""(.*?)"""\s*,\s*(None|"[^"]*"|\'[^\']*\'|[^,)]*)\s*,\s*(None|"[^"]*"|\'[^\']*\'|[^)]*)\s*\)',
    re.DOTALL,
)


def _load_tuple_rows(content: str) -> List[Tuple[Any, Any, Any]]:
    """Load rows from the source Python literal dataset, with regex fallback."""
    try:
        module = ast.parse(content)
        for node in module.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "dataset" for target in node.targets):
                literal_rows = ast.literal_eval(node.value)
                rows: List[Tuple[Any, Any, Any]] = []
                for row in literal_rows:
                    if isinstance(row, (tuple, list)) and len(row) >= 3:
                        rows.append((row[0], row[1], row[2]))
                return rows
    except (SyntaxError, ValueError):
        pass

    rows = []
    for match in DATASET_PATTERN.finditer(content):
        rows.append((match.group(1), match.group(2), match.group(3)))
    return rows


def _clean_field(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().rstrip(",")
    if cleaned in {"None", "null", "NULL", ""}:
        return None
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1]
    return cleaned.strip() or None


def parse_preclassified_dataset(file_path: Path, expected_status: str) -> List[Dict[str, Any]]:
    """Parse a source tuple dataset into normalized v2 records."""
    print(f"Parsing {file_path.name} as {expected_status}...")
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    records: List[Dict[str, Any]] = []
    source_file = file_path.name

    for source_index, (raw_context, raw_username, raw_password) in enumerate(_load_tuple_rows(content), 1):
        context = str(raw_context or "").strip()[:MAX_CONTEXT_CHARS]
        username = _clean_field(str(raw_username) if raw_username is not None else None)
        password = _clean_field(str(raw_password) if raw_password is not None else None)
        if expected_status == "REAL" and not password:
            continue

        prefix = {"REAL": "tp", "FALSE_POSITIVE": "fp", "REVIEW": "rv"}.get(expected_status, "rec")
        record_id = f"{prefix}-{source_index:06d}"
        records.append(
            make_record(
                record_id=record_id,
                source_file=source_file,
                source_index=source_index,
                context=context,
                username=username,
                password=password,
                status=expected_status,
                distractor_type=None,
                source_context_hash=context_hash(context),
            )
        )

    print(f"  loaded {len(records)} records")
    return records


def _refresh_augmented_features(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    refreshed = []
    for record in records:
        clone = dict(record)
        clone["features"] = compute_features(clone.get("password"))
        refreshed.append(clone)
    return refreshed


def build_merged_dataset(
    data_dir: Path,
    augment_fp: int,
    seed: int,
    tp_path: Optional[Path] = None,
    fp_path: Optional[Path] = None,
    review_path: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Merge the source corpora into v2 records.

    ``tp_path`` / ``fp_path`` override the default ``<data-dir>/*.crdownload``
    locations (e.g. to consume ``scripts/generate_axa_synthetic.py`` output).
    ``review_path`` is optional — when supplied, its rows enter the corpus as
    the v2 ``REVIEW`` class (``is_credentials = 0``, status preserved).
    """
    true_path = tp_path or (data_dir / "true_positive.crdownload")
    false_path = fp_path or (data_dir / "false_positive.crdownload")

    if not true_path.exists() or not false_path.exists():
        missing = [str(path) for path in [true_path, false_path] if not path.exists()]
        raise FileNotFoundError(f"Missing source dataset(s): {', '.join(missing)}")

    true_records = parse_preclassified_dataset(true_path, "REAL")
    false_records = parse_preclassified_dataset(false_path, "FALSE_POSITIVE")

    review_records: List[Dict[str, Any]] = []
    if review_path is not None:
        if not review_path.exists():
            raise FileNotFoundError(f"Missing REVIEW source dataset: {review_path}")
        review_records = parse_preclassified_dataset(review_path, "REVIEW")

    true_passwords = [record["password"] for record in true_records if record.get("password")]

    augmented_records: List[Dict[str, Any]] = []
    if augment_fp:
        base_augmented = augment_false_positives(false_records, true_passwords, seed=seed)
        if augment_fp < 3:
            grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for record in base_augmented:
                grouped[record["augmentation_parent_id"]].append(record)
            for variants in grouped.values():
                augmented_records.extend(variants[:augment_fp])
        else:
            augmented_records = base_augmented
        augmented_records = _refresh_augmented_features(augmented_records)

    merged = true_records + false_records + review_records + augmented_records
    rng = random.Random(seed)
    rng.shuffle(merged)
    deduped = deduplicate_records(merged)

    report = {
        "seed": seed,
        "source_counts": {
            "true_positive": len(true_records),
            "false_positive": len(false_records),
            "review": len(review_records),
        },
        "augmentation_requested_per_fp": augment_fp,
        "augmented_count": len(augmented_records),
        "deduplicated_removed": len(merged) - len(deduped),
        "final_counts": Counter(record["status"] for record in deduped),
        "is_credentials_counts": Counter(str(record["is_credentials"]) for record in deduped),
        "distractor_counts": Counter(record.get("distractor_type") or "original" for record in deduped),
    }
    return deduped, _jsonable_report(report)


def _jsonable_report(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: dict(value) if isinstance(value, Counter) else value
        for key, value in report.items()
    }


def group_aware_split(
    records: List[Dict[str, Any]],
    *,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = RANDOM_SEED,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["source_context_hash"]].append(record)

    grouped_items = list(groups.items())
    random.Random(seed).shuffle(grouped_items)
    n_groups = len(grouped_items)
    n_test = int(n_groups * test_ratio)
    n_val = int(n_groups * val_ratio)

    test_keys = {key for key, _ in grouped_items[:n_test]}
    val_keys = {key for key, _ in grouped_items[n_test : n_test + n_val]}

    train: List[Dict[str, Any]] = []
    val: List[Dict[str, Any]] = []
    test: List[Dict[str, Any]] = []
    for key, group_records in grouped_items:
        if key in test_keys:
            test.extend(group_records)
        elif key in val_keys:
            val.extend(group_records)
        else:
            train.extend(group_records)

    rng = random.Random(seed)
    rng.shuffle(train)
    rng.shuffle(val)
    rng.shuffle(test)
    _assert_no_group_leakage(train, val, test)
    return train, val, test


def _assert_no_group_leakage(*splits: List[Dict[str, Any]]) -> None:
    seen: Dict[str, int] = {}
    for split_index, split in enumerate(splits):
        for record in split:
            key = record["source_context_hash"]
            if key in seen and seen[key] != split_index:
                raise AssertionError(f"Context leakage detected for {key}")
            seen[key] = split_index


def load_rationales(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load a JSONL of teacher rationales keyed by record_id."""
    rationales: Dict[str, Dict[str, Any]] = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            record_id = entry.get("record_id")
            if record_id:
                rationales[record_id] = {
                    "reasoning": entry.get("reasoning"),
                    "evidence": entry.get("evidence"),
                }
    return rationales


def records_to_prompt_pairs(
    records: List[Dict[str, Any]],
    rationales: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    for record in records:
        teacher = (rationales or {}).get(record["record_id"]) if rationales else None
        label = build_label(record, reasoning=(teacher or {}).get("reasoning"))
        if teacher and isinstance(teacher.get("evidence"), list) and teacher["evidence"]:
            label["evidence"] = teacher["evidence"]
        pair = format_training_text_binary(record_to_detection(record), label)
        pair.update(
            {
                "record_id": record["record_id"],
                "status": record["status"],
                "is_credentials": record["is_credentials"],
                "distractor_type": record.get("distractor_type"),
                "source_context_hash": record["source_context_hash"],
            }
        )
        pairs.append(pair)
    return pairs


def apply_per_class_cap(records: List[Dict[str, Any]], per_class_cap: int, seed: int) -> List[Dict[str, Any]]:
    if per_class_cap <= 0:
        return records
    rng = random.Random(seed)
    by_status: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_status[record["status"]].append(record)
    capped: List[Dict[str, Any]] = []
    for items in by_status.values():
        rng.shuffle(items)
        capped.extend(items[:per_class_cap])
    rng.shuffle(capped)
    return capped


def write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_inspection_csv(path: Path, records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "record_id",
                "status",
                "is_credentials",
                "distractor_type",
                "entropy",
                "length",
                "password_preview",
                "context_preview",
            ],
        )
        writer.writeheader()
        for record in records:
            features = record.get("features", {})
            password = record.get("password")
            writer.writerow(
                {
                    "record_id": record["record_id"],
                    "status": record["status"],
                    "is_credentials": record["is_credentials"],
                    "distractor_type": record.get("distractor_type") or "original",
                    "entropy": f"{features.get('entropy', 0.0):.3f}",
                    "length": features.get("length", 0),
                    "password_preview": (password or "None")[:40],
                    "context_preview": (record.get("context") or "")[:120].replace("\n", " "),
                }
            )


def save_outputs(
    records: List[Dict[str, Any]],
    report: Dict[str, Any],
    data_dir: Path,
    per_class_cap: int,
    seed: int,
    rationales: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    records = apply_per_class_cap(records, per_class_cap, seed)
    train, val, test = group_aware_split(records, seed=seed)

    write_jsonl(data_dir / "merged_dataset.jsonl", records)
    write_jsonl(data_dir / "training_data_binary.jsonl", records_to_prompt_pairs(train, rationales))
    write_jsonl(data_dir / "val_data_binary.jsonl", records_to_prompt_pairs(val, rationales))
    write_jsonl(data_dir / "test_data_binary.jsonl", records_to_prompt_pairs(test, rationales))

    # Compatibility names used by existing scripts.
    write_jsonl(data_dir / "training_data.jsonl", records_to_prompt_pairs(train, rationales))
    write_jsonl(data_dir / "val_data.jsonl", records_to_prompt_pairs(val, rationales))
    write_jsonl(data_dir / "test_data.jsonl", records_to_prompt_pairs(test, rationales))

    write_inspection_csv(data_dir / "training_data_augmented.csv", records)
    write_inspection_csv(data_dir / "training_data.csv", records[:500])

    dataset_summary = {
        "summary": {
            "real_count": sum(1 for record in records if record["status"] == "REAL"),
            "false_positive_count": sum(1 for record in records if record["status"] == "FALSE_POSITIVE"),
            "review_count": sum(1 for record in records if record["status"] == "REVIEW"),
            "total": len(records),
        },
        "splits": {"train": len(train), "val": len(val), "test": len(test)},
    }
    (data_dir / "synthetic_training_dataset.json").write_text(json.dumps(dataset_summary, indent=2), encoding="utf-8")
    (data_dir / "augmentation_report.json").write_text(json.dumps({**report, "splits": dataset_summary["splits"]}, indent=2), encoding="utf-8")

    instruction_data = [
        {"instruction": "Classify this detected credential", "input": pair["prompt"], "output": pair["completion"]}
        for pair in records_to_prompt_pairs(records, rationales)
    ]
    (data_dir / "instruction_tuning_dataset.json").write_text(json.dumps(instruction_data, indent=2), encoding="utf-8")

    print("Saved v2 training artifacts:")
    for name in [
        "merged_dataset.jsonl",
        "training_data_binary.jsonl",
        "val_data_binary.jsonl",
        "test_data_binary.jsonl",
        "training_data_augmented.csv",
        "augmentation_report.json",
    ]:
        print(f"  {data_dir / name}")
    print(f"Split sizes: train={len(train)} val={len(val)} test={len(test)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process CRED-HUUNT v2 training data.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--augment-fp", type=int, default=3, help="Number of FP augmentations per source row, 0-3.")
    parser.add_argument("--target", choices=["binary", "multiclass", "both"], default="both", help="Output target contract; v2 emits binary JSON with status metadata.")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--per-class-cap", type=int, default=0, help="Optional cap per status after merge; 0 keeps all records.")
    parser.add_argument(
        "--rationales",
        default=None,
        help="Optional JSONL of teacher-generated rationales (from scripts/distill_rationales.py). Overrides _default_reasoning per record_id.",
    )
    parser.add_argument(
        "--source-tp",
        default=None,
        help="Override the true-positive source path (default: <data-dir>/true_positive.crdownload).",
    )
    parser.add_argument(
        "--source-fp",
        default=None,
        help="Override the false-positive source path (default: <data-dir>/false_positive.crdownload).",
    )
    parser.add_argument(
        "--source-review",
        default=None,
        help="Optional REVIEW-class source path (e.g. data/synthetic/review.crdownload from generate_axa_synthetic.py).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    records, report = build_merged_dataset(
        data_dir,
        max(0, min(args.augment_fp, 3)),
        args.seed,
        tp_path=Path(args.source_tp) if args.source_tp else None,
        fp_path=Path(args.source_fp) if args.source_fp else None,
        review_path=Path(args.source_review) if args.source_review else None,
    )
    rationales = load_rationales(Path(args.rationales)) if args.rationales else None
    if rationales is not None:
        print(f"Loaded {len(rationales)} teacher rationales from {args.rationales}")
    save_outputs(records, report, data_dir, args.per_class_cap, args.seed, rationales=rationales)


if __name__ == "__main__":
    main()
