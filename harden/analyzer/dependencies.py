"""Dependency analysis and CVE detection (OSV-backed)."""

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from harden.analyzer.models import DependencyInfo
from harden.analyzer.ast_utils import (
    extract_imports,
    iter_python_files,
    normalise_package_name,
    root_package,
    read_source,
    STDLIB_ROOTS,
)

_OSV_API_URL = "https://api.osv.dev/v1/querybatch"
_CACHE_TTL_SECONDS = int(os.getenv("HARDEN_OSV_CACHE_TTL_SECONDS", "86400"))


def _cache_key(dep: DependencyInfo) -> str:
    if dep.version:
        return f"{dep.name}@{dep.version}"
    return f"{dep.name}@*"


def _osv_cache_path(project_path: str) -> Path:
    state_dir = Path(project_path) / ".harden" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "osv_cache.json"


def _load_osv_cache(project_path: str) -> Dict[str, Any]:
    cache_path = _osv_cache_path(project_path)
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_osv_cache(project_path: str, cache: Dict[str, Any]) -> None:
    cache_path = _osv_cache_path(project_path)
    cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _is_cache_fresh(entry: Dict[str, Any]) -> bool:
    if _CACHE_TTL_SECONDS <= 0:
        return False
    ts = entry.get("fetched_at")
    if not ts:
        return False
    try:
        fetched = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = datetime.now(timezone.utc) - fetched
    return age.total_seconds() < _CACHE_TTL_SECONDS


def _severity_from_osv(vuln: Dict[str, Any]) -> str:
    # Try explicit database-specific severity first
    db_sev = (vuln.get("database_specific") or {}).get("severity")
    if isinstance(db_sev, str):
        sev = db_sev.strip().lower()
        if sev in {"critical", "high", "medium", "low"}:
            return sev

    # Try CVSS score if available
    for sev in vuln.get("severity", []) or []:
        if sev.get("type") in {"CVSS_V3", "CVSS_V2"}:
            try:
                score = float(sev.get("score", 0))
            except (TypeError, ValueError):
                score = 0
            if score >= 9.0:
                return "critical"
            if score >= 7.0:
                return "high"
            if score >= 4.0:
                return "medium"
            return "low"

    return "medium"


def _query_osv_batch(packages: List[DependencyInfo]) -> Dict[str, List[Dict[str, Any]]]:
    """Query OSV for a batch of packages. Returns mapping cache_key -> vulns."""
    if not packages:
        return {}

    queries = []
    for dep in packages:
        q = {"package": {"name": dep.name, "ecosystem": "PyPI"}}
        if dep.version:
            q["version"] = dep.version
        queries.append(q)

    payload = json.dumps({"queries": queries}).encode("utf-8")
    req = urllib.request.Request(
        _OSV_API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
    except Exception:
        return {}

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {}

    results = data.get("results", [])
    output: Dict[str, List[Dict[str, Any]]] = {}
    for dep, res in zip(packages, results):
        vulns = []
        for v in res.get("vulns", []) or []:
            vulns.append({
                "id": v.get("id", ""),
                "summary": v.get("summary", ""),
                "severity": _severity_from_osv(v),
            })
        output[_cache_key(dep)] = vulns
    return output


def _apply_osv_results(dependencies: List[DependencyInfo], osv_data: Dict[str, List[Dict[str, Any]]]) -> None:
    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    for dep in dependencies:
        vulns = osv_data.get(_cache_key(dep), [])
        if not vulns:
            continue
        dep.has_known_cves = True
        dep.cve_details = []
        max_sev = "low"
        for v in vulns:
            vid = v.get("id", "").strip()
            summary = v.get("summary", "").strip()
            if vid and summary:
                dep.cve_details.append(f"{vid}: {summary}")
            elif vid:
                dep.cve_details.append(vid)
            else:
                dep.cve_details.append(summary or "Unknown vulnerability")
            sev = str(v.get("severity", "medium")).lower()
            if severity_rank.get(sev, 0) > severity_rank.get(max_sev, 0):
                max_sev = sev
        dep.severity = max_sev


def analyze_dependencies(project_path: str) -> List[DependencyInfo]:
    """
    Analyze project dependencies for security issues.

    Args:
        project_path: Path to the project directory

    Returns:
        List of DependencyInfo objects
    """
    project = Path(project_path)
    dependencies = []

    skip_dirs = [".git", "node_modules", "__pycache__", ".venv", "venv"]

    # Parse all requirements.txt files (root + subdirectories)
    for req_file in sorted(project.rglob("requirements.txt")):
        if any(part in str(req_file) for part in skip_dirs):
            continue
        dependencies.extend(_parse_requirements_txt(req_file))

    # Parse all pyproject.toml files (root + subdirectories)
    for pyproject in sorted(project.rglob("pyproject.toml")):
        if any(part in str(pyproject) for part in skip_dirs):
            continue
        dependencies.extend(_parse_pyproject_toml(pyproject))

    if not dependencies:
        dependencies.extend(_infer_dependencies_from_imports(project_path))

    # Remove duplicates (keep the one with most info)
    unique_deps = {}
    for dep in dependencies:
        if dep.name not in unique_deps or (dep.version and not unique_deps[dep.name].version):
            unique_deps[dep.name] = dep

    deps = list(unique_deps.values())
    _enrich_with_osv(deps, project_path)
    return deps


def _parse_requirements_txt(req_file: Path) -> List[DependencyInfo]:
    """Parse requirements.txt file."""
    dependencies = []

    try:
        with open(req_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                # Skip editable installs and URLs
                if line.startswith("-e") or line.startswith("http://") or line.startswith("https://"):
                    continue

                # Parse package name and version
                dep_info = _parse_dependency_line(line)
                if dep_info:
                    dependencies.append(dep_info)

    except Exception:
        pass

    return dependencies


def _parse_pyproject_toml(pyproject: Path) -> List[DependencyInfo]:
    """Parse pyproject.toml file."""
    dependencies = []

    try:
        with open(pyproject, "r", encoding="utf-8") as f:
            content = f.read()

            # Look for dependencies section
            # Match patterns like: "package>=1.0.0", "package==1.0.0", etc.
            dep_pattern = r'"([a-zA-Z0-9_-]+)([>=<~!]+[0-9.]+[^"]*)"'
            matches = re.finditer(dep_pattern, content)

            for match in matches:
                package_name = match.group(1)
                version_spec = match.group(2)

                # Parse version
                version = None
                pinned = False

                if "==" in version_spec:
                    version = version_spec.replace("==", "").strip()
                    pinned = True
                elif ">=" in version_spec:
                    version = version_spec.replace(">=", "").strip()
                    pinned = False
                else:
                    version = version_spec.strip()
                    pinned = "==" in version_spec

                dep_info = DependencyInfo(
                    name=package_name.lower(),
                    version=version,
                    pinned=pinned,
                )

                dependencies.append(dep_info)

    except Exception:
        pass

    return dependencies


def _parse_dependency_line(line: str) -> DependencyInfo:
    """Parse a single dependency line."""
    # Handle extras like package[extra]
    line = re.sub(r'\[.*?\]', '', line)

    # Common version specifiers
    version_pattern = r'([a-zA-Z0-9_-]+)(==|>=|<=|>|<|~=|!=)([0-9.]+[a-zA-Z0-9.]*)'
    match = re.match(version_pattern, line)

    if match:
        name = match.group(1).strip().lower()
        operator = match.group(2)
        version = match.group(3).strip()

        dep_info = DependencyInfo(
            name=name,
            version=version,
            pinned=(operator == "=="),
        )
    else:
        # No version specified
        name = line.strip().lower()
        dep_info = DependencyInfo(
            name=name,
            version=None,
            pinned=False,
        )

    return dep_info


def _infer_dependencies_from_imports(project_path: str) -> List[DependencyInfo]:
    """Infer dependencies from import statements when no manifest exists."""
    project = Path(project_path)
    local_modules = {p.stem.lower() for p in project.rglob("*.py")}
    inferred = set()

    for py_file in iter_python_files(project):
        source = read_source(py_file)
        if not source:
            continue
        for imp in extract_imports(source):
            root = root_package(imp)
            norm = normalise_package_name(root)
            if root in STDLIB_ROOTS or norm in STDLIB_ROOTS:
                continue
            if root.lower() in local_modules or norm in local_modules:
                continue
            inferred.add(norm)

    return [DependencyInfo(name=name, version=None, pinned=False) for name in sorted(inferred)]


def _enrich_with_osv(dependencies: List[DependencyInfo], project_path: str) -> None:
    cache = _load_osv_cache(project_path)
    osv_results: Dict[str, List[Dict[str, Any]]] = {}
    to_query: List[DependencyInfo] = []

    for dep in dependencies:
        key = _cache_key(dep)
        entry = cache.get(key)
        if entry and _is_cache_fresh(entry):
            osv_results[key] = entry.get("vulns", [])
        else:
            to_query.append(dep)

    if to_query:
        fetched = _query_osv_batch(to_query)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for key, vulns in fetched.items():
            cache[key] = {"fetched_at": now, "vulns": vulns}
            osv_results[key] = vulns
        _save_osv_cache(project_path, cache)

    _apply_osv_results(dependencies, osv_results)
