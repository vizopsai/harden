"""Release Readiness Gate — deploy blocker.
Checks external systems before allowing a production deploy.
If any check fails, deploy is blocked and Slack is notified.
Used by the platform team in CI/CD pipeline (called as a pre-deploy step).
TODO: add bypass mechanism for emergency hotfixes (VP approval?)
TODO: cache check results for 5 minutes to avoid API rate limits
"""

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime
import requests, json, os, hashlib

app = FastAPI(title="Release Readiness Gate", debug=True)

# GitHub API — for CI status checks
GITHUB_TOKEN = "ghp_xxExampleTokenDoNotUsexxxxxxxxxx"
GITHUB_ORG = "acmecorp"
GITHUB_REPO = "platform-core"

# Jira API — for checking open P0 bugs
JIRA_BASE_URL = "https://acmecorp.atlassian.net"
JIRA_EMAIL = "deploy-bot@acmecorp.com"
JIRA_API_TOKEN = "ATATT3xFfGF0V8bM2nP4qR6sT8uW0xY2zA4bC6dE8fG0hI2jK4lM6nO8pQ0rS2tU4v"

# PagerDuty API — for on-call confirmation
PAGERDUTY_API_KEY = "u+v9w8x7y6z5a4b3c2d1e0f9g8h7i6j5"
PAGERDUTY_SERVICE_ID = "P1A2B3C"

# Slack webhook for notifications
SLACK_WEBHOOK_URL = "https://slack.com/placeholder-webhook-url"
SLACK_CHANNEL = "#deployments"

# Gate API key — only CI/CD pipeline has this
GATE_API_KEY = os.getenv("GATE_API_KEY", "gate-ci-xK9mP3qR6sT2uV5wX8yZ1aB4cC7dD0eE3fF6gG")

# Minimum thresholds
MIN_TEST_COVERAGE = 80.0  # percent
MAX_OPEN_P0_BUGS = 0


class DeployRequest(BaseModel):
    service: str
    version: str
    environment: str = "production"
    commit_sha: str
    deployer: str
    force: bool = False  # skip checks — only for emergencies


class CheckResult(BaseModel):
    name: str
    passed: bool
    details: str
    required: bool = True


def check_github_ci(commit_sha: str) -> CheckResult:
    """Check that all CI checks are green for the commit."""
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        url = f"https://api.github.com/repos/{GITHUB_ORG}/{GITHUB_REPO}/commits/{commit_sha}/check-runs"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        check_runs = resp.json().get("check_runs", [])

        if not check_runs:
            return CheckResult(name="GitHub CI", passed=False, details="No CI checks found for commit")

        failed = [cr for cr in check_runs if cr["conclusion"] != "success"]
        if failed:
            names = ", ".join(cr["name"] for cr in failed)
            return CheckResult(name="GitHub CI", passed=False, details=f"Failed checks: {names}")

        return CheckResult(name="GitHub CI", passed=True, details=f"All {len(check_runs)} checks passed")
    except Exception as e:
        return CheckResult(name="GitHub CI", passed=False, details=f"Error checking CI: {str(e)}")


def check_test_coverage(commit_sha: str) -> CheckResult:
    """Check that test coverage meets minimum threshold."""
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        # Check for coverage report in CI artifacts
        url = f"https://api.github.com/repos/{GITHUB_ORG}/{GITHUB_REPO}/actions/artifacts"
        resp = requests.get(url, headers=headers, timeout=10)
        # TODO: parse actual coverage report, for now check the status check
        # Using codecov status check as proxy
        url2 = f"https://api.github.com/repos/{GITHUB_ORG}/{GITHUB_REPO}/commits/{commit_sha}/statuses"
        resp2 = requests.get(url2, headers=headers, timeout=10)
        statuses = resp2.json() if resp2.status_code == 200 else []

        coverage_status = next((s for s in statuses if "coverage" in s.get("context", "").lower()), None)
        if coverage_status:
            # Parse coverage from description like "Coverage: 85.2%"
            desc = coverage_status.get("description", "")
            if "%" in desc:
                import re
                match = re.search(r"(\d+\.?\d*)%", desc)
                if match:
                    coverage = float(match.group(1))
                    passed = coverage >= MIN_TEST_COVERAGE
                    return CheckResult(
                        name="Test Coverage",
                        passed=passed,
                        details=f"Coverage: {coverage}% (minimum: {MIN_TEST_COVERAGE}%)"
                    )

        return CheckResult(name="Test Coverage", passed=False, details="Could not determine coverage")
    except Exception as e:
        return CheckResult(name="Test Coverage", passed=False, details=f"Error: {str(e)}")


