#!/usr/bin/env python3
"""AXA Group synthetic credential dataset generator for CRED-HUUNT v2.

Produces high-realism synthetic *source tuples* — ``(context, username, password)`` —
in the Python-literal ``.crdownload`` format consumed by
``scripts/process_synthetic_training_data.py``.

Three label files are written to ``--out-dir``:

* ``true_positive.crdownload``   — REAL secrets embedded in AXA-flavoured contexts.
* ``false_positive.crdownload``  — credential-shaped noise that is NOT a secret.
* ``review.crdownload``          — genuinely ambiguous records (the v2 ``REVIEW`` class).

Coverage (compositional — ``language x credential-type x carrier``)
-------------------------------------------------------------------
* **Languages (10):** en, fr, de, es, it, pt, nl, pl, tr, ja — AXA's core
  markets. Natural-language contexts (chat, tickets, audit logs, comments) and
  placeholder words are localised; key names mix localised + English forms.
* **Credential types (~55):** passwords (DB / LDAP / keystore / SMTP / SAP /
  RACF-mainframe / service); cloud keys (AWS id+secret, Azure storage key /
  AD client secret / SAS / connection string, GCP API key + service-account
  JSON); SaaS tokens (Stripe, GitHub, GitLab, npm, Slack, Twilio, SendGrid,
  Datadog, Atlassian, Azure DevOps, Docker Hub, Adyen); AI provider keys
  (OpenAI, Anthropic, Hugging Face); JWT, OAuth client secret, bearer / API
  keys, SAML assertions, Kerberos keytabs; private keys (RSA / EC / DSA /
  PKCS#8 / OpenSSH / PGP) and PFX passphrases; HMAC / encryption / framework
  secret keys, Vault tokens, DB / Redis / AMQP connection URIs, webhook URLs,
  bcrypt hashes, TOTP seeds, HTTP basic-auth.
* **Key-name variety:** every credential is emitted under a randomly-cased key
  (snake / SCREAMING_SNAKE / camelCase / kebab-case / PascalCase / dotted) drawn
  from a pool of English *and* localised aliases (mot_de_passe, contrasena,
  passwort, kennwort, senha, wachtwoord, haslo, parola, sifre, パスワード, ...).
* **Carriers (~16):** .properties / .yml / .json / .xml / .env, Java / Python /
  C# / JS / Go code, HTTP headers, CLI commands, JDBC/URI connection strings,
  PEM blocks, plus natural-language chat / ticket / audit / code-comment.

SAFETY / ETHICS
---------------
SYNTHETIC DATA ONLY. Every credential value is randomly generated and is NOT a
real AXA secret. AXA infrastructure naming reproduced here is a *naming
convention* drawn from the provided synthetic corpus, not confidential data. Do
not add real credentials, real employee identities, or proprietary information
to this generator or its output.

Usage
-----
    python scripts/generate_axa_synthetic.py --out-dir data/synthetic --seed 42
    python scripts/process_synthetic_training_data.py --target both --augment-fp 3 \\
        --source-tp data/synthetic/true_positive.crdownload \\
        --source-fp data/synthetic/false_positive.crdownload \\
        --source-review data/synthetic/review.crdownload
"""

from __future__ import annotations

import argparse
import ast
import json
import random
import re
import string
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

# (context, username_or_None, password_or_None, label, category)
GenRecord = Tuple[str, Optional[str], Optional[str], str, str]

MAX_CONTEXT_CHARS = 512  # processor caps at 600; keep contexts tight

AZ09 = string.ascii_uppercase + string.digits
B64 = string.ascii_letters + string.digits + "+/"
B64URL = string.ascii_letters + string.digits + "-_"
ALNUM = string.ascii_letters + string.digits


# --------------------------------------------------------------------------- #
# Curated AXA vocabulary (fallback / seed for the miner)
# --------------------------------------------------------------------------- #

CURATED_DOMAINS = [
    "adsfr.intraxa", "adsgb.intraxa", "agd.intraxa", "absin.intraxa",
    "absmr.intraxa", "absmrnp.intraxa", "acicprod.intraxa", "acicsit.intraxa",
    "acicpp.intraxa", "acicmgmt.intraxa", "ads-be.intraxa", "ads-it.intraxa",
    "adstest.intraxa", "adsgb-test.intraxa", "aaph.intraxa",
    "admglobaldirect.intraxa", "ad.axa-cs.intraxa", "nedc.mgmt.axa-tech.intraxa",
    "axa.com", "login.axa", "adfs.gbidns.com", "adfs-cw.td-env.gbidns.com",
    "adfs-sc.td-env.gbidns.com", "acred.local", "ags-spain.local", "aan.com",
]
CURATED_DOMAIN_PREFIXES = ["AXASGP", "AXA-BE", "MEDC", "SEDC", "SESD"]
CURATED_TICKET_PREFIXES = ["INC", "RITM", "CHG"]
CURATED_KEY_NAMES = [
    "DB_PASSWORD", "POSTGRES_PASSWORD", "MASTER_PASSWORD", "ADMIN_PASSWORD",
    "VAULT_ROOT_TOKEN", "GITHUB_TOKEN", "API_SECRET", "JWT_SECRET",
]

INSURANCE_SYSTEMS = ["policycenter", "claimcenter", "billingcenter", "sapiens",
                     "solife", "actuariat", "sap-fico", "sap-hr", "underwriting"]
SERVICE_ACCOUNTS = ["svc_policycenter", "svc-claimcenter", "svc_billingcenter",
                    "sa_guidewire", "svc_sapiens", "svc_solife", "batch_actuariat",
                    "svc-sap-rfc", "svc_datapipeline", "app_underwriting"]
ENVIRONMENTS = ["prod", "uat", "preprod", "qa", "sit", "dev", "recette", "homologation"]
DB_HOST_PREFIXES = ["pgsql", "mssql", "oracle", "mongo", "redis", "db"]

FIRST_NAMES = ["james", "william", "laura", "michelle", "robert", "sandra",
               "joseph", "kimberly", "david", "karen", "paul", "jean", "marie",
               "pierre", "sophie", "thomas", "julie", "nicolas", "antoine",
               "emilie", "hans", "anke", "lukas", "carlos", "lucia", "marco",
               "giulia", "joao", "ana", "sven", "katja", "piotr", "yuki", "kenji"]
LAST_NAMES = ["lopez", "martinez", "rodriguez", "wilson", "garcia", "campbell",
              "rivera", "hill", "scott", "dubois", "lefebvre", "moreau",
              "laurent", "bernard", "rousseau", "mercier", "schmidt", "muller",
              "weber", "rossi", "ferrari", "silva", "santos", "kowalski",
              "nowak", "tanaka", "sato", "yilmaz"]

# Password material.
PW_NOUNS = ["Phoenix", "Falcon", "Knight", "Dragon", "Titan", "Spartan", "Wolf",
            "Tiger", "Lion", "Eagle", "Hawk", "Raven", "Cobra", "Viper"]
