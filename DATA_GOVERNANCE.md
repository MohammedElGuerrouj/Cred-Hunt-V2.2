# Data Governance

CRED-HUUNT v2 processes data that may contain real credentials. This document defines how that data is classified, where it lives, how long it is kept, and who is responsible for it. Operators deploying CRED-HUUNT must adopt or supersede this policy before scanning production code.

This document complements [SECURITY.md](SECURITY.md) (vulnerability disclosure), [THREAT_MODEL.md](THREAT_MODEL.md) (T-4 specifically addresses information disclosure of detection traces), and [MODEL_CARD.md](MODEL_CARD.md) (ethical considerations).

## Data Classes

CRED-HUUNT data falls into four classes. The class determines storage, retention, and access controls.

| Class | Examples | Sensitivity | Default storage |
|---|---|---|---|
| **C1 — Synthetic training data** | `data/true_positive.crdownload`, `data/false_positive.crdownload` | Low (synthetic by construction) | Version-controlled |
| **C2 — Derived datasets** | `data/merged_dataset.jsonl`, `data/training_data_binary.jsonl`, `data/training_data_augmented.csv` | Low–Medium (derived from C1) | Local filesystem, gitignored |
| **C3 — Live detection inputs and outputs** | `data/output_report.json`, benchmark JSONL on real scans, `results/benchmark_matrix.jsonl` if run on real data | **High — may contain real credentials** | Restricted local storage, encrypted at rest |
| **C4 — Model artifacts** | `./lora-credentials-detector/`, Ollama model cache, `models/` | High (executable + may encode training data) | Restricted, signed if platform supports |

A single field — `matched_value` — escalates a record from C2 to C3. Once a record holds a real credential, every derivative (logs, traces, aggregated reports) inherits C3 classification.

## Data Flow

```
Repository / scanner ──► detection JSON (C3) ──► src/main.py
                                                      │
                                                      ▼
                                              ┌─ entropy prefilter (C3 in mem)
                                              │
                                              ▼
                                              ┌─ Ollama API call (C3 over loopback)
                                              │
                                              ▼
                                              ├─ classifier.py (C3 in mem)
                                              │
                                              ▼
                                              └─ aggregator.py
                                                      │
                                                      ▼
                                              data/output_report.json (C3 at rest)
                                                      │
                                                      ▼
                                              Analyst review (C3 in transit)
```

Synthetic-data flow (training pipeline) operates only on C1 → C2 and never sees C3 unless the operator intentionally mixes real and synthetic data.

## Storage and Retention

### C1 — Synthetic training data

- **Storage:** git-tracked, repository-local.
- **Retention:** indefinite, version-controlled.
- **Access:** anyone with repository access.

### C2 — Derived datasets

- **Storage:** `data/` directory, gitignored.
- **Retention:** regenerated on demand; no formal retention policy required. Delete and rebuild when augmentation parameters change.
- **Access:** local user.

### C3 — Live detection inputs and outputs

- **Storage:** `data/output_report.json`, `results/`, any custom path passed via `--output`. Operator-defined location must be:
  - On a filesystem with at-rest encryption when the platform supports it.
  - Owner-only permissions (Unix mode `0700` on directories, `0600` on files).
  - Excluded from any centralized backup that lacks equivalent controls.
- **Retention:** per organizational secret-incident policy. Default recommendation: **delete within 30 days** of analyst review completion. The shorter, the better.
- **Access:** authorized incident responders only. Treat access events as auditable.
- **Logging:** when emitting log lines about a detection, **never** include `matched_value`. Use `record_id` and `value_hash` (sha256 truncated to 16 chars) instead.

### C4 — Model artifacts

- **Storage:** internal artifact registry (preferred) or restricted local directory.
- **Retention:** as long as the artifact is referenced by an active model card / deployment.
- **Access:** ops + ML engineers. Treat as executable code.
- **Integrity:** record SHA-256 digest of every artifact. Pin by digest in production. See [SECURITY.md §Model Supply Chain](SECURITY.md).

## Personally Identifiable Information (PII)

CRED-HUUNT is **not** a PII detector. However, scanned context may incidentally contain PII (commit author emails in git blame, usernames in connection strings).

| PII surface | Handling |
|---|---|
| Author email / committer identity | Not collected by the current pipeline. If `git_blame_check` is added in the future (currently deferred), see [THREAT_MODEL.md §T-7](THREAT_MODEL.md). |
| Usernames inside `context` | Treated as opaque text. Not extracted, not stored separately, not used as a routing key. |
| Personal access tokens that bind to a user account | Classified as C3 by virtue of being a credential. The user identity associated with the token is incidental and must not be persisted separately. |

