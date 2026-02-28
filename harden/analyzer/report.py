"""Analysis report generation."""

import json
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from harden.analyzer.models import AppAnalysis


def generate_terminal_report(analysis: AppAnalysis) -> None:
    """
    Generate and print a rich terminal report.

    Args:
        analysis: AppAnalysis object with all findings
    """
    console = Console()

    # Header
    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]Harden Security Analysis Report[/bold cyan]\n"
            f"Project: {analysis.project_path}",
            border_style="cyan",
        )
    )
    console.print()

    # Risk score summary
    risk_score = analysis.risk_score
    risk_level = analysis.risk_level

    if risk_level == "CRITICAL":
        color = "red"
    elif risk_level == "HIGH":
        color = "orange1"
    elif risk_level == "MEDIUM":
        color = "yellow"
    else:
        color = "green"

    console.print(
        Panel(
            f"[bold {color}]Risk Score: {risk_score:.1f}/100[/bold {color}]\n"
            f"[bold {color}]Risk Level: {risk_level}[/bold {color}]",
            title="Overall Security Posture",
            border_style=color,
        )
    )
    console.print()

    # Framework info
    if analysis.framework:
        fw = analysis.framework
        entry_cmd = fw.entry_command or "Not detected"
        console.print(
            Panel(
                f"[bold]Framework:[/bold] {fw.name}\n"
                f"[bold]Version:[/bold] {fw.version or 'Unknown'}\n"
                f"[bold]Entry Point:[/bold] {fw.entry_point or 'Not detected'}\n"
                f"[bold]Entry Command:[/bold] {entry_cmd}\n"
                f"[bold]Confidence:[/bold] {fw.confidence * 100:.0f}%",
                title="Detected Framework",
                border_style="blue",
            )
        )
        console.print()

    if analysis.python_version:
        console.print(f"[bold]Python Version:[/bold] {analysis.python_version}")
        console.print()

    # App spec
    if analysis.app_spec:
        app = analysis.app_spec
        port_str = f"{app.listen_port}" if app.listen_port else "Not detected"
        async_str = "Yes" if app.is_async else "No"

        console.print(
            Panel(
                f"[bold]Type:[/bold] {app.app_type}\n"
                f"[bold]Listen Port:[/bold] {port_str}\n"
                f"[bold]Async:[/bold] {async_str}",
                title="Application Spec",
                border_style="blue",
            )
        )
        console.print()

    # Secrets findings
    if analysis.secrets:
        console.print("[bold red]SECRETS DETECTED[/bold red]")
        secrets_table = Table(show_header=True, header_style="bold red")
        secrets_table.add_column("File", style="cyan")
        secrets_table.add_column("Line", style="white")
        secrets_table.add_column("Type", style="yellow")
        secrets_table.add_column("Severity", style="red")
        secrets_table.add_column("Preview", style="dim")

        for secret in analysis.secrets:
            severity_color = _get_severity_color(secret.severity)
            secrets_table.add_row(
                secret.file,
                str(secret.line),
                secret.description,
                f"[{severity_color}]{secret.severity.upper()}[/{severity_color}]",
                secret.value_preview,
            )

        console.print(secrets_table)
        console.print()
    else:
        console.print("[bold green]✓ No secrets detected[/bold green]")
        console.print()

    # AI usage
    if analysis.ai_usage:
        console.print("[bold magenta]AI API USAGE DETECTED[/bold magenta]")
        ai_table = Table(show_header=True, header_style="bold magenta")
        ai_table.add_column("Provider", style="cyan")
        ai_table.add_column("SDK", style="white")
        ai_table.add_column("Config Method", style="yellow")
        ai_table.add_column("Files", style="dim")

        for ai in analysis.ai_usage:
            config_color = "red" if ai.config_method == "hardcoded" else "green" if ai.config_method == "env_var" else "yellow"
            ai_table.add_row(
                ai.provider,
                ai.sdk,
                f"[{config_color}]{ai.config_method}[/{config_color}]",
                str(len(ai.files)),
            )

        console.print(ai_table)
        console.print()
    else:
        console.print("[bold]No AI API usage detected[/bold]")
        console.print()

    # External services
    if analysis.external_services:
        console.print("[bold cyan]EXTERNAL SERVICES DETECTED[/bold cyan]")
        services_table = Table(show_header=True, header_style="bold cyan")
        services_table.add_column("Provider", style="cyan")
        services_table.add_column("Category", style="white")
        services_table.add_column("SDK", style="yellow")
        services_table.add_column("Auth Method", style="magenta")
        services_table.add_column("Domains", style="dim")

        for svc in analysis.external_services:
            auth_color = "green" if svc.auth_method in ("oauth", "iam") else "yellow" if svc.auth_method == "api_key" else "red" if svc.auth_method == "connection_string" else "dim"
            domains_str = ", ".join(svc.domains[:2]) if svc.domains else "N/A"
            if len(svc.domains) > 2:
                domains_str += f" (+{len(svc.domains) - 2})"

            services_table.add_row(
                svc.provider,
                svc.category,
                svc.sdk,
                f"[{auth_color}]{svc.auth_method}[/{auth_color}]",
                domains_str,
            )

        console.print(services_table)
        console.print()
    else:
        console.print("[bold]No external services detected[/bold]")
        console.print()

    # Dependencies
    if analysis.dependencies:
        vulnerable_deps = [d for d in analysis.dependencies if d.has_known_cves]
        unpinned_deps = [d for d in analysis.dependencies if not d.pinned]

        if vulnerable_deps:
            console.print("[bold red]VULNERABLE DEPENDENCIES[/bold red]")
            deps_table = Table(show_header=True, header_style="bold red")
            deps_table.add_column("Package", style="cyan")
            deps_table.add_column("Version", style="white")
            deps_table.add_column("Severity", style="red")
            deps_table.add_column("CVE Details", style="yellow")

            for dep in vulnerable_deps:
                severity_color = _get_severity_color(dep.severity)
                deps_table.add_row(
                    dep.name,
                    dep.version or "Not pinned",
                    f"[{severity_color}]{dep.severity.upper()}[/{severity_color}]",
                    "\n".join(dep.cve_details),
                )

            console.print(deps_table)
            console.print()

        if unpinned_deps:
            console.print(f"[bold yellow]⚠ {len(unpinned_deps)} unpinned dependencies detected[/bold yellow]")
            console.print("[dim]Unpinned dependencies can lead to inconsistent deployments[/dim]")
            console.print()

        total_deps = len(analysis.dependencies)
        safe_deps = total_deps - len(vulnerable_deps)
        console.print(f"[bold]Total dependencies:[/bold] {total_deps}")
        console.print(f"[bold green]Safe:[/bold green] {safe_deps}")
        console.print(f"[bold red]Vulnerable:[/bold red] {len(vulnerable_deps)}")
        console.print()
    else:
        console.print("[bold]No dependencies file found (requirements.txt or pyproject.toml)[/bold]")
        console.print()

    # Risk items
    if analysis.risks:
        console.print("[bold red]RISK ITEMS[/bold red]")
        for risk in analysis.risks:
            severity_color = _get_severity_color(risk.severity)
            console.print(
                Panel(
                    f"[bold]Category:[/bold] {risk.category}\n"
                    f"[bold]Description:[/bold] {risk.description}\n"
                    f"[bold]Remediation:[/bold] {risk.remediation}",
                    title=f"[{severity_color}]{risk.severity.upper()}[/{severity_color}] - {risk.title}",
                    border_style=severity_color,
                )
            )
        console.print()

    # Recommendations
    console.print(
        Panel.fit(
            _generate_recommendations(analysis),
            title="Recommendations",
            border_style="cyan",
        )
    )
    console.print()


