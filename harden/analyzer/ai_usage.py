"""AI API usage detection — three-layer approach.

Layer 1: Package manifest lookup.  Cross-reference declared dependencies
         (requirements.txt, pyproject.toml) against a curated dict of known
         AI/ML package names.  Handles ~80% of real apps with zero false
         positives.

Layer 2: AST-based import extraction.  Parse every .py file into an AST,
         walk Import/ImportFrom nodes, and match root packages against the
         same dict.  Catches imports not declared in manifest files (common
         in vibe-coded apps that never write a requirements.txt).  Replaces
         all regex-based import detection.

Layer 3: LLM classification (optional).  For imports that don't match any
         known package, and for configuration-method detection, send a small
         summary to an LLM.  Handles novel SDKs, direct HTTP calls to AI
         APIs, and exotic config patterns (toml.load, python-decouple, etc.).
         Gracefully degrades if no API key is available.
"""

import ast
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from harden.analyzer.models import AIUsageInfo
from harden.analyzer.ast_utils import (
    extract_imports,
    root_package,
    normalise_package_name,
    collect_declared_deps,
    detect_config_method,
    iter_python_files,
    read_source,
    STDLIB_ROOTS,
)
from harden.analyzer.llm import llm_classify

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layer 1 & 2: Known AI/ML packages
# ---------------------------------------------------------------------------
# Key = PyPI package name (normalised to lowercase, hyphens).
# Also includes common import names that differ from the PyPI name.
# This dict is trivial to maintain: package names rarely change.

AI_PACKAGES: Dict[str, Tuple[str, str, List[str]]] = {
    # (provider, category, egress_domains)
    # --- LLM API providers ---
    "openai":                ("OpenAI",          "llm_api",     ["api.openai.com"]),
    "anthropic":             ("Anthropic",       "llm_api",     ["api.anthropic.com"]),
    "google-generativeai":   ("Google AI",       "llm_api",     ["generativelanguage.googleapis.com"]),
    "google.generativeai":   ("Google AI",       "llm_api",     ["generativelanguage.googleapis.com"]),
    "cohere":                ("Cohere",          "llm_api",     ["api.cohere.ai"]),
    "together":              ("Together AI",     "llm_api",     ["api.together.xyz"]),
    "groq":                  ("Groq",            "llm_api",     ["api.groq.com"]),
    "fireworks-ai":          ("Fireworks",       "llm_api",     ["api.fireworks.ai"]),
    "fireworks":             ("Fireworks",       "llm_api",     ["api.fireworks.ai"]),
    "mistralai":             ("Mistral",         "llm_api",     ["api.mistral.ai"]),
    "replicate":             ("Replicate",       "llm_api",     ["api.replicate.com"]),
    "deepseek":              ("DeepSeek",        "llm_api",     ["api.deepseek.com"]),
    "litellm":               ("LiteLLM",         "llm_proxy",   []),
    "ollama":                ("Ollama",          "local_model", []),

    # --- Frameworks / orchestrators ---
    "langchain":             ("LangChain",       "framework",   []),
    "langchain-openai":      ("LangChain",       "framework",   ["api.openai.com"]),
    "langchain_openai":      ("LangChain",       "framework",   ["api.openai.com"]),
    "langchain-anthropic":   ("LangChain",       "framework",   ["api.anthropic.com"]),
    "langchain_anthropic":   ("LangChain",       "framework",   ["api.anthropic.com"]),
    "langchain-google-genai":("LangChain",       "framework",   ["generativelanguage.googleapis.com"]),
    "langchain_google_genai":("LangChain",       "framework",   ["generativelanguage.googleapis.com"]),
    "langchain-community":   ("LangChain",       "framework",   []),
    "langchain_community":   ("LangChain",       "framework",   []),
    "langchain-core":        ("LangChain",       "framework",   []),
    "langchain_core":        ("LangChain",       "framework",   []),
    "llama-index":           ("LlamaIndex",      "framework",   []),
    "llama_index":           ("LlamaIndex",      "framework",   []),
    "llamaindex":            ("LlamaIndex",      "framework",   []),
    "haystack-ai":           ("Haystack",        "framework",   []),
    "crewai":                ("CrewAI",          "framework",   []),
    "autogen":               ("AutoGen",         "framework",   []),

    # --- Local model / ML libraries ---
    "transformers":          ("HuggingFace",     "local_model", ["huggingface.co"]),
    "diffusers":             ("HuggingFace",     "local_model", ["huggingface.co"]),
    "accelerate":            ("HuggingFace",     "local_model", ["huggingface.co"]),
    "huggingface-hub":       ("HuggingFace",     "local_model", ["huggingface.co"]),
    "huggingface_hub":       ("HuggingFace",     "local_model", ["huggingface.co"]),
    "torch":                 ("PyTorch",         "local_model", []),
    "torchvision":           ("PyTorch",         "local_model", []),
    "torchaudio":            ("PyTorch",         "local_model", []),
    "tensorflow":            ("TensorFlow",      "local_model", []),
    "keras":                 ("Keras",           "local_model", []),
    "jax":                   ("JAX",             "local_model", []),
    "flax":                  ("JAX",             "local_model", []),
    "vllm":                  ("vLLM",            "local_model", []),
    "ctransformers":         ("CTransformers",   "local_model", []),
    "mlx":                   ("MLX",             "local_model", []),
    "mlx-lm":               ("MLX",             "local_model", []),
    "onnxruntime":           ("ONNX",            "local_model", []),
    "onnx":                  ("ONNX",            "local_model", []),
    "sentence-transformers": ("HuggingFace",     "embedding",   ["huggingface.co"]),
    "sentence_transformers": ("HuggingFace",     "embedding",   ["huggingface.co"]),

    # --- Vector DBs (AI-adjacent) ---
    "chromadb":              ("ChromaDB",        "vector_db",   []),
    "pinecone-client":       ("Pinecone",        "vector_db",   ["*.pinecone.io"]),
    "pinecone":              ("Pinecone",        "vector_db",   ["*.pinecone.io"]),
    "weaviate-client":       ("Weaviate",        "vector_db",   []),
    "qdrant-client":         ("Qdrant",          "vector_db",   []),
    "faiss-cpu":             ("FAISS",           "vector_db",   []),
    "faiss-gpu":             ("FAISS",           "vector_db",   []),

    # --- Speech / Vision / specialized ---
    "whisper":               ("OpenAI Whisper",  "local_model", []),
    "openai-whisper":        ("OpenAI Whisper",  "local_model", []),
    "elevenlabs":            ("ElevenLabs",      "speech_api",  ["api.elevenlabs.io"]),
    "stability-sdk":         ("Stability AI",    "image_api",   ["api.stability.ai"]),
    "tiktoken":              ("OpenAI",          "tokenizer",   []),
}


