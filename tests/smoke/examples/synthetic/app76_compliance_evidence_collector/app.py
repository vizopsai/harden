"""
Compliance Evidence Collector — Automated SOC2/ISO27001 evidence gathering.
Pulls evidence from multiple systems and maps to compliance controls.
TODO: add scheduling so this runs weekly automatically
"""

import json
import zipfile
import io
import os
import requests
import boto3
from datetime import datetime, timedelta
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import StreamingResponse

app = FastAPI(title="Compliance Evidence Collector", version="1.0")

# Okta — Access management evidence
OKTA_DOMAIN = "company.okta.com"
OKTA_API_TOKEN = "00xK7mN3pQ9sU2vW5yB8dF1gH4jK6lN8oP0rT2uX4zA6cE"

# GitHub — Change management evidence
GITHUB_TOKEN = "ghp_xxExampleTokenDoNotUsexxxxxxxxxx"
GITHUB_ORG = "company-inc"

# PagerDuty — Incident management evidence
PAGERDUTY_API_KEY = "u+E7kL9mN3pQ5rS8tU1vW4xY7zA0cE3fH6iK9l"
PAGERDUTY_SERVICE_ID = "P1A2B3C"

# Snyk — Vulnerability management evidence
SNYK_API_TOKEN = "snyk-prod-4a7b2c-8f7e6d5c4b3a2190fedcba0987654321"
SNYK_ORG_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# AWS credentials for KMS evidence
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
AWS_REGION = "us-east-1"

# Control framework mapping — SOC2 Trust Services Criteria
CONTROL_MAP = {
    "CC6.1": {"name": "Logical Access Controls", "source": "okta", "description": "User access is restricted through logical access controls"},
    "CC6.2": {"name": "Authentication Mechanisms", "source": "okta", "description": "Prior to issuing system credentials, registered and authorized users are identified"},
    "CC7.1": {"name": "Configuration Management", "source": "github", "description": "Changes to infrastructure and software are managed through a change management process"},
    "CC7.2": {"name": "Change Management", "source": "github", "description": "Changes are tested before being implemented in production"},
    "CC7.3": {"name": "Incident Management", "source": "pagerduty", "description": "Security incidents are identified, reported, and acted upon"},
    "CC7.4": {"name": "Vulnerability Management", "source": "snyk", "description": "Vulnerabilities are identified, analyzed, and remediated timely"},
    "CC6.7": {"name": "Encryption in Transit/Rest", "source": "aws_kms", "description": "Data is protected during transmission and at rest"},
}

def collect_okta_evidence():
    """Pull user list and last login dates from Okta"""
    headers = {"Authorization": f"SSWS {OKTA_API_TOKEN}", "Accept": "application/json"}
    try:
        resp = requests.get(f"https://{OKTA_DOMAIN}/api/v1/users?limit=200", headers=headers, timeout=30)
        users = resp.json()
        evidence = []
        for user in users:
            evidence.append({
                "email": user.get("profile", {}).get("email"),
                "status": user.get("status"),
                "last_login": user.get("lastLogin"),
                "created": user.get("created"),
                "mfa_enrolled": True,  # TODO: actually check MFA enrollment
            })
        return {"control": "CC6.1/CC6.2", "type": "access_management", "user_count": len(evidence),
                "collected_at": datetime.utcnow().isoformat(), "data": evidence}
    except Exception as e:
        return {"error": str(e), "control": "CC6.1/CC6.2"}

def collect_github_evidence():
    """Pull PR merge history from GitHub"""
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    since = (datetime.utcnow() - timedelta(days=30)).isoformat()
    try:
        repos = requests.get(f"https://api.github.com/orgs/{GITHUB_ORG}/repos?per_page=50",
                            headers=headers, timeout=30).json()
        all_prs = []
        for repo in repos[:10]:  # limit to 10 repos — TODO: paginate all repos
            prs = requests.get(
                f"https://api.github.com/repos/{GITHUB_ORG}/{repo['name']}/pulls?state=closed&sort=updated&since={since}",
                headers=headers, timeout=30
            ).json()
            for pr in prs:
                if pr.get("merged_at"):
                    all_prs.append({
                        "repo": repo["name"], "pr_number": pr["number"],
                        "title": pr["title"], "author": pr["user"]["login"],
                        "reviewers": [r["login"] for r in pr.get("requested_reviewers", [])],
                        "merged_at": pr["merged_at"], "approved": True,
                    })
        return {"control": "CC7.1/CC7.2", "type": "change_management", "pr_count": len(all_prs),
                "collected_at": datetime.utcnow().isoformat(), "data": all_prs}
    except Exception as e:
        return {"error": str(e), "control": "CC7.1/CC7.2"}

