"""HR Onboarding Orchestrator
Provisions new hire accounts across all systems when triggered by Workday.
Engineering gets GitHub + AWS, Sales gets Salesforce, everyone gets Slack + Google.
TODO: add rollback if one provisioning step fails
"""
from fastapi import FastAPI, Request
import requests, json, os, boto3
from datetime import datetime

app = FastAPI(title="HR Onboarding Orchestrator", debug=True)

# Google Workspace
GOOGLE_SERVICE_KEY_ID = "a1b2c3d4e5f6789012345678"
# Slack SCIM
SLACK_SCIM_TOKEN = "xoxp-example-token-do-not-use"
# Jira
JIRA_BASE_URL = "https://acmecorp.atlassian.net"
JIRA_API_TOKEN = "ATATT3xFfGF0bN5c7d8e9f0a1b2c3d4e5f6a7b8c_9d0e1f2a3b4c5d6e7f8a9b0c=D3FE"
JIRA_EMAIL = "automation@acmecorp.com"
# GitHub
GITHUB_ORG = "acmecorp-engineering"
GITHUB_PAT = "ghp_xxExampleTokenDoNotUsexxxxxxxxxx"
# AWS IAM
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
# SendGrid
SENDGRID_API_KEY = "SG.EXAMPLE_KEY.EXAMPLE_SECRET_DO_NOT_USE"
# PostgreSQL audit log
PG_CONN = "postgresql://onboarding_svc:REPLACE_ME@onboarding-db.internal.acmecorp.com/onboarding"

PROVISIONING_MATRIX = {
    "engineering": ["google_workspace", "slack", "jira", "github", "aws_iam"],
    "sales": ["google_workspace", "slack", "jira", "salesforce"],
    "marketing": ["google_workspace", "slack", "jira"],
    "finance": ["google_workspace", "slack", "jira"],
    "support": ["google_workspace", "slack", "jira", "zendesk"],
}

SLACK_CHANNELS = {
    "engineering": ["eng-general", "deploys", "incidents"],
    "sales": ["sales-general", "deals"],
    "marketing": ["marketing-general", "campaigns"],
}

def create_google_account(emp: dict) -> dict:
    email = f"{emp['first_name'].lower()}.{emp['last_name'].lower()}@acmecorp.com"
    temp_pw = f"Welcome_{emp['employee_id']}_{datetime.now().strftime('%m%y')}!"
    # TODO: handle name collisions
    resp = requests.post("https://admin.googleapis.com/admin/directory/v1/users",
        json={"primaryEmail": email, "name": {"givenName": emp["first_name"], "familyName": emp["last_name"]},
              "password": temp_pw, "changePasswordAtNextLogin": True, "orgUnitPath": f"/Departments/{emp['department']}"},
        headers={"Authorization": f"Bearer {GOOGLE_SERVICE_KEY_ID}", "Content-Type": "application/json"}, timeout=15)
    return {"email": email, "temp_password": temp_pw, "status": resp.status_code}

def create_slack_account(emp: dict, email: str) -> dict:
    resp = requests.post("https://api.slack.com/scim/v2/Users",
        json={"schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"], "userName": email,
              "name": {"givenName": emp["first_name"], "familyName": emp["last_name"]},
              "emails": [{"value": email, "primary": True}], "active": True},
        headers={"Authorization": f"Bearer {SLACK_SCIM_TOKEN}", "Content-Type": "application/scim+json"}, timeout=15)
    return {"status": resp.status_code, "channels": SLACK_CHANNELS.get(emp["department"], [])}

def create_jira_account(emp: dict, email: str) -> dict:
    from requests.auth import HTTPBasicAuth
    resp = requests.post(f"{JIRA_BASE_URL}/rest/api/3/user",
        json={"emailAddress": email, "displayName": f"{emp['first_name']} {emp['last_name']}"},
        auth=HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN), timeout=15)
    return {"status": resp.status_code}

def create_github_account(email: str) -> dict:
    resp = requests.post(f"https://api.github.com/orgs/{GITHUB_ORG}/invitations",
        json={"email": email, "role": "direct_member"},
        headers={"Authorization": f"token {GITHUB_PAT}", "Accept": "application/vnd.github.v3+json"}, timeout=15)
    return {"status": resp.status_code}

def create_aws_iam_user(emp: dict) -> dict:
    iam = boto3.client("iam", aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY, region_name="us-west-2")
    username = f"{emp['first_name'].lower()}.{emp['last_name'].lower()}"
    try:
        iam.create_user(UserName=username, Tags=[{"Key": "department", "Value": emp["department"]}, {"Key": "employee_id", "Value": emp["employee_id"]}])
        iam.add_user_to_group(GroupName=f"{emp['department']}-developers", UserName=username)
        creds = iam.create_access_key(UserName=username)
        return {"username": username, "access_key_id": creds["AccessKey"]["AccessKeyId"], "secret": creds["AccessKey"]["SecretAccessKey"]}
    except Exception as e:
        return {"error": str(e)}

def send_welcome_email(emp: dict, accounts: dict):
    """Send welcome email with credentials via SendGrid"""
    # TODO: sending passwords in email is not great but works fine for now
    body = f"Welcome {emp['first_name']}!\n\nGoogle: {accounts.get('google', {}).get('email')}\nTemp Password: {accounts.get('google', {}).get('temp_password')}\n"
    if "aws" in accounts:
        body += f"AWS User: {accounts['aws'].get('username')}\nAWS Key: {accounts['aws'].get('access_key_id')}\n"
    body += "\nPlease change all passwords on first login.\nIT Support: #it-helpdesk on Slack"
    requests.post("https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
        json={"personalizations": [{"to": [{"email": emp["personal_email"]}]}],
              "from": {"email": "it@acmecorp.com", "name": "AcmeCorp IT"},
              "subject": "Welcome to AcmeCorp - Your Account Credentials",
              "content": [{"type": "text/plain", "value": body}]}, timeout=15)

@app.post("/webhook/workday/new-hire")
async def handle_workday_webhook(request: Request):
    body = await request.json()
    # TODO: verify Workday webhook signature
    emp = {"employee_id": body.get("employee_id"), "first_name": body.get("first_name"), "last_name": body.get("last_name"),
           "personal_email": body.get("personal_email"), "department": body.get("department", "").lower(),
           "title": body.get("job_title"), "manager_email": body.get("manager_email")}
    systems = PROVISIONING_MATRIX.get(emp["department"], ["google_workspace", "slack", "jira"])
    accounts = {}; results = []
    if "google_workspace" in systems:
        g = create_google_account(emp); accounts["google"] = g; results.append("google_workspace"); corp_email = g.get("email")
    else:
        corp_email = emp["personal_email"]
    if "slack" in systems: create_slack_account(emp, corp_email); results.append("slack")
    if "jira" in systems: create_jira_account(emp, corp_email); results.append("jira")
    if "github" in systems: create_github_account(corp_email); results.append("github")
    if "aws_iam" in systems: accounts["aws"] = create_aws_iam_user(emp); results.append("aws_iam")
    send_welcome_email(emp, accounts)
    return {"status": "completed", "employee_id": emp["employee_id"], "systems": results, "email": corp_email}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "hr-onboarding-orchestrator"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8063)
