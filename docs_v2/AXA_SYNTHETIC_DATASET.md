# AXA Group Synthetic Credential Dataset

A high-realism synthetic corpus for fine-tuning and benchmarking the CRED-HUUNT
v2 credential classifier against AXA Group's enterprise environment. Generated
by [`scripts/generate_axa_synthetic.py`](../scripts/generate_axa_synthetic.py).

> **Synthetic data only.** Every credential value in this corpus is randomly
> generated and is **not** a real AXA secret. AXA infrastructure naming
> (`.intraxa` domains, `AXASGP\`/`AXA-BE\` prefixes) is a *naming convention*
> reproduced from the provided synthetic source corpus — it is not confidential
> data. See [Ethics](#ethics) below.

## 1. Why a generator

The two source files in `data/` (`true_positive*.crdownload`,
`false_positive*.crdownload`) are fixed, finite, pre-classified tuple corpora.
The false-positive side is already AXA-saturated; the true-positive side is
generic. Fine-tuning a small model well needs:

- **More volume and variety** than the source provides.
- **AXA enterprise contexts** the source lacks (Spring config, Guidewire/SAP,
  JDBC, enterprise code).
- **Full credential-type coverage** — not just DB passwords.
- **Many languages** — AXA operates across France, Germany, Spain, Italy,
  Belgium, the Netherlands, the UK, Poland, Turkey, Japan and more.
- A **`REVIEW` slice** so the model learns to abstain instead of guessing.

The generator *mines* AXA vocabulary from the real source files, then
*recombines* it compositionally. It does not copy source rows.

## 2. Output

`python scripts/generate_axa_synthetic.py --out-dir data/synthetic` writes:

| File | Label | Contract |
|---|---|---|
| `true_positive.crdownload` | `REAL` | A real secret embedded in an AXA context. |
| `false_positive.crdownload` | `FALSE_POSITIVE` | Credential-shaped noise; no secret. |
| `review.crdownload` | `REVIEW` | Genuinely ambiguous — the model should abstain. |
| `*.jsonl` | — | Inspection copies (one JSON object per record). |
| `axa_generation_report.json` | — | Coverage, vocab, and per-category counts. |

Each `.crdownload` is a Python literal `dataset = [(context, username, password), ...]`
— drop-in compatible with `process_synthetic_training_data.py:_load_tuple_rows`.
Files carry a synthetic-data disclaimer header, the seed, and a UTC timestamp.

Default counts: **4000 TP / 4000 FP / 700 REVIEW** (~8% REVIEW). After the
processor's `--augment-fp 3` step the corpus is `REAL 4000 / FALSE_POSITIVE
16000 / REVIEW 700` — the realistic production skew (most detections are false
positives) while retaining enough positive signal for F1.

## 3. Compositional design — `language × credential-type × carrier`

Rather than fixed templates, each true-positive record is composed from three
independent axes. This maximises variety and prevents the model from memorising
template shells (which would also break the group-aware split).

### 3.1 Languages (10)

`en, fr, de, es, it, pt, nl, pl, tr, ja` — AXA's core markets. Localised:
natural-language contexts (chat, tickets, audit logs, code comments),
placeholder words, and a share of key names. Examples of localised password
key words: `mot_de_passe`, `motdepasse`, `mdp`, `contrasena`, `clave`,
`passwort`, `kennwort`, `senha`, `wachtwoord`, `haslo`, `parola`, `sifre`,
`パスワード`.

### 3.2 Credential types (~55)

| Group | Types |
|---|---|
| Passwords | `password`, `admin_password`, `ldap_password`, `keystore_password`, `smtp_password`, `private_key_passphrase`, `pfx_password`, `sap_password`, `mainframe_password` (RACF) |
| Cloud keys | `aws_access_key_id`, `aws_secret_access_key`, `azure_storage_key`, `azure_ad_client_secret`, `azure_sas_token`, `azure_connection_string`, `gcp_api_key`, `gcp_service_account_json` |
| SaaS tokens | `stripe_secret`, `github_pat`, `gitlab_pat`, `npm_token`, `slack_token`, `slack_webhook_url`, `twilio_auth_token`, `sendgrid_api_key`, `datadog_api_key`, `atlassian_api_token`, `azure_devops_pat`, `dockerhub_token`, `adyen_api_key` |
| AI provider keys | `openai_api_key`, `anthropic_api_key`, `huggingface_token` |
| App secrets | `jwt`, `oauth_client_secret`, `bearer_token`, `api_key_generic`, `saml_assertion`, `kerberos_keytab`, `framework_secret_key`, `totp_seed` |
| Crypto / keys | `hmac_secret`, `encryption_key`, `vault_token`, `ssh_private_key`, `rsa_private_key`, `ec_private_key`, `dsa_private_key`, `pkcs8_private_key`, `pgp_private_key`, `bcrypt_hash` |
| Structural | `db_connection_uri`, `redis_url`, `amqp_url`, `basic_auth` |

Each type has a value generator that matches its real shape — `AKIA…` for AWS
key ids, `sk_live_…` for Stripe, `ghp_…` for GitHub, `sk-…` / `sk-ant-…` / `hf_…`
for AI providers, three base64url segments for JWTs, `-----BEGIN … PRIVATE KEY-----`
blocks for SSH / RSA / EC / DSA / PKCS#8 / PGP keys, a JSON document with an
embedded private key for GCP service accounts, and so on.

### 3.3 Key-name variety

Every credential is emitted under a key drawn from a pool of English **and**
localised aliases, then re-cased into one of: `snake_case`,
`SCREAMING_SNAKE`, `camelCase`, `kebab-case`, `PascalCase`, or dotted
(`spring.datasource.password`). This is deliberate — the runtime classifier
must not key off one canonical spelling.

### 3.4 Carriers (6 groups, ~16 concrete forms)

`.properties` / `.yml` / `.json` / `.xml` / `.env`; Java / Python / C# / JS /
Go code; HTTP headers; CLI commands (`curl`, `sshpass`, `docker login`); JDBC /
URI connection strings; PEM blocks; and natural-language chat / reset tickets /
audit logs / code comments. Each credential type declares which carrier groups
are valid for it (e.g. SSH keys only render as PEM blocks).

## 4. False positives & hard negatives

The false-positive file is *credential-shaped noise* — `password` is always
`None`, matching the source convention; a deceptive token may occupy the
username field. Categories: localised placeholders (`votre_mot_de_passe`,
`changeme`, `<PASSWORT>`), `.env.example` rows, environment-variable
references, masked values, password-reset URLs, account-expiry mentions, and
**hard negatives** — high-entropy non-secrets that look like credentials:
commit SHAs, UUIDs, `sk_test_` sandbox keys, IBANs, and insurance-domain IDs
(policy numbers, claim references, SIRET, contract IDs).

Valued hard negatives (a real-looking secret labelled `FALSE_POSITIVE`) are
produced *downstream* by `scripts/augment_false_positives.py` via
`--augment-fp` — the generator does not duplicate that layer.

## 5. The `REVIEW` slice

Genuinely ambiguous records where a confident verdict is wrong. Categories:
partially-masked values (`Lio****43`), historical/rotated passwords, a token
that could be a hash or a password, a bare high-entropy value next to a
username, `ChangeMe…`-style values that may or may not be live, and
`${VAR:-default}` fallbacks. These teach the model to emit `status: REVIEW`
rather than guess — which is what makes `self_consistency` escalation and
analyst hand-off meaningful.

## 6. Behaviour notes — why the corpus is shaped this way

- **Entropy-prefilter overlap.** The runtime classifier short-circuits values
  with `shannon_entropy < 2.5` *before* the LLM. So TP values include
  low-entropy real passwords (`Passw0rd`, `Summer2025#`) that survive the
  prefilter, and hard-negative FPs are deliberately high-entropy. The TP and FP
  entropy distributions overlap on purpose — otherwise the model would learn a
  threshold instead of reading context.
- **Context shell varies per record**, not just the secret value — different
  host, key name, comment, language, carrier. The split is group-aware by
  `source_context_hash`; near-identical shells would all land in one split.
- **Context length** is capped at 512 chars (processor caps at 600); most
  records sit near the ~200-char research sweet spot.

## 7. Running it

```powershell
# 1. Generate (deterministic via --seed; never writes into data/ itself)
python scripts/generate_axa_synthetic.py --out-dir data/synthetic --seed 42

# 2. Build the v2 training corpus from the generated source
python scripts/process_synthetic_training_data.py --target both --augment-fp 3 `
  --data-dir data/synthetic `
  --source-tp data/synthetic/true_positive.crdownload `
  --source-fp data/synthetic/false_positive.crdownload `
  --source-review data/synthetic/review.crdownload
```

Useful flags: `--n-tp / --n-fp / --n-review` (counts), `--no-mine` (curated
vocabulary only), `--no-jsonl`, `--report <path>`.

The `--source-tp / --source-fp / --source-review` flags on the processor are
the bridge: without them `build_merged_dataset` uses the hardcoded
`data/*.crdownload` names and has no `REVIEW` path.

## 8. Ethics

- Synthetic data only — no real credentials, no real employee identities, no
  proprietary AXA information. Every value is randomly generated.
- AXA infrastructure naming is a naming convention drawn from the provided
  synthetic source corpus, not confidential data.
- Output files carry a disclaimer header so they remain auditable if copied.
- Do not add real secrets to the generator or its output. Generated artefacts
  under `data/` are gitignored — regenerate, do not commit.
