"""Framework and environment detection."""

import ast
import os
import re
from pathlib import Path
from typing import Optional, List

from harden.analyzer.models import FrameworkInfo, AppSpec
from harden.analyzer.ast_utils import (
    extract_imports,
    extract_call_kwargs,
    root_package,
    iter_python_files,
    read_source,
)


def detect_framework(project_path: str) -> Optional[FrameworkInfo]:
    """
    Detect the web framework used in the project.

    Args:
        project_path: Path to the project directory

    Returns:
        FrameworkInfo if a framework is detected, None otherwise
    """
    project = Path(project_path)

    # Find all Python files
    python_files = list(project.rglob("*.py"))

    # Framework detection patterns
    frameworks = {
        "fastapi": {
            "imports": [r"from\s+fastapi\s+import", r"import\s+fastapi"],
            "patterns": [r"FastAPI\(", r"@app\.(get|post|put|delete)"],
        },
        "flask": {
            "imports": [r"from\s+flask\s+import", r"import\s+flask"],
            "patterns": [r"Flask\(__name__\)", r"@app\.route"],
        },
        "streamlit": {
            "imports": [r"import\s+streamlit\s+as\s+st", r"import\s+streamlit"],
            "patterns": [r"st\.(write|title|header|button)", r"streamlit\."],
        },
        "gradio": {
            "imports": [r"import\s+gradio\s+as\s+gr", r"import\s+gradio"],
            "patterns": [r"gr\.(Interface|Blocks|launch)", r"gradio\."],
        },
        "django": {
            "imports": [r"from\s+django", r"import\s+django"],
            "patterns": [r"django\."],
        },
    }

    detected = {}

    for py_file in python_files:
        try:
            with open(py_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

                for framework_name, patterns in frameworks.items():
                    score = 0

                    # Check imports
                    for import_pattern in patterns["imports"]:
                        if re.search(import_pattern, content):
                            score += 10

                    # Check usage patterns
                    for usage_pattern in patterns["patterns"]:
                        score += len(re.findall(usage_pattern, content)) * 2

                    if score > 0:
                        if framework_name not in detected:
                            detected[framework_name] = {"score": 0, "files": []}
                        detected[framework_name]["score"] += score
                        detected[framework_name]["files"].append(str(py_file.relative_to(project)))

        except Exception:
            continue

    if not detected:
        return None

    # Return the framework with the highest score
    best_framework = max(detected.items(), key=lambda x: x[1]["score"])
    framework_name = best_framework[0]
    framework_data = best_framework[1]

    # Try to find entry point
    entry_point = _find_entry_point(project, framework_name, framework_data["files"])

    # Try to detect version
    version = _detect_framework_version(project, framework_name)

    # Infer entry command
    entry_command = _infer_entry_command(project, framework_name, entry_point)

    return FrameworkInfo(
        name=framework_name,
        version=version,
        entry_point=entry_point,
        entry_command=entry_command,
        confidence=min(framework_data["score"] / 25.0, 1.0),
    )


def _find_entry_point(project: Path, framework: str, framework_files: List[str]) -> Optional[str]:
    """Find the main entry point file."""
    # Common entry point names
    common_names = ["main.py", "app.py", "server.py", "run.py", "__main__.py"]

    # Check common names first
    for name in common_names:
        if name in [Path(f).name for f in framework_files]:
            return next(f for f in framework_files if Path(f).name == name)

    # Check for if __name__ == "__main__" in framework files
    for file_path in framework_files:
        full_path = project / file_path
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if re.search(r'if\s+__name__\s*==\s*["\']__main__["\']', content):
                    # Check if it has framework-specific launch code
                    if framework == "fastapi" and re.search(r'uvicorn\.run', content):
                        return file_path
                    elif framework == "flask" and re.search(r'app\.run\(', content):
                        return file_path
                    elif framework == "streamlit":
                        return file_path
                    elif framework == "gradio" and re.search(r'\.launch\(', content):
                        return file_path
        except Exception:
            continue

    # Return the first file with the framework usage
    return framework_files[0] if framework_files else None


def _detect_framework_version(project: Path, framework: str) -> Optional[str]:
    """Try to detect the framework version from dependencies."""
    # Search all requirements.txt files (root + subdirectories)
    for req_file in sorted(project.rglob("requirements.txt")):
        if any(part in str(req_file) for part in [".git", "node_modules", "__pycache__", ".venv", "venv"]):
            continue
        try:
            with open(req_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.lower().startswith(framework):
                        match = re.search(r"==([0-9.]+)", line)
                        if match:
                            return match.group(1)
                        match = re.search(r">=([0-9.]+)", line)
                        if match:
                            return f">={match.group(1)}"
        except Exception:
            pass

    # Search all pyproject.toml files
    for pyproject in sorted(project.rglob("pyproject.toml")):
        if any(part in str(pyproject) for part in [".git", "node_modules", "__pycache__", ".venv", "venv"]):
            continue
        try:
            with open(pyproject, "r", encoding="utf-8") as f:
                content = f.read()
                pattern = rf'"{framework}[^"]*"'
                matches = re.findall(pattern, content)
                if matches:
                    version_match = re.search(r"==([0-9.]+)", matches[0])
                    if version_match:
                        return version_match.group(1)
        except Exception:
            pass

    return None


def _detect_app_variable(entry_path: Path, class_name: str) -> Optional[str]:
    """Detect the app variable name (e.g., app = FastAPI())."""
    try:
        content = entry_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    pattern = rf"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*{class_name}\s*\("
    match = re.search(pattern, content, re.MULTILINE)
    if match:
        return match.group(1)
    return None


def _infer_entry_command(project: Path, framework: str, entry_point: Optional[str]) -> Optional[str]:
    """Infer a best-effort entry command for the detected framework."""
    if not entry_point:
        return None

    entry_module = Path(entry_point).with_suffix("").as_posix().replace("/", ".")
    entry_path = project / entry_point

    if framework == "fastapi":
        app_var = _detect_app_variable(entry_path, "FastAPI") or "app"
        return f"uvicorn {entry_module}:{app_var} --host 0.0.0.0 --port 8000"
    if framework == "flask":
        app_var = _detect_app_variable(entry_path, "Flask") or "app"
        return f"gunicorn -w 4 -b 0.0.0.0:5000 {entry_module}:{app_var}"
    if framework == "streamlit":
        return f"streamlit run {entry_point} --server.port 8501 --server.address 0.0.0.0"
    if framework == "gradio":
        return f"python {entry_point}"
    if framework == "django":
        if (project / "manage.py").exists():
            return "python manage.py runserver 0.0.0.0:8000"
        return f"gunicorn {entry_module}.wsgi:application"

    return f"python {entry_point}"


def detect_python_version(project_path: str) -> Optional[str]:
    """
    Detect the Python version used by the project.

    Args:
        project_path: Path to the project directory

    Returns:
        Python version string or None
    """
    project = Path(project_path)

    # Check pyproject.toml
    pyproject = project / "pyproject.toml"
    if pyproject.exists():
        try:
            with open(pyproject, "r", encoding="utf-8") as f:
                content = f.read()
                # Look for requires-python
                match = re.search(r'requires-python\s*=\s*"([^"]+)"', content)
                if match:
                    return match.group(1)
        except Exception:
            pass

    # Check runtime.txt (common in deployment configs)
    runtime = project / "runtime.txt"
    if runtime.exists():
        try:
            with open(runtime, "r", encoding="utf-8") as f:
                content = f.read().strip()
                match = re.search(r"python-([0-9.]+)", content)
                if match:
                    return match.group(1)
        except Exception:
            pass

    # Check .python-version (pyenv)
    python_version_file = project / ".python-version"
    if python_version_file.exists():
        try:
            with open(python_version_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass

    return None


def detect_app_spec(project_path: str, framework: Optional[FrameworkInfo] = None) -> Optional[AppSpec]:
    """Detect application specification (type, port, async).

    Uses AST-based extraction for:
    - CLI detection: AST imports of click/argparse/typer/fire
    - Port detection: extract_call_kwargs for uvicorn.run/app.run/run_simple
    - Async detection: AST imports of asyncio + async function defs
    """
    project = Path(project_path)

    # CLI framework root packages
    _CLI_PACKAGES = {"click", "argparse", "typer", "fire"}

    # Framework-specific run functions whose `port=` kwarg is the app port
    _PORT_FUNCTIONS = ["uvicorn.run", "app.run", "run_simple"]

    # Framework default ports
    _DEFAULT_PORTS = {
        "fastapi": 8000, "django": 8000, "flask": 5000,
        "streamlit": 8501, "gradio": 7860,
    }

    # Determine app_type
    app_type = "script"
    if framework:
        app_type = "web"
    else:
        notebook_files = list(project.rglob("*.ipynb"))
        if notebook_files:
            app_type = "notebook"
        else:
            for py_file in iter_python_files(project):
                source = read_source(py_file)
                if not source:
                    continue
                imports = extract_imports(source)
                roots = {root_package(imp) for imp in imports}
                if roots & _CLI_PACKAGES:
                    app_type = "cli"
                    break

    # Detect listen_port
    listen_port = None

    if app_type == "web":
        # Framework-specific default
        if framework:
            listen_port = _DEFAULT_PORTS.get(framework.name, None)

        # AST-based: extract port= kwargs from framework run calls
        for py_file in iter_python_files(project):
            source = read_source(py_file)
            if not source:
                continue

            kwargs = extract_call_kwargs(source, _PORT_FUNCTIONS)
            for func_name, kwarg_list in kwargs.items():
                for kwarg_name, kwarg_value, lineno in kwarg_list:
                    if kwarg_name == "port" and isinstance(kwarg_value, int):
                        listen_port = kwarg_value

            # Fallback: regex for env-based port and CLI flags
            for pattern in [
                r'os\.environ\.get\s*\(\s*["\']PORT["\']\s*,\s*["\']?(\d+)',
                r'int\s*\(\s*os\.environ\.get\s*\(\s*["\']PORT["\']\s*,\s*["\']?(\d+)',
                r'--port[=\s]+(\d+)',
            ]:
                match = re.search(pattern, source)
                if match:
                    try:
                        listen_port = int(match.group(1))
                    except (ValueError, IndexError):
                        pass

    # Detect is_async via AST
    is_async = False
    for py_file in iter_python_files(project):
        source = read_source(py_file)
        if not source:
            continue

        imports = extract_imports(source)
        if "asyncio" in imports or any(imp.startswith("asyncio.") for imp in imports):
            is_async = True
            break

        # Also check for async def via AST
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    is_async = True
                    break
            if is_async:
                break
        except SyntaxError:
            continue

    return AppSpec(
        app_type=app_type,
        listen_port=listen_port,
        is_async=is_async,
    )


def analyze_project_structure(project_path: str) -> dict:
    """
    Analyze the project structure.

    Args:
        project_path: Path to the project directory

    Returns:
        Dictionary with project structure information
    """
    project = Path(project_path)

    python_files = list(project.rglob("*.py"))
    env_files = [f for f in project.rglob(".env*")
                 if not any(part in str(f) for part in [".git", "node_modules", "__pycache__", ".venv", "venv"])]
    config_files = []

    # Look for common config files
    config_patterns = ["*.yaml", "*.yml", "*.json", "*.toml", "*.ini", "*.conf"]
    for pattern in config_patterns:
        config_files.extend(project.glob(pattern))

    return {
        "python_files": len(python_files),
        "env_files": [str(f.relative_to(project)) for f in env_files],
        "config_files": [str(f.relative_to(project)) for f in config_files],
        "has_tests": any(
            "test" in str(f).lower() or "tests" in str(f).lower() for f in python_files
        ),
        "has_requirements": any(project.rglob("requirements.txt")),
        "has_pyproject": any(project.rglob("pyproject.toml")),
        "has_dockerfile": (project / "Dockerfile").exists(),
        "has_gitignore": (project / ".gitignore").exists(),
    }
