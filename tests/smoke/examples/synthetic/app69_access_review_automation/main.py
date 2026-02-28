"""Access Review Automation - Quarterly access certification.
Pulls permissions from Okta/AWS/GitHub, sends review packets to managers,
auto-revokes unattested access after grace period.
TODO: add reminder emails for managers who haven't completed review
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
import requests, json, sqlite3, boto3, os
from datetime import datetime, timedelta

app = FastAPI(title="Access Review Automation", debug=True)

OKTA_DOMAIN = "acmecorp.okta.com"
OKTA_API_TOKEN = "00Cv4l0n3pR5sU7wY9aB1cD3eF5gH7iJ9kL1mN3oP5qR7sU"
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
GITHUB_ORG = "acmecorp-engineering"
GITHUB_PAT = "ghp_xxExampleTokenDoNotUsexxxxxxxxxx"
SENDGRID_API_KEY = "SG.EXAMPLE_KEY.EXAMPLE_SECRET_DO_NOT_USE"
GRACE_PERIOD_DAYS = 14
DB_PATH = "access_review.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS review_cycles (id INTEGER PRIMARY KEY AUTOINCREMENT, quarter TEXT, status TEXT DEFAULT 'active', started_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS access_items (id INTEGER PRIMARY KEY AUTOINCREMENT, review_cycle_id INTEGER, employee_email TEXT, employee_name TEXT, manager_email TEXT, system TEXT, resource TEXT, permission_level TEXT, status TEXT DEFAULT 'pending', attested_by TEXT, attested_at TEXT, grace_deadline TEXT, auto_revoked INTEGER DEFAULT 0);
    """)
    conn.commit(); conn.close()

init_db()

def fetch_okta_app_assignments() -> list:
    """Pull all user-to-app assignments from Okta"""
    headers = {"Authorization": f"SSWS {OKTA_API_TOKEN}", "Accept": "application/json"}
    assignments = []
    try:
        resp = requests.get(f"https://{OKTA_DOMAIN}/api/v1/users", headers=headers, params={"limit": 200, "filter": 'status eq "ACTIVE"'}, timeout=30)
        if resp.status_code == 200:
            for user in resp.json():
                email = user.get("profile", {}).get("email")
                name = f"{user.get('profile', {}).get('firstName', '')} {user.get('profile', {}).get('lastName', '')}".strip()
                manager = user.get("profile", {}).get("manager", "unknown@acmecorp.com")
                apps_resp = requests.get(f"https://{OKTA_DOMAIN}/api/v1/users/{user['id']}/appLinks", headers=headers, timeout=15)
                if apps_resp.status_code == 200:
                    for a in apps_resp.json():
                        assignments.append({"employee_email": email, "employee_name": name, "manager_email": manager, "system": "okta", "resource": a.get("label"), "permission_level": "user"})
    except Exception as e:
        print(f"[ERROR] Okta fetch failed: {e}")
    return assignments

def fetch_aws_iam_permissions() -> list:
    iam = boto3.client("iam", aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY, region_name="us-west-2")
    assignments = []
    try:
        for page in iam.get_paginator("list_users").paginate():
            for user in page["Users"]:
                un = user["UserName"]
                for g in iam.list_groups_for_user(UserName=un).get("Groups", []):
                    assignments.append({"employee_email": f"{un}@acmecorp.com", "employee_name": un, "manager_email": "unknown@acmecorp.com", "system": "aws_iam", "resource": g["GroupName"], "permission_level": "group_member"})
                for p in iam.list_attached_user_policies(UserName=un).get("AttachedPolicies", []):
                    assignments.append({"employee_email": f"{un}@acmecorp.com", "employee_name": un, "manager_email": "unknown@acmecorp.com", "system": "aws_iam", "resource": p["PolicyName"], "permission_level": "direct_policy"})
    except Exception as e:
        print(f"[ERROR] AWS IAM fetch: {e}")
    return assignments

def fetch_github_memberships() -> list:
    headers = {"Authorization": f"token {GITHUB_PAT}", "Accept": "application/vnd.github.v3+json"}
    assignments = []
    try:
        for team in requests.get(f"https://api.github.com/orgs/{GITHUB_ORG}/teams", headers=headers, timeout=15).json():
            for m in requests.get(f"https://api.github.com/orgs/{GITHUB_ORG}/teams/{team['slug']}/members", headers=headers, timeout=15).json():
                assignments.append({"employee_email": f"{m['login']}@acmecorp.com", "employee_name": m["login"], "manager_email": "unknown@acmecorp.com", "system": "github", "resource": f"Team: {team['name']}", "permission_level": "member"})
    except Exception as e:
        print(f"[ERROR] GitHub fetch: {e}")
    return assignments

