"""OSS CLI interface for the harden tool."""

import json
import os
import re
import sys
from pathlib import Path

import click
from rich.console import Console

from harden.analyzer.models import AppAnalysis, RiskItem
from harden.analyzer.detector import detect_framework, detect_python_version, detect_app_spec
from harden.analyzer.secrets import detect_secrets
from harden.analyzer.dependencies import analyze_dependencies
from harden.analyzer.ai_usage import detect_ai_usage
from harden.analyzer.external_services import detect_external_services
from harden.analyzer.ast_utils import iter_python_files, read_source, collect_declared_deps
from harden.analyzer.report import generate_terminal_report, save_json_report
from harden.generators import generate_dockerfile, generate_dockerignore, generate_compose
from harden.generators.sbom import build_sbom_document
from harden.generators.egress_proxy import generate_squid_config, collect_egress_domains
from harden.pipeline import StateManager, Stage


console = Console()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _run_analysis(project_path):
    """Run all analyzers and return an AppAnalysis object."""
    framework = detect_framework(project_path)
    app_spec = detect_app_spec(project_path, framework)
    python_version = detect_python_version(project_path)
    secrets = detect_secrets(project_path)
    dependencies = analyze_dependencies(project_path)
    ai_usage = detect_ai_usage(project_path)
    external_services = detect_external_services(project_path)
    risks = _generate_risk_items(framework, secrets, dependencies, ai_usage, project_path)

    return AppAnalysis(
        project_path=project_path,
        framework=framework,
        app_spec=app_spec,
        python_version=python_version,
        secrets=secrets,
        dependencies=dependencies,
        ai_usage=ai_usage,
        external_services=external_services,
        risks=risks,
    )


def _record_pipeline(project_path, stage, metadata=None):
    """Record pipeline stage completion (best-effort)."""
    try:
        sm = StateManager(project_path)
        sm.record_stage(stage, metadata)
    except Exception:
        pass


def _ensure_state_dir(project_path: str) -> str:
    """Ensure .harden/state exists and return its path."""
    state_dir = os.path.join(project_path, ".harden", "state")
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    return state_dir


# ------------------------------------------------------------------
# CLI group
# ------------------------------------------------------------------


@click.group()
@click.version_option(version="0.4.0")
def main():
    """Harden (OSS) - Analyze, lock, and generate Dockerfile-only artifacts."""
    pass


# ------------------------------------------------------------------
# analyze
# ------------------------------------------------------------------


@main.command()
@click.argument("path", type=click.Path(exists=True), default=".")
def analyze(path):
    """
    Run security analysis and print report.

    PATH: Path to the project directory (default: current directory)
    """
    project_path = os.path.abspath(path)

    console.print(f"\n[bold cyan]Analyzing project:[/bold cyan] {project_path}\n")

    # Run all analyzers
    with console.status("[bold green]Detecting framework..."):
        framework = detect_framework(project_path)

    with console.status("[bold green]Detecting application spec..."):
        app_spec = detect_app_spec(project_path, framework)

    with console.status("[bold green]Detecting Python version..."):
        python_version = detect_python_version(project_path)

    with console.status("[bold green]Scanning for secrets..."):
        secrets = detect_secrets(project_path)

    with console.status("[bold green]Analyzing dependencies..."):
        dependencies = analyze_dependencies(project_path)

    with console.status("[bold green]Detecting AI usage..."):
        ai_usage = detect_ai_usage(project_path)

    with console.status("[bold green]Detecting external services..."):
        external_services = detect_external_services(project_path)

    # Generate risk items based on findings
    risks = _generate_risk_items(framework, secrets, dependencies, ai_usage, project_path)

    # Create analysis object
    analysis = AppAnalysis(
        project_path=project_path,
        framework=framework,
        app_spec=app_spec,
        python_version=python_version,
        secrets=secrets,
        dependencies=dependencies,
        ai_usage=ai_usage,
        external_services=external_services,
        risks=risks,
    )

    # Print terminal report
    generate_terminal_report(analysis)

    # Save JSON report to .harden/state/
    state_dir = _ensure_state_dir(project_path)
    report_path = os.path.join(state_dir, "harden-report.json")
    save_json_report(analysis, report_path)
    console.print(f"[bold green]Report saved to:[/bold green] {report_path}\n")

    # Pipeline state
    _record_pipeline(project_path, Stage.ANALYZE, {
        "risk_score": analysis.risk_score,
        "risk_level": analysis.risk_level,
        "deps": len(analysis.dependencies),
    })


# ------------------------------------------------------------------
# lock
# ------------------------------------------------------------------


@main.command()
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--strategy", type=click.Choice(["auto", "uv", "pip-compile", "pip-freeze"]),
              default="auto", help="Locking strategy")
