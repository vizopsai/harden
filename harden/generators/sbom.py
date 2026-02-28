"""SBOM (Software Bill of Materials) generator."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..analyzer.models import AppAnalysis, DependencyInfo
from ..analyzer import dependencies as depmod

# Use a fixed timestamp so that generation is idempotent (same input → same output).
# The actual generation time is captured by the caller when writing to disk.
_SBOM_TIMESTAMP = "2024-01-01T00:00:00Z"


def _parse_lockfile(lock_file: Path) -> List[DependencyInfo]:
    dependencies: List[DependencyInfo] = []
    if not lock_file.exists():
        return dependencies

    for line in lock_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Remove environment markers
        line = line.split(";", 1)[0].strip()
        # Strip extras: pkg[extra]==1.2.3
        line = re.sub(r"\[.*?\]", "", line)
        match = re.match(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
        if not match:
            continue
        name = match.group(1).lower()
        version = match.group(2)
        dependencies.append(DependencyInfo(name=name, version=version, pinned=True))

    return dependencies


def _dependencies_for_sbom(analysis: AppAnalysis) -> List[DependencyInfo]:
    lock_file = Path(analysis.project_path) / "requirements.lock"
    if lock_file.exists():
        deps = _parse_lockfile(lock_file)
        # Enrich with OSV data for vuln reporting
        depmod._enrich_with_osv(deps, analysis.project_path)
        return deps

    return list(analysis.dependencies)


def build_sbom_document(analysis: AppAnalysis) -> Tuple[Dict[str, Any], List[DependencyInfo]]:
    """
    Generate a CycloneDX 1.5 SBOM in JSON format.

    Creates a Software Bill of Materials documenting:
    - All dependencies (name, version, package URL)
    - Known vulnerabilities (CVEs)
    - Component metadata

    Args:
        analysis: Application analysis results

    Returns:
        (SBOM document dict, dependencies used)
    """
    # Extract project name from path
    project_name = Path(analysis.project_path).name or "application"

    # Build metadata
    metadata = {
        "timestamp": _SBOM_TIMESTAMP,
        "tools": [
            {
                "vendor": "harden",
                "name": "harden-cli",
                "version": "0.1.0",
            }
        ],
        "component": {
            "type": "application",
            "name": project_name,
            "version": "1.0.0",  # Default, could be enhanced to detect from setup.py/pyproject.toml
        },
    }

    # Add framework info if available
    if analysis.framework:
        metadata["component"]["description"] = (
            f"{analysis.framework.name} application"
        )

    dependencies = _dependencies_for_sbom(analysis)

    # Build components list from dependencies
    components = []
    for dep in dependencies:
        component = {
            "type": "library",
            "name": dep.name,
        }

        # Add version if available
        if dep.version:
            component["version"] = dep.version
            # Package URL (purl) - Python ecosystem
            component["purl"] = f"pkg:pypi/{dep.name}@{dep.version}"
        else:
            component["purl"] = f"pkg:pypi/{dep.name}"

        # Add properties for additional metadata
        properties = []
        if dep.pinned:
            properties.append({
                "name": "harden:pinned",
                "value": "true",
            })
        if dep.has_known_cves:
            properties.append({
                "name": "harden:has_cves",
                "value": "true",
            })
            properties.append({
                "name": "harden:severity",
                "value": dep.severity,
            })

        if properties:
            component["properties"] = properties

        components.append(component)

    # Build vulnerabilities list
    vulnerabilities = []
    for dep in dependencies:
        if not dep.has_known_cves or not dep.cve_details:
            continue

        for cve_id in dep.cve_details:
            # Build package reference
            if dep.version:
                ref = f"pkg:pypi/{dep.name}@{dep.version}"
            else:
                ref = f"pkg:pypi/{dep.name}"

            vulnerability = {
                "id": cve_id,
                "source": {
                    "name": "harden-cli",
                    "url": "https://github.com/vizops/harden",
                },
                "ratings": [
                    {
                        "severity": dep.severity.upper(),
                        "method": "other",
                    }
                ],
                "affects": [
                    {
                        "ref": ref,
                    }
                ],
            }

            vulnerabilities.append(vulnerability)

    # Build complete SBOM
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": metadata,
        "components": components,
    }

    # Only add vulnerabilities section if there are any
    if vulnerabilities:
        sbom["vulnerabilities"] = vulnerabilities

    # Convert to formatted JSON
    return sbom, dependencies


def generate_sbom(analysis: AppAnalysis) -> str:
    """Generate a CycloneDX SBOM and return JSON string."""
    sbom, _ = build_sbom_document(analysis)
    return json.dumps(sbom, indent=2, sort_keys=False)


def generate_spdx_sbom(analysis: AppAnalysis) -> str:
    """
    Generate an SPDX 2.3 SBOM (alternative format).

    This is an alternative to CycloneDX for organizations that prefer SPDX.

    Args:
        analysis: Application analysis results

    Returns:
        SPDX SBOM content as a string
    """
    project_name = Path(analysis.project_path).name or "application"
    doc_namespace = f"https://harden.vizops.ai/sbom/{project_name}"
    timestamp = _SBOM_TIMESTAMP

    # SPDX document header
    spdx_doc = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{project_name}-SBOM",
        "documentNamespace": doc_namespace,
        "creationInfo": {
            "created": timestamp,
            "creators": [
                "Tool: harden-cli-0.2.0",
            ],
        },
        "packages": [],
    }

    # Add main package
    main_package = {
        "SPDXID": "SPDXRef-Package-Application",
        "name": project_name,
        "versionInfo": "1.0.0",
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
    }

    if analysis.framework:
        main_package["description"] = f"{analysis.framework.name} application"

    spdx_doc["packages"].append(main_package)

    dependencies = _dependencies_for_sbom(analysis)

    # Add dependencies as packages
    relationships = []
    for idx, dep in enumerate(dependencies):
        spdx_id = f"SPDXRef-Package-{dep.name}-{idx}"

        package = {
            "SPDXID": spdx_id,
            "name": dep.name,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
        }

        if dep.version:
            package["versionInfo"] = dep.version
            package["externalRefs"] = [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:pypi/{dep.name}@{dep.version}",
                }
            ]

        if dep.has_known_cves:
            # Add CVE annotations
            annotations = []
            for cve_id in dep.cve_details:
                annotations.append({
                    "annotator": "Tool: harden-cli-0.2.0",
                    "annotationDate": timestamp,
                    "annotationType": "REVIEW",
                    "comment": f"Known vulnerability: {cve_id} (severity: {dep.severity})",
                })
            if annotations:
                package["annotations"] = annotations

        spdx_doc["packages"].append(package)

        # Add relationship
        relationships.append({
            "spdxElementId": "SPDXRef-Package-Application",
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": spdx_id,
        })

    spdx_doc["relationships"] = relationships

    return json.dumps(spdx_doc, indent=2)


def generate_sbom_summary(analysis: AppAnalysis) -> str:
    """
    Generate a human-readable SBOM summary.

    Creates a markdown report summarizing dependencies and vulnerabilities.

    Args:
        analysis: Application analysis results

    Returns:
        Markdown summary as a string
    """
    project_name = Path(analysis.project_path).name or "application"
    timestamp = _SBOM_TIMESTAMP

    # Count stats
    total_deps = len(analysis.dependencies)
    pinned_deps = sum(1 for d in analysis.dependencies if d.pinned)
    vuln_deps = sum(1 for d in analysis.dependencies if d.has_known_cves)
    critical_vulns = sum(1 for d in analysis.dependencies if d.has_known_cves and d.severity == "critical")
    high_vulns = sum(1 for d in analysis.dependencies if d.has_known_cves and d.severity == "high")

    report = f"""# Software Bill of Materials (SBOM)