def _build_lookup() -> Dict[str, Tuple[str, str, List[str]]]:
    """Build a lookup dict keyed by both hyphen and underscore forms."""
    lookup = {}
    for key, val in AI_PACKAGES.items():
        lookup[key.lower()] = val
        lookup[normalise_package_name(key)] = val
    return lookup


_LOOKUP = _build_lookup()


# ---------------------------------------------------------------------------
# Import matching
# ---------------------------------------------------------------------------

def _match_import(import_path: str) -> Optional[Tuple[str, str, str, List[str]]]:
    """Try to match an import path against known AI packages.

    Returns (sdk_key, provider, category, domains) or None.
    """
    # Try the full import path first, then progressively shorter prefixes
    parts = import_path.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        for norm in (candidate.lower(), normalise_package_name(candidate)):
            if norm in _LOOKUP:
                provider, category, domains = _LOOKUP[norm]
                return norm, provider, category, domains

    return None


# ---------------------------------------------------------------------------
# AI-specific config method detection
# ---------------------------------------------------------------------------

_KEY_PATTERNS = [
    re.compile(r'^sk-[a-zA-Z0-9]{20,}$'),          # OpenAI
    re.compile(r'^sk-proj-[a-zA-Z0-9_-]{20,}$'),    # OpenAI project
    re.compile(r'^sk-ant-[a-zA-Z0-9_-]{20,}$'),     # Anthropic
    re.compile(r'^AIza[0-9A-Za-z_-]{30,}$'),         # Google AI
    re.compile(r'^gsk_[a-zA-Z0-9]{20,}$'),           # Groq
    re.compile(r'^hf_[a-zA-Z0-9]{20,}$'),            # HuggingFace
    re.compile(r'^r8_[a-zA-Z0-9]{20,}$'),            # Replicate
    re.compile(r'^sk-or-v1-[a-zA-Z0-9]{20,}$'),      # OpenRouter
]


def _looks_like_api_key(val: str) -> bool:
    """Check if a string looks like a hardcoded API key."""
    return any(p.match(val) for p in _KEY_PATTERNS)


