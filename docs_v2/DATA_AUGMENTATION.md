# Data Augmentation

The goal is to make false positives harder and more realistic. A model that only learns password entropy will over-classify random strings as credentials. The v2 dataset should force the model to use context.

## Source Inputs

```text
data/true_positive.crdownload
data/false_positive.crdownload
```

The true-positive file provides real credential contexts. The false-positive file provides contexts that mention password-like concepts but do not contain real secrets.

## Augmentation Target

For every false-positive source row, keep the original row and create three augmented variants.

```text
original FP + 3 augmented FP variants = 4 FP records per source context
```

All false-positive records remain:

```json
{
  "status": "FALSE_POSITIVE",
  "is_credentials": 0
}
```

## Distractor Types

| Type | Purpose | Example shape |
|---|---|---|
| `none_literal` | Teach absence of a value | `null`, empty string, `None` |
| `placeholder` | Teach placeholder rejection | `your_password`, `<PASSWORD>`, `changeme`, `P@ssw0rd`, `****` |
| `context_token` | Teach that emails/FQDNs/tickets/dates are not passwords | `INC123456`, `user@example.com`, `host.example.local` |
| `dictionary_word` | Teach common-word rejection | `password`, `secret`, `token`, `admin`, `temporary` |
| `high_entropy_non_secret` | Teach high entropy is not enough | UUID, commit SHA, hash-like string |
| `hard_negative` | Teach context dominance | real-looking password string inserted into a reset/help/policy context |

## Variant Distribution

Generate three variants per original FP context:

| Variant | Difficulty | Source types |
|---|---|---|
| 1 | Easy | `none_literal` or `placeholder` |
| 2 | Medium | `context_token` or `dictionary_word` |
| 3 | Hard | `high_entropy_non_secret` or `hard_negative` |

Use a fixed seed for reproducibility:

```python
RANDOM_SEED = 42
```

## Hard Negatives

Hard negatives are the most important augmentation for this project.

A hard negative puts a realistic-looking password value into a context that is clearly not a credential assignment, such as:

```text
password reset requested 2025-01-12
password policy updated for user@example.com
visit https://example.local/reset-password
```

The label remains:

```json
{
  "status": "FALSE_POSITIVE",
  "is_credentials": 0,
  "distractor_type": "hard_negative"
}
```

This prevents the model from learning the wrong shortcut:

```text
high entropy string = always credential
```

## Context Token Extraction

For `context_token`, extract one of:

| Token | Regex sketch |
|---|---|
| Email | `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+` |
| FQDN | `\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\b` |
| Ticket | `\b(?:INC|RITM|CHG)\d+\b` |
| Date | multiple common date formats |
| Domain user | `\b[A-Z0-9_-]+\\[A-Z0-9._-]+\b` |

If no token is found, fall back to `dictionary_word`.

## Deduplication

Deduplicate after merging true positives and augmented false positives.

Recommended key:

```text
(source_context_hash, password, status, distractor_type)
```

For train/eval leakage protection, the split grouping key is only:

```text
source_context_hash
```

## Class Balance

False-positive augmentation will increase negative examples substantially. Track class balance in `data/augmentation_report.json`.

Minimum report fields:

```json
{
  "source_counts": {
    "true_positive": 25000,
    "false_positive": 20000
  },
  "augmented_counts": {
    "none_literal": 20000,
    "placeholder": 20000,
    "context_token": 20000,
    "hard_negative": 20000
  },
  "final_counts": {
    "is_credentials_1": 25000,
    "is_credentials_0": 80000
  }
}
```

Exact numbers depend on parser results and deduplication.

## Mitigating Imbalance

If false positives dominate after augmentation, use one of:

1. Weighted loss during training.
2. Downsample augmented FP records per epoch.
3. Upsample true-positive records.
4. Keep full dataset but report per-class metrics and balanced F1.

Recommended first option:

```text
keep all data, use balanced metrics, add weighted loss only if recall drops
```

## Files To Add

```text
src/dataset_schema.py
scripts/augment_false_positives.py
```

## Processor Changes

Update [../scripts/process_synthetic_training_data.py](../scripts/process_synthetic_training_data.py) to:

1. Parse both source files.
2. Normalize records to one schema.
3. Add `is_credentials`.
4. Generate false-positive variants.
5. Merge TP + original FP + augmented FP.
6. Shuffle with fixed seed.
7. Deduplicate.
8. Group-aware split by `source_context_hash`.
9. Emit JSONL, CSV inspection, and augmentation report.

## Verification

Required checks:

- `data/merged_dataset.jsonl` contains both `REAL` and `FALSE_POSITIVE`.
- Every line has `is_credentials`.
- Every augmented record has `is_credentials: 0`.
- No `source_context_hash` appears in more than one split.
- `augmentation_report.json` includes counts per `distractor_type`.
- Manual CSV sample shows correct labels for 20 rows per distractor type.