@click.option("--python-version", default=None, help="Target Python version (e.g. 3.12)")
def lock(path, strategy, python_version):
    """
    Lock dependencies to exact versions.

    Produces requirements.lock and build_report.json.

    PATH: Path to the project directory (default: current directory)
    """
    from harden.locker import lock_dependencies, generate_build_report, verify_imports

    project_path = os.path.abspath(path)
    console.print(f"\n[bold cyan]Locking dependencies for:[/bold cyan] {project_path}")
    console.print(f"[bold]Strategy:[/bold] {strategy}\n")

    with console.status("[bold green]Locking dependencies..."):
        result = lock_dependencies(project_path, strategy=strategy, python_version=python_version)

    if result.errors:
        for err in result.errors:
            console.print(f"  [bold red]Error:[/bold red] {err}")
        if not result.lock_file:
            sys.exit(1)

    console.print(f"[bold green]Lock file:[/bold green] {result.lock_file}")
    console.print(f"[bold]Strategy used:[/bold] {result.strategy_used}")
    console.print(f"[bold]Packages locked:[/bold] {result.package_count}")

    # Verify imports are covered by the lock file
    if result.lock_file and not verify_imports(project_path, result.lock_file):
        console.print(
            "\n[bold yellow]Warning:[/bold yellow] Some imports in the source code "
            "are not covered by the lock file."
        )
        console.print(
            "[dim]This can happen when pyproject.toml dependencies are incomplete. "
            "Check build_report.json for details.[/dim]"
        )

    # Generate build report
    report_path = generate_build_report(project_path, result)
    console.print(f"[bold green]Build report:[/bold green] {report_path}\n")

    # Pipeline state
    _record_pipeline(project_path, Stage.LOCK, {
        "strategy": result.strategy_used,
        "package_count": result.package_count,
    })


# ------------------------------------------------------------------
# generate (Dockerfile-only)
# ------------------------------------------------------------------


@main.command()
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option(
    "--fail-on-critical",
    is_flag=True,
    help="Exit non-zero if critical CVEs are detected in dependencies",
)
def generate(path, fail_on_critical):
    """
    Generate OSS hardening artifacts into <path>/.harden/

    Produces:
    - .harden/Dockerfile
    - .harden/sbom.json
    - (optional) .dockerignore in project root if missing
    """
    project_path = os.path.abspath(path)
    harden_dir = os.path.join(project_path, ".harden")

    console.print(f"\n[bold cyan]Generating OSS artifacts for:[/bold cyan] {project_path}\n")

    # Run analysis first
    with console.status("[bold green]Running analysis..."):
        analysis = _run_analysis(project_path)

    # Create .harden directory
    Path(harden_dir).mkdir(exist_ok=True)

    # Generate Dockerfile + SBOM + compose + squid
    dockerfile = generate_dockerfile(analysis)
    sbom_doc, sbom_deps = build_sbom_document(analysis)
    sbom = json.dumps(sbom_doc, indent=2, sort_keys=False)

    egress_domains = collect_egress_domains(analysis)
    squid_conf = generate_squid_config(egress_domains)
    compose = generate_compose(analysis)

    dockerfile_path = os.path.join(harden_dir, "Dockerfile")
    sbom_path = os.path.join(harden_dir, "sbom.json")
    compose_path = os.path.join(harden_dir, "docker-compose.yml")
    squid_path = os.path.join(harden_dir, "squid.conf")

    with open(dockerfile_path, "w", encoding="utf-8") as f:
        f.write(dockerfile)
    with open(sbom_path, "w", encoding="utf-8") as f:
        f.write(sbom)
    with open(compose_path, "w", encoding="utf-8") as f:
        f.write(compose)
    with open(squid_path, "w", encoding="utf-8") as f:
        f.write(squid_conf)

    if fail_on_critical:
        critical = [d for d in sbom_deps if d.has_known_cves and d.severity == "critical"]
        if critical:
            console.print("[bold red]Critical vulnerabilities detected in dependencies.[/bold red]")
            for dep in critical:
                console.print(f"  - {dep.name} ({dep.version or 'unversioned'})")
            sys.exit(1)

    # Generate .dockerignore at project root if missing
    dockerignore_path = os.path.join(project_path, ".dockerignore")
    if not os.path.exists(dockerignore_path):
        with open(dockerignore_path, "w", encoding="utf-8") as f:
            f.write(generate_dockerignore(analysis))
        console.print(f"[bold green]Wrote .dockerignore:[/bold green] {dockerignore_path}")
    else:
        console.print("[dim].dockerignore already exists — leaving as-is.[/dim]")

    console.print("\n[bold green]Generated files:[/bold green]")
    console.print(f"  • {dockerfile_path}")
    console.print(f"  • {sbom_path}")
    console.print(f"  • {compose_path}")
    console.print(f"  • {squid_path}")
    if egress_domains:
        console.print(f"\n[bold]Egress allowlist[/bold] ({len(egress_domains)} domains):")
        for d in egress_domains:
            console.print(f"  [dim]• {d}[/dim]")
    console.print(f"\n[bold cyan]Run with:[/bold cyan] cd .harden && docker compose up")
    console.print()

    # Pipeline state
    _record_pipeline(project_path, Stage.GENERATE, {
        "artifact_count": 4,
        "egress_domains": len(egress_domains),
    })


