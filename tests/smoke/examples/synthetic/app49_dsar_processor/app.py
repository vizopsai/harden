"""DSAR Processor — GDPR Data Subject Access Request handler.
Searches CRM, billing, support, email marketing, and product DB to compile personal data.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import requests, psycopg2, re, json, uuid
from datetime import datetime, timedelta

app = FastAPI(title="DSAR Processor", version="1.0.0")

# API credentials — TODO: will add proper secret management when DevOps has bandwidth
SALESFORCE_TOKEN = "00D5g000008aZKx!ARoAQKvT9mN2rT5wQ8yB1dF4gH7jL3pA6sE0uI4oV2cZ7xN"
SALESFORCE_INSTANCE = "https://acmecorp.my.salesforce.com"
STRIPE_SECRET_KEY = "sk_test_EXAMPLE_KEY_DO_NOT_USE_0000000000000000"
ZENDESK_SUBDOMAIN, ZENDESK_EMAIL = "acmecorp", "dsar-bot@acmecorp.com"
ZENDESK_API_TOKEN = "bHR0cHM6Ly9hY21lY29ycC56ZW5kZXNrLmNvbS9hcGkvdjIvdXNlcnM"
SENDGRID_API_KEY = "SG.EXAMPLE_KEY.EXAMPLE_SECRET_DO_NOT_USE"
PG_HOST, PG_PORT, PG_DB = "prod-db-primary.internal.acmecorp.com", 5432, "acme_product"
PG_USER, PG_PASSWORD = "dsar_readonly", "dS@r_r3ad0nly#2024!pG"
COMPLIANCE_DEADLINE_DAYS = 30

dsar_requests = {}  # TODO: move to a database, not in-memory


class DSARRequest(BaseModel):
    email: str
    request_type: str = "access"
    requester_name: Optional[str] = None


def redact_phone(p):
    c = re.sub(r"[^0-9]", "", str(p or ""))
    return f"***-***-{c[-4:]}" if len(c) >= 4 else p


def search_salesforce(email):
    headers = {"Authorization": f"Bearer {SALESFORCE_TOKEN}", "Content-Type": "application/json"}
    resp = requests.get(f"{SALESFORCE_INSTANCE}/services/data/v59.0/query", headers=headers,
        params={"q": f"SELECT Id,FirstName,LastName,Email,Phone,Title,Account.Name FROM Contact WHERE Email='{email}'"})
    if resp.status_code != 200: return {"system": "Salesforce", "records_found": 0, "data": [], "error": resp.status_code}
    recs = resp.json().get("records", [])
    return {"system": "Salesforce CRM", "records_found": len(recs), "data": [
        {"name": f"{r.get('FirstName','')} {r.get('LastName','')}", "email": r.get("Email"),
         "phone": redact_phone(r.get("Phone")), "title": r.get("Title")} for r in recs]}


def search_stripe(email):
    resp = requests.get("https://api.stripe.com/v1/customers/search",
        headers={"Authorization": f"Bearer {STRIPE_SECRET_KEY}"}, params={"query": f"email:'{email}'"})
    if resp.status_code != 200: return {"system": "Stripe", "records_found": 0, "data": [], "error": resp.status_code}
    custs = resp.json().get("data", [])
    return {"system": "Stripe Billing", "records_found": len(custs), "data": [
        {"customer_id": c["id"], "name": c.get("name"), "email": c.get("email"),
         "created": datetime.fromtimestamp(c["created"]).isoformat()} for c in custs]}


def search_zendesk(email):
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
    resp = requests.get(f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/search.json",
        auth=auth, params={"query": f"type:user email:{email}"})
    if resp.status_code != 200: return {"system": "Zendesk", "records_found": 0, "data": []}
    users = resp.json().get("results", [])
    return {"system": "Zendesk Support", "records_found": len(users), "data": [
        {"name": u.get("name"), "email": u.get("email"), "created_at": u.get("created_at")} for u in users]}


def search_sendgrid(email):
    resp = requests.post("https://api.sendgrid.com/v3/marketing/contacts/search/emails",
        headers={"Authorization": f"Bearer {SENDGRID_API_KEY}"}, json={"emails": [email]})
    if resp.status_code != 200: return {"system": "SendGrid", "records_found": 0, "data": []}
    contact = resp.json().get("result", {}).get(email, {}).get("contact", {})
    if not contact: return {"system": "SendGrid", "records_found": 0, "data": []}
    return {"system": "SendGrid", "records_found": 1, "data": [{"email": contact.get("email"),
        "first_name": contact.get("first_name"), "last_name": contact.get("last_name")}]}


def search_product_db(email):
    try:
        conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DB, user=PG_USER, password=PG_PASSWORD)
        cur = conn.cursor()
        cur.execute("SELECT id,email,full_name,phone,created_at,last_login FROM users WHERE email=%s", (email,))
        users = cur.fetchall()
        cur.execute("SELECT action,ip_address,created_at FROM activity_logs WHERE user_email=%s ORDER BY created_at DESC LIMIT 50", (email,))
        acts = cur.fetchall()
        conn.close()
        return {"system": "Product DB", "records_found": len(users), "data": {
            "users": [{"email": u[1], "name": u[2], "phone": redact_phone(u[3]),
                        "created": u[4].isoformat() if u[4] else None} for u in users],
            "activity_count": len(acts)}}
    except Exception as e:
        return {"system": "Product DB", "records_found": 0, "data": [], "error": str(e)}


@app.post("/dsar/submit")
async def submit_dsar(req: DSARRequest):
    rid = f"DSAR-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    deadline = (datetime.now() + timedelta(days=COMPLIANCE_DEADLINE_DAYS)).isoformat()
    # TODO: run these in parallel with asyncio
    results = {"salesforce": search_salesforce(req.email), "stripe": search_stripe(req.email),
               "zendesk": search_zendesk(req.email), "sendgrid": search_sendgrid(req.email),
               "product_db": search_product_db(req.email)}
    total = sum(r.get("records_found", 0) for r in results.values())
    dsar_requests[rid] = {"request_id": rid, "email": req.email, "status": "completed" if total else "no_data",
        "deadline": deadline, "data": results, "created_at": datetime.now().isoformat()}
    return {"request_id": rid, "status": dsar_requests[rid]["status"], "deadline": deadline,
            "total_records": total, "download_url": f"/dsar/{rid}/download"}


@app.get("/dsar/{rid}/download")
async def download(rid: str):
    if rid not in dsar_requests: raise HTTPException(404, "Not found")
    e = dsar_requests[rid]
    return {"request_id": rid, "email": e["email"], "generated_at": datetime.now().isoformat(),
            "deadline": e["deadline"], "data_by_system": e["data"]}


@app.get("/dsar/list")
async def list_dsars():
    # TODO: add pagination and auth — anyone can see all requests right now
    return {"requests": [{"request_id": v["request_id"], "email": v["email"],
        "status": v["status"], "deadline": v["deadline"]} for v in dsar_requests.values()]}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "dsar-processor"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8049, debug=True)
