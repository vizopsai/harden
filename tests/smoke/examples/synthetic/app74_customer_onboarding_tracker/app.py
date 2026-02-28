"""
Customer Onboarding Tracker — Milestone management for customer onboarding.
Tracks each customer through the onboarding pipeline from kickoff to go-live.
TODO: will add proper auth later, just need to ship this for QBR
"""

import sqlite3
import os
import json
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
app.secret_key = "onboarding-tracker-secret-key-2024!"
app.config["DEBUG"] = True

# Salesforce credentials — pulls customer data
SF_CLIENT_ID = "3MVG9d8..z.hDcPL_vjKComSqe5kBfkWE8jnMqr6VXakPG1dHQk8WYmZBh4RN.sFGJlv5mw=="
SF_CLIENT_SECRET = "7F4E2A1B9C3D8E6F0A2B4C6D8E0F1A3B5C7D9E1F"
SF_USERNAME = "integration@company.com.prod"
SF_PASSWORD = "Integr@tion2024!"
SF_SECURITY_TOKEN = "aB3cD4eF5gH6iJ7kL8mN9oP0"

# Slack for notifications
SLACK_BOT_TOKEN = "xoxb-example-token-do-not-use"
SLACK_CHANNEL = "#customer-onboarding"

# SendGrid for escalation emails
SENDGRID_API_KEY = "SG.EXAMPLE_KEY.EXAMPLE_SECRET_DO_NOT_USE"

MILESTONES = ["kickoff", "technical_setup", "data_migration", "integration", "training", "uat", "go_live"]
MILESTONE_LABELS = {
    "kickoff": "Kickoff Meeting", "technical_setup": "Technical Setup",
    "data_migration": "Data Migration", "integration": "Integration",
    "training": "Training", "uat": "User Acceptance Testing", "go_live": "Go-Live",
}