# ------------------------------------------------------------------
# Risk items helper
# ------------------------------------------------------------------


def _generate_risk_items(framework, secrets, dependencies, ai_usage, project_path):
    """Generate risk items based on findings."""
    risks = []
    project = Path(project_path)

    def _has_pattern(patterns: list[str]) -> bool:
        for py_file in iter_python_files(project):
            source = read_source(py_file)
            if not source:
                continue
            for pat in patterns:
                if re.search(pat, source, re.IGNORECASE):
                    return True
        return False

    # Check for missing .gitignore
    if not (project / ".gitignore").exists():
        risks.append(
            RiskItem(
                severity="medium",
                category="security",
                title="Missing .gitignore",
                description="No .gitignore file found. This may lead to accidental commits of sensitive files.",
                remediation="Create a .gitignore file and add common patterns (*.env, __pycache__, etc.)",
            )
        )

    # Check for production readiness (framework-specific risks)
    if framework:
        for py_file in iter_python_files(project):
            source = read_source(py_file)
            if not source:
                continue

            rel_path = str(py_file.relative_to(project))

            # Flask: debug=True
            if framework.name == "flask" and "debug=True" in source:
                risks.append(
                    RiskItem(
                        severity="high",
                        category="security",
                        title="Debug mode enabled",
                        description="Flask debug mode is enabled, which exposes sensitive information.",
                        remediation="Set debug=False in production environments",
                        files=[rel_path],
                    )
                )

            # Django: DEBUG = True
            if framework.name == "django" and re.search(r'^\s*DEBUG\s*=\s*True', source, re.MULTILINE):
                risks.append(
                    RiskItem(
                        severity="high",
                        category="security",
                        title="Django DEBUG mode enabled",
                        description="Django DEBUG=True exposes tracebacks, SQL queries, and settings to users.",
                        remediation="Set DEBUG=False and configure ALLOWED_HOSTS for production",
                        files=[rel_path],
                    )
                )

            # Django: ALLOWED_HOSTS = ['*']
            if framework.name == "django" and re.search(r"ALLOWED_HOSTS\s*=\s*\[\s*['\"]?\*['\"]?\s*\]", source):
                risks.append(
                    RiskItem(
                        severity="medium",
                        category="security",
                        title="Django ALLOWED_HOSTS accepts all",
                        description="ALLOWED_HOSTS=['*'] permits HTTP Host header attacks.",
                        remediation="Set ALLOWED_HOSTS to your actual domain(s)",
                        files=[rel_path],
                    )
                )

    # Check for hardcoded AI keys
    hardcoded_ai = [ai for ai in ai_usage if ai.config_method == "hardcoded"]
    if hardcoded_ai:
        risks.append(
            RiskItem(
                severity="critical",
                category="security",
                title="Hardcoded AI API keys",
                description=f"Found {len(hardcoded_ai)} AI SDK(s) with hardcoded API keys. This is a critical security risk.",
                remediation="Move all API keys to environment variables or a secrets manager",
                files=[f for ai in hardcoded_ai for f in ai.files],
            )
        )

    # Check for lack of dependency management
    has_dep_file = bool(collect_declared_deps(project))
    if not has_dep_file:
        risks.append(
            RiskItem(
                severity="medium",
                category="reliability",
                title="No dependency management",
                description="No requirements.txt or pyproject.toml found. Dependencies are not tracked.",
                remediation="Create a requirements.txt or pyproject.toml file with pinned versions",
            )
        )

    # Missing production scaffolding checklist (best-effort heuristics)
    scaffolding_checks = [
        (
            "Missing authentication layer",
            ["oauth", "oidc", "authlib", "flask_login", "fastapi.security", "jwt"],
            "Add an auth layer (OIDC/OAuth) before exposing the app in production.",
        ),
        (
            "Missing health endpoints",
            [r"/healthz", r"/readyz", r"healthcheck", r"health_check"],
            "Expose /healthz and /readyz endpoints for production health probes.",
        ),
        (
            "Missing structured logging",
            ["structlog", "loguru", r"logging\.basicConfig", r"logging\.getLogger"],
            "Emit structured JSON logs (timestamp, request_id, status, latency).",
        ),
        (
            "Missing rate limiting",
            ["ratelimit", "rate_limit", "slowapi", "flask_limiter", "limits"],
            "Add per-user rate limiting to protect upstream APIs and costs.",
        ),
    ]

    # Cost caps only relevant if AI usage is detected
    if ai_usage:
        scaffolding_checks.append(
            (
                "Missing AI cost caps",
                ["cost cap", "budget", "quota", "max_tokens", "token_budget"],
                "Add daily or per-request AI cost caps (or token budget enforcement).",
            )
        )

    for title, patterns, remediation in scaffolding_checks:
        if not _has_pattern(patterns):
            risks.append(
                RiskItem(
                    severity="medium",
                    category="operational",
                    title=title,
                    description="No evidence of production scaffolding detected in source.",
                    remediation=remediation,
                )
            )

    return risks


if __name__ == "__main__":
    main()
