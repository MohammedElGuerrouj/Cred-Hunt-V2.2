import argparse
import json
from classifier import classify_batch
from aggregator import aggregate_by_owner

def run(input_file: str, output_file: str, test_mode: bool = False, model: str | None = None):
    with open(input_file, encoding="utf-8-sig") as f:
        detections = json.load(f)

    print(f"Processing {len(detections)} detections...")
    classified = classify_batch(detections, test_mode=test_mode, model=model)

    report = aggregate_by_owner(classified)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Done. Report saved to {output_file}")
    for owner, data in report.items():
        s = data["summary"]
        print(f"  {owner}: {s['real']} REAL, {s['review']} REVIEW, {s['false_positive']} FP")

def parse_args():
    parser = argparse.ArgumentParser(description="Run credential classification on detection JSON data.")
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input JSON file containing detection records."
    )
    parser.add_argument(
        "--output", "-o",
        default="data/output_report.json",
        help="Output JSON report file."
    )
    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="Run in test mode with fake LLM responses."
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Ollama model name to use for classification."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.input, args.output, test_mode=args.test, model=args.model)