PW_ELEMENTS = ["Ocean", "Solar", "Lunar", "Crystal", "Quantum", "Nova", "Storm",
               "Thunder", "Frost", "Ember", "Shadow", "Stellar"]
PW_SEASONS = ["Spring", "Summer", "Autumn", "Winter", "Ete", "Hiver"]
PW_KEYBOARD = ["Q1w2e3r4t", "Qwerty", "Zxcvbn", "Azerty", "Motdepasse", "Passw0rd"]
PW_SYMBOLS = "!@#$%&*-_+="
PW_SYMBOLS_WIDE = "!@#$%^&*()-_=+[]{};:,.?/~"
LEET = {"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7"}


# --------------------------------------------------------------------------- #
# Languages — AXA's core markets
# --------------------------------------------------------------------------- #

@dataclass
class Lang:
    code: str
    pw_words: List[str]          # localised password words + abbreviations
    placeholders: List[str]      # localised "fill me in" placeholder values
    chat: str                    # slots: {env} {sys} {noun} {val}
    reset: str                   # slots: {tk} {noun} {val}
    audit: str                   # slots: {date} {user} {noun} {val}
    comment: str                 # slots: {noun}  (code comment, no value)
    expired: str                 # slots: {acct}  (FP — account mention, no value)


LANGS: List[Lang] = [
    Lang("en", ["password", "passwd", "pwd", "pass", "pw"],
         ["your_password", "changeme", "<PASSWORD>", "to_be_defined", "example_value"],
         "the {env} {sys} {noun} is {val} - update your config",
         "Ticket {tk}: account reset complete, initial {noun}: {val}",
         "[{date}] AUDIT {noun} set for {user}: {val}",
         "TODO: move this {noun} to the vault",
         "{acct} password expired - please reset"),
    Lang("fr", ["mot_de_passe", "motdepasse", "mdp", "passe"],
         ["votre_mot_de_passe", "changez_moi", "<MOT_DE_PASSE>", "a_definir", "exemple"],
         "le {noun} {sys} en {env} est {val} - mets a jour ta config",
         "Ticket {tk} : compte reinitialise, {noun} initial : {val}",
         "[{date}] AUDIT {noun} defini pour {user} : {val}",
         "TODO : deplacer ce {noun} vers le coffre-fort",
         "{acct} mot de passe expire - merci de reinitialiser"),
    Lang("de", ["passwort", "kennwort", "passw", "pwd"],
         ["ihr_passwort", "bitte_aendern", "<PASSWORT>", "noch_festzulegen", "beispiel"],
         "das {sys}-{noun} in {env} lautet {val} - Konfiguration aktualisieren",
         "Ticket {tk}: Konto zurueckgesetzt, initiales {noun}: {val}",
         "[{date}] AUDIT {noun} gesetzt fuer {user}: {val}",
         "TODO: dieses {noun} in den Tresor verschieben",
         "{acct} Passwort abgelaufen - bitte zuruecksetzen"),
    Lang("es", ["contrasena", "contraseña", "clave", "pwd", "pass"],
         ["su_contrasena", "cambiame", "<CONTRASENA>", "por_definir", "ejemplo"],
         "la {noun} de {sys} en {env} es {val} - actualiza tu configuracion",
         "Ticket {tk}: cuenta restablecida, {noun} inicial: {val}",
         "[{date}] AUDIT {noun} definida para {user}: {val}",
         "TODO: mover esta {noun} a la boveda",
         "{acct} contrasena caducada - restablecer por favor"),
    Lang("it", ["password", "parola_chiave", "pwd", "pass"],
         ["la_tua_password", "cambiami", "<PASSWORD>", "da_definire", "esempio"],
         "la {noun} di {sys} in {env} e {val} - aggiorna la configurazione",
         "Ticket {tk}: account reimpostato, {noun} iniziale: {val}",
         "[{date}] AUDIT {noun} impostata per {user}: {val}",
         "TODO: spostare questa {noun} nel vault",
         "{acct} password scaduta - reimpostare prego"),
    Lang("pt", ["senha", "palavra_passe", "pwd", "pass"],
         ["sua_senha", "altere_me", "<SENHA>", "a_definir", "exemplo"],
         "a {noun} do {sys} em {env} e {val} - atualize a configuracao",
         "Ticket {tk}: conta redefinida, {noun} inicial: {val}",
         "[{date}] AUDIT {noun} definida para {user}: {val}",
         "TODO: mover esta {noun} para o cofre",
         "{acct} senha expirada - redefina por favor"),
    Lang("nl", ["wachtwoord", "pwd", "pass"],
         ["uw_wachtwoord", "wijzig_mij", "<WACHTWOORD>", "nader_te_bepalen", "voorbeeld"],
         "het {sys}-{noun} in {env} is {val} - werk je configuratie bij",
         "Ticket {tk}: account gereset, initieel {noun}: {val}",
         "[{date}] AUDIT {noun} ingesteld voor {user}: {val}",
         "TODO: dit {noun} naar de kluis verplaatsen",
         "{acct} wachtwoord verlopen - reset alstublieft"),
    Lang("pl", ["haslo", "haslo_dostepu", "pwd", "pass"],
         ["twoje_haslo", "zmien_mnie", "<HASLO>", "do_ustalenia", "przyklad"],
         "haslo {sys} w {env} to {val} - zaktualizuj konfiguracje",
         "Zgloszenie {tk}: konto zresetowane, {noun} poczatkowe: {val}",
         "[{date}] AUDIT {noun} ustawione dla {user}: {val}",
         "TODO: przenies to {noun} do sejfu",
         "{acct} haslo wygaslo - zresetuj prosze"),
    Lang("tr", ["parola", "sifre", "şifre", "pwd"],
         ["parolaniz", "beni_degistir", "<PAROLA>", "belirlenecek", "ornek"],
         "{env} ortamindaki {sys} {noun} {val} - yapilandirmani guncelle",
         "Talep {tk}: hesap sifirlandi, ilk {noun}: {val}",
         "[{date}] AUDIT {noun} ayarlandi {user}: {val}",
         "TODO: bu {noun} kasaya tasi",
         "{acct} parola suresi doldu - sifirla lutfen"),
    Lang("ja", ["パスワード", "password", "pwd"],
         ["パスワードを入力", "変更してください", "<パスワード>", "未定", "サンプル"],
         "{env}環境の{sys}の{noun}は{val}です。設定を更新してください",
         "チケット{tk}: アカウントがリセットされました。初期{noun}: {val}",
         "[{date}] AUDIT {user}の{noun}を設定: {val}",
         "TODO: この{noun}をVaultに移動する",
         "{acct} パスワードの有効期限が切れました。リセットしてください"),
]
LANG_BY_CODE = {lang.code: lang for lang in LANGS}
ALL_PW_WORDS = sorted({w for lang in LANGS for w in lang.pw_words})


# --------------------------------------------------------------------------- #
# Credential value generators
# --------------------------------------------------------------------------- #

