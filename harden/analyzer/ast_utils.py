"""Shared AST and project-scanning utilities for all analyzers.

Provides a single, reliable set of primitives so that ai_usage,
secrets, external_services, and detector can all work from AST
instead of regex.
"""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Directories to skip when scanning projects
SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".harden", ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
})


def iter_python_files(project: Path):
    """Yield .py file paths, skipping virtual envs and build dirs."""
    for py_file in sorted(project.rglob("*.py")):
        if any(part in py_file.parts for part in SKIP_DIRS):
            continue
        yield py_file


def read_source(path: Path) -> Optional[str]:
    """Read a Python file's source, returning None on error."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------

def extract_imports(source: str) -> List[str]:
    """Extract all import module paths from Python source via AST.

    Returns dotted import paths, e.g. ["openai", "langchain_openai", "os.path"].
    Never raises — returns [] on syntax error.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def root_package(import_path: str) -> str:
    """Get the root package from a dotted import path."""
    return import_path.split(".")[0]


# ---------------------------------------------------------------------------
# Dependency manifest parsing
# ---------------------------------------------------------------------------

def collect_declared_deps(project: Path) -> Set[str]:
    """Collect package names from requirements.txt and pyproject.toml files."""
    deps: Set[str] = set()

    for req_file in project.rglob("requirements.txt"):
        if any(part in req_file.parts for part in SKIP_DIRS):
            continue
        try:
            for line in req_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                name = re.split(r'[>=<~!\[\]@;]', line)[0].strip()
                if name:
                    deps.add(name)
        except OSError:
            continue

    for pyproject in project.rglob("pyproject.toml"):
        if any(part in pyproject.parts for part in SKIP_DIRS):
            continue
        try:
            content = pyproject.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'"([a-zA-Z0-9][a-zA-Z0-9._-]*)', content):
                deps.add(m.group(1))
        except OSError:
            continue

    return deps


# ---------------------------------------------------------------------------
# String assignment extraction (for secrets detection)
# ---------------------------------------------------------------------------

def extract_assignments(source: str) -> List[Tuple[str, str, int]]:
    """Extract (variable_name, string_value, line_number) for all simple
    string assignments in the source.

    Handles:
    - x = "value"               → ("x", "value", lineno)
    - MY_KEY = 'value'          → ("MY_KEY", "value", lineno)
    - config["KEY"] = "value"   → ("KEY", "value", lineno)
    - {"KEY": "value"}          → ("KEY", "value", lineno)
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    results = []

    for node in ast.walk(tree):
        # Simple assignment:  X = "..."
        if isinstance(node, ast.Assign):
            for target in node.targets:
                name = _extract_name(target)
                if name and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    results.append((name, node.value.value, node.lineno))

        # Dict literal:  {"KEY": "value"}
        if isinstance(node, ast.Dict):
            for key, val in zip(node.keys, node.values):
                if (key and isinstance(key, ast.Constant) and isinstance(key.value, str)
                        and isinstance(val, ast.Constant) and isinstance(val.value, str)):
                    results.append((key.value, val.value, key.lineno))

        # Keyword argument:  func(api_key="...")
        if isinstance(node, ast.keyword):
            if (node.arg and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                results.append((node.arg, node.value.value, node.value.lineno))

    return results


def _extract_name(node) -> Optional[str]:
    """Extract the variable name from an AST target node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            return node.slice.value
    return None


# ---------------------------------------------------------------------------
# Function call keyword extraction (for port detection, etc.)
# ---------------------------------------------------------------------------

def extract_call_kwargs(source: str, func_names: List[str]) -> Dict[str, List[Tuple[str, object, int]]]:
    """Find calls to specific functions and extract their keyword arguments.

    Args:
        source: Python source code
        func_names: Function names to look for (e.g. ["uvicorn.run", "app.run"])

    Returns:
        {func_name: [(kwarg_name, kwarg_value, lineno), ...]}

    Only extracts kwargs with constant values (str, int, float, bool).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    results: Dict[str, list] = {name: [] for name in func_names}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        call_name = _resolve_call_name(node.func)
        if call_name not in results:
            continue

        for kw in node.keywords:
            if kw.arg and isinstance(kw.value, ast.Constant):
                results[call_name].append((kw.arg, kw.value.value, node.lineno))

    return results


def _resolve_call_name(node) -> str:
    """Resolve a Call func node to a dotted string like 'uvicorn.run'."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _resolve_call_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr
    return ""


# ---------------------------------------------------------------------------
# URL / domain extraction from source
# ---------------------------------------------------------------------------

