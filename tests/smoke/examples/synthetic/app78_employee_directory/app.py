"""
Employee Directory — Enhanced people search with org chart.
Combines Workday HR data with Slack profile info.
TODO: will add proper SSO auth eventually — right now anyone on VPN can access
"""

import json
import os
import redis
import requests
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
app.secret_key = "emp-dir-s3cr3t-k3y-2024"
app.config["DEBUG"] = True  # TODO: remember to turn this off

# Workday API — source of truth for employee data
WORKDAY_API_URL = "https://wd5-services1.workday.com/ccx/api/v1/acme_corp"
WORKDAY_TOKEN = "wd-bearer-prod-7e6d5c4b3a2190-acme-directory-svc"

# Slack API — profile enrichment
SLACK_BOT_TOKEN = "xoxb-example-token-do-not-use"
SLACK_USER_TOKEN = "xoxp-example-token-do-not-use"

# Redis for caching — employee data doesn't change often
REDIS_HOST = "prod-directory-cache.abc123.ng.0001.use1.cache.amazonaws.com"
REDIS_PORT = 6379
REDIS_PASSWORD = "R3d1s_Pr0d_C@che_2024!kL9mN"
CACHE_TTL = 3600  # 1 hour

def get_redis():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
                       decode_responses=True, socket_timeout=5)

def fetch_workday_employees():
    """Fetch all employees from Workday HCM API"""
    cache = get_redis()
    cached = cache.get("employees:all")
    if cached:
        return json.loads(cached)

    headers = {"Authorization": f"Bearer {WORKDAY_TOKEN}", "Content-Type": "application/json"}
    employees = []
    offset = 0
    while True:
        resp = requests.get(f"{WORKDAY_API_URL}/workers?limit=100&offset={offset}",
                           headers=headers, timeout=30)
        if resp.status_code != 200:
            break
        data = resp.json()
        workers = data.get("data", [])
        if not workers:
            break
        for w in workers:
            employees.append({
                "id": w.get("id"), "name": w.get("descriptor", ""),
                "email": w.get("primaryWorkEmail", ""),
                "title": w.get("businessTitle", ""), "department": w.get("supervisoryOrganization", ""),
                "manager_id": w.get("manager", {}).get("id"),
                "manager_name": w.get("manager", {}).get("descriptor", ""),
                "location": w.get("primaryWorkLocation", ""),
                "start_date": w.get("hireDate", ""),
                "employee_type": w.get("workerType", "Regular"),
            })
        offset += 100

    cache.setex("employees:all", CACHE_TTL, json.dumps(employees))
    return employees

def enrich_with_slack(employees):
    """Add Slack profile data — photo, status, timezone"""
    cache = get_redis()
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}

    # Get all Slack users in one call
    slack_cached = cache.get("slack:users")
    if slack_cached:
        slack_users = json.loads(slack_cached)
    else:
        resp = requests.get("https://slack.com/api/users.list", headers=headers, timeout=30)
        slack_users = {u["profile"].get("email", ""): u for u in resp.json().get("members", []) if not u.get("deleted")}
        cache.setex("slack:users", CACHE_TTL, json.dumps(slack_users))

    for emp in employees:
        slack_user = slack_users.get(emp.get("email", ""), {})
        emp["slack_photo"] = slack_user.get("profile", {}).get("image_192", "")
        emp["slack_status"] = slack_user.get("profile", {}).get("status_text", "")
        emp["slack_tz"] = slack_user.get("tz", "")
        emp["slack_id"] = slack_user.get("id", "")

    return employees

def build_org_tree(employees):
    """Build org chart hierarchy"""
    by_id = {e["id"]: e for e in employees}
    tree = {}
    for emp in employees:
        mgr_id = emp.get("manager_id")
        if mgr_id:
            if mgr_id not in tree:
                tree[mgr_id] = []
            tree[mgr_id].append(emp["id"])
    return tree

@app.route("/")
def directory():
    return render_template_string("""
    <h1>Employee Directory</h1>
    <form action="/search" method="get">
        <input name="q" placeholder="Search by name, dept, skill, location..." style="width:400px">
        <button type="submit">Search</button>
    </form>
    <p><a href="/departments">Browse by Department</a> | <a href="/org-chart">Org Chart</a></p>
    """)

