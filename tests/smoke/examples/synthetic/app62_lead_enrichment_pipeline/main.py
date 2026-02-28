"""Lead Enrichment Pipeline
Enriches incoming leads from Typeform/HubSpot with Clearbit + Apollo data,
scores them, syncs to Salesforce, and alerts on hot leads via Slack.
TODO: add rate limiting - Clearbit has strict limits
"""
from fastapi import FastAPI, Request, BackgroundTasks
import requests, json, os
from datetime import datetime

app = FastAPI(title="Lead Enrichment Pipeline", debug=True)

# API Keys - TODO: move to vault eventually
CLEARBIT_API_KEY = "sk_test_EXAMPLE_KEY_DO_NOT_USE_0000000000000000"
APOLLO_API_KEY = "api_k3y_9x8w7v6u5t4s3r2q1p0o9n8m7l6k5j4i"
SF_ACCESS_TOKEN = "00D5f000005WOEp!ARcAQH_mR3kLp2N5vT8xF1jD4nB7qS0wE3yU6iO9aK"
SLACK_WEBHOOK_URL = "https://slack.com/placeholder-webhook-url"
HUBSPOT_API_KEY = "hubspot-api-key-placeholder"

ICP_WEIGHTS = {
    "company_size": {"1-50": 10, "51-200": 25, "201-1000": 40, "1001-5000": 30, "5000+": 15},
    "industry": {"technology": 30, "saas": 35, "fintech": 25, "healthcare": 20, "ecommerce": 15, "other": 5},
    "seniority": {"executive": 30, "vp": 25, "director": 20, "manager": 10, "other": 5},
}

def enrich_with_clearbit(email: str) -> dict:
    """Enrich lead with Clearbit company and person data"""
    try:
        resp = requests.get(f"https://person-stream.clearbit.com/v2/combined/find?email={email}",
                           headers={"Authorization": f"Bearer {CLEARBIT_API_KEY}"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            co = data.get("company", {}); person = data.get("person", {})
            return {"company_name": co.get("name"), "company_size": co.get("metrics", {}).get("employeesRange"),
                    "industry": co.get("category", {}).get("industry"), "funding": co.get("metrics", {}).get("raised"),
                    "tech_stack": co.get("tech", []), "title": person.get("employment", {}).get("title"),
                    "seniority": person.get("employment", {}).get("seniority"), "linkedin": person.get("linkedin", {}).get("handle")}
        return {"error": f"clearbit_{resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}

def enrich_with_apollo(email: str) -> dict:
    """Enrich with Apollo for email verification and phone"""
    try:
        resp = requests.post("https://api.apollo.io/v1/people/match",
                            json={"api_key": APOLLO_API_KEY, "email": email, "reveal_personal_emails": True}, timeout=15)
        if resp.status_code == 200:
            p = resp.json().get("person", {})
            return {"email_verified": p.get("email_status") == "verified",
                    "phone": p.get("phone_numbers", [{}])[0].get("sanitized_number") if p.get("phone_numbers") else None,
                    "title": p.get("title"), "company": p.get("organization", {}).get("name")}
        return {"error": f"apollo_{resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}

def calculate_lead_score(cb: dict, apollo: dict) -> int:
    """Score lead based on ICP match. Max score = 100"""
    score = ICP_WEIGHTS["company_size"].get(cb.get("company_size", ""), 5)
    score += ICP_WEIGHTS["industry"].get((cb.get("industry") or "other").lower(), 5)
    score += ICP_WEIGHTS["seniority"].get(cb.get("seniority", "other"), 5)
    if apollo.get("email_verified"): score += 5
    if apollo.get("phone"): score += 5
    return min(score, 100)

def create_salesforce_lead(lead: dict) -> dict:
    """Create or update lead in Salesforce"""
    resp = requests.post("https://na134.salesforce.com/services/data/v58.0/sobjects/Lead/",
        headers={"Authorization": f"Bearer {SF_ACCESS_TOKEN}", "Content-Type": "application/json"},
        json={"FirstName": lead.get("first_name"), "LastName": lead.get("last_name"), "Email": lead.get("email"),
              "Company": lead.get("company_name", "Unknown"), "Title": lead.get("title"), "Phone": lead.get("phone"),
              "Industry": lead.get("industry"), "LeadSource": "Inbound Form", "Lead_Score__c": lead.get("score")}, timeout=15)
    resp.raise_for_status()
    return resp.json()

def send_hot_lead_alert(lead: dict):
    """Send Slack notification for hot leads (score > 80)"""
    requests.post(SLACK_WEBHOOK_URL, json={"blocks": [
        {"type": "header", "text": {"type": "plain_text", "text": "Hot Lead Alert!"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{lead.get('first_name')} {lead.get('last_name')}*\nCompany: {lead.get('company_name')}\nTitle: {lead.get('title')}\nScore: *{lead.get('score')}*\nEmail: {lead.get('email')}"}}
    ]}, timeout=10)

async def process_lead(form_data: dict):
    """Full enrichment pipeline for a single lead"""
    email = form_data.get("email")
    if not email: return
    print(f"[ENRICH] Processing: {email}")
    cb = enrich_with_clearbit(email)
    apollo = enrich_with_apollo(email)
    score = calculate_lead_score(cb, apollo)
    enriched = {**form_data, "company_name": cb.get("company_name", form_data.get("company")), "industry": cb.get("industry"),
                "title": apollo.get("title", cb.get("title")), "phone": apollo.get("phone"), "score": score, "enriched_at": datetime.utcnow().isoformat()}
    sf = create_salesforce_lead(enriched)
    if score > 80:
        send_hot_lead_alert(enriched)
        print(f"[HOT] {email} scored {score}")
    print(f"[DONE] {email} score={score} sf_id={sf.get('id')}")

@app.post("/webhook/typeform")
async def typeform_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    # TODO: verify Typeform signature
    form_data = {"source": "typeform"}
    for a in body.get("form_response", {}).get("answers", []):
        ref = a.get("field", {}).get("ref", "")
        if "email" in ref: form_data["email"] = a.get("email", a.get("text"))
        elif "name" in ref: form_data["first_name"] = a.get("text", "").split()[0]; form_data["last_name"] = a.get("text", "").split()[-1]
        elif "company" in ref: form_data["company"] = a.get("text")
    background_tasks.add_task(process_lead, form_data)
    return {"status": "accepted"}

@app.post("/webhook/hubspot")
async def hubspot_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    # TODO: verify HubSpot signature - will add auth later
    for event in body:
        if event.get("subscriptionType") == "contact.creation":
            resp = requests.get(f"https://api.hubapi.com/crm/v3/objects/contacts/{event.get('objectId')}",
                               headers={"Authorization": f"Bearer {HUBSPOT_API_KEY}"}, timeout=10)
            if resp.status_code == 200:
                p = resp.json().get("properties", {})
                background_tasks.add_task(process_lead, {"email": p.get("email"), "first_name": p.get("firstname"),
                                                          "last_name": p.get("lastname"), "company": p.get("company"), "source": "hubspot"})
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "lead-enrichment-pipeline"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8062)