def _detect_ai_config_method(source: str) -> str:
    """Detect config method, including hardcoded AI API key detection.

    Extends the shared detect_config_method with AI-specific hardcoded
    key pattern matching (sk-..., AIza..., etc.).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return detect_config_method(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _looks_like_api_key(node.value):
                return "hardcoded"

    return detect_config_method(source)


# ---------------------------------------------------------------------------
# Layer 3: LLM classification for unknowns
# ---------------------------------------------------------------------------

_LLM_PROMPT = """\
You are analyzing a Python application for AI/ML service usage.

Below are two inputs:
1. UNKNOWN_IMPORTS: Python imports that were not recognized as known AI packages.
2. CODE_SNIPPETS: Relevant code excerpts that might indicate AI API usage.

For each AI/ML-related item you find, return a JSON array of objects with:
- "sdk": the package or service name
- "provider": the provider (e.g., "OpenAI", "DeepSeek", "HuggingFace")
- "category": one of ["llm_api", "local_model", "framework", "vector_db", "embedding", "speech_api", "image_api", "llm_proxy", "tokenizer"]
- "config_method": how the API key is configured — one of ["hardcoded", "env_var", "secrets_file", "secrets_manager", "unknown"]
- "domains": list of external domains this service calls (empty list if local-only)

If nothing is AI/ML-related, return an empty JSON array: []

UNKNOWN_IMPORTS:
{imports}

CODE_SNIPPETS:
{snippets}

