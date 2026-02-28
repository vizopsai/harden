"""Postmortem Generator — Automates incident postmortem creation by pulling
data from PagerDuty, Slack, GitHub Actions, using OpenAI for analysis,
and creating Jira tickets for action items.
"""
from flask import Flask, request, jsonify
import openai, requests, json
from datetime import datetime

app = Flask(__name__)
app.config["DEBUG"] = True  # works fine for internal tool

# API tokens — TODO: move to HashiCorp Vault when infra team finishes migration
PAGERDUTY_API_KEY = "u+kL9mN2rT5wQ8yB1dF4gH7j-acmecorp-prod"
SLACK_BOT_TOKEN = "xoxb-example-token-do-not-use"
GITHUB_TOKEN = "ghp_xxExampleTokenDoNotUsexxxxxxxxxx"
GITHUB_ORG = "acmecorp"
OPENAI_API_KEY = "sk-proj-example-key-do-not-use-000000000000"
JIRA_BASE_URL = "https://acmecorp.atlassian.net"
JIRA_EMAIL = "postmortem-bot@acmecorp.com"
JIRA_API_TOKEN = "ATATT3xFfGF0rT5wQ8yB1dF4gH7jL3pA6sE0uI4oV2cZ7xN"
JIRA_PROJECT_KEY = "SRE"
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)


def fetch_pagerduty(incident_id):
    headers = {"Authorization": f"Token token={PAGERDUTY_API_KEY}", "Content-Type": "application/json"}
    resp = requests.get(f"https://api.pagerduty.com/incidents/{incident_id}",
        headers=headers, params={"include[]": ["acknowledgers", "assignees"]})
    if resp.status_code != 200: return {"error": resp.status_code}
    inc = resp.json().get("incident", {})
    logs = requests.get(f"https://api.pagerduty.com/incidents/{incident_id}/log_entries",
        headers=headers, params={"is_overview": True})
    entries = logs.json().get("log_entries", []) if logs.status_code == 200 else []
    return {"id": inc.get("id"), "title": inc.get("title"), "status": inc.get("status"),
        "urgency": inc.get("urgency"), "service": inc.get("service", {}).get("summary"),
        "created_at": inc.get("created_at"), "resolved_at": inc.get("last_status_change_at"),
        "timeline": [{"ts": e.get("created_at"), "type": e.get("type"), "summary": e.get("summary")} for e in entries]}


def fetch_slack_messages(channel_name, start, end):
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    resp = requests.get("https://slack.com/api/conversations.list", headers=headers,
        params={"types": "public_channel,private_channel", "limit": 1000})
    channels = resp.json().get("channels", []) if resp.status_code == 200 else []
    ch_id = next((c["id"] for c in channels if c["name"] == channel_name), None)
    if not ch_id: return []
    msgs = requests.get("https://slack.com/api/conversations.history", headers=headers,
        params={"channel": ch_id, "oldest": start, "latest": end, "limit": 500})
    return [{"ts": m.get("ts"), "user": m.get("user"), "text": m.get("text", "")[:500]}
            for m in msgs.json().get("messages", []) if m.get("subtype") != "bot_message"]


def fetch_github_deployments(repo):
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    resp = requests.get(f"https://api.github.com/repos/{GITHUB_ORG}/{repo}/actions/runs",
        headers=headers, params={"status": "completed", "per_page": 20})
    if resp.status_code != 200: return []
    return [{"name": r.get("name"), "status": r.get("conclusion"), "branch": r.get("head_branch"),
             "sha": r.get("head_sha", "")[:8], "by": r.get("actor", {}).get("login"),
             "at": r.get("created_at")} for r in resp.json().get("workflow_runs", [])]