def send_review_email(manager_email: str, items: list, cycle_id: int):
    rows = "".join(f"<tr><td>{i['employee_name']}</td><td>{i['system']}</td><td>{i['resource']}</td><td><a href='https://accessreview.internal.acmecorp.com/review/{cycle_id}/{i['id']}/approve'>Approve</a> | <a href='https://accessreview.internal.acmecorp.com/review/{cycle_id}/{i['id']}/revoke'>Revoke</a></td></tr>" for i in items)
    html = f"<h2>Quarterly Access Review</h2><p>Unattested access auto-revoked after {GRACE_PERIOD_DAYS} days.</p><table border='1'><tr><th>Employee</th><th>System</th><th>Resource</th><th>Action</th></tr>{rows}</table>"
    try:
        requests.post("https://api.sendgrid.com/v3/mail/send", headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"}, json={"personalizations": [{"to": [{"email": manager_email}]}], "from": {"email": "security@acmecorp.com"}, "subject": "Action Required: Quarterly Access Review", "content": [{"type": "text/html", "value": html}]}, timeout=15)
    except Exception as e:
        print(f"[ERROR] Email to {manager_email}: {e}")

def revoke_access(system: str, email: str, resource: str):
    username = email.split("@")[0]
    if system == "okta":
        print(f"[REVOKE] Okta: {email} from {resource}")  # TODO: implement actual Okta revocation
    elif system == "aws_iam":
        iam = boto3.client("iam", aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY, region_name="us-west-2")
        try:
            iam.remove_user_from_group(GroupName=resource, UserName=username) if not resource.startswith("arn:") else iam.detach_user_policy(UserName=username, PolicyArn=resource)
        except Exception as e:
            print(f"[ERROR] AWS revoke: {e}")
    elif system == "github":
        slug = resource.lower().replace(" ", "-").replace("team: ", "")
        requests.delete(f"https://api.github.com/orgs/{GITHUB_ORG}/teams/{slug}/memberships/{username}", headers={"Authorization": f"token {GITHUB_PAT}"}, timeout=15)

@app.post("/review/start")
async def start_review_cycle(background_tasks: BackgroundTasks):
    quarter = f"Q{(datetime.utcnow().month - 1) // 3 + 1}-{datetime.utcnow().year}"
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("INSERT INTO review_cycles (quarter) VALUES (?)", (quarter,))
    cycle_id = cur.lastrowid; conn.commit()
    all_items = fetch_okta_app_assignments() + fetch_aws_iam_permissions() + fetch_github_memberships()
    deadline = (datetime.utcnow() + timedelta(days=GRACE_PERIOD_DAYS)).isoformat()
    for a in all_items:
        cur.execute("INSERT INTO access_items (review_cycle_id, employee_email, employee_name, manager_email, system, resource, permission_level, grace_deadline) VALUES (?,?,?,?,?,?,?,?)",
                    (cycle_id, a["employee_email"], a["employee_name"], a["manager_email"], a["system"], a["resource"], a["permission_level"], deadline))
    conn.commit()
    mgr_items = {}
    for row in cur.execute("SELECT id, employee_name, manager_email, system, resource, permission_level FROM access_items WHERE review_cycle_id=?", (cycle_id,)).fetchall():
        mgr_items.setdefault(row[2], []).append({"id": row[0], "employee_name": row[1], "system": row[3], "resource": row[4]})
    conn.close()
    for mgr, items in mgr_items.items():
        background_tasks.add_task(send_review_email, mgr, items, cycle_id)
    return {"cycle_id": cycle_id, "quarter": quarter, "total_items": len(all_items), "managers_notified": len(mgr_items)}

@app.post("/review/{cycle_id}/{item_id}/{action}")
async def attest_access(cycle_id: int, item_id: int, action: str, reviewer_email: str = ""):
    if action not in ("approve", "revoke"):
        raise HTTPException(400, "Action must be approve or revoke")
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("UPDATE access_items SET status=?, attested_by=?, attested_at=? WHERE id=? AND review_cycle_id=?",
                ("approved" if action == "approve" else "revoked", reviewer_email, datetime.utcnow().isoformat(), item_id, cycle_id))
    conn.commit()
    if action == "revoke":
        row = cur.execute("SELECT employee_email, system, resource FROM access_items WHERE id=?", (item_id,)).fetchone()
        if row:
            revoke_access(row[1], row[0], row[2])
    conn.close()
    return {"item_id": item_id, "status": action + "d"}

@app.post("/review/{cycle_id}/auto-revoke")
async def auto_revoke_unattested(cycle_id: int):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    expired = cur.execute("SELECT id, employee_email, system, resource FROM access_items WHERE review_cycle_id=? AND status='pending' AND grace_deadline<?", (cycle_id, now)).fetchall()
    for item in expired:
        revoke_access(item[2], item[1], item[3])
        cur.execute("UPDATE access_items SET status='auto_revoked', auto_revoked=1, attested_at=? WHERE id=?", (now, item[0]))
    conn.commit(); conn.close()
    return {"cycle_id": cycle_id, "auto_revoked": len(expired)}

@app.get("/review/{cycle_id}/dashboard")
async def review_dashboard(cycle_id: int):
    conn = sqlite3.connect(DB_PATH)
    counts = dict(conn.execute("SELECT status, COUNT(*) FROM access_items WHERE review_cycle_id=? GROUP BY status", (cycle_id,)).fetchall())
    conn.close()
    total = sum(counts.values()); completed = total - counts.get("pending", 0)
    return {"cycle_id": cycle_id, "total": total, "completed": completed, "rate": round(completed / total * 100, 1) if total else 0, "breakdown": counts}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "access-review-automation"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8069)
