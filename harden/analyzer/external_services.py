"""External service integration detection — three-layer approach.

Layer 1: Package manifest lookup.  Cross-reference declared dependencies
         against a curated dict of known service packages.

Layer 2: AST-based import extraction.  Parse every .py file, extract imports,
         and match against the known services dict.  Replaces regex-based
         import + usage-pattern scanning.

Layer 3: URL extraction from AST string literals.  Finds HTTP(S) URLs in code
         to detect HTTP API integrations.  Replaces regex-based URL scanning.

Auth method detection uses the shared detect_config_method from ast_utils.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from harden.analyzer.models import ExternalServiceInfo
from harden.analyzer.ast_utils import (
    extract_imports,
    root_package,
    normalise_package_name,
    collect_declared_deps,
    detect_config_method,
    extract_domains_from_urls,
    iter_python_files,
    read_source,
    STDLIB_ROOTS,
)

# ---------------------------------------------------------------------------
# Known external service packages
# ---------------------------------------------------------------------------
# Key = PyPI package name or import name.
# Value = (provider, category, default_auth, egress_domains)
#
# This replaces the old regex-based EXTERNAL_SERVICE_SDKS dict.
# Adding a new service = one line in this dict (no regex to maintain).

KNOWN_SERVICES: Dict[str, Tuple[str, str, str, List[str]]] = {
    # CRM
    "simple_salesforce":     ("Salesforce",             "crm",           "api_key",           ["login.salesforce.com", "*.my.salesforce.com"]),
    "hubspot":               ("HubSpot",               "crm",           "api_key",           ["api.hubapi.com"]),

    # Microsoft / Office
    "msgraph":               ("Microsoft Graph",       "office",        "oauth",             ["graph.microsoft.com"]),
    "msal":                  ("Microsoft Identity",    "office",        "oauth",             ["login.microsoftonline.com"]),
    "openpyxl":              ("Excel (local)",         "office",        "none",              []),
    # python-docx: PyPI name is "python-docx", import name is "docx"
    "docx":                  ("Word (local)",          "office",        "none",              []),

    # Databases
    "psycopg2":              ("PostgreSQL",            "database",      "connection_string", []),
    "psycopg":               ("PostgreSQL",            "database",      "connection_string", []),
    "pymongo":               ("MongoDB",              "database",      "connection_string", []),
    "motor":                 ("MongoDB",              "database",      "connection_string", []),
    "sqlalchemy":            ("SQLAlchemy",            "database",      "connection_string", []),
    "redis":                 ("Redis",                "database",      "connection_string", []),
    "elasticsearch":         ("Elasticsearch",        "database",      "api_key",           []),
    "pymysql":               ("MySQL",                "database",      "connection_string", []),
    "mysql.connector":       ("MySQL",                "database",      "connection_string", []),
    "sqlite3":               ("SQLite",               "database",      "none",              []),
    "aiosqlite":             ("SQLite",               "database",      "none",              []),

    # Message queues
    "pika":                  ("RabbitMQ",             "message_queue", "connection_string", []),
    "kafka":                 ("Kafka",                "message_queue", "connection_string", []),
    "celery":                ("Celery",               "message_queue", "connection_string", []),

    # Cloud - AWS
    "boto3":                 ("AWS",                  "cloud",         "iam",               ["*.amazonaws.com"]),
    "botocore":              ("AWS",                  "cloud",         "iam",               ["*.amazonaws.com"]),

    # Cloud - GCP
    "google.cloud.storage":  ("Google Cloud Storage", "cloud",         "iam",               ["storage.googleapis.com"]),
    "google.cloud.bigquery": ("Google Cloud BigQuery","cloud",         "iam",               ["bigquery.googleapis.com"]),
    "google.cloud.pubsub":   ("Google Cloud Pub/Sub", "cloud",         "iam",               ["pubsub.googleapis.com"]),
    "google.cloud.firestore":("Google Cloud Firestore","cloud",        "iam",               ["firestore.googleapis.com"]),

    # Cloud - Azure
    "azure.storage.blob":    ("Azure Blob Storage",   "cloud",         "iam",               ["blob.core.windows.net"]),
    "azure.storage":         ("Azure Storage",        "cloud",         "iam",               ["blob.core.windows.net"]),
    "azure.identity":        ("Azure Identity",       "cloud",         "iam",               ["login.microsoftonline.com"]),
    "azure.cosmos":          ("Azure Cosmos DB",      "cloud",         "connection_string", ["*.documents.azure.com"]),

    # Payments
    "stripe":                ("Stripe",               "payments",      "api_key",           ["api.stripe.com"]),

    # Email / notifications
    "sendgrid":              ("SendGrid",             "email",         "api_key",           ["api.sendgrid.com"]),
    "twilio":                ("Twilio",               "notifications", "api_key",           ["api.twilio.com"]),
    "slack_sdk":             ("Slack",                "notifications", "api_key",           ["slack.com"]),
}

# ---------------------------------------------------------------------------
# Service governance metadata — rate limits, cost, retry behavior
# ---------------------------------------------------------------------------
# Keyed by the same package names as KNOWN_SERVICES.  Looked up at generation
# time to populate the outbound_guard.py artifact.  Services without an entry
# here get DEFAULT_GOVERNANCE.

DEFAULT_GOVERNANCE: dict = {
    "rate_limit": None,
    "cost_per_call": None,
    "retry": {"max_retries": 2, "backoff_base": 1.0, "retry_on": [429, 500, 502, 503]},
    "rate_limit_headers": None,
}

SERVICE_GOVERNANCE: Dict[str, dict] = {
    # ── CRM ────────────────────────────────────────────────────────
    "simple_salesforce": {
        "rate_limit": {"requests": 100, "period_seconds": 900},
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": [429, 500, 502, 503]},
        "rate_limit_headers": {"remaining": "Sforce-Limit-Info", "reset": None},
    },
    "hubspot": {
        "rate_limit": {"requests": 100, "period_seconds": 10},
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": [429, 500, 502, 503]},
        "rate_limit_headers": {"remaining": "X-HubSpot-RateLimit-Remaining", "reset": "X-HubSpot-RateLimit-Reset"},
    },

    # ── Payments ───────────────────────────────────────────────────
    "stripe": {
        "rate_limit": {"requests": 100, "period_seconds": 1},
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 0.5, "retry_on": [429, 500, 502, 503]},
        "rate_limit_headers": {"remaining": "X-RateLimit-Remaining", "reset": "X-RateLimit-Reset"},
    },

    # ── Email / Notifications ──────────────────────────────────────
    "sendgrid": {
        "rate_limit": {"requests": 600, "period_seconds": 60},
        "cost_per_call": {"email": 0.00025, "default": 0.00025},
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": [429, 500, 502, 503]},
        "rate_limit_headers": {"remaining": "X-RateLimit-Remaining", "reset": "X-RateLimit-Reset"},
    },
    "twilio": {
        "rate_limit": {"requests": 100, "period_seconds": 1},
        "cost_per_call": {"sms": 0.0079, "voice": 0.013, "default": 0.0079},
        "retry": {"max_retries": 2, "backoff_base": 0.5, "retry_on": [429, 500, 502, 503]},
        "rate_limit_headers": {"remaining": "X-RateLimit-Remaining", "reset": "X-RateLimit-Reset"},
    },
    "slack_sdk": {
        "rate_limit": {"requests": 1, "period_seconds": 1},
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": [429, 500, 502, 503]},
        "rate_limit_headers": {"remaining": None, "reset": "Retry-After"},
    },

    # ── Cloud ──────────────────────────────────────────────────────
    "boto3": {
        "rate_limit": None,
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": [429, 500, 502, 503, 504]},
        "rate_limit_headers": None,
    },
    "botocore": {
        "rate_limit": None,
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": [429, 500, 502, 503, 504]},
        "rate_limit_headers": None,
    },
    "google.cloud.storage": {
        "rate_limit": None,
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": [429, 500, 502, 503]},
        "rate_limit_headers": None,
    },
    "google.cloud.bigquery": {
        "rate_limit": None,
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": [429, 500, 502, 503]},
        "rate_limit_headers": None,
    },

    # ── Databases ──────────────────────────────────────────────────
    "psycopg2": {
        "rate_limit": None,
        "cost_per_call": None,
        "retry": {"max_retries": 2, "backoff_base": 0.5, "retry_on": []},
        "rate_limit_headers": None,
    },
    "psycopg": {
        "rate_limit": None,
        "cost_per_call": None,
        "retry": {"max_retries": 2, "backoff_base": 0.5, "retry_on": []},
        "rate_limit_headers": None,
    },
    "pymongo": {
        "rate_limit": None,
        "cost_per_call": None,
        "retry": {"max_retries": 2, "backoff_base": 0.5, "retry_on": []},
        "rate_limit_headers": None,
    },
    "redis": {
        "rate_limit": None,
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 0.3, "retry_on": []},
        "rate_limit_headers": None,
    },
    "elasticsearch": {
        "rate_limit": None,
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": [429, 500, 502, 503]},
        "rate_limit_headers": None,
    },

    # ── Microsoft ──────────────────────────────────────────────────
    "msgraph": {
        "rate_limit": {"requests": 10000, "period_seconds": 600},
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": [429, 500, 502, 503, 504]},
        "rate_limit_headers": {"remaining": "RateLimit-Remaining", "reset": "RateLimit-Reset"},
    },

    # ── Message Queues ─────────────────────────────────────────────
    "pika": {
        "rate_limit": None,
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": []},
        "rate_limit_headers": None,
    },
    "kafka": {
        "rate_limit": None,
        "cost_per_call": None,
        "retry": {"max_retries": 3, "backoff_base": 1.0, "retry_on": []},
        "rate_limit_headers": None,
    },
}


def get_service_governance(sdk_key: str) -> dict:
    """Look up governance metadata for a service, falling back to defaults."""
    return SERVICE_GOVERNANCE.get(sdk_key, DEFAULT_GOVERNANCE)


# Packages that should NOT be flagged as external services
_NON_SERVICE_PACKAGES = STDLIB_ROOTS | frozenset({
    # Frameworks (handled by detector.py)
    "flask", "fastapi", "django", "starlette", "uvicorn", "gunicorn",
    "werkzeug", "itsdangerous", "jinja2",
    "streamlit", "gradio",
    # Common libraries that aren't services
    "click", "typer", "rich", "tqdm", "pydantic", "attrs",
    "numpy", "pandas", "scipy", "matplotlib", "seaborn", "plotly",
    "pytest", "unittest", "coverage",
    "yaml", "pyyaml", "toml", "tomli", "dotenv",
    "cryptography", "bcrypt", "jwt",
    "beautifulsoup4", "bs4", "lxml",
    "pillow", "PIL",
    "black", "ruff", "isort", "mypy",
    # AI packages (handled by ai_usage.py)
    "openai", "anthropic", "langchain", "transformers", "torch",
    "tensorflow", "keras", "chromadb", "pinecone", "huggingface_hub",
})


_ALIASES = {
    # PyPI name → canonical (import name)
    "python-docx": "docx", "python_docx": "docx",
    "kafka-python": "kafka", "kafka_python": "kafka",
    "mysql-connector-python": "mysql.connector", "mysql_connector": "mysql.connector",
    "mysql_connector_python": "mysql.connector",
}


def _build_lookup() -> Dict[str, Tuple[str, str, str, List[str]]]:
    """Build a lookup dict keyed by normalized forms."""
    lookup = {}
    for key, val in KNOWN_SERVICES.items():
        lookup[key.lower()] = val
        lookup[normalise_package_name(key)] = val
    for alias, canonical in _ALIASES.items():
        if canonical in lookup and alias not in lookup:
            lookup[alias] = lookup[canonical]
    return lookup


_LOOKUP = _build_lookup()


def _canonical_key(name: str) -> str:
    """Map any package name variant to its canonical key (import name)."""
    lower = name.lower()
    if lower in _ALIASES:
        return _ALIASES[lower]
    norm = normalise_package_name(name)
    if norm in _ALIASES:
        return _ALIASES[norm]
    return lower


def _match_import(import_path: str) -> Optional[Tuple[str, str, str, str, List[str]]]:
    """Try to match an import path against known services.

    Returns (sdk_key, provider, category, auth, domains) or None.
    The sdk_key is always the canonical (import) name.
    """
    parts = import_path.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        for norm in (candidate.lower(), normalise_package_name(candidate)):
            if norm in _LOOKUP:
                provider, category, auth, domains = _LOOKUP[norm]
                return _canonical_key(norm), provider, category, auth, domains
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_external_services(project_path: str) -> List[ExternalServiceInfo]:
    """Detect external service integrations in the project.

    Three-layer detection:
    1. Cross-reference declared dependencies against KNOWN_SERVICES.
    2. AST-parse all .py files, extract imports, match against KNOWN_SERVICES.
    3. Extract URLs from string literals to detect HTTP API calls.
    """
    project = Path(project_path)

    # Layer 1: Package manifest lookup
    declared_deps = collect_declared_deps(project)
    found: Dict[str, dict] = {}

    for dep_name in declared_deps:
        for norm in (dep_name.lower(), normalise_package_name(dep_name)):
            if norm in _LOOKUP:
                provider, category, auth, domains = _LOOKUP[norm]
                sdk_key = _canonical_key(norm)
                _merge_found(found, sdk_key, provider, category, auth, domains, "(dependency manifest)")
                break

    # Layer 2: AST import extraction
    for py_file in iter_python_files(project):
        source = read_source(py_file)
        if not source:
            continue

        rel_path = str(py_file.relative_to(project))
        imports = extract_imports(source)

        file_has_service = False
        for imp in imports:
            match = _match_import(imp)
            if match:
                sdk_key, provider, category, auth, domains = match
                _merge_found(found, sdk_key, provider, category, auth, domains, rel_path)
                file_has_service = True

        # Refine auth method from file context
        if file_has_service:
            cm = detect_config_method(source)
            if cm != "unknown":
                for sdk_key, info in found.items():
                    if rel_path in info.get("files", []):
                        if info.get("auth_method") in ("unknown", info.get("default_auth")):
                            info["auth_method"] = cm

        # Layer 3: Extract external URLs from string literals
        ext_domains = extract_domains_from_urls(source)
        for domain in ext_domains:
            # Skip domains already covered by known services
            if _domain_covered(domain, found):
                continue
            domain_key = f"http_api_{domain}"
            _merge_found(found, domain_key, f"HTTP API ({domain})", "http_api",
                         "unknown", [domain], rel_path)

    # Check for Django database backends (string patterns in settings)
    _detect_django_db(project, found)

    # Build results
    results = []
    for sdk_key, info in found.items():
        results.append(ExternalServiceInfo(
            provider=info["provider"],
            category=info["category"],
            sdk=sdk_key,
            auth_method=info.get("auth_method", "unknown"),
            domains=info.get("domains", []),
            files=info.get("files", []),
        ))

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _merge_found(found: dict, sdk_key: str, provider: str, category: str,
                 auth: str, domains: list, source_file: str = ""):
    """Merge a detection into the found dict, deduplicating files."""
    if sdk_key not in found:
        found[sdk_key] = {
            "provider": provider,
            "category": category,
            "auth_method": auth,
            "default_auth": auth,
            "domains": list(domains),
            "files": [],
        }
    if source_file and source_file not in found[sdk_key]["files"]:
        found[sdk_key]["files"].append(source_file)


def _domain_covered(domain: str, found: dict) -> bool:
    """Check if a domain is already covered by a known service's domains."""
    for info in found.values():
        for d in info.get("domains", []):
            if d == domain:
                return True
            # Wildcard match: *.amazonaws.com matches s3.amazonaws.com
            if d.startswith("*.") and domain.endswith(d[1:]):
                return True
    return False


def _detect_django_db(project: Path, found: dict):
    """Detect Django database backends from settings strings.

    Django DATABASES uses string paths like 'django.db.backends.postgresql'
    which won't appear as imports but as string values in assignments.
    """
    backend_map = {
        "postgresql": ("PostgreSQL (Django)", "database"),
        "mysql": ("MySQL (Django)", "database"),
        "oracle": ("Oracle (Django)", "database"),
        "sqlite3": ("SQLite (Django)", "database"),
    }

    for py_file in iter_python_files(project):
        source = read_source(py_file)
        if not source:
            continue

        # Quick check before AST parsing
        if "django.db.backends" not in source:
            continue

        rel_path = str(py_file.relative_to(project))
        for backend, (provider, category) in backend_map.items():
            pattern = f"django.db.backends.{backend}"
            if pattern in source:
                key = f"django_db_{backend}"
                _merge_found(found, key, provider, category, "connection_string", [], rel_path)