If a regulated environment (GDPR, HIPAA, etc.) requires explicit PII handling, layer a PII detector ahead of CRED-HUUNT and redact before the candidate enters this pipeline.

## Cross-Border and Multi-Tenant Considerations

- **Cross-border:** detection inputs may be subject to data-residency rules. Deployments serving EU code repositories should run CRED-HUUNT within the same residency region as the source code.
- **Multi-tenant:** if a single CRED-HUUNT instance serves multiple tenants, partition C3 storage per tenant and never write cross-tenant aggregate reports without explicit consent. The current pipeline has no tenant-awareness and must be wrapped by an orchestrator that enforces partitioning.

## Data Minimization

The pipeline already minimizes by:

- Truncating `context` to `MAX_CONTEXT_CHARS = 600` (`scripts/process_synthetic_training_data.py`).
- Not storing `raw_response` in the runtime report (only in benchmark JSONL, which operators control).
- Not persisting the Ollama prompt cache (Ollama itself may cache; configure accordingly).

Further minimization to consider for production:

- Set `MAX_CONTEXT_CHARS` to 200 in line with the literature finding (arXiv 2504.18784) that 200 chars match the F1 of 600 chars.
- Strip `raw_response` from benchmark outputs once aggregate metrics are computed.
- Hash `matched_value` in any artifact intended for long-term storage; keep the cleartext only in the immediate review queue.

## Deletion and Right-to-Erasure

For environments subject to GDPR Article 17 or similar:

- C1 and C4 contain no personal data and are out of scope.
- C2 is derived from C1 and is out of scope.
- C3 may contain credentials that resolve to a natural person (PATs, service accounts associated with an individual). The operator is responsible for:
  - Maintaining a mapping from `record_id` to ingestion source to enable targeted deletion.
  - Honoring deletion requests by purging C3 artifacts including derived logs.
  - Documenting the deletion in an audit log.

The codebase provides no deletion CLI. Operators must implement deletion within their orchestration layer.

## Audit Trail

Every decision in C3 should be reconstructable. The minimum provenance bundle:

| Field | Source |
|---|---|
| `record_id` | Detection input |
| `value_hash` | `dataset_schema.context_hash`-style hash of `matched_value` |
| `model_digest` | SHA-256 of the model artifact (not just the Ollama tag) |
| `adapter_version` | LoRA adapter version + dataset commit hash |
| `prompt_version` | Hash of `src/prompt_builder.SYSTEM_PROMPT` |
| `strategy` | `agent_trace.strategy` from the decision |
| `timestamp` | Wall-clock at decision time |
| `decision` | `is_credentials`, `status`, `confidence` |
| `escalated` | `agent_trace.escalated` for self_consistency |
| `tool_calls` | `agent_trace.tool_calls` for react_triage |

The current pipeline emits most of these in `agent_trace`. Provenance fields not yet emitted (`model_digest`, `adapter_version`, `prompt_version`) should be added by the orchestration layer until the codebase tracks them natively. See [ROADMAP.md](ROADMAP.md).

## Roles and Responsibilities

| Role | Responsible for |
|---|---|
| **Data owner** | Defines classification rules per environment; approves cross-tenant aggregation |
| **ML engineer** | Maintains C1/C2 synthetic data integrity; documents model card updates |
| **Security engineer** | Maintains C3 storage controls; reviews tool additions per [THREAT_MODEL.md §T-7](THREAT_MODEL.md) |
| **Incident responder** | Consumes C3 reports; triggers deletion after review |
| **Operator** | Configures retention, encryption, access control on the host running CRED-HUUNT |

## Compliance References

- **EU AI Act Article 13** — transparency requirements: [MODEL_CARD.md](MODEL_CARD.md).
- **GDPR Articles 5, 17, 32** — minimization, erasure, integrity: this document.
- **NIST AI RMF 1.0** — risk management: [THREAT_MODEL.md](THREAT_MODEL.md) + this document.
- **NIST SP 800-53 / SP 800-171** — for federal deployments, the operator must map C3 controls to the relevant family (AC, AU, IR, SC).

## Review Cadence

This policy is reviewed:

- On every release.
- When a new data class is introduced.
- When a new field is added to detection records or model outputs.
- Annually at minimum.