Return ONLY the JSON array, no other text."""


def _llm_classify_ai(unknown_imports: List[str], code_snippets: List[str]) -> List[dict]:
    """Use an LLM to classify unrecognized imports/code as AI or not.

    Formats an AI-specific prompt and delegates to the shared llm_classify.
    """
    if not unknown_imports and not code_snippets:
        return []

    prompt = _LLM_PROMPT.format(
        imports="\n".join(unknown_imports[:50]),
        snippets="\n".join(code_snippets[:30]),
    )

    items = llm_classify(prompt)

    # Validate each item has required fields
    valid = []
    for item in items:
        if isinstance(item, dict) and "sdk" in item and "provider" in item:
            valid.append({
                "sdk": str(item["sdk"]),
                "provider": str(item["provider"]),
                "category": str(item.get("category", "unknown")),
                "config_method": str(item.get("config_method", "unknown")),
                "domains": list(item.get("domains", [])),
            })
    return valid


# ---------------------------------------------------------------------------
# Helpers for collecting code context for the LLM
# ---------------------------------------------------------------------------

_INTERESTING_PATTERNS = re.compile(
    r'(api_key|API_KEY|api\.key|token|\.create\(|\.generate\(|\.complete\('
    r'|\.chat\(|model\s*=|engine\s*=|\.infer\(|\.predict\('
    r'|from_pretrained\(|pipeline\(|ChatCompletion'
    r'|https?://api\.)',
    re.IGNORECASE,
)


def _extract_interesting_lines(source: str, max_lines: int = 20) -> List[str]:
    """Pull lines that look like they might be AI-related API calls."""
    lines = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and _INTERESTING_PATTERNS.search(stripped):
            lines.append(stripped[:200])  # cap line length
            if len(lines) >= max_lines:
                break
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_ai_usage(project_path: str) -> List[AIUsageInfo]:
    """Detect AI/ML usage in a Python project.

    Three-layer detection:
    1. Cross-reference declared dependencies against AI_PACKAGES.
    2. AST-parse all .py files, extract imports, match against AI_PACKAGES.
    3. For unrecognized imports + interesting code, ask an LLM (optional).

    Returns List[AIUsageInfo] — same interface as before.
    """
    project = Path(project_path)

    # Collect declared dependency names (from requirements.txt, pyproject.toml)
    declared_deps = collect_declared_deps(project)

    # -----------------------------------------------------------------------
    # Layer 1: Package manifest lookup
    # -----------------------------------------------------------------------
    found: Dict[str, dict] = {}  # key → {provider, category, domains, files, config_method}

    for dep_name in declared_deps:
        for norm in (dep_name.lower(), normalise_package_name(dep_name)):
            if norm in _LOOKUP:
                provider, category, domains = _LOOKUP[norm]
                _merge_found(found, norm, provider, category, domains, source_file="(dependency manifest)")
                break

    # -----------------------------------------------------------------------
    # Layer 2: AST import extraction
    # -----------------------------------------------------------------------
    unknown_imports: Set[str] = set()
    all_interesting_lines: List[str] = []

    for py_file in iter_python_files(project):
        source = read_source(py_file)
        if not source:
            continue

        imports = extract_imports(source)
        rel_path = str(py_file.relative_to(project))

        file_has_ai = False
        for imp in imports:
            match = _match_import(imp)
            if match:
                sdk_key, provider, category, domains = match
                _merge_found(found, sdk_key, provider, category, domains, source_file=rel_path)
                file_has_ai = True
            else:
                root = root_package(imp)
                if root not in STDLIB_ROOTS and root not in _COMMON_NON_AI:
                    unknown_imports.add(imp)

        # Detect config method per file (only for files with AI imports)
        if file_has_ai:
            cm = _detect_ai_config_method(source)
            if cm != "unknown":
                for sdk_key, info in found.items():
                    if rel_path in info.get("files", []):
                        existing = info.get("config_method", "unknown")
                        info["config_method"] = _better_config(existing, cm)

        # Collect interesting code for LLM
        interesting = _extract_interesting_lines(source)
        if interesting:
            all_interesting_lines.extend(interesting)

    # If we found AI packages but all have unknown config, scan ALL files
    # for config patterns (key config is often in app.py / main.py, not in
    # the file that imports the AI SDK).
    all_unknown = all(info.get("config_method") == "unknown" for info in found.values())
    if found and all_unknown:
        project_config_method = "unknown"
        for py_file in iter_python_files(project):
            source = read_source(py_file)
            if not source:
                continue
            cm = _detect_ai_config_method(source)
            if cm != "unknown":
                project_config_method = _better_config(project_config_method, cm)

        if project_config_method != "unknown":
            for info in found.values():
                if info.get("config_method") == "unknown":
                    info["config_method"] = project_config_method

    # -----------------------------------------------------------------------
    # Layer 3: LLM classification for unknowns
    # -----------------------------------------------------------------------
    if unknown_imports or all_interesting_lines:
        llm_results = _llm_classify_ai(sorted(unknown_imports)[:50], all_interesting_lines[:30])
        for item in llm_results:
            sdk_key = normalise_package_name(item["sdk"])
            if sdk_key not in found:
                found[sdk_key] = {
                    "provider": item["provider"],
                    "category": item.get("category", "unknown"),
                    "domains": item.get("domains", []),
                    "files": ["(detected by LLM)"],
                    "config_method": item.get("config_method", "unknown"),
                }

    # -----------------------------------------------------------------------
    # Build return value
    # -----------------------------------------------------------------------
    results = []
    for sdk_key, info in found.items():
        results.append(AIUsageInfo(
            provider=info["provider"],
            sdk=sdk_key,
            config_method=info.get("config_method", "unknown"),
            files=info.get("files", []),
        ))

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _merge_found(found: dict, sdk_key: str, provider: str, category: str,
                 domains: list, source_file: str = ""):
    """Merge a detection into the found dict, deduplicating files."""
    if sdk_key not in found:
        found[sdk_key] = {
            "provider": provider,
            "category": category,
            "domains": list(domains),
            "files": [],
            "config_method": "unknown",
        }
    if source_file and source_file not in found[sdk_key]["files"]:
        found[sdk_key]["files"].append(source_file)


def _better_config(existing: str, new: str) -> str:
    """Pick the more specific/important config method."""
    priority = {"hardcoded": 0, "secrets_manager": 1, "secrets_file": 2, "env_var": 3, "unknown": 4}
    if priority.get(new, 5) < priority.get(existing, 5):
        return new
    return existing


# Common non-AI packages to skip for LLM classification
_COMMON_NON_AI = {
    "flask", "fastapi", "django", "starlette", "uvicorn", "gunicorn",
    "requests", "httpx", "aiohttp", "urllib3", "certifi",
    "pydantic", "marshmallow", "attrs",
    "sqlalchemy", "psycopg2", "pymongo", "redis", "celery",
    "boto3", "botocore", "google", "azure",
    "click", "typer", "rich", "tqdm", "colorama",
    "pytest", "nose", "coverage", "mock",
    "numpy", "pandas", "scipy", "matplotlib", "seaborn", "plotly",
    "pillow", "PIL",
    "yaml", "pyyaml", "toml", "tomli", "dotenv", "python_dotenv",
    "jinja2", "mako", "markupsafe",
    "streamlit", "gradio",
    "werkzeug", "itsdangerous",
    "cryptography", "bcrypt", "jwt", "oauthlib",
    "beautifulsoup4", "bs4", "lxml", "scrapy",
    "paramiko", "fabric",
    "docker", "kubernetes",
    "black", "ruff", "isort", "flake8", "mypy",
    "decouple",
    "fitz", "pymupdf", "img2pdf", "python_docx", "docx", "openpyxl",
    "markdown", "pypandoc", "frontmatter",
    "fire",
}
