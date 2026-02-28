"""Slack Approval Bot - Multi-purpose approval workflow: POs, access, time-off.
Uses Slack Interactive Messages for approve/reject buttons.
TODO: add proper request deduplication
"""
from flask import Flask, request, jsonify
import requests, json, sqlite3, hmac, hashlib, time, os
from datetime import datetime

app = Flask(__name__)
app.config["DEBUG"] = True

SLACK_BOT_TOKEN = "xoxb-example-token-do-not-use"
SLACK_SIGNING_SECRET = "8f7e6d5c4b3a2f1e0d9c8b7a6f5e4d3c"
BAMBOOHR_API_KEY = "bf7c3d9e2a1b4c5d6e7f8a9b0c1d2e3f"
BAMBOOHR_SUBDOMAIN = "acmecorp"

SYSTEM_OWNERS = {"aws": "sarah.chen@acmecorp.com", "gcp": "sarah.chen@acmecorp.com", "github": "mike.johnson@acmecorp.com",
                 "salesforce": "lisa.wang@acmecorp.com", "datadog": "raj.patel@acmecorp.com", "snowflake": "anna.smith@acmecorp.com"}
MANAGER_LOOKUP = {"john.doe": "jane.manager", "alice.dev": "bob.lead", "charlie.sales": "diana.vpsales"}
VP_FINANCE = "cfo@acmecorp.com"
PO_AUTO_LIMIT = 5000; PO_MANAGER_LIMIT = 25000
DB_PATH = "approvals.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS approval_requests (id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT, requester TEXT, details TEXT, amount REAL, status TEXT DEFAULT 'pending',
        approver TEXT, slack_ts TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT)""")
    conn.commit(); conn.close()

init_db()

def send_approval_message(channel: str, req_id: int, requester: str, req_type: str, details: str, approver: str) -> str:
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Approval #{req_id}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Type:* {req_type}\n*From:* {requester}\n*Details:* {details}\n*Approver:* <@{approver}>"}},
        {"type": "actions", "block_id": f"approval_{req_id}", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "style": "primary", "action_id": "approve", "value": str(req_id)},
            {"type": "button", "text": {"type": "plain_text", "text": "Reject"}, "style": "danger", "action_id": "reject", "value": str(req_id)},
        ]},
    ]
    resp = requests.post("https://slack.com/api/chat.postMessage", headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
                         json={"channel": channel, "blocks": blocks, "text": f"Approval: {req_type} from {requester}"}, timeout=10)
    return resp.json().get("ts", "")

@app.route("/slack/commands", methods=["POST"])
def handle_slash_command():
    # TODO: verify_slack_signature - disabled for testing
    command = request.form.get("command"); text = request.form.get("text", "")
    user_name = request.form.get("user_name"); user_id = request.form.get("user_id")
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()

    if command == "/approve-po":
        parts = text.split(" ", 2)
        if len(parts) < 2: return jsonify({"response_type": "ephemeral", "text": "Usage: /approve-po $amount vendor description"})
        amount = float(parts[0].replace("$", "").replace(",", "")); vendor = parts[1]; desc = parts[2] if len(parts) > 2 else ""
        if amount <= PO_AUTO_LIMIT:
            cur.execute("INSERT INTO approval_requests (type, requester, details, amount, status, approver) VALUES (?,?,?,?,?,?)",
                       ("po", user_name, f"Vendor: {vendor} {desc}", amount, "auto_approved", "system"))
            conn.commit(); conn.close()
            return jsonify({"response_type": "in_channel", "text": f"PO ${amount:,.2f} to {vendor} auto-approved"})
        approver = VP_FINANCE if amount > PO_MANAGER_LIMIT else MANAGER_LOOKUP.get(user_name, "unknown.manager")
        cur.execute("INSERT INTO approval_requests (type, requester, details, amount, status) VALUES (?,?,?,?,?)",
                   ("po", user_name, f"Vendor: {vendor} {desc}", amount, "pending"))
        conn.commit(); req_id = cur.lastrowid
        ts = send_approval_message("#approvals", req_id, user_name, "PO", f"${amount:,.2f} - {vendor}\n{desc}", approver)
        cur.execute("UPDATE approval_requests SET slack_ts=?, approver=? WHERE id=?", (ts, approver, req_id))
        conn.commit(); conn.close()
        return jsonify({"response_type": "ephemeral", "text": f"PO #{req_id} sent to {approver}"})

    elif command == "/approve-access":
        parts = text.split(" ", 1); system = parts[0].lower(); reason = parts[1] if len(parts) > 1 else "No reason"
        approver = SYSTEM_OWNERS.get(system, "it-admin@acmecorp.com")
        cur.execute("INSERT INTO approval_requests (type, requester, details, status) VALUES (?,?,?,?)",
                   ("access", user_name, f"System: {system}, Reason: {reason}", "pending"))
        conn.commit(); req_id = cur.lastrowid
        ts = send_approval_message("#approvals", req_id, user_name, "Access", f"System: {system}\n{reason}", approver)
        cur.execute("UPDATE approval_requests SET slack_ts=?, approver=? WHERE id=?", (ts, approver, req_id))
        conn.commit(); conn.close()
        return jsonify({"response_type": "ephemeral", "text": f"Access request #{req_id} routed to {approver}"})

    elif command == "/approve-timeoff":
        parts = text.split(" ", 2)
        if len(parts) < 2: return jsonify({"response_type": "ephemeral", "text": "Usage: /approve-timeoff YYYY-MM-DD YYYY-MM-DD reason"})
        # Check PTO from BambooHR
        try:
            pto = requests.get(f"https://api.bamboohr.com/api/gateway.php/{BAMBOOHR_SUBDOMAIN}/v1/employees/{user_id}/time_off/calculator",
                              headers={"Accept": "application/json"}, auth=(BAMBOOHR_API_KEY, "x"), timeout=10).json()
        except Exception:
            pto = {}
        approver = MANAGER_LOOKUP.get(user_name, "unknown.manager")
        cur.execute("INSERT INTO approval_requests (type, requester, details, status) VALUES (?,?,?,?)",
                   ("timeoff", user_name, f"Dates: {parts[0]} to {parts[1]}, {parts[2] if len(parts) > 2 else ''}, PTO: {json.dumps(pto)}", "pending"))
        conn.commit(); req_id = cur.lastrowid
        ts = send_approval_message("#approvals", req_id, user_name, "Time Off", f"{parts[0]} to {parts[1]}", approver)
        cur.execute("UPDATE approval_requests SET slack_ts=?, approver=? WHERE id=?", (ts, approver, req_id))
        conn.commit(); conn.close()
        return jsonify({"response_type": "ephemeral", "text": f"Time off #{req_id} sent to {approver}"})

    return jsonify({"response_type": "ephemeral", "text": "Unknown command"})

@app.route("/slack/interactions", methods=["POST"])
def handle_interaction():
    payload = json.loads(request.form.get("payload", "{}")); action = payload.get("actions", [{}])[0]
    req_id = int(action.get("value", 0)); user = payload.get("user", {}).get("username")
    status = "approved" if action.get("action_id") == "approve" else "rejected"
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE approval_requests SET status=?, resolved_at=? WHERE id=?", (status, datetime.utcnow().isoformat(), req_id))
    conn.commit(); conn.close()
    resp_url = payload.get("response_url")
    if resp_url:
        requests.post(resp_url, json={"replace_original": True, "text": f"Request #{req_id} *{status}* by <@{user}>"}, timeout=10)
    return "", 200

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "slack-approval-bot"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8065, debug=True)