def _rand(rng: random.Random, alphabet: str, size: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(size))


def gen_hex(rng: random.Random, size: int) -> str:
    return _rand(rng, "0123456789abcdef", size)


def leetify(rng: random.Random, word: str) -> str:
    return "".join(LEET.get(c.lower(), c) if rng.random() < 0.7 else c for c in word)


def gen_password(rng: random.Random) -> str:
    """A human-chosen password matching the source-corpus distribution."""
    strategy = rng.choices(["word", "leet", "lower", "mixed", "keyboard"],
                           weights=[35, 15, 20, 20, 10])[0]
    if strategy == "word":
        pool = PW_NOUNS + PW_ELEMENTS + PW_SEASONS
        body = "".join(rng.sample(pool, rng.randint(1, 2)))
        body += _rand(rng, string.digits, rng.randint(2, 4))
        return body + _rand(rng, PW_SYMBOLS, rng.randint(0, 2))
    if strategy == "leet":
        parts = rng.sample(PW_NOUNS + PW_ELEMENTS, rng.randint(2, 3))
        return rng.choice(["_", "", "-"]).join(leetify(rng, p) for p in parts)
    if strategy == "lower":
        return _rand(rng, string.ascii_lowercase + string.digits, rng.randint(8, 16))
    if strategy == "mixed":
        return _rand(rng, ALNUM + PW_SYMBOLS_WIDE, rng.randint(12, 22))
    base = rng.choice(PW_KEYBOARD)
    if rng.random() < 0.6:
        base += _rand(rng, string.digits, rng.randint(2, 4))
    if rng.random() < 0.4:
        base += _rand(rng, PW_SYMBOLS, rng.randint(1, 2))
    return base


_PEM_HEADERS = {
    "openssh": "OPENSSH PRIVATE KEY",
    "rsa": "RSA PRIVATE KEY",
    "ec": "EC PRIVATE KEY",
    "pkcs8": "PRIVATE KEY",
    "dsa": "DSA PRIVATE KEY",
    "pgp": "PGP PRIVATE KEY BLOCK",
}


def gen_pem(rng: random.Random, kind: str) -> str:
    """A short PEM private-key block (3 base64 lines — synthetic, non-functional)."""
    header = _PEM_HEADERS.get(kind, "RSA PRIVATE KEY")
    body = "\n".join(_rand(rng, B64, 64) for _ in range(3))
    return f"-----BEGIN {header}-----\n{body}\n-----END {header}-----"


def gen_gcp_sa_json(rng: random.Random) -> str:
    """A GCP service-account key file — JSON with an embedded private key."""
    slug = _rand(rng, string.ascii_lowercase, 6)
    key_body = "\\n".join(_rand(rng, B64, 64) for _ in range(2))
    pem = f"-----BEGIN PRIVATE KEY-----\\n{key_body}\\n-----END PRIVATE KEY-----\\n"
    return ('{\n'
            '  "type": "service_account",\n'
            f'  "project_id": "axa-{slug}-prod",\n'
            f'  "private_key_id": "{gen_hex(rng, 40)}",\n'
            f'  "private_key": "{pem}",\n'
            f'  "client_email": "svc@axa-{slug}.iam.gserviceaccount.com"\n'
            '}')


@dataclass
class Cred:
    """A credential type: how it is named and how its value is generated."""

    cid: str
    keys: List[str]                              # base key aliases (snake_case)
    value: Callable[[random.Random], str]
    noun: str                                    # English noun for NL contexts
    groups: List[str]                            # allowed carrier groups
    is_password: bool = False


