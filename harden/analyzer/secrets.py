"""Secret and credential detection — AST + pattern matching approach.

For Python files: uses AST-based assignment extraction to find
(variable_name, string_value, lineno) tuples, then checks values against
known API key formats, connection string patterns, and entropy heuristics.
This catches dict literals, keyword args, and multi-line assignments that
line-by-line regex misses, while ignoring comments automatically.

For config files (.env, .yaml, .json, .toml): uses regex scanning since
they are not Python-parseable.
"""

import math
import re
from collections import Counter
from pathlib import Path
from typing import List

from harden.analyzer.models import SecretFinding
from harden.analyzer.ast_utils import (
    extract_assignments,
    iter_python_files,
    read_source,
    SKIP_DIRS,
)

# ---------------------------------------------------------------------------
# Known secret VALUE patterns (applied to extracted string values)
# ---------------------------------------------------------------------------

_SECRET_VALUE_PATTERNS = {
    "openai_api_key":       (re.compile(r'^sk-[a-zA-Z0-9]{20,}$'),           "OpenAI API Key"),
    "openai_api_key_new":   (re.compile(r'^sk-proj-[a-zA-Z0-9_-]{20,}$'),    "OpenAI API Key (new format)"),
    "anthropic_api_key":    (re.compile(r'^sk-ant-[a-zA-Z0-9_-]{20,}$'),     "Anthropic API Key"),
    "google_api_key":       (re.compile(r'^AIza[0-9A-Za-z_-]{35}$'),          "Google API Key"),
    "groq_api_key":         (re.compile(r'^gsk_[a-zA-Z0-9]{20,}$'),          "Groq API Key"),
    "aws_access_key":       (re.compile(r'^AKIA[0-9A-Z]{16}$'),              "AWS Access Key ID"),
    "github_token":         (re.compile(r'^ghp_[a-zA-Z0-9]{36}$'),           "GitHub Personal Access Token"),
    "slack_token":          (re.compile(r'^xox[baprs]-[0-9a-zA-Z]{10,}$'),   "Slack Token"),
    "stripe_key":           (re.compile(r'^sk_live_[0-9a-zA-Z]{24,}$'),      "Stripe Secret Key"),
    "huggingface_token":    (re.compile(r'^hf_[a-zA-Z0-9]{20,}$'),           "HuggingFace Token"),
    "replicate_token":      (re.compile(r'^r8_[a-zA-Z0-9]{20,}$'),           "Replicate Token"),
    "openrouter_key":       (re.compile(r'^sk-or-v1-[a-zA-Z0-9]{20,}$'),     "OpenRouter API Key"),
}

# Connection string patterns (applied to string values — partial match)
_CONNECTION_STRING_PATTERNS = {
    "mongodb_connection":    (re.compile(r'mongodb(?:\+srv)?://[^:]+:[^@]+@'),  "MongoDB connection string with embedded credentials"),
    "postgresql_connection": (re.compile(r'postgres(?:ql)?://[^:]+:[^@]+@'),    "PostgreSQL connection string with embedded credentials"),
    "mysql_connection":      (re.compile(r'mysql(?:\+pymysql)?://[^:]+:[^@]+@'),"MySQL connection string with embedded credentials"),
    "redis_connection":      (re.compile(r'rediss?://:[^@]+@'),                 "Redis connection string with embedded credentials"),
    "amqp_connection":       (re.compile(r'amqps?://[^:]+:[^@]+@'),             "AMQP connection string with embedded credentials"),
}

# Variable name indicators for entropy-based detection
_SECRET_NAME_INDICATORS = frozenset({
    "key", "secret", "token", "password", "passwd", "pwd",
    "auth", "api", "credential", "api_key", "apikey",
    "secret_key", "access_key",
})

# Values containing these are probably examples/placeholders
_SKIP_MARKERS = frozenset({
    "<YOUR_", "your-api-key-here", "CHANGE_ME", "xxx",
    "EXAMPLE", "dummy", "test_key", "placeholder",
    "INSERT_", "REPLACE_", "TODO", "your_",
})