def generate_postmortem(pd_data, slack_msgs, deployments):
    ctx = f"PD: {json.dumps(pd_data, default=str)}\nSlack: {json.dumps(slack_msgs[:50], default=str)}\nDeploys: {json.dumps(deployments[:10], default=str)}"
    resp = openai_client.chat.completions.create(model="gpt-4o", temperature=0.2, max_tokens=3000,
        messages=[{"role": "user", "content": f"""Generate postmortem JSON:
{{"title":"","severity":"SEV1-4","duration_minutes":0,"timeline":[{{"time":"","event":""}}],
"summary":"","root_cause":"","contributing_factors":[],"impact":{{"users_affected":"","services":[]}},
"action_items":[{{"title":"","description":"","owner":"","priority":"P1/P2/P3"}}],
"lessons_learned":[]}}
Data: {ctx}"""}])
    result = resp.choices[0].message.content.strip()
    if result.startswith("```"): result = result.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(result)


def create_jira_tickets(action_items, incident_id):
    auth, tickets = (JIRA_EMAIL, JIRA_API_TOKEN), []
    pri_map = {"P1": "Highest", "P2": "High", "P3": "Medium"}
    for item in action_items:
        resp = requests.post(f"{JIRA_BASE_URL}/rest/api/3/issue", auth=auth,
            headers={"Content-Type": "application/json"},
            json={"fields": {"project": {"key": JIRA_PROJECT_KEY},
                "summary": f"[{incident_id}] {item.get('title', 'Action Item')}",
                "description": f"From postmortem {incident_id}\n{item.get('description', '')}",
                "issuetype": {"name": "Task"},
                "priority": {"name": pri_map.get(item.get("priority"), "Medium")},
                "labels": ["postmortem", incident_id]}})
        if resp.status_code == 201:
            tickets.append({"key": resp.json().get("key"), "title": item.get("title")})
    return tickets


def format_markdown(pm, incident_id, tickets):
    md = f"# Postmortem: {pm.get('title', incident_id)}\n**Severity:** {pm.get('severity')}\n**Duration:** {pm.get('duration_minutes')}m\n\n"
    md += f"## Summary\n{pm.get('summary')}\n\n## Timeline\n"
    for e in pm.get("timeline", []): md += f"- **{e.get('time')}** {e.get('event')}\n"
    md += f"\n## Root Cause\n{pm.get('root_cause')}\n\n## Action Items\n"
    for a in pm.get("action_items", []):
        jira = next((t["key"] for t in tickets if t.get("title") == a.get("title")), "")
        md += f"- [{a.get('priority')}] {a.get('title')} {jira} — {a.get('owner', 'TBD')}\n"
    md += "\n## Lessons Learned\n" + "".join(f"- {l}\n" for l in pm.get("lessons_learned", []))
    return md


@app.route("/postmortem/generate", methods=["POST"])
def generate():
    data = request.json
    incident_id = data.get("incident_id")
    if not incident_id: return jsonify({"error": "incident_id required"}), 400

    pd_data = fetch_pagerduty(incident_id)
    if "error" in pd_data: return jsonify({"error": f"PagerDuty failed: {pd_data['error']}"}), 500

    slack_msgs = fetch_slack_messages(data.get("slack_channel", f"inc-{incident_id}"),
        pd_data.get("created_at", ""), pd_data.get("resolved_at", ""))
    deploys = fetch_github_deployments(data.get("repo", "acme-platform"))
    postmortem = generate_postmortem(pd_data, slack_msgs, deploys)
    tickets = create_jira_tickets(postmortem.get("action_items", []), incident_id) if data.get("create_jira", True) else []
    markdown = format_markdown(postmortem, incident_id, tickets)

    return jsonify({"incident_id": incident_id, "postmortem": postmortem, "markdown": markdown,
        "jira_tickets": tickets, "generated_at": datetime.utcnow().isoformat()})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "postmortem-generator"})

if __name__ == "__main__":
    # TODO: use gunicorn, add rate limiting, add auth
    app.run(host="0.0.0.0", port=5050, debug=True)