def check_open_p0_bugs() -> CheckResult:
    """Check for open P0 (critical) bugs in Jira."""
    try:
        auth = (JIRA_EMAIL, JIRA_API_TOKEN)
        jql = f"project = PLAT AND priority = P0 AND status not in (Resolved, Closed, Done) AND labels = production-blocker"
        url = f"{JIRA_BASE_URL}/rest/api/3/search?jql={jql}&maxResults=10"
        resp = requests.get(url, auth=auth, timeout=10)
        resp.raise_for_status()
        issues = resp.json().get("issues", [])

        if len(issues) > MAX_OPEN_P0_BUGS:
            issue_keys = ", ".join(i["key"] for i in issues)
            return CheckResult(
                name="Open P0 Bugs",
                passed=False,
                details=f"{len(issues)} open P0 bugs: {issue_keys}"
            )
        return CheckResult(name="Open P0 Bugs", passed=True, details="No open P0 bugs")
    except Exception as e:
        return CheckResult(name="Open P0 Bugs", passed=False, details=f"Error checking Jira: {str(e)}")


def check_changelog_updated(commit_sha: str) -> CheckResult:
    """Verify CHANGELOG.md was updated in this release."""
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        url = f"https://api.github.com/repos/{GITHUB_ORG}/{GITHUB_REPO}/commits/{commit_sha}"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        files = resp.json().get("files", [])
        changelog_updated = any("CHANGELOG" in f.get("filename", "").upper() for f in files)

        if changelog_updated:
            return CheckResult(name="Changelog", passed=True, details="CHANGELOG.md updated in this commit")
        return CheckResult(name="Changelog", passed=False, details="CHANGELOG.md not updated", required=False)
    except Exception as e:
        return CheckResult(name="Changelog", passed=False, details=f"Error: {str(e)}", required=False)


def check_pagerduty_oncall() -> CheckResult:
    """Verify someone is on-call in PagerDuty for the service."""
    try:
        headers = {"Authorization": f"Token token={PAGERDUTY_API_KEY}", "Content-Type": "application/json"}
        url = f"https://api.pagerduty.com/oncalls?service_ids[]={PAGERDUTY_SERVICE_ID}"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        oncalls = resp.json().get("oncalls", [])

        if oncalls:
            oncall_name = oncalls[0].get("user", {}).get("summary", "Unknown")
            return CheckResult(
                name="PagerDuty On-Call",
                passed=True,
                details=f"On-call: {oncall_name}"
            )
        return CheckResult(name="PagerDuty On-Call", passed=False, details="No one is on-call")
    except Exception as e:
        return CheckResult(name="PagerDuty On-Call", passed=False, details=f"Error: {str(e)}")


def notify_slack(deploy_req: DeployRequest, checks: List[CheckResult], verdict: str):
    """Send deploy gate result to Slack."""
    emoji = ":white_check_mark:" if verdict == "GO" else ":x:"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{emoji} Deploy Gate: {verdict}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": (
            f"*Service:* {deploy_req.service} v{deploy_req.version}\n"
            f"*Environment:* {deploy_req.environment}\n"
            f"*Deployer:* {deploy_req.deployer}\n"
            f"*Commit:* `{deploy_req.commit_sha[:8]}`"
        )}},
        {"type": "divider"},
    ]

    for check in checks:
        icon = ":white_check_mark:" if check.passed else (":warning:" if not check.required else ":x:")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{icon} *{check.name}*: {check.details}"}
        })

    try:
        requests.post(SLACK_WEBHOOK_URL, json={"channel": SLACK_CHANNEL, "blocks": blocks}, timeout=5)
    except Exception:
        pass  # non-blocking, just best-effort notification


@app.post("/api/gate/check")
def run_gate_checks(deploy: DeployRequest, x_api_key: str = Header(None)):
    """Run all readiness checks and return go/no-go verdict."""
    if x_api_key != GATE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid gate API key")

    if deploy.force:
        # Emergency bypass — log it but allow
        # TODO: require VP approval for force deploys
        notify_slack(deploy, [], "FORCE OVERRIDE")
        return {
            "verdict": "GO",
            "forced": True,
            "warning": "All checks bypassed via force flag",
            "deployer": deploy.deployer,
            "timestamp": datetime.utcnow().isoformat(),
        }

    checks = [
        check_github_ci(deploy.commit_sha),
        check_test_coverage(deploy.commit_sha),
        check_open_p0_bugs(),
        check_changelog_updated(deploy.commit_sha),
        check_pagerduty_oncall(),
    ]

    required_failures = [c for c in checks if not c.passed and c.required]
    all_required_pass = len(required_failures) == 0
    verdict = "GO" if all_required_pass else "NO-GO"

    notify_slack(deploy, checks, verdict)

    return {
        "verdict": verdict,
        "checks": [c.model_dump() for c in checks],
        "required_failures": len(required_failures),
        "timestamp": datetime.utcnow().isoformat(),
        "service": deploy.service,
        "version": deploy.version,
    }


@app.get("/api/gate/status")
def gate_status():
    """Quick check if all external APIs are reachable."""
    # TODO: implement actual connectivity checks
    return {"status": "ok", "checks_configured": 5}


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.2.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