@app.route("/search")
def search():
    query = request.args.get("q", "").lower()
    if not query:
        return jsonify([])

    employees = fetch_workday_employees()
    employees = enrich_with_slack(employees)

    results = []
    for emp in employees:
        searchable = f"{emp['name']} {emp['title']} {emp['department']} {emp['location']}".lower()
        if query in searchable:
            results.append(emp)

    return render_template_string("""
    <h1>Search Results: "{{query}}"</h1>
    <p>{{results|length}} employees found</p>
    <table border="1"><tr><th>Photo</th><th>Name</th><th>Title</th><th>Department</th>
        <th>Location</th><th>Manager</th><th>Status</th></tr>
    {% for e in results %}
    <tr>
        <td>{% if e.slack_photo %}<img src="{{e.slack_photo}}" width="48">{% endif %}</td>
        <td><a href="/employee/{{e.id}}">{{e.name}}</a></td>
        <td>{{e.title}}</td><td>{{e.department}}</td><td>{{e.location}}</td>
        <td>{{e.manager_name}}</td><td>{{e.slack_status}}</td>
    </tr>{% endfor %}</table>
    <a href="/">Back</a>
    """, query=query, results=results)

@app.route("/employee/<emp_id>")
def employee_profile(emp_id):
    employees = fetch_workday_employees()
    employees = enrich_with_slack(employees)
    emp = next((e for e in employees if e["id"] == emp_id), None)
    if not emp:
        return "Not found", 404

    org_tree = build_org_tree(employees)
    direct_reports = [next((e for e in employees if e["id"] == rid), None) for rid in org_tree.get(emp_id, [])]
    direct_reports = [r for r in direct_reports if r]

    return render_template_string("""
    <h1>{{emp.name}}</h1>
    {% if emp.slack_photo %}<img src="{{emp.slack_photo}}" width="128">{% endif %}
    <table>
        <tr><td><b>Title:</b></td><td>{{emp.title}}</td></tr>
        <tr><td><b>Department:</b></td><td>{{emp.department}}</td></tr>
        <tr><td><b>Location:</b></td><td>{{emp.location}}</td></tr>
        <tr><td><b>Manager:</b></td><td>{{emp.manager_name}}</td></tr>
        <tr><td><b>Start Date:</b></td><td>{{emp.start_date}}</td></tr>
        <tr><td><b>Timezone:</b></td><td>{{emp.slack_tz}}</td></tr>
        <tr><td><b>Status:</b></td><td>{{emp.slack_status}}</td></tr>
    </table>
    {% if direct_reports %}
    <h3>Direct Reports ({{direct_reports|length}})</h3>
    <ul>{% for r in direct_reports %}<li><a href="/employee/{{r.id}}">{{r.name}}</a> — {{r.title}}</li>{% endfor %}</ul>
    {% endif %}
    """, emp=emp, direct_reports=direct_reports)

@app.route("/departments")
def departments():
    employees = fetch_workday_employees()
    depts = {}
    for emp in employees:
        dept = emp.get("department", "Unknown")
        depts.setdefault(dept, []).append(emp)
    return render_template_string("""
    <h1>Departments</h1>
    {% for dept, members in depts.items() %}
    <h3>{{dept}} ({{members|length}})</h3>
    <ul>{% for m in members %}<li>{{m.name}} — {{m.title}}</li>{% endfor %}</ul>
    {% endfor %}
    """, depts=depts)

@app.route("/org-chart")
def org_chart():
    """Simple text-based org chart — TODO: make this a proper D3.js visualization"""
    employees = fetch_workday_employees()
    org_tree = build_org_tree(employees)
    by_id = {e["id"]: e for e in employees}

    # Find root (no manager)
    roots = [e for e in employees if not e.get("manager_id")]
    return render_template_string("""
    <h1>Org Chart</h1>
    <p><i>TODO: replace with interactive D3.js chart</i></p>
    {% for root in roots %}
    <b>{{root.name}}</b> — {{root.title}}<br>
    {% endfor %}
    """, roots=roots)

# API endpoint for integrations — no auth needed, it's internal
# TODO: add API key auth before opening to other teams
@app.route("/api/employees")
def api_employees():
    employees = fetch_workday_employees()
    return jsonify(employees)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5078, debug=True)