# Extra regex patterns for config files (non-Python) — line-based
_CONFIG_FILE_PATTERNS = {
    "openai_api_key":       (r"sk-[a-zA-Z0-9]{48}",                          "OpenAI API Key"),
    "openai_api_key_new":   (r"sk-proj-[a-zA-Z0-9_-]{48,}",                  "OpenAI API Key (new format)"),
    "anthropic_api_key":    (r"sk-ant-[a-zA-Z0-9_-]{95,}",                   "Anthropic API Key"),
    "google_api_key":       (r"AIza[0-9A-Za-z_-]{35}",                        "Google API Key"),
    "groq_api_key":         (r"gsk_[a-zA-Z0-9]{32,}",                        "Groq API Key"),
    "aws_access_key":       (r"AKIA[0-9A-Z]{16}",                            "AWS Access Key ID"),
    "github_token":         (r"ghp_[a-zA-Z0-9]{36}",                         "GitHub Personal Access Token"),
    "slack_token":          (r"xox[baprs]-[0-9a-zA-Z]{10,}",                 "Slack Token"),
    "stripe_key":           (r"sk_live_[0-9a-zA-Z]{24,}",                    "Stripe Secret Key"),
    "django_secret_key":    (r'SECRET_KEY\s*=\s*["\']([^"\']{10,})["\']',     "Django/JWT SECRET_KEY hardcoded"),
    "django_db_password":   (r"['\"]PASSWORD['\"]\s*:\s*['\"]([^'\"]+)['\"]", "Database password in Django DATABASES dict"),
    "generic_api_key":      (r'api_key\s*=\s*["\']([a-zA-Z0-9_-]{16,})["\']',"Hardcoded API key assignment"),
    "password_assignment":  (r'(?:password|passwd|pwd)\s*=\s*["\']([^"\']+)["\']', "Password in code"),
    "token_assignment":     (r'(?:token|auth_token|api_token)\s*=\s*["\']([^"\']+)["\']', "Token in code"),
    "secret_assignment":    (r'(?:secret|api_secret|client_secret)\s*=\s*["\']([^"\']+)["\']', "Secret in code"),
    "mongodb_connection":   (r'mongodb(?:\+srv)?://[^:]+:[^@]+@[^\s"\']+',   "MongoDB connection string with embedded credentials"),
    "postgresql_connection":(r'postgres(?:ql)?://[^:]+:[^@]+@[^\s"\']+',      "PostgreSQL connection string with embedded credentials"),
    "mysql_connection":     (r'mysql(?:\+pymysql)?://[^:]+:[^@]+@[^\s"\']+', "MySQL connection string with embedded credentials"),
    "redis_connection":     (r'rediss?://:[^@]+@[^\s"\']+',                   "Redis connection string with embedded credentials"),
    "amqp_connection":      (r'amqps?://[^:]+:[^@]+@[^\s"\']+',              "AMQP connection string with embedded credentials"),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_secrets(project_path: str) -> List[SecretFinding]:
    """Detect secrets and credentials in the project.

    - Python files: AST-based extraction of string assignments + pattern matching.
    - Config files: line-based regex scanning.
    - .env files: existence + gitignore checks.
    """
    project = Path(project_path)
    findings = []
    seen = set()  # (file, line, type) for dedup

    # --- Phase 1: Scan Python files via AST ---
    for py_file in iter_python_files(project):
        source = read_source(py_file)
        if not source:
            continue

        rel_path = str(py_file.relative_to(project))
        assignments = extract_assignments(source)

        for var_name, value, lineno in assignments:
            # Skip placeholder/example values
            if _is_placeholder(value):
                continue

            # Check against known API key formats
            for secret_type, (pattern, description) in _SECRET_VALUE_PATTERNS.items():
                if pattern.match(value):
                    key = (rel_path, lineno, secret_type)
                    if key not in seen:
                        seen.add(key)
                        findings.append(SecretFinding(
                            file=rel_path,
                            line=lineno,
                            type=secret_type,
                            description=description,
                            value_preview=_redact_secret(value),
                            severity="critical",
                        ))
                    break

            # Check for connection strings with credentials
            for cs_type, (pattern, description) in _CONNECTION_STRING_PATTERNS.items():
                if pattern.search(value):
                    key = (rel_path, lineno, cs_type)
                    if key not in seen:
                        seen.add(key)
                        findings.append(SecretFinding(
                            file=rel_path,
                            line=lineno,
                            type=cs_type,
                            description=description,
                            value_preview=_redact_secret(value),
                            severity="critical",
                        ))
                    break

            # High-entropy check for secret-named variables
            var_lower = var_name.lower()
            if any(ind in var_lower for ind in _SECRET_NAME_INDICATORS):
                if len(value) >= 20 and _calculate_entropy(value) > 4.0:
                    # Skip URLs and paths
                    if not any(m in value for m in ["http://", "https://", "/", "\\"]):
                        key = (rel_path, lineno, "high_entropy_string")
                        if key not in seen:
                            seen.add(key)
                            findings.append(SecretFinding(
                                file=rel_path,
                                line=lineno,
                                type="high_entropy_string",
                                description=f"High-entropy string in '{var_name}' (entropy: {_calculate_entropy(value):.2f})",
                                value_preview=_redact_secret(value),
                                severity="medium",
                            ))

    # --- Phase 2: Scan config files via regex ---
    config_globs = [".env*", "*.yaml", "*.yml", "*.json", "*.toml"]
    config_files = set()
    for pattern in config_globs:
        for f in project.rglob(pattern):
            if any(part in f.parts for part in SKIP_DIRS) or not f.is_file():
                continue
            # Skip Python files (already handled by AST)
            if f.suffix == ".py":
                continue
            config_files.add(f)

    for cfg_file in sorted(config_files):
        rel_path = str(cfg_file.relative_to(project))
        try:
            lines = cfg_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue

        for lineno, line in enumerate(lines, start=1):
            for secret_type, (pattern, description) in _CONFIG_FILE_PATTERNS.items():
                for match in re.finditer(pattern, line, re.IGNORECASE):
                    secret_value = match.group(0)
                    if _is_placeholder(line):
                        continue
                    key = (rel_path, lineno, secret_type)
                    if key not in seen:
                        seen.add(key)
                        findings.append(SecretFinding(
                            file=rel_path,
                            line=lineno,
                            type=secret_type,
                            description=description,
                            value_preview=_redact_secret(secret_value),
                            severity="critical",
                        ))

    # --- Phase 3: .env file presence + gitignore checks ---
    env_files = [f for f in project.rglob(".env*")
                 if not any(part in f.parts for part in SKIP_DIRS) and f.is_file()]

    secrets_toml_files = [f for f in project.rglob("secrets.toml")
                          if not any(part in f.parts for part in SKIP_DIRS) and f.is_file()]

    for env_file in env_files:
        findings.append(SecretFinding(
            file=str(env_file.relative_to(project)),
            line=0,
            type="env_file_present",
            description="Environment file detected — may contain secrets",
            value_preview=env_file.name,
            severity="medium",
        ))

    for secrets_file in secrets_toml_files:
        findings.append(SecretFinding(
            file=str(secrets_file.relative_to(project)),
            line=0,
            type="secrets_file_present",
            description="Streamlit secrets file detected — likely contains API keys",
            value_preview=secrets_file.name,
            severity="high",
        ))

    if env_files:
        gitignore_path = project / ".gitignore"
        if gitignore_path.exists():
            try:
                gitignore_content = gitignore_path.read_text(encoding="utf-8")
                for env_file in env_files:
                    env_name = env_file.name
                    if env_name not in gitignore_content and ".env" not in gitignore_content:
                        findings.append(SecretFinding(
                            file=str(env_file.relative_to(project)),
                            line=0,
                            type="unignored_env_file",
                            description="Environment file not in .gitignore",
                            value_preview=env_name,
                            severity="high",
                        ))
            except OSError:
                pass
        else:
            for env_file in env_files:
                findings.append(SecretFinding(
                    file=str(env_file.relative_to(project)),
                    line=0,
                    type="unignored_env_file",
                    description="Environment file exists but no .gitignore found",
                    value_preview=env_file.name,
                    severity="high",
                ))

    return findings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_placeholder(text: str) -> bool:
    """Check if text contains placeholder/example markers."""
    return any(marker in text for marker in _SKIP_MARKERS)


def _redact_secret(secret: str) -> str:
    """Redact a secret, showing only first and last few characters."""
    if len(secret) <= 8:
        return "***"
    return f"{secret[:4]}...{secret[-4:]}"


def _calculate_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not s:
        return 0
    counts = Counter(s)
    length = len(s)
    entropy = 0
    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy
