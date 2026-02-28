"""Dependency locking for reproducible builds.

Supports multiple strategies:
- uv: uses `uv pip compile` (fastest, recommended)
- pip-compile: uses `pip-compile` from pip-tools
- pip-freeze: creates a venv and runs `pip freeze`
- auto: tries uv -> pip-compile -> pip-freeze in order
"""

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from harden.analyzer.ast_utils import (
    extract_imports,
    iter_python_files,
    normalise_package_name,
    read_source,
    root_package,
    STDLIB_ROOTS,
)


@dataclass
class LockResult:
    """Result of a dependency locking operation."""

    lock_file: str
    strategy_used: str
    package_count: int
    source_file: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def lock_dependencies(
    project_path: str,
    strategy: str = "auto",
    python_version: Optional[str] = None,
) -> LockResult:
    """Lock project dependencies to exact versions.

    Args:
        project_path: Path to the project root.
        strategy: One of "auto", "uv", "pip-compile", "pip-freeze".
        python_version: Target Python version (e.g. "3.12").

    Returns:
        LockResult with path to the generated lock file.
    """
    project_path = os.path.abspath(project_path)
    source_file = _find_source_file(project_path)

    if not source_file:
        inferred = _infer_requirements_from_imports(project_path)
        if not inferred:
            return LockResult(
                lock_file="",
                strategy_used="none",
                package_count=0,
                source_file="",
                errors=["No pyproject.toml, requirements.txt, or importable dependencies found"],
            )
        source_file = _write_inferred_requirements(project_path, inferred)

    lock_file = os.path.join(project_path, "requirements.lock")

    strategies = {
        "uv": _lock_with_uv,
        "pip-compile": _lock_with_pip_compile,
        "pip-freeze": _lock_with_pip_freeze,
    }

    if strategy == "auto":
        order = ["uv", "pip-compile", "pip-freeze"]
    else:
        order = [strategy]

    last_error = ""
    for strat in order:
        fn = strategies.get(strat)
        if not fn:
            continue
        try:
            result = fn(project_path, source_file, lock_file, python_version)
            if result.errors:
                last_error = result.errors[0]
                continue
            return result
        except Exception as e:
            last_error = f"{strat}: {e}"
            continue

    return LockResult(
        lock_file="",
        strategy_used="none",
        package_count=0,
        source_file=source_file,
        errors=[f"All strategies failed. Last error: {last_error}"],
    )


def verify_imports(project_path: str, lock_file: str) -> bool:
    """Verify that the lock file satisfies the project's imports.

    Does a quick check: parses the lock file for package names, then
    scans .py files for import statements and checks coverage.

    Returns True if all detected third-party imports are in the lock file.
    """
    if not os.path.exists(lock_file):
        return False

    # Parse locked packages
    locked = set()
    with open(lock_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            pkg = line.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0]
            locked.add(pkg.strip().lower().replace("-", "_"))

    # Scan for imports
    imported = set()
    for py_file in Path(project_path).rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("import "):
                    mod = line.split()[1].split(".")[0]
                    imported.add(mod.lower())
                elif line.startswith("from ") and " import " in line:
                    mod = line.split()[1].split(".")[0]
                    imported.add(mod.lower())
        except Exception:
            continue

    # Filter to likely third-party (not stdlib, not local)
    stdlib_mods = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()
    local_files = {p.stem.lower() for p in Path(project_path).rglob("*.py")}

    third_party = imported - stdlib_mods - local_files - {"__future__"}
    missing = third_party - locked

    return len(missing) == 0


def generate_build_report(
    project_path: str,
    lock_result: LockResult,
) -> str:
    """Generate a build_report.json with lock metadata.

    Returns path to the written report.
    """
    report_path = os.path.join(project_path, "build_report.json")
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "lock_file": lock_result.lock_file,
        "strategy": lock_result.strategy_used,
        "source_file": lock_result.source_file,
        "package_count": lock_result.package_count,
        "errors": lock_result.errors,
        "warnings": lock_result.warnings,
        "verified": verify_imports(project_path, lock_result.lock_file)
        if lock_result.lock_file
        else False,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    return report_path


# ------------------------------------------------------------------
# Internal strategy implementations
# ------------------------------------------------------------------


def _find_source_file(project_path: str) -> Optional[str]:
    """Find the dependency source file."""
    pyproject = os.path.join(project_path, "pyproject.toml")
    if os.path.exists(pyproject):
        return pyproject
    reqs = os.path.join(project_path, "requirements.txt")
    if os.path.exists(reqs):
        return reqs
    return None


