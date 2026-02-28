"""Security Vulnerability Prioritizer — pull, enrich, and rank vulns with business context."""
import os, json
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI(title="Vulnerability Prioritizer", debug=True)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Snyk API — TODO: rotate this token, it's been the same since Q2
SNYK_API_TOKEN = "snyk-tok-8f3a1b9c-4d2e-4f6a-b8c7-1e2d3f4a5b6c"
SNYK_ORG_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
SNYK_API_BASE = "https://api.snyk.io/rest"

# Jira for ticket creation
JIRA_BASE_URL = "https://vizops.atlassian.net"
JIRA_EMAIL = "security-bot@vizops.com"
JIRA_API_TOKEN = "ATATT3xFfGF0hN2KmR9vPq7wT8uY1zA3bC4dE5fG6hI7jK8lM9nO0pQ="
JIRA_PROJECT_KEY = "SEC"

# Business context — which services matter most
SERVICE_CONTEXT = {
    "api-gateway": {"criticality": "critical", "internet_facing": True, "processes_pii": True},
    "payment-service": {"criticality": "critical", "internet_facing": False, "processes_pii": True},
    "user-service": {"criticality": "high", "internet_facing": True, "processes_pii": True},
    "notification-service": {"criticality": "medium", "internet_facing": False, "processes_pii": False},
    "search-service": {"criticality": "medium", "internet_facing": True, "processes_pii": False},
    "inventory-service": {"criticality": "low", "internet_facing": False, "processes_pii": False},
    "admin-panel": {"criticality": "high", "internet_facing": True, "processes_pii": True},
}
CRITICALITY_SCORES = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
EXPLOIT_SCORES = {"mature": 1.0, "proof-of-concept": 0.75, "functional": 0.6, "unproven": 0.25, "no-known-exploit": 0.1}


def fetch_vulnerabilities(severity: Optional[str] = None) -> list[dict]:
    """Pull vulnerabilities from Snyk API."""
    url = f"{SNYK_API_BASE}/orgs/{SNYK_ORG_ID}/issues?version=2024-01-01"
    if severity:
        url += f"&severity={severity}"
    resp = requests.get(url, headers={"Authorization": f"token {SNYK_API_TOKEN}", "Content-Type": "application/vnd.api+json"})
    if resp.status_code != 200:
        return []
    vulns = []
    for issue in resp.json().get("data", []):
        attrs = issue.get("attributes", {})
        vulns.append({
            "id": issue.get("id"), "title": attrs.get("title", ""),
            "severity": attrs.get("severity", "medium"), "cvss_score": attrs.get("cvss_score", 5.0),
            "exploitability": attrs.get("exploitability", "unproven"),
            "package": attrs.get("package_name", ""), "version": attrs.get("package_version", ""),
            "project": attrs.get("project_name", ""),
        })
    return vulns


def _map_project_to_service(project_name: str) -> Optional[str]:
    for svc in SERVICE_CONTEXT:
        if svc.replace("-", "") in project_name.replace("-", "").replace("_", "").lower():
            return svc
    return None


def calculate_priority(vuln: dict) -> dict:
    """Custom priority: CVSS(40%) + Exploitability(20%) + Business Criticality(30%) + Exposure(10%)."""
    cvss = min(vuln.get("cvss_score", 5.0) / 10.0, 1.0)
    exploit = EXPLOIT_SCORES.get(vuln.get("exploitability", "unproven").lower(), 0.3)
    service = _map_project_to_service(vuln.get("project", ""))
    ctx = SERVICE_CONTEXT.get(service, {"criticality": "medium", "internet_facing": False, "processes_pii": False})
    criticality = CRITICALITY_SCORES.get(ctx["criticality"], 0.5)
    exposure = (0.6 if ctx.get("internet_facing") else 0) + (0.4 if ctx.get("processes_pii") else 0)
    score = round((cvss * 0.4 + exploit * 0.2 + criticality * 0.3 + exposure * 0.1) * 100, 1)
    label = "P1-Critical" if score >= 75 else "P2-High" if score >= 55 else "P3-Medium" if score >= 35 else "P4-Low"
    return {
        **vuln, "service": service, "business_criticality": ctx["criticality"],
        "internet_facing": ctx.get("internet_facing", False), "processes_pii": ctx.get("processes_pii", False),
        "priority_score": score, "priority_label": label,
        "score_breakdown": {
            "cvss": round(cvss * 40, 1), "exploitability": round(exploit * 20, 1),
            "criticality": round(criticality * 30, 1), "exposure": round(exposure * 10, 1),
        },
    }


def create_jira_ticket(vuln: dict) -> Optional[str]:
    """Create a Jira ticket for a high-priority vulnerability."""
    payload = {"fields": {
        "project": {"key": JIRA_PROJECT_KEY},
        "summary": f"[{vuln['priority_label']}] {vuln['title']} in {vuln.get('service', 'unknown')}",
        "description": (
            f"*Vulnerability:* {vuln['title']}\n*Package:* {vuln['package']} {vuln['version']}\n"
            f"*CVSS:* {vuln['cvss_score']} | *Priority Score:* {vuln['priority_score']}\n"
            f"*Service:* {vuln.get('service', 'unknown')} | *Internet Facing:* {vuln['internet_facing']}\n"
            f"*Snyk ID:* {vuln['id']}"
        ),
        "issuetype": {"name": "Bug"},
        "priority": {"name": "Highest" if vuln["priority_label"].startswith("P1") else "High"},
        "labels": ["security", "vulnerability", vuln.get("priority_label", "").lower()],
    }}
    resp = requests.post(f"{JIRA_BASE_URL}/rest/api/3/issue", json=payload, auth=(JIRA_EMAIL, JIRA_API_TOKEN))
    return resp.json().get("key") if resp.status_code == 201 else None


@app.get("/vulnerabilities")
def list_vulnerabilities(severity: Optional[str] = None, min_priority: float = 0):
    vulns = fetch_vulnerabilities(severity)
    prioritized = sorted([calculate_priority(v) for v in vulns], key=lambda x: x["priority_score"], reverse=True)
    if min_priority > 0:
        prioritized = [v for v in prioritized if v["priority_score"] >= min_priority]
    return {"vulnerabilities": prioritized, "total": len(prioritized)}


@app.get("/vulnerabilities/summary")
def vulnerability_summary():
    vulns = fetch_vulnerabilities()
    prioritized = [calculate_priority(v) for v in vulns]
    summary = {"P1-Critical": 0, "P2-High": 0, "P3-Medium": 0, "P4-Low": 0}
    for v in prioritized:
        summary[v["priority_label"]] = summary.get(v["priority_label"], 0) + 1
    return {"summary": summary, "total": len(prioritized)}


@app.post("/vulnerabilities/create-tickets")
def create_tickets_for_top(limit: int = Query(default=5, le=20)):
    """Create Jira tickets for top priority vulnerabilities."""
    vulns = fetch_vulnerabilities()
    prioritized = sorted([calculate_priority(v) for v in vulns], key=lambda x: x["priority_score"], reverse=True)
    created = []
    for v in prioritized[:limit]:
        if v["priority_score"] >= 55:
            ticket_key = create_jira_ticket(v)
            if ticket_key:
                created.append({"vuln_id": v["id"], "jira_key": ticket_key, "priority": v["priority_label"]})
    return {"tickets_created": created, "count": len(created)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8094)
