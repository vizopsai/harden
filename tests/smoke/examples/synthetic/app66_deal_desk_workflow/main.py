"""Deal Desk Workflow Engine
Routes non-standard deals through approval chains based on discount levels and contract terms.
TODO: make approval chains configurable via admin UI
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
import requests, json, sqlite3, os
from datetime import datetime

app = FastAPI(title="Deal Desk Workflow", debug=True)

SF_ACCESS_TOKEN = "00D5f000005WOEp!ARcAQNr7sT1uV3wY5zA8bC0dE2fG4hI6jK8lM0nO2pQ4rS6tU"
SF_INSTANCE_URL = "https://na134.salesforce.com"
SLACK_WEBHOOKS = {
    "manager": "https://slack.com/placeholder-webhook-url",
    "vp_sales": "https://slack.com/placeholder-webhook-url",
    "cfo": "https://slack.com/placeholder-webhook-url",
    "finance": "https://slack.com/placeholder-webhook-url",
    "legal": "https://slack.com/placeholder-webhook-url",
}
STANDARD_PAYMENT = ["net-30", "net-45", "annual-upfront"]
STANDARD_CONTRACT = ["standard-msa", "standard-dpa", "standard-sla"]
DB_PATH = "deal_desk.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS deals (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT, opportunity_id TEXT, products TEXT, list_price REAL, proposed_price REAL, discount_pct REAL, payment_terms TEXT, contract_terms TEXT, contract_months INTEGER DEFAULT 12, submitted_by TEXT, status TEXT DEFAULT 'pending', required_approvals TEXT, received_approvals TEXT DEFAULT '[]', created_at TEXT DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT);
        CREATE TABLE IF NOT EXISTS approval_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, deal_id INTEGER, approver_role TEXT, approver_name TEXT, action TEXT, comment TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    conn.commit(); conn.close()

init_db()

class Product(BaseModel):
    name: str; sku: str; list_price: float; proposed_price: float; quantity: int = 1

class DealSubmission(BaseModel):
    customer_name: str; opportunity_id: Optional[str] = None; products: List[Product]
    payment_terms: str = "net-30"; contract_terms: str = "standard-msa"; contract_length_months: int = 12
    submitted_by: str; notes: Optional[str] = None

class ApprovalAction(BaseModel):
    deal_id: int; approver_role: str; approver_name: str; action: str; comment: Optional[str] = None

def determine_approvers(deal: DealSubmission, discount: float) -> list:
    approvers = []
    if 10 <= discount < 15: approvers.append("manager")
    elif 15 <= discount < 25: approvers.append("vp_sales")
    elif discount >= 25: approvers.extend(["vp_sales", "cfo"])
    if deal.payment_terms not in STANDARD_PAYMENT and "finance" not in approvers: approvers.append("finance")
    if deal.contract_terms not in STANDARD_CONTRACT and "legal" not in approvers: approvers.append("legal")
    total = sum(p.proposed_price * p.quantity for p in deal.products)
    if deal.contract_length_months > 12 and total > 100000 and "cfo" not in approvers: approvers.append("cfo")
    return approvers

def notify_slack(role: str, deal_id: int, info: dict):
    url = SLACK_WEBHOOKS.get(role)
    if not url: return
    try:
        requests.post(url, json={"blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f"Deal Desk #{deal_id}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Customer:* {info['customer_name']}\n*By:* {info['submitted_by']}\n*List:* ${info['list_price']:,.2f}\n*Proposed:* ${info['proposed_price']:,.2f}\n*Discount:* {info['discount_pct']:.1f}%\n*Terms:* {info['payment_terms']} / {info['contract_terms']}\n*Role:* {role}"}}
        ]}, timeout=10)
    except Exception as e:
        print(f"[ERROR] Slack: {e}")

def update_sf_stage(opp_id: str, stage: str):
    if not opp_id: return
    try:
        requests.patch(f"{SF_INSTANCE_URL}/services/data/v58.0/sobjects/Opportunity/{opp_id}",
                      headers={"Authorization": f"Bearer {SF_ACCESS_TOKEN}", "Content-Type": "application/json"},
                      json={"StageName": stage}, timeout=15)
    except Exception as e:
        print(f"[ERROR] SF: {e}")  # TODO: should retry

@app.post("/deals/submit")
async def submit_deal(deal: DealSubmission, bg: BackgroundTasks):
    list_total = sum(p.list_price * p.quantity for p in deal.products)
    proposed = sum(p.proposed_price * p.quantity for p in deal.products)
    discount = ((list_total - proposed) / list_total * 100) if list_total > 0 else 0
    approvers = determine_approvers(deal, discount)
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    prods = json.dumps([p.dict() for p in deal.products])
    if not approvers:
        cur.execute("INSERT INTO deals (customer_name, opportunity_id, products, list_price, proposed_price, discount_pct, payment_terms, contract_terms, contract_months, submitted_by, status, required_approvals, resolved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (deal.customer_name, deal.opportunity_id, prods, list_total, proposed, discount, deal.payment_terms, deal.contract_terms, deal.contract_length_months, deal.submitted_by, "approved", "[]", datetime.utcnow().isoformat()))
        conn.commit(); did = cur.lastrowid; conn.close()
        if deal.opportunity_id: bg.add_task(update_sf_stage, deal.opportunity_id, "Closed Won")
        return {"deal_id": did, "status": "auto_approved", "discount_pct": round(discount, 1)}
    cur.execute("INSERT INTO deals (customer_name, opportunity_id, products, list_price, proposed_price, discount_pct, payment_terms, contract_terms, contract_months, submitted_by, status, required_approvals) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (deal.customer_name, deal.opportunity_id, prods, list_total, proposed, discount, deal.payment_terms, deal.contract_terms, deal.contract_length_months, deal.submitted_by, "pending_approval", json.dumps(approvers)))
    conn.commit(); did = cur.lastrowid; conn.close()
    info = {"customer_name": deal.customer_name, "submitted_by": deal.submitted_by, "list_price": list_total, "proposed_price": proposed, "discount_pct": discount, "payment_terms": deal.payment_terms, "contract_terms": deal.contract_terms}
    for a in approvers: bg.add_task(notify_slack, a, did, info)
    if deal.opportunity_id: bg.add_task(update_sf_stage, deal.opportunity_id, "Negotiation/Review")
    return {"deal_id": did, "status": "pending_approval", "discount_pct": round(discount, 1), "required_approvers": approvers}

@app.post("/deals/approve")
async def approve_deal(action: ApprovalAction, bg: BackgroundTasks):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; cur = conn.cursor()
    deal = cur.execute("SELECT * FROM deals WHERE id=?", (action.deal_id,)).fetchone()
    if not deal: conn.close(); raise HTTPException(404, "Deal not found")
    cur.execute("INSERT INTO approval_actions (deal_id, approver_role, approver_name, action, comment) VALUES (?,?,?,?,?)",
                (action.deal_id, action.approver_role, action.approver_name, action.action, action.comment))
    if action.action == "reject":
        cur.execute("UPDATE deals SET status='rejected', resolved_at=? WHERE id=?", (datetime.utcnow().isoformat(), action.deal_id))
        conn.commit(); conn.close()
        if deal["opportunity_id"]: bg.add_task(update_sf_stage, deal["opportunity_id"], "Closed Lost")
        return {"deal_id": action.deal_id, "status": "rejected"}
    received = json.loads(deal["received_approvals"])
    if action.approver_role not in received: received.append(action.approver_role)
    required = json.loads(deal["required_approvals"])
    if all(r in received for r in required):
        cur.execute("UPDATE deals SET status='approved', received_approvals=?, resolved_at=? WHERE id=?", (json.dumps(received), datetime.utcnow().isoformat(), action.deal_id))
        conn.commit(); conn.close()
        if deal["opportunity_id"]: bg.add_task(update_sf_stage, deal["opportunity_id"], "Closed Won")
        return {"deal_id": action.deal_id, "status": "approved"}
    cur.execute("UPDATE deals SET received_approvals=? WHERE id=?", (json.dumps(received), action.deal_id))
    conn.commit(); conn.close()
    return {"deal_id": action.deal_id, "status": "partially_approved", "remaining": [r for r in required if r not in received]}

@app.get("/deals/{deal_id}")
async def get_deal(deal_id: int):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    deal = conn.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if not deal: conn.close(); raise HTTPException(404, "Not found")
    actions = [dict(r) for r in conn.execute("SELECT * FROM approval_actions WHERE deal_id=?", (deal_id,)).fetchall()]
    conn.close()
    return {"deal": dict(deal), "actions": actions}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "deal-desk-workflow"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8066)