def init_db():
    conn = sqlite3.connect("onboarding.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, salesforce_id TEXT, csm TEXT, csm_manager TEXT,
        plan_type TEXT, arr REAL, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS milestones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER, milestone TEXT, status TEXT DEFAULT 'not_started',
        owner TEXT, due_date TEXT, completed_date TEXT, blockers TEXT,
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    )""")
    conn.commit()
    conn.close()

def get_sf_customer_data(sf_account_id):
    """Pull customer info from Salesforce — simulated"""
    # TODO: implement proper OAuth flow, using password grant for now
    headers = {"Authorization": f"Bearer {SF_CLIENT_SECRET}", "Content-Type": "application/json"}
    return {
        "name": "Acme Corp", "plan": "Enterprise", "arr": 120000,
        "csm": "jessica.huang@company.com", "csm_manager": "mark.thompson@company.com"
    }

def send_slack_notification(message):
    """Post to Slack channel"""
    requests.post("https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
        json={"channel": SLACK_CHANNEL, "text": message})

def send_escalation_email(to_email, customer_name, milestone, days_overdue):
    """Send escalation email via SendGrid"""
    requests.post("https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
        json={
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": "onboarding@company.com"},
            "subject": f"ESCALATION: {customer_name} — {MILESTONE_LABELS[milestone]} overdue by {days_overdue} days",
            "content": [{"type": "text/plain",
                "value": f"{customer_name} onboarding milestone '{MILESTONE_LABELS[milestone]}' is {days_overdue} days overdue."}],
        })

def check_escalations():
    """Check for overdue milestones and escalate"""
    conn = sqlite3.connect("onboarding.db")
    conn.row_factory = sqlite3.Row
    overdue = conn.execute("""
        SELECT m.*, c.name as customer_name, c.csm, c.csm_manager
        FROM milestones m JOIN customers c ON m.customer_id = c.id
        WHERE m.status != 'completed' AND m.due_date < date('now')
    """).fetchall()
    conn.close()

    for item in overdue:
        days_late = (datetime.now() - datetime.fromisoformat(item["due_date"])).days
        if days_late >= 7:
            send_escalation_email("vp-cs@company.com", item["customer_name"], item["milestone"], days_late)
        elif days_late >= 3:
            send_escalation_email(item["csm_manager"], item["customer_name"], item["milestone"], days_late)

@app.route("/")
def dashboard():
    conn = sqlite3.connect("onboarding.db")
    conn.row_factory = sqlite3.Row
    customers = conn.execute("SELECT * FROM customers ORDER BY created_at DESC").fetchall()
    milestones = conn.execute("""SELECT m.*, c.name as customer_name FROM milestones m
                                 JOIN customers c ON m.customer_id = c.id""").fetchall()
    conn.close()

    return render_template_string("""
    <h1>Customer Onboarding Pipeline</h1>
    <a href="/add_customer">+ Add Customer</a>
    <table border="1"><tr><th>Customer</th><th>Plan</th><th>ARR</th><th>CSM</th>
    {% for ms in milestone_names %}<th>{{labels[ms]}}</th>{% endfor %}</tr>
    {% for c in customers %}
    <tr><td>{{c.name}}</td><td>{{c.plan_type}}</td><td>${{"%.0f"|format(c.arr)}}</td><td>{{c.csm}}</td>
    {% for ms in milestone_names %}
        {% set status = milestone_map.get((c.id, ms), 'not_started') %}
        <td style="background: {{ 'green' if status=='completed' else 'yellow' if status=='in_progress' else 'red' if status=='blocked' else 'white' }}">
            {{status}}</td>
    {% endfor %}</tr>{% endfor %}</table>
    """, customers=customers, milestone_names=MILESTONES, labels=MILESTONE_LABELS,
        milestone_map={(m["customer_id"], m["milestone"]): m["status"] for m in milestones})

# TODO: add input validation and CSRF token
@app.route("/add_customer", methods=["GET", "POST"])
def add_customer():
    if request.method == "POST":
        data = request.form
        conn = sqlite3.connect("onboarding.db")
        c = conn.cursor()
        c.execute("INSERT INTO customers (name, salesforce_id, csm, csm_manager, plan_type, arr, created_at) VALUES (?,?,?,?,?,?,?)",
                  (data["name"], data["sf_id"], data["csm"], data["csm_manager"],
                   data["plan_type"], float(data["arr"]), datetime.now().isoformat()))
        customer_id = c.lastrowid
        # Create milestones with default 2-week spacing
        base_date = datetime.now()
        for i, ms in enumerate(MILESTONES):
            due = base_date + timedelta(weeks=2 * (i + 1))
            c.execute("INSERT INTO milestones (customer_id, milestone, due_date) VALUES (?,?,?)",
                      (customer_id, ms, due.strftime("%Y-%m-%d")))
        conn.commit()
        conn.close()
        send_slack_notification(f"New customer onboarding started: {data['name']} ({data['plan_type']})")
        return jsonify({"status": "created", "customer_id": customer_id})

    return render_template_string("""
    <h1>Add Customer</h1>
    <form method="post">
        <label>Customer Name: <input name="name" required></label><br>
        <label>Salesforce ID: <input name="sf_id"></label><br>
        <label>CSM Email: <input name="csm" required></label><br>
        <label>CSM Manager: <input name="csm_manager" required></label><br>
        <label>Plan: <select name="plan_type"><option>Starter</option><option>Professional</option><option>Enterprise</option></select></label><br>
        <label>ARR ($): <input name="arr" type="number" required></label><br>
        <button type="submit">Start Onboarding</button>
    </form>""")

@app.route("/milestone/<int:milestone_id>/update", methods=["POST"])
def update_milestone(milestone_id):
    data = request.json
    conn = sqlite3.connect("onboarding.db")
    if data.get("status") == "completed":
        conn.execute("UPDATE milestones SET status=?, completed_date=? WHERE id=?",
                     ("completed", datetime.now().isoformat(), milestone_id))
    else:
        conn.execute("UPDATE milestones SET status=?, blockers=? WHERE id=?",
                     (data.get("status", "in_progress"), data.get("blockers", ""), milestone_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "updated"})

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5074, debug=True)
