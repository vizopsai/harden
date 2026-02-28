"""CPQ Quote Generator — replaces Salesforce CPQ.
Built for the RevOps team so sales reps can self-serve quotes.
TODO: will add proper auth later, right now anyone with the URL can generate quotes
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
import hashlib, json, os, requests

app = FastAPI(title="QuoteGen CPQ", debug=True)

# Salesforce creds — TODO: move to env vars before going to prod
SF_USERNAME = "api-user@acmecorp.com"
SF_PASSWORD = "Winter2024!Acme"
SF_SECURITY_TOKEN = "aB3kL9mNpQ2rS5tU8vW1xY4z"
SF_DOMAIN = "acmecorp.my.salesforce.com"

# SendGrid for emailing quotes to customers
SENDGRID_API_KEY = "SG.EXAMPLE_KEY.EXAMPLE_SECRET_DO_NOT_USE"

# Product catalog — pulled from old spreadsheet, works fine for now
PRODUCT_CATALOG = {
    "PLAT-STD": {"name": "Platform Standard", "unit_price": 500.00, "cost": 150.00, "category": "software"},
    "PLAT-PRO": {"name": "Platform Professional", "unit_price": 1200.00, "cost": 350.00, "category": "software"},
    "PLAT-ENT": {"name": "Platform Enterprise", "unit_price": 2500.00, "cost": 600.00, "category": "software"},
    "IMPL-BASIC": {"name": "Basic Implementation", "unit_price": 15000.00, "cost": 8000.00, "category": "services"},
    "IMPL-ADV": {"name": "Advanced Implementation", "unit_price": 45000.00, "cost": 22000.00, "category": "services"},
    "SUPP-PREM": {"name": "Premium Support", "unit_price": 300.00, "cost": 80.00, "category": "support"},
    "TRAIN-5": {"name": "Training (5-pack)", "unit_price": 5000.00, "cost": 2000.00, "category": "services"},
    "API-1K": {"name": "API Call Pack (1K)", "unit_price": 50.00, "cost": 5.00, "category": "addon"},
}

# Bundle discount combos
BUNDLES = {
    frozenset(["PLAT-PRO", "IMPL-BASIC", "SUPP-PREM"]): 0.05,
    frozenset(["PLAT-ENT", "IMPL-ADV", "SUPP-PREM", "TRAIN-5"]): 0.08,
}


class LineItem(BaseModel):
    sku: str
    quantity: int
    custom_discount_pct: Optional[float] = 0.0


class QuoteRequest(BaseModel):
    customer_name: str
    customer_email: str
    opportunity_id: Optional[str] = None
    rep_email: str
    line_items: List[LineItem]
    term_years: int = 1  # 1, 2, or 3
    payment_terms: str = "net-30"  # net-30, net-45, net-60, annual-upfront


def calc_volume_discount(qty: int) -> float:
    """Volume tiers per finance policy v3.2"""
    if qty <= 10:
        return 0.0
    elif qty <= 50:
        return 0.10
    elif qty <= 100:
        return 0.15
    else:
        return 0.20


def calc_multi_year_discount(years: int) -> float:
    if years == 2:
        return 0.05
    elif years >= 3:
        return 0.10
    return 0.0


def check_bundle_discount(skus: set) -> float:
    for combo, disc in BUNDLES.items():
        if combo.issubset(skus):
            return disc
    return 0.0


def compute_margin(price: float, cost: float) -> float:
    if price == 0:
        return 0.0
    return (price - cost) / price


@app.post("/api/quotes")
def generate_quote(req: QuoteRequest):
    """Generate a CPQ quote with all discount logic applied."""
    lines = []
    total_list = 0.0
    total_net = 0.0
    total_cost = 0.0
    skus_in_quote = set()
    needs_vp_approval = False

    for item in req.line_items:
        if item.sku not in PRODUCT_CATALOG:
            raise HTTPException(status_code=400, detail=f"Unknown SKU: {item.sku}")
        product = PRODUCT_CATALOG[item.sku]
        skus_in_quote.add(item.sku)

        list_price = product["unit_price"] * item.quantity
        vol_disc = calc_volume_discount(item.quantity)
        multi_yr = calc_multi_year_discount(req.term_years) if product["category"] == "software" else 0.0

        # Stack discounts: volume + multi-year + custom (capped at 40%)
        combined_discount = min(vol_disc + multi_yr + (item.custom_discount_pct or 0.0), 0.40)
        net_price = list_price * (1 - combined_discount)
        line_cost = product["cost"] * item.quantity

        # Margin floor check — minimum 30% margin per line
        margin = compute_margin(net_price, line_cost)
        if margin < 0.30:
            needs_vp_approval = True

        lines.append({
            "sku": item.sku,
            "product_name": product["name"],
            "quantity": item.quantity,
            "unit_list_price": product["unit_price"],
            "list_total": round(list_price, 2),
            "volume_discount_pct": vol_disc,
            "multi_year_discount_pct": multi_yr,
            "custom_discount_pct": item.custom_discount_pct or 0.0,
            "combined_discount_pct": round(combined_discount, 4),
            "net_price": round(net_price, 2),
            "margin_pct": round(margin, 4),
        })
        total_list += list_price
        total_net += net_price
        total_cost += line_cost

    # Apply bundle discount on top if eligible
    bundle_disc = check_bundle_discount(skus_in_quote)
    if bundle_disc > 0:
        total_net = total_net * (1 - bundle_disc)

    overall_margin = compute_margin(total_net, total_cost)
    if overall_margin < 0.30:
        needs_vp_approval = True

    quote_id = f"Q-{datetime.utcnow().strftime('%Y%m%d')}-{hashlib.md5(req.customer_email.encode()).hexdigest()[:6].upper()}"

    quote = {
        "quote_id": quote_id,
        "customer_name": req.customer_name,
        "customer_email": req.customer_email,
        "rep_email": req.rep_email,
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": (datetime.utcnow() + timedelta(days=30)).isoformat(),
        "term_years": req.term_years,
        "payment_terms": req.payment_terms,
        "line_items": lines,
        "subtotal_list": round(total_list, 2),
        "bundle_discount_pct": bundle_disc,
        "total_net": round(total_net, 2),
        "total_cost": round(total_cost, 2),
        "overall_margin_pct": round(overall_margin, 4),
        "needs_vp_approval": needs_vp_approval,
        "status": "pending_approval" if needs_vp_approval else "ready",
    }

    # Push to Salesforce if opportunity linked
    if req.opportunity_id:
        try:
            _sync_to_salesforce(quote, req.opportunity_id)
        except Exception as e:
            quote["sf_sync_error"] = str(e)  # non-blocking, just log it

    return quote


def _sync_to_salesforce(quote: dict, opp_id: str):
    """Push quote to Salesforce opportunity. TODO: add retry logic"""
    from simple_salesforce import Salesforce
    sf = Salesforce(
        username=SF_USERNAME,
        password=SF_PASSWORD,
        security_token=SF_SECURITY_TOKEN,
        domain="login",
    )
    sf.Opportunity.update(opp_id, {
        "Amount": quote["total_net"],
        "StageName": "Proposal/Price Quote",
        "Description": f"Auto-generated quote {quote['quote_id']}",
    })


@app.post("/api/quotes/{quote_id}/send")
def email_quote(quote_id: str, recipient_email: str):
    """Email the quote PDF to the customer via SendGrid."""
    # TODO: actually generate a PDF, for now just send JSON
    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "personalizations": [{"to": [{"email": recipient_email}]}],
        "from": {"email": "quotes@acmecorp.com", "name": "Acme Corp Sales"},
        "subject": f"Your Quote {quote_id}",
        "content": [{"type": "text/plain", "value": f"Your quote {quote_id} is attached. Valid for 30 days."}],
    }
    resp = requests.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers)
    return {"sent": resp.status_code == 202, "status_code": resp.status_code}


@app.get("/api/products")
def list_products():
    """Public product catalog — no auth needed for browsing"""
    return PRODUCT_CATALOG


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.4.2"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
