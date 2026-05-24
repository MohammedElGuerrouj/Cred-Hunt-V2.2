#!/usr/bin/env python3
"""Non-interactive v2 smoke tests for local Ollama credential models."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llm_client import call_llm  # noqa: E402
from prompt_builder import build_prompt, get_system  # noqa: E402

TEST_CASES = [
    {
        "file_path": "config/prod.env",
        "pattern_name": "AWS_KEY",
        "matched_value": "AKIAIOSFODNN7REALKEY9",
        "context": "AWS_KEY=AKIAIOSFODNN7REALKEY9\nboto3.client('s3')",
        "expected_status": "REAL",
        "expected_is_credentials": 1,
    },
    {
        "file_path": "README.md",
        "pattern_name": "API_KEY",
        "matched_value": "YOUR_API_KEY_HERE",
        "context": "Replace YOUR_API_KEY_HERE with your key",
        "expected_status": "FALSE_POSITIVE",
        "expected_is_credentials": 0,
    },
    {
        "file_path": "src/auth.js",
        "pattern_name": "TOKEN",
        "matched_value": "abc123def456",
        "context": "const token = 'abc123def456'; authenticate(token);",
        "expected_status": "REVIEW",
        "expected_is_credentials": 0,
    },
    {
        "file_path": ".github/workflows/deploy.yml",
        "pattern_name": "GITHUB_TOKEN",
        "matched_value": "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345",
        "context": "GH_TOKEN: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345",
        "expected_status": "REAL",
        "expected_is_credentials": 1,
    },
    {
        "file_path": "docs/setup.md",
        "pattern_name": "SECRET",
        "matched_value": "sk-xxxxxxxxxxxxxxxxxxxxxxxx",
        "context": "OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx",
        "expected_status": "FALSE_POSITIVE",
        "expected_is_credentials": 0,
    },
    {
        "file_path": "security/password-reset.md",
        "pattern_name": "PASSWORD",
        "matched_value": "550e8400-e29b-41d4-a716-446655440000",
        "context": "password reset requested by user@example.com on 2025-01-12",
        "expected_status": "FALSE_POSITIVE",
        "expected_is_credentials": 0,
    },
    {
        "file_path": "docs/policy.md",
        "pattern_name": "PASSWORD",
        "matched_value": "NexusAutumn48!@#",
        "context": "password policy updated 2026-05-18; do not reuse passwords",
        "expected_status": "FALSE_POSITIVE",
        "expected_is_credentials": 0,
    },
]


def run_tests(model: str, test_mode: bool = False) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for case in TEST_CASES:
        detection = {
            "file_path": case["file_path"],
            "source": "smoke_test",
            "pattern_name": case["pattern_name"],
            "matched_value": case["matched_value"],
            "context": case["context"],
        }
        result = call_llm(build_prompt(detection), get_system(), model=model, test_mode=test_mode)
        schema_ok = all(key in result for key in ["is_credentials", "status", "confidence", "reasoning", "evidence", "agent_trace"])
        correct = result.get("is_credentials") == case["expected_is_credentials"]
        results.append({"case": case, "result": result, "schema_ok": schema_ok, "correct": correct})
    total = len(results)
    correct = sum(1 for item in results if item["correct"])
    schema_ok = sum(1 for item in results if item["schema_ok"])
    return {
        "model": model,
        "summary": {
            "total": total,
            "correct": correct,
            "accuracy": correct / total if total else 0.0,
            "schema_ok": schema_ok,
            "schema_validity": schema_ok / total if total else 0.0,
        },
        "test_cases": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test CRED-HUUNT v2 local models.")
    parser.add_argument("--models", nargs="+", default=["qwen2.5-coder:3b", "granite3.3:2b", "llama3.2:3b"])
    parser.add_argument("--output", default="data/model_test_results.json")
    parser.add_argument("--test-mode", action="store_true")
    args = parser.parse_args()

    all_results = [run_tests(model, test_mode=args.test_mode) for model in args.models]
    for result in all_results:
        summary = result["summary"]
        print(f"{result['model']}: accuracy={summary['accuracy'] * 100:.1f}% schema={summary['schema_validity'] * 100:.1f}%")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(all_results, handle, indent=2)
    print(f"Results saved to {output_path}")


if __name__ == "__main__":
    main()