def extract_urls(source: str) -> List[Tuple[str, int]]:
    """Extract (url, lineno) for HTTP(S) URLs found in string literals.

    Skips localhost and private IPs.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    urls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for m in re.finditer(r'https?://[^\s"\'<>]+', node.value):
                url = m.group(0).rstrip(".,;:)")
                domain = _extract_domain(url)
                if domain and domain not in ("localhost", "127.0.0.1", "0.0.0.0", "example.com"):
                    if not domain.startswith("10.") and not domain.startswith("192.168."):
                        urls.append((url, node.lineno))

        # Also check JoinedStr (f-strings)
        if isinstance(node, ast.JoinedStr):
            for val in node.values:
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    for m in re.finditer(r'https?://[^\s"\'<>{]+', val.value):
                        url = m.group(0).rstrip(".,;:)")
                        domain = _extract_domain(url)
                        if domain and domain not in ("localhost", "127.0.0.1", "0.0.0.0", "example.com"):
                            if not domain.startswith("10.") and not domain.startswith("192.168."):
                                urls.append((url, node.lineno))

    return urls


_VALID_DOMAIN_RE = re.compile(
    r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?'
    r'(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)+$'
)


def _extract_domain(url: str) -> Optional[str]:
    """Extract domain from a URL string. Returns None for non-FQDN values."""
    m = re.search(r'https?://([^/:?\s]+)', url)
    if not m:
        return None
    domain = m.group(1)
    if domain == "localhost" or _VALID_DOMAIN_RE.match(domain):
        return domain
    return None


def extract_domains_from_urls(source: str) -> Set[str]:
    """Extract unique external domains from URLs in source."""
    domains = set()
    for url, _ in extract_urls(source):
        d = _extract_domain(url)
        if d:
            domains.add(d)
    return domains


# ---------------------------------------------------------------------------
# Config method detection (shared by ai_usage and secrets)
# ---------------------------------------------------------------------------

def detect_config_method(source: str) -> str:
    """Detect how secrets/API keys are configured in a source file.

    Returns one of: "hardcoded", "secrets_manager", "secrets_file", "env_var", "unknown".
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "unknown"

    has_env_var = False
    has_secrets_file = False
    has_secrets_manager = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            if _is_attr_chain(node.value, ["os", "environ"]):
                has_env_var = True
            if _is_attr_chain(node.value, ["st", "secrets"]):
                has_secrets_file = True

        if isinstance(node, ast.Call):
            func = node.func
            if _is_attr_chain(func, ["os", "environ", "get"]):
                has_env_var = True
            elif _is_attr_chain(func, ["os", "getenv"]):
                has_env_var = True
            elif _is_name_or_attr(func, "dotenv_values"):
                has_env_var = True
            elif _is_name_or_attr(func, "load_dotenv"):
                has_env_var = True
            elif _is_name_or_attr(func, "env_config"):
                has_env_var = True
            elif _is_attr_chain(func, ["toml", "load"]):
                has_secrets_file = True
            elif _is_name_or_attr(func, "get_secret") or _is_name_or_attr(func, "get_secret_value"):
                has_secrets_manager = True
            elif _is_name_or_attr(func, "config") and _has_string_arg_matching(node, r"(?i)(key|token|secret|api)"):
                has_env_var = True  # python-decouple config() reads from .env

    if re.search(r'secretsmanager|vault\.|get_secret', source, re.IGNORECASE):
        has_secrets_manager = True

    if has_secrets_manager:
        return "secrets_manager"
    if has_secrets_file:
        return "secrets_file"
    if has_env_var:
        return "env_var"
    return "unknown"


def _is_attr_chain(node, chain: list) -> bool:
    if not chain:
        return True
    if len(chain) == 1:
        return isinstance(node, ast.Name) and node.id == chain[0]
    if isinstance(node, ast.Attribute):
        return node.attr == chain[-1] and _is_attr_chain(node.value, chain[:-1])
    return False


def _is_name_or_attr(node, name: str) -> bool:
    if isinstance(node, ast.Name) and node.id == name:
        return True
    if isinstance(node, ast.Attribute) and node.attr == name:
        return True
    return False


def _has_string_arg_matching(call_node: ast.Call, pattern: str) -> bool:
    for arg in call_node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if re.search(pattern, arg.value):
                return True
    for kw in call_node.keywords:
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            if re.search(pattern, kw.value.value):
                return True
    return False


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def normalise_package_name(name: str) -> str:
    """Normalise: lowercase, hyphens and dots to underscores."""
    return name.lower().replace("-", "_").replace(".", "_")


# Common stdlib root modules (baseline for Python 3.8-3.9)
_STDLIB_BASELINE = frozenset({
    "__future__", "os", "sys", "re", "json", "math", "time", "datetime",
    "pathlib", "collections", "functools", "itertools", "typing", "abc",
    "io", "subprocess", "threading", "multiprocessing", "logging",
    "warnings", "unittest", "dataclasses", "enum", "copy", "hashlib",
    "hmac", "base64", "secrets", "string", "textwrap", "struct", "csv",
    "html", "xml", "http", "urllib", "email", "socket", "ssl",
    "asyncio", "concurrent", "queue", "signal", "tempfile", "shutil",
    "glob", "fnmatch", "stat", "zipfile", "gzip", "tarfile",
    "configparser", "argparse", "getpass", "pprint", "traceback",
    "inspect", "importlib", "pkgutil", "platform", "ctypes", "uuid",
    "decimal", "fractions", "random", "statistics", "operator",
    "contextlib", "atexit", "weakref", "array", "bisect", "heapq",
    "pdb", "dis", "ast", "token", "tokenize", "pickle", "shelve",
    "sqlite3", "dbm", "mmap", "select", "selectors", "builtins",
    "_thread", "posixpath", "ntpath", "genericpath", "encodings",
    "codecs", "locale", "gettext", "calendar", "sched", "doctest",
    "site", "sysconfig", "venv", "distutils", "setuptools", "pip",
    "types", "numbers", "cmath", "difflib", "reprlib", "timeit",
    "profile", "cProfile", "pstats", "webbrowser", "mimetypes",
    "lzma", "zipimport", "runpy", "unicodedata", "wave",
})

# Use sys.stdlib_module_names (Python 3.10+) for a complete, authoritative list
STDLIB_ROOTS = (
    _STDLIB_BASELINE | frozenset(sys.stdlib_module_names)
    if hasattr(sys, "stdlib_module_names")
    else _STDLIB_BASELINE
)