CRED_TYPES: List[Cred] = [
    Cred("password", ["password", "db_password", "service_password", "user_password"],
         gen_password, "password", ["kv", "cli", "connstring", "nl"], is_password=True),
    Cred("admin_password", ["admin_password", "root_password", "master_password"],
         gen_password, "admin password", ["kv", "cli", "nl"], is_password=True),
    Cred("ldap_password", ["ldap_bind_password", "bind_password", "ldap_password"],
         gen_password, "LDAP bind password", ["kv", "nl"], is_password=True),
    Cred("keystore_password", ["keystore_password", "truststore_password", "key_store_pwd"],
         gen_password, "keystore password", ["kv"], is_password=True),
    Cred("smtp_password", ["smtp_password", "mail_password"],
         gen_password, "SMTP password", ["kv", "nl"], is_password=True),
    Cred("private_key_passphrase", ["private_key_passphrase", "key_passphrase"],
         gen_password, "private-key passphrase", ["kv"], is_password=True),
    Cred("aws_access_key_id", ["aws_access_key_id"],
         lambda r: "AKIA" + _rand(r, AZ09, 16), "AWS access key id", ["kv", "cli"]),
    Cred("aws_secret_access_key", ["aws_secret_access_key", "aws_secret_key"],
         lambda r: _rand(r, B64, 40), "AWS secret access key", ["kv", "cli"]),
    Cred("azure_storage_key", ["azure_storage_key", "storage_account_key"],
         lambda r: _rand(r, B64, 86) + "==", "Azure storage account key", ["kv"]),
    Cred("gcp_api_key", ["gcp_api_key", "google_api_key"],
         lambda r: "AIza" + _rand(r, B64URL, 35), "GCP API key", ["kv", "header"]),
    Cred("stripe_secret", ["stripe_secret_key", "stripe_api_key"],
         lambda r: "sk_live_" + _rand(r, ALNUM, 24), "Stripe live secret key",
         ["kv", "header"]),
    Cred("github_pat", ["github_token", "gh_pat", "github_pat"],
         lambda r: "ghp_" + _rand(r, ALNUM, 36), "GitHub token", ["kv", "header", "cli"]),
    Cred("gitlab_pat", ["gitlab_token", "ci_job_token"],
         lambda r: "glpat-" + _rand(r, B64URL, 20), "GitLab token", ["kv", "header"]),
    Cred("npm_token", ["npm_token", "npm_auth_token"],
         lambda r: "npm_" + _rand(r, ALNUM, 36), "npm token", ["kv"]),
    Cred("slack_token", ["slack_bot_token", "slack_token"],
         lambda r: f"xoxb-{r.randint(10**11, 10**12)}-{r.randint(10**11, 10**12)}-"
                   + _rand(r, ALNUM, 24), "Slack bot token", ["kv", "nl"]),
    Cred("jwt", ["jwt", "id_token", "access_token"],
         lambda r: ".".join(_rand(r, B64URL, r.randint(24, 44)) for _ in range(3)),
         "JWT", ["kv", "header", "nl"]),
    Cred("oauth_client_secret", ["client_secret", "oauth_client_secret", "app_secret"],
         lambda r: _rand(r, ALNUM, r.randint(32, 48)), "OAuth client secret",
         ["kv", "header"]),
    Cred("bearer_token", ["bearer_token", "api_token", "auth_token"],
         lambda r: _rand(r, B64URL, 40), "bearer token", ["kv", "header", "cli", "nl"]),
    Cred("api_key_generic", ["api_key", "apikey", "x_api_key"],
         lambda r: gen_hex(r, 32), "API key", ["kv", "header", "cli", "nl"]),
    Cred("hmac_secret", ["hmac_secret", "webhook_secret", "signing_secret"],
         lambda r: gen_hex(r, 40), "HMAC signing secret", ["kv"]),
    Cred("encryption_key", ["encryption_key", "aes_key", "data_encryption_key"],
         lambda r: _rand(r, B64, 44), "encryption key", ["kv"]),
    Cred("vault_token", ["vault_token", "vault_root_token"],
         lambda r: "hvs." + _rand(r, ALNUM, 24), "Vault token", ["kv", "cli", "nl"]),
    Cred("db_connection_uri", ["database_url", "jdbc_url", "connection_string"],
         gen_password, "database connection string", ["connstring"]),
    Cred("ssh_private_key", ["ssh_private_key", "id_rsa"],
         lambda r: gen_pem(r, "openssh"), "SSH private key", ["pem"]),
    Cred("rsa_private_key", ["rsa_private_key", "tls_private_key"],
         lambda r: gen_pem(r, "rsa"), "RSA private key", ["pem"]),
    Cred("basic_auth", ["authorization"],
         gen_password, "HTTP basic-auth credentials", ["header", "cli"]),

    # --- Tier A: core secret types every scanner detects ---------------
    Cred("gcp_service_account_json", ["gcp_service_account", "google_credentials"],
         gen_gcp_sa_json, "GCP service-account key", ["pem"]),
    Cred("ec_private_key", ["ec_private_key", "ecdsa_key"],
         lambda r: gen_pem(r, "ec"), "EC private key", ["pem"]),
    Cred("pkcs8_private_key", ["private_key", "tls_private_key"],
         lambda r: gen_pem(r, "pkcs8"), "PKCS#8 private key", ["pem"]),
    Cred("dsa_private_key", ["dsa_private_key"],
         lambda r: gen_pem(r, "dsa"), "DSA private key", ["pem"]),
    Cred("pgp_private_key", ["pgp_private_key", "gpg_secret_key"],
         lambda r: gen_pem(r, "pgp"), "PGP private key", ["pem"]),
    Cred("pfx_password", ["pfx_password", "pkcs12_password", "p12_password"],
         gen_password, "PFX / PKCS#12 password", ["kv"], is_password=True),
    Cred("openai_api_key", ["openai_api_key", "openai_key"],
         lambda r: "sk-" + _rand(r, ALNUM, 48), "OpenAI API key", ["kv", "header"]),
    Cred("anthropic_api_key", ["anthropic_api_key", "claude_api_key"],
         lambda r: "sk-ant-api03-" + _rand(r, ALNUM + "-_", 80),
         "Anthropic API key", ["kv", "header"]),
    Cred("huggingface_token", ["hf_token", "huggingface_token"],
         lambda r: "hf_" + _rand(r, ALNUM, 34), "Hugging Face token", ["kv", "header"]),
    Cred("azure_ad_client_secret", ["azure_client_secret", "aad_client_secret"],
         lambda r: _rand(r, ALNUM, 3) + "8Q~" + _rand(r, ALNUM + "._-", 34),
         "Azure AD client secret", ["kv", "header"]),
    Cred("azure_sas_token", ["azure_sas_token", "sas_token"],
         lambda r: "sv=2023-01-03&ss=bfqt&srt=sco&sp=rwdlacupx&sig=" + _rand(r, B64, 43) + "%3D",
         "Azure SAS token", ["kv", "header"]),
    Cred("azure_connection_string", ["azure_storage_connection_string", "storage_connection_string"],
         lambda r: ("DefaultEndpointsProtocol=https;AccountName=axa"
                    + _rand(r, string.ascii_lowercase, 8) + ";AccountKey="
                    + _rand(r, B64, 86) + "==;EndpointSuffix=core.windows.net"),
         "Azure storage connection string", ["kv"]),
    Cred("redis_url", ["redis_url", "redis_connection_string"],
         lambda r: f"redis://:{gen_password(r)}@cache01.adsfr.intraxa:6379/0",
         "Redis connection URL", ["kv"]),
    Cred("amqp_url", ["amqp_url", "rabbitmq_url", "broker_url"],
         lambda r: f"amqp://svc_mq:{gen_password(r)}@mq01.adsfr.intraxa:5672/insurance",
         "AMQP / RabbitMQ connection URL", ["kv"]),

    # --- Tier B: AXA enterprise-specific -------------------------------
    Cred("saml_assertion", ["saml_response", "saml_assertion"],
         lambda r: _rand(r, B64, r.randint(180, 260)),
         "SAML assertion / ADFS token", ["kv", "header"]),
    Cred("kerberos_keytab", ["keytab", "krb5_keytab"],
         lambda r: _rand(r, B64, 200), "Kerberos keytab", ["pem"]),
    Cred("mainframe_password", ["racf_password", "tso_password", "mainframe_password"],
         lambda r: _rand(r, string.ascii_uppercase + string.digits, r.randint(6, 8)),
         "RACF / mainframe password", ["kv", "nl"], is_password=True),
    Cred("sap_password", ["sap_password", "ddic_password", "sapstar_password"],
         gen_password, "SAP password", ["kv", "cli", "nl"], is_password=True),

    # --- Tier C: SaaS breadth ------------------------------------------
    Cred("twilio_auth_token", ["twilio_auth_token", "twilio_token"],
         lambda r: gen_hex(r, 32), "Twilio auth token", ["kv", "header"]),
    Cred("sendgrid_api_key", ["sendgrid_api_key", "sendgrid_key"],
         lambda r: "SG." + _rand(r, B64URL, 22) + "." + _rand(r, B64URL, 43),
         "SendGrid API key", ["kv", "header"]),
    Cred("datadog_api_key", ["datadog_api_key", "dd_api_key"],
         lambda r: gen_hex(r, 32), "Datadog API key", ["kv", "header"]),
    Cred("atlassian_api_token", ["atlassian_api_token", "jira_api_token", "confluence_token"],
         lambda r: "ATATT3xFfGF0" + _rand(r, ALNUM, 40),
         "Atlassian / Jira API token", ["kv", "header"]),
    Cred("azure_devops_pat", ["azure_devops_pat", "ado_pat", "system_accesstoken"],
         lambda r: _rand(r, ALNUM, 52), "Azure DevOps PAT", ["kv", "header"]),
    Cred("dockerhub_token", ["dockerhub_token", "docker_pat"],
         lambda r: "dckr_pat_" + _rand(r, B64URL, 27), "Docker Hub token", ["kv", "cli"]),
    Cred("adyen_api_key", ["adyen_api_key", "adyen_key"],
         lambda r: "AQE" + _rand(r, B64, 90), "Adyen payment API key", ["kv", "header"]),

    # --- Tier D: other common secret patterns --------------------------
    Cred("framework_secret_key",
         ["secret_key", "secret_key_base", "django_secret_key", "flask_secret_key"],
         lambda r: _rand(r, ALNUM + "!@#$%^&*(-_=+)", 50),
         "web-framework secret key", ["kv"]),
    Cred("slack_webhook_url", ["slack_webhook_url", "webhook_url"],
         lambda r: ("https://hooks.slack.com/services/T" + _rand(r, AZ09, 10)
                    + "/B" + _rand(r, AZ09, 10) + "/" + _rand(r, ALNUM, 24)),
         "Slack webhook URL", ["kv", "nl"]),
    Cred("bcrypt_hash", ["password_hash", "htpasswd_entry"],
         lambda r: "$2b$12$" + _rand(r, ALNUM, 53), "bcrypt password hash", ["kv"]),
    Cred("totp_seed", ["totp_secret", "mfa_seed", "otp_secret"],
         lambda r: _rand(r, "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567", 32),
         "TOTP / 2FA seed", ["kv", "nl"]),
]