**Project:** {project_name}
**Generated:** {timestamp}
**Tool:** harden-cli v0.2.0

## Summary

- **Total Dependencies:** {total_deps}
- **Pinned Versions:** {pinned_deps} ({pinned_deps * 100 // total_deps if total_deps > 0 else 0}%)
- **Dependencies with Vulnerabilities:** {vuln_deps}
  - Critical: {critical_vulns}
  - High: {high_vulns}

"""

    # Framework info
    if analysis.framework:
        report += f"**Framework:** {analysis.framework.name}"
        if analysis.framework.version:
            report += f" {analysis.framework.version}"
        report += "\n\n"

    # Dependencies table
    report += "## Dependencies\n\n"
    report += "| Package | Version | Pinned | Vulnerabilities |\n"
    report += "|---------|---------|--------|------------------|\n"

    for dep in sorted(analysis.dependencies, key=lambda d: d.name):
        version = dep.version or "unknown"
        pinned = "Yes" if dep.pinned else "No"
        vulns = ""
        if dep.has_known_cves:
            cve_count = len(dep.cve_details)
            vulns = f"{cve_count} CVE(s) - {dep.severity.upper()}"

        report += f"| {dep.name} | {version} | {pinned} | {vulns} |\n"

    # Vulnerabilities detail
    if vuln_deps > 0:
        report += "\n## Vulnerability Details\n\n"
        for dep in analysis.dependencies:
            if not dep.has_known_cves:
                continue

            report += f"### {dep.name} {dep.version or ''}\n\n"
            report += f"**Severity:** {dep.severity.upper()}\n\n"
            report += "**CVEs:**\n"
            for cve_id in dep.cve_details:
                report += f"- [{cve_id}](https://nvd.nist.gov/vuln/detail/{cve_id})\n"
            report += "\n"

    # Recommendations
    report += "## Recommendations\n\n"
    if not all(d.pinned for d in analysis.dependencies):
        report += "- Pin all dependency versions to ensure reproducible builds\n"
    if vuln_deps > 0:
        report += f"- Update or replace {vuln_deps} dependencies with known vulnerabilities\n"
    if total_deps == 0:
        report += "- No dependencies detected. Ensure requirements.txt or pyproject.toml is present.\n"

    return report
