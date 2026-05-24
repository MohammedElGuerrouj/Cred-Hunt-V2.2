# Security Policy

CRED-HUUNT v2 is a credential-detection AI pipeline that operates on source code, configuration files, and detection feeds. By definition the tool handles material that may include real secrets. This document governs how security issues in the project are reported, what is in scope, and the hardening commitments we make for the codebase itself.

## Reporting a Vulnerability

**Do not open public GitHub issues for security findings.** Email the maintainers at the project security contact configured by the organization deploying CRED-HUUNT. Include:

- A description of the issue and the affected component (`src/classifier.py`, `scripts/reasoning_runner.py`, etc.).
- A minimal reproduction (input record, command, observed vs expected behavior).
- The commit hash you tested against.
- Your assessment of impact and exploitability.

Use PGP if your organization requires confidential transport. The maintainer team commits to:

| Stage | SLA |
|---|---|
| Acknowledge receipt | 2 business days |
| Initial triage with severity | 5 business days |
| Mitigation plan or fix | 30 days for High/Critical, 90 days for Medium/Low |
| Public disclosure (CVE if applicable) | 90 days after fix availability, coordinated with reporter |

## Scope

**In scope:**

- Code execution, sandbox escape, or arbitrary file access via malicious detection input fed to `src/main.py` or `scripts/benchmark_models.py`.
- Prompt-injection attacks that cause the classifier to leak the system prompt, exfiltrate detected secrets, or change its decision based on attacker-controlled text in `context` / `matched_value`.
- Path traversal in scripts that touch `data/` or `results/`.
- JSON-parsing vulnerabilities in `src/llm_client.parse_json_safely`.
- Supply-chain risks via dependencies pinned in `requirements.txt`.
- Model-output handling where untrusted model JSON could trigger downstream code paths unsafely.

**Out of scope:**

- The intrinsic accuracy of the classifier (false positives, false negatives) — these are tracked as quality issues, not security issues.
- Vulnerabilities in upstream models (Ollama, Hugging Face checkpoints) — report those upstream.
- Issues that require the attacker to already have local shell access on the host running the tool.
- Hardening of synthetic training data tuples — they are read-only inputs.

## Security Posture of the Codebase

- **No network egress beyond Ollama.** The runtime classifier calls only `http://localhost:11434/api/generate`. Any new network call requires a documented justification and security review.
- **Read-only tools only.** `scripts/react_tools.py` and its `TOOL_REGISTRY` host deterministic, side-effect-free checks. Adding a tool that performs I/O (filesystem read, git blame, network) requires a security review and an addition to this document's "in scope" list.
- **No `eval`, no `exec`, no `shell=True`.** Confirmed across `src/` and `scripts/`. Any change that introduces dynamic code execution must be rejected by code review.
- **Strict JSON parsing.** Model output goes through `src/llm_client.parse_json_safely`, which rejects unparseable input and never substitutes user-controlled text into Python objects.
- **No telemetry.** The project does not phone home. Logs and reports are written to the local filesystem only.

## Sensitive Data Handling

The tool processes data that may contain real credentials. See [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md) for the full data-handling policy. Key points:

- Detection inputs, model outputs, and benchmark traces may include real secret material. Treat all `data/` and `results/` output paths as **secret-class storage**.
- The default `.gitignore` excludes every generated file. Do not commit `data/output_report.json`, `data/merged_dataset.jsonl`, or anything under `results/`.
- Source `.crdownload` datasets are synthetic and labeled. They are not real production credentials — verify before extending the dataset with new sources.

## Dependency Hygiene

Pinned dependencies live in `requirements.txt`. Hardening commitments:

- All dependencies are pinned with `>=` floors; production deployments should additionally `pip-compile` to a fully resolved `requirements.lock` and pin upper bounds.
- The dependency surface is intentionally small: `requests`, `tqdm`, `torch`, `transformers`, `peft`, `datasets`, `accelerate`, `numpy`, `scikit-learn`. Adding a dependency requires a code review note explaining why an existing one cannot serve.
- Known vulnerable versions should be tracked via `pip-audit` or equivalent in CI when the project moves to a hosted CI pipeline.

## Model Supply Chain

The benchmark pulls models from the Ollama public registry (`qwen2.5-coder:3b`, `granite3.3:2b`, `llama3.2:3b`). Risks:

- An attacker controlling the Ollama registry could publish a malicious model under a familiar tag. Enterprise deployments should mirror models to an internal registry and pin by digest, not tag.
- LoRA adapters loaded from `./lora-credentials-detector/` are trusted code paths via `peft.PeftModel.from_pretrained`. Treat adapter files as code: source them only from trusted internal builds, signed if your platform supports it.

## Threat Model

A detailed threat model — including prompt injection, model evasion, and trust boundaries — is documented in [THREAT_MODEL.md](THREAT_MODEL.md).

## Versions Supported

This is a research / benchmarking codebase. Security fixes are applied to `main` only. There is no parallel maintenance of older branches until a `v1.0` release is cut.

## Acknowledgements

We credit researchers who report security issues responsibly, with explicit consent, in release notes and the project changelog. Anonymous credit is available on request.