# --------------------------------------------------------------------------- #
# Mined vocabulary
# --------------------------------------------------------------------------- #

@dataclass
class MinedVocab:
    domains: List[str] = field(default_factory=lambda: list(CURATED_DOMAINS))
    domain_prefixes: List[str] = field(default_factory=lambda: list(CURATED_DOMAIN_PREFIXES))
    ticket_prefixes: List[str] = field(default_factory=lambda: list(CURATED_TICKET_PREFIXES))
    key_names: List[str] = field(default_factory=lambda: list(CURATED_KEY_NAMES))
    intraxa_domains: List[str] = field(default_factory=list)

    def finalize(self) -> "MinedVocab":
        self.domains = sorted(set(self.domains))
        self.domain_prefixes = sorted(set(self.domain_prefixes))
        self.ticket_prefixes = sorted(set(self.ticket_prefixes))
        self.key_names = sorted(set(self.key_names))
        self.intraxa_domains = sorted(d for d in self.domains if d.endswith(".intraxa"))
        if not self.intraxa_domains:
            self.intraxa_domains = [d for d in CURATED_DOMAINS if d.endswith(".intraxa")]
        return self


_SERVICE_LABELS = {"www", "auth", "login", "portal", "admin", "secure",
                   "sso", "api", "mail"}
_SERVER_LABEL = re.compile(r"^[a-z]{6}\d{6}$")
_HOSTNAME = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:intraxa|gbidns\.com|axa|local))\b")


def _domain_of(host: str) -> str:
    parts = host.split(".")
    if len(parts) > 2 and (_SERVER_LABEL.match(parts[0]) or parts[0] in _SERVICE_LABELS):
        return ".".join(parts[1:])
    return host


def load_tuple_rows(content: str) -> List[Tuple[object, object, object]]:
    """Minimal local copy of the processor's ``dataset = [...]`` loader."""
    try:
        module = ast.parse(content)
        for node in module.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "dataset" for t in node.targets
            ):
                rows: List[Tuple[object, object, object]] = []
                for row in ast.literal_eval(node.value):
                    if isinstance(row, (tuple, list)) and len(row) >= 3:
                        rows.append((row[0], row[1], row[2]))
                return rows
    except (SyntaxError, ValueError):
        pass
    return []


def mine_corpus(tp_path: Optional[Path], fp_path: Optional[Path]) -> MinedVocab:
    """Extract AXA vocabulary from the provided synthetic source files."""
    vocab = MinedVocab()
    text = ""
    for path in (tp_path, fp_path):
        if path and path.exists():
            text += path.read_text(encoding="utf-8", errors="ignore") + "\n"
    if not text:
        return vocab.finalize()

    for match in _HOSTNAME.finditer(text):
        vocab.domains.append(_domain_of(match.group(1)))
    vocab.domains.append("axa.com")

    # An AXA NETBIOS prefix is letters/hyphens only AND is followed by a
    # backslash + a user-id (e.g. AXASGP\P641UF). Requiring the user-id form
    # rejects password fragments that happen to precede an escaped backslash.
    for match in re.finditer(r"\b([A-Z][A-Z-]{2,11})\\+[A-Z]\d{3}[A-Z]{2}\b", text):
        vocab.domain_prefixes.append(match.group(1))
    for match in re.finditer(r"\b(INC|RITM|CHG)\d", text):
        vocab.ticket_prefixes.append(match.group(1))
    for match in re.finditer(
        r"\b([A-Z][A-Z0-9_]{2,}(?:PASSWORD|TOKEN|SECRET|PWD|KEY))\b", text
    ):
        vocab.key_names.append(match.group(1))
    return vocab.finalize()


# --------------------------------------------------------------------------- #
# Token helpers
# --------------------------------------------------------------------------- #

def gen_userid(rng: random.Random) -> str:
    """AXA user-id, e.g. ``L429ZC`` — letter + 3 digits + 2 letters."""
    return (rng.choice(string.ascii_uppercase) + _rand(rng, string.digits, 3)
            + _rand(rng, string.ascii_uppercase, 2))


def gen_username(rng: random.Random, vocab: MinedVocab) -> str:
    first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    style = rng.choices(["compact", "dotted", "hyphen", "email", "userid", "service"],
                        weights=[18, 22, 12, 25, 13, 10])[0]
    if style == "compact":
        return f"{first}{last}"
    if style == "dotted":
        return f"{first}.{last}"
    if style == "hyphen":
        return f"{last}-{first[0]}"
    if style == "email":
        return f"{first}.{last}@{rng.choice(vocab.domains)}"
    if style == "userid":
        return gen_userid(rng)
    return rng.choice(SERVICE_ACCOUNTS)


def gen_qualified_userid(rng: random.Random, vocab: MinedVocab) -> str:
    return (f"{rng.choice(vocab.domain_prefixes)}\\{gen_userid(rng)}"
            f"@{rng.choice(vocab.intraxa_domains)}")


def gen_server_fqdn(rng: random.Random, vocab: MinedVocab) -> str:
    label = _rand(rng, string.ascii_lowercase, 6) + _rand(rng, string.digits, 6)
    return f"{label}.{rng.choice(vocab.intraxa_domains)}"


def gen_db_host(rng: random.Random, vocab: MinedVocab) -> str:
    return (f"{rng.choice(DB_HOST_PREFIXES)}-{rng.choice(ENVIRONMENTS)}."
            f"{rng.choice(vocab.intraxa_domains)}")


def gen_ticket(rng: random.Random, vocab: MinedVocab) -> str:
    return f"{rng.choice(vocab.ticket_prefixes)}{rng.randint(100000, 99999999)}"


def gen_date(rng: random.Random) -> str:
    y, m, d = rng.randint(2024, 2026), rng.randint(1, 12), rng.randint(1, 28)
    return rng.choice([f"{y}-{m:02d}-{d:02d}", f"{y}/{m:02d}/{d:02d}",
                       f"{d:02d}/{m:02d}/{y}", f"{y}{m:02d}{d:02d}"])