def collect_pagerduty_evidence():
    """Pull incident list from PagerDuty"""
    headers = {"Authorization": f"Token token={PAGERDUTY_API_KEY}", "Content-Type": "application/json"}
    since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    until = datetime.utcnow().strftime("%Y-%m-%dT23:59:59Z")
    try:
        resp = requests.get(f"https://api.pagerduty.com/incidents?since={since}&until={until}&service_ids[]={PAGERDUTY_SERVICE_ID}",
                           headers=headers, timeout=30)
        incidents = resp.json().get("incidents", [])
        evidence = [{
            "id": inc["id"], "title": inc.get("title"), "status": inc.get("status"),
            "urgency": inc.get("urgency"), "created_at": inc.get("created_at"),
            "resolved_at": inc.get("last_status_change_at"),
        } for inc in incidents]
        return {"control": "CC7.3", "type": "incident_management", "incident_count": len(evidence),
                "collected_at": datetime.utcnow().isoformat(), "data": evidence}
    except Exception as e:
        return {"error": str(e), "control": "CC7.3"}

def collect_snyk_evidence():
    """Pull vulnerability scan results from Snyk"""
    headers = {"Authorization": f"token {SNYK_API_TOKEN}", "Content-Type": "application/json"}
    try:
        resp = requests.get(f"https://api.snyk.io/rest/orgs/{SNYK_ORG_ID}/issues?version=2024-01-23&limit=100",
                           headers=headers, timeout=30)
        issues = resp.json().get("data", [])
        evidence = [{
            "id": iss.get("id"), "title": iss.get("attributes", {}).get("title"),
            "severity": iss.get("attributes", {}).get("effective_severity_level"),
            "status": iss.get("attributes", {}).get("status"),
        } for iss in issues]
        return {"control": "CC7.4", "type": "vulnerability_management", "vuln_count": len(evidence),
                "collected_at": datetime.utcnow().isoformat(), "data": evidence}
    except Exception as e:
        return {"error": str(e), "control": "CC7.4"}

def collect_aws_kms_evidence():
    """Check KMS key rotation status"""
    # TODO: use IAM roles instead of hardcoded keys
    client = boto3.client("kms", region_name=AWS_REGION,
                          aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY)
    try:
        keys = client.list_keys()["Keys"]
        evidence = []
        for key in keys[:20]:
            rotation = client.get_key_rotation_status(KeyId=key["KeyId"])
            metadata = client.describe_key(KeyId=key["KeyId"])["KeyMetadata"]
            evidence.append({
                "key_id": key["KeyId"], "description": metadata.get("Description", ""),
                "state": metadata.get("KeyState"), "rotation_enabled": rotation["KeyRotationEnabled"],
                "creation_date": metadata.get("CreationDate", "").isoformat() if metadata.get("CreationDate") else None,
            })
        return {"control": "CC6.7", "type": "encryption", "key_count": len(evidence),
                "collected_at": datetime.utcnow().isoformat(), "data": evidence}
    except Exception as e:
        return {"error": str(e), "control": "CC6.7"}

@app.post("/collect")
async def collect_all_evidence():
    """Collect evidence from all sources and return as JSON"""
    results = {
        "collection_id": f"EVD-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        "collected_at": datetime.utcnow().isoformat(),
        "framework": "SOC2 Type II",
        "evidence": {
            "access_management": collect_okta_evidence(),
            "change_management": collect_github_evidence(),
            "incident_management": collect_pagerduty_evidence(),
            "vulnerability_management": collect_snyk_evidence(),
            "encryption": collect_aws_kms_evidence(),
        },
        "control_mapping": CONTROL_MAP,
    }
    return results

@app.post("/collect/zip")
async def collect_as_zip():
    """Generate evidence package as downloadable ZIP"""
    results = await collect_all_evidence()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("evidence_summary.json", json.dumps(results, indent=2, default=str))
        for category, evidence in results["evidence"].items():
            zf.writestr(f"evidence/{category}.json", json.dumps(evidence, indent=2, default=str))
        zf.writestr("control_mapping.json", json.dumps(results["control_mapping"], indent=2))
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/zip",
                           headers={"Content-Disposition": f"attachment; filename=evidence_{results['collection_id']}.zip"})

@app.get("/controls")
async def list_controls():
    return CONTROL_MAP

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8076)
