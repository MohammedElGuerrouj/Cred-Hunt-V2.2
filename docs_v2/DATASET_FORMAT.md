# Dataset Format

The v2 dataset should use JSONL as the primary format. The current `.crdownload` files remain read-only source inputs, and all downstream training and benchmark artifacts should be generated from a unified merged JSONL corpus.

## Format Decision

| Format | Role | Decision |
|---|---|---|
| `.crdownload` Python-like tuples | Existing source data | Keep read-only |
| JSONL | Primary v2 corpus and training data | Use for all model inputs |
| CSV | Manual inspection | Export only, never train from it |
| JSON | Reports/config summaries | Use for metrics and reports |
| `.py` dataset files | New datasets | Avoid |

## Why JSONL

JSONL is the best fit because it is:

- Streamable line by line.
- Robust for quotes, commas, backslashes, and multiline context.
- Friendly to Hugging Face `datasets`, PyTorch, and CLI inspection.
- Append-friendly for augmentation and benchmark output.
- Diff-friendly because one record is one line.

CSV is useful only for inspection because credential-like strings often contain commas, quotes, equals signs, newlines, backslashes, and other characters that can corrupt flat CSV rows if not escaped perfectly.

## Source Files

The existing files are source inputs:

```text
data/true_positive.crdownload
data/false_positive.crdownload
```

They contain Python-like tuples:

```text
(context_text, username_or_none, password_or_none)
```

For v2, do not edit these files directly. Parse them into normalized JSONL instead.

## Unified Dataset

Primary v2 corpus:

```text
data/merged_dataset.jsonl
```

Each line should be one normalized record:

```json
{
  "record_id": "tp-000001",
  "source_file": "true_positive.crdownload",
  "source_index": 1,
  "context": "DB_USER=svc_app\nDB_PASS=example-value\nDB_HOST=10.0.0.4",
  "username": "svc_app",
  "password": "example-value",
  "status": "REAL",
  "is_credentials": 1,
  "distractor_type": null,
  "source_context_hash": "sha256:...",
  "features": {
    "entropy": 3.9,
    "length": 18,
    "has_special": true,
    "has_upper": false,
    "has_lower": true,
    "has_digit": true
  }
}
```

False-positive augmented examples should use the same schema:

```json
{
  "record_id": "fp-000123-aug-hard-negative",
  "source_file": "false_positive.crdownload",
  "source_index": 123,
  "context": "password reset requested by user@example.com",
  "username": "user@example.com",
  "password": "real-looking-distractor",
  "status": "FALSE_POSITIVE",
  "is_credentials": 0,
  "distractor_type": "hard_negative",
  "source_context_hash": "sha256:...",
  "features": {
    "entropy": 4.2,
    "length": 24,
    "has_special": true,
    "has_upper": true,
    "has_lower": true,
    "has_digit": true
  }
}
```

## Label Rules

| `status` | `is_credentials` | Meaning |
|---|---:|---|
| `REAL` | 1 | Actual credential-like value in credential-bearing context |
| `FALSE_POSITIVE` | 0 | Placeholder, reset URL, policy mention, ticket, docs, hard negative, or non-secret context |
| `REVIEW` | optional | Ambiguous future label; no current source data |

For the first v2 pass:

```text
is_credentials = 1 iff status == "REAL"
is_credentials = 0 iff status == "FALSE_POSITIVE"
```

## Prompt/Completion JSONL

LoRA-ready binary training file:

```text
data/training_data_binary.jsonl
```

Each line should contain prompt, completion, split metadata, and labels:

```json
{
  "record_id": "tp-000001",
  "prompt": "File: synthetic/training_sample | Source: synthetic_dataset\nPattern: PASSWORD | Match: example-value\nContext:\n...",
  "completion": "{\"is_credentials\":1,\"status\":\"REAL\",\"confidence\":0.98,\"reasoning\":\"Pre-classified as real credential\",\"evidence\":[\"source:true_positive\"]}",
  "status": "REAL",
  "is_credentials": 1,
  "distractor_type": null,
  "source_context_hash": "sha256:..."
}
```

Validation and test splits should follow the same schema:

```text
data/val_data_binary.jsonl
data/test_data_binary.jsonl
```

## Split Requirements

Use group-aware splitting by `source_context_hash`.

Reason: if the same false-positive context appears in train and test with different distractor passwords, the model can memorize the context and inflate metrics.

Required rule:

```text
all records with the same source_context_hash must stay in exactly one split
```

Recommended split:

```text
train: 80%
val: 10%
test: 10%
```

## Inspection Files

Human inspection export:

```text
data/training_data_augmented.csv
```

This should include only flat fields:

```text
record_id,status,is_credentials,distractor_type,entropy,length,password_preview,context_preview
```

CSV must not become the training source.

## Reports

Recommended generated reports:

```text
data/augmentation_report.json
data/evaluation_report.json
results/benchmark_matrix.jsonl
results/benchmark_summary.json
```

These are derived artifacts and can be regenerated.