def cased(rng: random.Random, base: str) -> str:
    """Render a key alias in a randomly-chosen identifier casing."""
    parts = [p for p in base.replace("-", "_").split("_") if p]
    style = rng.choice(["snake", "upper", "camel", "kebab", "pascal", "dotted"])
    if style == "snake":
        return "_".join(parts)
    if style == "upper":
        return "_".join(parts).upper()
    if style == "camel":
        return parts[0] + "".join(p.title() for p in parts[1:])
    if style == "kebab":
        return "-".join(parts)
    if style == "pascal":
        return "".join(p.title() for p in parts)
    return rng.choice(["spring.datasource.", "app.", "config.", "axa."]) + ".".join(parts)


def pick_key(rng: random.Random, cred: Cred) -> str:
    """A key name for ``cred`` — localised password words mixed in for variety."""
    pool = list(cred.keys)
    if cred.is_password and rng.random() < 0.55:
        pool.append(rng.choice(ALL_PW_WORDS))
    return cased(rng, rng.choice(pool))


def cred_value(rng: random.Random, cred: Cred) -> str:
    return cred.value(rng)


def nl_noun(rng: random.Random, cred: Cred, lang: Lang) -> str:
    """How to refer to ``cred`` inside a natural-language sentence."""
    if cred.is_password:
        return rng.choice(lang.pw_words)
    return cred.noun


# --------------------------------------------------------------------------- #
# Carriers — render (cred, key, value) into a context
# --------------------------------------------------------------------------- #

# Each carrier returns ``(context, username_or_None, secret)`` — the secret is
# the exact value embedded in the context, used for the record's password field.
Carried = Tuple[str, Optional[str], str]


def carrier_kv(rng: random.Random, lang: Lang, cred: Cred,
               vocab: MinedVocab) -> Carried:
    key = pick_key(rng, cred)
    val = cred_value(rng, cred)
    fmt = rng.choice(["properties", "yaml", "json", "xml", "dotenv",
                      "java", "python", "csharp", "js", "go"])
    comment = lang.comment.format(noun=nl_noun(rng, cred, lang))
    short = key.split(".")[-1]
    if fmt == "properties":
        head = f"# {comment}\n" if rng.random() < 0.4 else ""
        ctx = f"{head}{key}={val}"
    elif fmt == "yaml":
        ctx = f"datasource:\n  host: {gen_db_host(rng, vocab)}\n  {key}: {val}"
    elif fmt == "json":
        ctx = f'{{ "{key}": "{val}" }}'
    elif fmt == "xml":
        tag = "".join(p.title() for p in key.replace(".", "_").split("_"))
        ctx = f'<add key="{tag}" value="{val}" />'
    elif fmt == "dotenv":
        ctx = f"# .env\n{key.upper().replace('.', '_')}={val}"
    elif fmt == "java":
        ctx = f'String {short} = "{val}";  // {comment}'
    elif fmt == "python":
        ctx = f'{short} = "{val}"  # {comment}'
    elif fmt == "csharp":
        ctx = f'var {short} = "{val}"; // {comment}'
    elif fmt == "js":
        ctx = f"const {short} = '{val}'; // {comment}"
    else:
        ctx = f'{short} := "{val}" // {comment}'
    return ctx, None, val


def carrier_header(rng: random.Random, lang: Lang, cred: Cred,
                   vocab: MinedVocab) -> Carried:
    if cred.cid == "basic_auth":
        user = gen_username(rng, vocab)
        token = _rand(rng, B64, 28) + "=="
        return f"Authorization: Basic {token}", user, token
    val = cred_value(rng, cred)
    header = rng.choice(["Authorization: Bearer", "X-API-Key:", "X-Auth-Token:",
                         "Private-Token:"])
    return f"{header} {val}", None, val


def carrier_cli(rng: random.Random, lang: Lang, cred: Cred,
                vocab: MinedVocab) -> Carried:
    host = rng.choice(vocab.intraxa_domains)
    val = cred_value(rng, cred)
    if cred.is_password or cred.cid == "basic_auth":
        user = gen_username(rng, vocab)
        tool = rng.choice([
            f"curl -u {user}:{val} https://api.{host}/v1/policies",
            f"sshpass -p '{val}' ssh {user}@{gen_server_fqdn(rng, vocab)}",
            f"docker login -u {user} -p {val} registry.{host}",
        ])
        return tool, user, val
    return f'curl -H "Authorization: Bearer {val}" https://api.{host}/v1/quotes', None, val


def carrier_connstring(rng: random.Random, lang: Lang, cred: Cred,
                       vocab: MinedVocab) -> Carried:
    user = gen_username(rng, vocab)
    val = gen_password(rng)
    host = gen_db_host(rng, vocab)
    sys_ = rng.choice(INSURANCE_SYSTEMS)
    style = rng.choice(["jdbc_pg", "jdbc_mssql", "mongo", "uri"])
    if style == "jdbc_pg":
        ctx = f"jdbc:postgresql://{host}:5432/{sys_}db?user={user}&password={val}"
    elif style == "jdbc_mssql":
        ctx = f"jdbc:sqlserver://{host};databaseName={sys_};user={user};password={val}"
    elif style == "mongo":
        ctx = f"mongodb://{user}:{val}@{host}:27017/{sys_}"
    else:
        ctx = f"postgres://{user}:{val}@{host}/{sys_}"
    return ctx, user, val


def carrier_pem(rng: random.Random, lang: Lang, cred: Cred,
                vocab: MinedVocab) -> Carried:
    val = cred_value(rng, cred)
    comment = lang.comment.format(noun=cred.noun)
    return f"# {comment}\n{val}", None, val


def carrier_nl(rng: random.Random, lang: Lang, cred: Cred,
               vocab: MinedVocab) -> Carried:
    val = cred_value(rng, cred)
    noun = nl_noun(rng, cred, lang)
    kind = rng.choice(["chat", "reset", "audit", "comment_leak"])
    if kind == "chat":
        ctx = lang.chat.format(env=rng.choice(ENVIRONMENTS),
                               sys=rng.choice(INSURANCE_SYSTEMS), noun=noun, val=val)
        return ctx, None, val
    if kind == "reset":
        return lang.reset.format(tk=gen_ticket(rng, vocab), noun=noun, val=val), None, val
    if kind == "audit":
        user = gen_username(rng, vocab)
        ctx = lang.audit.format(date=gen_date(rng), user=user, noun=noun, val=val)
        return ctx, user, val
    # comment_leak — a hardcoded value flagged by a code comment
    return f'{lang.comment.format(noun=noun)}: "{val}"', None, val


CARRIER_GROUPS: Dict[str, Callable[..., Carried]] = {
    "kv": carrier_kv,
    "header": carrier_header,
    "cli": carrier_cli,
    "connstring": carrier_connstring,
    "pem": carrier_pem,
    "nl": carrier_nl,
}