def save_json_report(analysis: AppAnalysis, output_path: str) -> None:
    """
    Save analysis report as JSON.

    Args:
        analysis: AppAnalysis object
        output_path: Path to save JSON file
    """
    report_data = {
        "project_path": analysis.project_path,
        "risk_score": analysis.risk_score,
        "risk_level": analysis.risk_level,
        "framework": {
            "name": analysis.framework.name,
            "version": analysis.framework.version,
            "entry_point": analysis.framework.entry_point,
            "entry_command": analysis.framework.entry_command,
            "confidence": analysis.framework.confidence,
        } if analysis.framework else None,
        "app_spec": {
            "app_type": analysis.app_spec.app_type,
            "listen_port": analysis.app_spec.listen_port,
            "is_async": analysis.app_spec.is_async,
        } if analysis.app_spec else None,
        "python_version": analysis.python_version,
        "secrets": [
            {
                "file": s.file,
                "line": s.line,
                "type": s.type,
                "description": s.description,
                "value_preview": s.value_preview,
                "severity": s.severity,
            }
            for s in analysis.secrets
        ],
        "dependencies": [
            {
                "name": d.name,
                "version": d.version,
                "pinned": d.pinned,
                "has_known_cves": d.has_known_cves,
                "cve_details": d.cve_details,
                "severity": d.severity,
            }
            for d in analysis.dependencies
        ],
        "ai_usage": [
            {
                "provider": ai.provider,
                "sdk": ai.sdk,
                "config_method": ai.config_method,
                "files": ai.files,
            }
            for ai in analysis.ai_usage
        ],
        "external_services": [
            {
                "provider": es.provider,
                "category": es.category,
                "sdk": es.sdk,
                "auth_method": es.auth_method,
                "domains": es.domains,
                "files": es.files,
            }
            for es in analysis.external_services
        ],
        "risks": [
            {
                "severity": r.severity,
                "category": r.category,
                "title": r.title,
                "description": r.description,
                "remediation": r.remediation,
                "files": r.files,
            }
            for r in analysis.risks
        ],
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)