def _infer_requirements_from_imports(project_path: str) -> List[str]:
    """Infer top-level dependencies from import statements."""
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

    return sorted(inferred)


def _write_inferred_requirements(project_path: str, packages: List[str]) -> str:
    """Write inferred requirements to .harden/state and return the file path."""
    state_dir = Path(project_path) / ".harden" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    req_path = state_dir / "requirements.inferred.txt"
    req_path.write_text("\n".join(packages) + "\n", encoding="utf-8")
    return str(req_path)


def _count_packages(lock_file: str) -> int:
    """Count non-comment, non-blank lines in a lock file."""
    count = 0
    try:
        with open(lock_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("-"):
                    count += 1
    except OSError:
        pass
    return count


def _lock_with_uv(
    project_path: str,
    source_file: str,
    lock_file: str,
    python_version: Optional[str],
) -> LockResult:
    """Lock using uv pip compile."""
    if not shutil.which("uv"):
        return LockResult(
            lock_file="", strategy_used="uv", package_count=0,
            source_file=source_file, errors=["uv not found on PATH"],
        )

    cmd = ["uv", "pip", "compile", source_file, "-o", lock_file, "--quiet"]
    if python_version:
        cmd.extend(["--python-version", python_version])

    result = subprocess.run(
        cmd, cwd=project_path, capture_output=True, text=True, timeout=120,
    )

    if result.returncode != 0:
        return LockResult(
            lock_file="", strategy_used="uv", package_count=0,
            source_file=source_file,
            errors=[result.stderr.strip()[:500] or "uv pip compile failed"],
        )

    pkg_count = _count_packages(lock_file)
    return LockResult(
        lock_file=lock_file, strategy_used="uv",
        package_count=pkg_count, source_file=source_file,
    )


def _lock_with_pip_compile(
    project_path: str,
    source_file: str,
    lock_file: str,
    python_version: Optional[str],
) -> LockResult:
    """Lock using pip-compile from pip-tools."""
    if not shutil.which("pip-compile"):
        return LockResult(
            lock_file="", strategy_used="pip-compile", package_count=0,
            source_file=source_file, errors=["pip-compile not found on PATH"],
        )

    cmd = ["pip-compile", source_file, "-o", lock_file, "--quiet"]

    result = subprocess.run(
        cmd, cwd=project_path, capture_output=True, text=True, timeout=120,
    )

    if result.returncode != 0:
        return LockResult(
            lock_file="", strategy_used="pip-compile", package_count=0,
            source_file=source_file,
            errors=[result.stderr.strip()[:500] or "pip-compile failed"],
        )

    pkg_count = _count_packages(lock_file)
    return LockResult(
        lock_file=lock_file, strategy_used="pip-compile",
        package_count=pkg_count, source_file=source_file,
    )


def _lock_with_pip_freeze(
    project_path: str,
    source_file: str,
    lock_file: str,
    python_version: Optional[str],
) -> LockResult:
    """Lock by creating a temp venv, installing deps, and running pip freeze."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="harden_lock_") as tmp:
        venv_path = os.path.join(tmp, "venv")

        # Create venv
        result = subprocess.run(
            [sys.executable, "-m", "venv", venv_path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return LockResult(
                lock_file="", strategy_used="pip-freeze", package_count=0,
                source_file=source_file, errors=["Failed to create venv"],
            )

        pip_path = os.path.join(venv_path, "bin", "pip")
        if not os.path.exists(pip_path):
            pip_path = os.path.join(venv_path, "Scripts", "pip.exe")

        # Install deps
        install_flag = "-r" if source_file.endswith(".txt") else source_file
        if source_file.endswith(".toml"):
            # Install from pyproject.toml using pip install .
            install_cmd = [pip_path, "install", ".", "--quiet"]
        else:
            install_cmd = [pip_path, "install", "-r", source_file, "--quiet"]

        result = subprocess.run(
            install_cmd, cwd=project_path, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            return LockResult(
                lock_file="", strategy_used="pip-freeze", package_count=0,
                source_file=source_file,
                errors=[result.stderr.strip()[:500] or "pip install failed"],
            )

        # Freeze
        result = subprocess.run(
            [pip_path, "freeze"], capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return LockResult(
                lock_file="", strategy_used="pip-freeze", package_count=0,
                source_file=source_file, errors=["pip freeze failed"],
            )

        with open(lock_file, "w") as f:
            f.write(f"# Locked by harden (pip-freeze strategy)\n")
            f.write(result.stdout)

    pkg_count = _count_packages(lock_file)
    return LockResult(
        lock_file=lock_file, strategy_used="pip-freeze",
        package_count=pkg_count, source_file=source_file,
    )