def make_true_positive(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    """Compose a REAL record: pick a credential type, a compatible carrier and
    a language, then render. The carrier returns the exact embedded secret."""
    cred = rng.choice(CRED_TYPES)
    carrier = CARRIER_GROUPS[rng.choice(cred.groups)]
    context, username, secret = carrier(rng, rng.choice(LANGS), cred, vocab)
    return context[:MAX_CONTEXT_CHARS], username, secret, "REAL", cred.cid


# --------------------------------------------------------------------------- #
# FALSE-POSITIVE templates  ->  (context, matched_token_or_None, None)
# --------------------------------------------------------------------------- #

def fp_placeholder(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    lang = rng.choice(LANGS)
    cred = rng.choice([c for c in CRED_TYPES if c.is_password] + CRED_TYPES[:6])
    key = pick_key(rng, cred)
    ph = rng.choice(lang.placeholders)
    return f"{key}={ph}", None, None, "FALSE_POSITIVE", f"placeholder_{lang.code}"


def fp_env_example(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    cred = rng.choice(CRED_TYPES)
    key = pick_key(rng, cred).upper().replace(".", "_")
    ctx = (f"# .env.example - copy to .env and fill in real values\n"
           f"{key}=your-{cred.cid}-here")
    return ctx, None, None, "FALSE_POSITIVE", "env_example"


def fp_var_reference(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    cred = rng.choice(CRED_TYPES)
    key = pick_key(rng, cred)
    env = key.upper().replace(".", "_")
    ctx = rng.choice([
        f'password = os.getenv("{env}")',
        f"spring.datasource.{cred.keys[0]}=${{{env}}}",
        f'String s = System.getenv("{env}");',
        f"value: {{{{ .Values.secret.{cred.keys[0]} }}}}",
    ])
    return ctx, None, None, "FALSE_POSITIVE", "var_reference"


def fp_masked(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    cred = rng.choice([c for c in CRED_TYPES if c.is_password])
    mask = rng.choice(["********", "[hidden]", "xxxxxxxx", "<redacted>", "******"])
    return f"{pick_key(rng, cred)}={mask}", None, None, "FALSE_POSITIVE", "masked"


def fp_insurance_id(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    kind = rng.choice(["policy", "claim", "siret", "contract"])
    if kind == "policy":
        token = f"POL{rng.randint(10**8, 10**9 - 1)}"
        ctx = f"police n {token} - verifier le mot de passe du souscripteur"
    elif kind == "claim":
        token = f"CLM-{rng.randint(2024, 2026)}-{rng.randint(100000, 999999)}"
        ctx = f"claim reference {token} logged; password reset email queued"
    elif kind == "siret":
        token = _rand(rng, string.digits, 14)
        ctx = f"SIRET {token} - contrat groupe AXA, password policy attached"
    else:
        token = f"CTR{gen_hex(rng, 10).upper()}"
        ctx = f"contract id {token} requires password confirmation by client"
    return ctx, token, None, "FALSE_POSITIVE", "insurance_id"


def fp_sandbox_key(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    token = "sk_test_" + _rand(rng, ALNUM, 24)
    ctx = f"# sandbox only - not a live secret\npayment.api.key={token}"
    return ctx, token, None, "FALSE_POSITIVE", "sandbox_key"


def fp_commit_hash(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    sha = gen_hex(rng, 40)
    ctx = (f"deployed commit {sha} to {rng.choice(ENVIRONMENTS)} - "
           f"password module unchanged")
    return ctx, sha, None, "FALSE_POSITIVE", "commit_hash"


def fp_iban(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    iban = "FR76" + _rand(rng, string.digits, 20)
    return (f"exemple IBAN pour le formulaire: {iban} (donnee fictive)",
            iban, None, "FALSE_POSITIVE", "iban_example")


def fp_uuid(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    parts = [gen_hex(rng, n) for n in (8, 4, 4, 4, 12)]
    uid = "-".join(parts)
    ctx = f"correlation id {uid} logged for the password-reset request"
    return ctx, uid, None, "FALSE_POSITIVE", "uuid"


def fp_policy_line(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    ctx = rng.choice([
        f"password policy: minimum {rng.randint(8, 16)} characters required",
        f"longueur minimale du mot de passe : {rng.randint(8, 16)} caracteres",
        f"Passwort-Mindestlaenge: {rng.randint(8, 16)} Zeichen",
        f"password audit completed {gen_date(rng)}",
        f"next password rotation due {gen_date(rng)}",
    ])
    return ctx, None, None, "FALSE_POSITIVE", "policy_line"


def fp_reset_url(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    ctx = (f"self-service password reset: "
           f"https://auth.{rng.choice(vocab.intraxa_domains)}/account/password/change")
    return ctx, None, None, "FALSE_POSITIVE", "reset_url"


def fp_account_mention(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    lang = rng.choice(LANGS)
    acct = gen_qualified_userid(rng, vocab)
    return (lang.expired.format(acct=acct), acct, None,
            "FALSE_POSITIVE", f"account_mention_{lang.code}")


FP_TEMPLATES: List[Callable[[random.Random, MinedVocab], GenRecord]] = [
    fp_placeholder, fp_placeholder, fp_env_example, fp_var_reference, fp_masked,
    fp_insurance_id, fp_sandbox_key, fp_commit_hash, fp_iban, fp_uuid,
    fp_policy_line, fp_reset_url, fp_account_mention,
]


# --------------------------------------------------------------------------- #
# REVIEW templates  ->  genuinely ambiguous; the model should abstain
# --------------------------------------------------------------------------- #

def rv_partial_mask(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    pw = gen_password(rng)
    masked = pw[:3] + "****" + pw[-2:]
    cred = rng.choice([c for c in CRED_TYPES if c.is_password])
    return f"{pick_key(rng, cred)}={masked}", None, masked, "REVIEW", "partial_mask"


def rv_historical(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    pw = gen_password(rng)
    return (f"the old password was {pw} - it has since been rotated, do not reuse",
            None, pw, "REVIEW", "historical")


def rv_hash_or_password(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    token = gen_hex(rng, 40)
    return (f"password hash stored for the account: {token}",
            None, token, "REVIEW", "hash_or_password")


def rv_bare_value(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    user = gen_username(rng, vocab)
    token = gen_password(rng)
    return f"{user} / {token}", user, token, "REVIEW", "bare_value"


def rv_example_plausible(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    pw = "ChangeMe" + _rand(rng, string.digits, 4) + rng.choice("!#$")
    cred = rng.choice([c for c in CRED_TYPES if c.is_password])
    return f"{pick_key(rng, cred)}={pw}", None, pw, "REVIEW", "example_plausible"


def rv_default_fallback(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    pw = gen_password(rng)
    cred = rng.choice([c for c in CRED_TYPES if c.is_password])
    key = pick_key(rng, cred)
    return f"{key}=${{{key.upper()}:-{pw}}}", None, pw, "REVIEW", "default_fallback"


def rv_truncated_token(rng: random.Random, vocab: MinedVocab) -> GenRecord:
    token = "ghp_" + _rand(rng, ALNUM, 8) + "..."
    return (f"token logged (truncated): {token}", None, token,
            "REVIEW", "truncated_token")


REVIEW_TEMPLATES: List[Callable[[random.Random, MinedVocab], GenRecord]] = [
    rv_partial_mask, rv_historical, rv_hash_or_password, rv_bare_value,
    rv_example_plausible, rv_default_fallback, rv_truncated_token,
]


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #

def generate(make: Callable, count: int, rng: random.Random,
             vocab: MinedVocab, seen: set) -> List[GenRecord]:
    out: List[GenRecord] = []
    attempts, cap = 0, count * 60
    while len(out) < count and attempts < cap:
        attempts += 1
        record = make(rng, vocab)
        context = record[0][:MAX_CONTEXT_CHARS]
        if context in seen:
            continue
        seen.add(context)
        out.append((context,) + record[1:])
    if len(out) < count:
        print(f"  WARNING: only {len(out)}/{count} unique records produced")
    return out


def render_dataset_file(records: List[GenRecord], label: str, seed: int,
                        hint: str) -> str:
    header = (
        f"# CRED-HUUNT v2 - AXA Group SYNTHETIC dataset ({label})\n"
        f"# Format: (context_text, username_or_None, password_or_None)\n"
        f"# {hint}\n"
        f"# Generated by scripts/generate_axa_synthetic.py - seed={seed}, "
        f"records={len(records)}, utc={datetime.utcnow().isoformat(timespec='seconds')}Z\n"
        f"# SYNTHETIC DATA ONLY - all credential values are randomly generated.\n"
        f"# Not a real AXA secret. Do not add real credentials to this file.\n\n"
        f"dataset = [\n"
    )
    lines = [f"    {(ctx, user, pw)!r}," for ctx, user, pw, _l, _c in records]
    return header + "\n".join(lines) + "\n]\n"


def write_jsonl(path: Path, records: List[GenRecord]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for ctx, user, pw, label, category in records:
            handle.write(json.dumps({
                "context": ctx, "username": user, "password": pw,
                "label": label, "category": category,
            }, ensure_ascii=False) + "\n")


def category_counts(records: List[GenRecord]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for *_rest, category in records:
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def _autodetect(data_dir: Path, stem: str) -> Optional[Path]:
    for candidate in (data_dir / f"{stem}.crdownload", data_dir / f"{stem} (1).crdownload"):
        if candidate.exists():
            return candidate
    matches = sorted(data_dir.glob(f"{stem}*.crdownload"))
    return matches[0] if matches else None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-tp", type=Path, default=None,
                        help="Source true-positive corpus to mine (auto-detected in data/).")
    parser.add_argument("--source-fp", type=Path, default=None,
                        help="Source false-positive corpus to mine (auto-detected in data/).")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "synthetic",
                        help="Output directory (default: data/synthetic - never data/).")
    parser.add_argument("--n-tp", type=int, default=4000, help="True-positive records.")
    parser.add_argument("--n-fp", type=int, default=4000, help="False-positive records.")
    parser.add_argument("--n-review", type=int, default=700, help="REVIEW records (~8%).")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic RNG seed.")
    parser.add_argument("--jsonl", dest="jsonl", action="store_true", default=True,
                        help="Also emit inspection JSONL (default: on).")
    parser.add_argument("--no-jsonl", dest="jsonl", action="store_false")
    parser.add_argument("--no-mine", action="store_true",
                        help="Skip corpus mining; use curated vocabulary only.")
    parser.add_argument("--report", type=Path, default=None,
                        help="Generation report path (default: <out-dir>/axa_generation_report.json).")
    return parser


def main() -> None:
    args = build_argparser().parse_args()
    data_dir = ROOT / "data"

    if args.out_dir.resolve() == data_dir.resolve():
        raise SystemExit("Refusing to write into data/ - that would overwrite the "
                         "source corpus. Use --out-dir data/synthetic.")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    tp_src = args.source_tp or _autodetect(data_dir, "true_positive")
    fp_src = args.source_fp or _autodetect(data_dir, "false_positive")

    if args.no_mine:
        vocab = MinedVocab().finalize()
        print("Mining skipped - using curated AXA vocabulary.")
    else:
        vocab = mine_corpus(tp_src, fp_src)
        print(f"Mined vocabulary from: tp={tp_src}, fp={fp_src}")
    print(f"  domains={len(vocab.domains)}  prefixes={len(vocab.domain_prefixes)}  "
          f"tickets={vocab.ticket_prefixes}  key_names={len(vocab.key_names)}")
    print(f"  languages={len(LANGS)}  credential_types={len(CRED_TYPES)}  "
          f"carriers={len(CARRIER_GROUPS)}")

    rng = random.Random(args.seed)
    seen: set = set()
    tp = generate(make_true_positive, args.n_tp, rng, vocab, seen)
    fp = generate(lambda r, v: rng.choice(FP_TEMPLATES)(r, v),
                  args.n_fp, rng, vocab, seen)
    review = generate(lambda r, v: rng.choice(REVIEW_TEMPLATES)(r, v),
                       args.n_review, rng, vocab, seen)

    outputs = {
        "true_positive": (tp, "REAL secrets embedded in AXA enterprise contexts."),
        "false_positive": (fp, "Credential-shaped noise - NOT secrets."),
        "review": (review, "Genuinely ambiguous - the v2 REVIEW class."),
    }
    for stem, (records, hint) in outputs.items():
        path = args.out_dir / f"{stem}.crdownload"
        path.write_text(render_dataset_file(records, stem, args.seed, hint),
                        encoding="utf-8")
        print(f"Wrote {path}  ({len(records)} records)")
        if args.jsonl:
            jsonl_path = args.out_dir / f"{stem}.jsonl"
            write_jsonl(jsonl_path, records)
            print(f"Wrote {jsonl_path}")

    report = {
        "generator": "generate_axa_synthetic.py",
        "seed": args.seed,
        "generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source_tp": str(tp_src) if tp_src else None,
        "source_fp": str(fp_src) if fp_src else None,
        "mining": not args.no_mine,
        "coverage": {
            "languages": [lang.code for lang in LANGS],
            "credential_types": [c.cid for c in CRED_TYPES],
            "carriers": sorted(CARRIER_GROUPS),
        },
        "vocab": {
            "domains": len(vocab.domains),
            "domain_prefixes": vocab.domain_prefixes,
            "ticket_prefixes": vocab.ticket_prefixes,
        },
        "counts": {stem: len(records) for stem, (records, _h) in outputs.items()},
        "categories": {stem: category_counts(records)
                       for stem, (records, _h) in outputs.items()},
    }
    report_path = args.report or (args.out_dir / "axa_generation_report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    print(f"Wrote {report_path}")
    total = sum(len(r) for r, _h in outputs.values())
    print(f"Done. {total} records total "
          f"(TP {len(tp)} / FP {len(fp)} / REVIEW {len(review)}).")


if __name__ == "__main__":
    main()