def _get_severity_color(severity: str) -> str:
    """Get color for severity level."""
    severity = severity.lower()
    if severity == "critical":
        return "red"
    elif severity == "high":
        return "orange1"
    elif severity == "medium":
        return "yellow"
    else:
        return "blue"


def _generate_recommendations(analysis: AppAnalysis) -> str:
    """Generate recommendations based on analysis."""
    recommendations = []

    # Secrets
    if analysis.secrets:
        recommendations.append(
            "• [bold red]URGENT:[/bold red] Remove hardcoded secrets and use environment variables or a secrets manager"
        )

    # AI API keys
    hardcoded_ai = [ai for ai in analysis.ai_usage if ai.config_method == "hardcoded"]
    if hardcoded_ai:
        recommendations.append(
            "• [bold red]CRITICAL:[/bold red] Move AI API keys to environment variables or secrets manager"
        )

    # Vulnerable dependencies
    critical_deps = [d for d in analysis.dependencies if d.has_known_cves and d.severity == "critical"]
    if critical_deps:
        recommendations.append(
            f"• [bold red]CRITICAL:[/bold red] Update {len(critical_deps)} dependencies with critical CVEs"
        )

    # Unpinned dependencies
    unpinned = [d for d in analysis.dependencies if not d.pinned]
    if unpinned:
        recommendations.append(
            f"• [yellow]Pin all dependency versions ({len(unpinned)} unpinned found)[/yellow]"
        )

    # .env files
    env_secrets = [s for s in analysis.secrets if s.type == "unignored_env_file"]
    if env_secrets:
        recommendations.append(
            "• [bold yellow]Add .env files to .gitignore[/bold yellow]"
        )

    # General recommendations
    if not recommendations:
        recommendations.append("[green]• No critical issues found[/green]")
        recommendations.append("• Consider running `harden generate` to create production-ready artifacts")
    else:
        recommendations.append("\n• Run `harden generate <path>` to create hardened deployment artifacts")
        recommendations.append("• Review the harden-report.json for detailed findings")

    return "\n".join(recommendations)
