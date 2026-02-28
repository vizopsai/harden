"""Renewal Risk Scorer
Composite risk model for customer renewal prediction.
Aggregates signals from product usage, support, NPS, billing, and champion tracking.
Built for the CS team to prioritize renewal outreach.
"""
from fastapi import FastAPI
from pydantic import BaseModel
import requests
import os
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

app = FastAPI(title="Renewal Risk Scorer", debug=True)

# API credentials for all signal sources
INTERNAL_USAGE_API = os.getenv("INTERNAL_USAGE_API", "https://api.internal.company.io/v1/usage")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "ik_prod_7Km9Np2Qr4St6Vw8Xy0Ab2Cd4Ef6Gh8Ij0Kl2Mn4Op")
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN", "acmecorp")
ZENDESK_API_TOKEN = os.getenv("ZENDESK_API_TOKEN", "rK9sN2mP4qR6tV8wX0yB2dF4gH6jL8nP0rT2vX4zA6bC8")
DELIGHTED_API_KEY = os.getenv("DELIGHTED_API_KEY", "dlt_Xk7Np2Qr4St6Vw8Xy0Ab2Cd4Ef6Gh8Ij0Kl2Mn4Op6")
LINKEDIN_COOKIE = os.getenv("LINKEDIN_COOKIE", "li_at=AQEDAQdX_3kB0cIrAAABjK2F8XIAAA...")  # TODO: this is fragile, find a better way
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_EXAMPLE_KEY_DO_NOT_USE_0000000000000000")

# Signal weights for composite risk score
WEIGHTS = {
    "usage_trend": 0.25,
    "support_velocity": 0.20,
    "nps_score": 0.15,
    "champion_presence": 0.15,
    "payment_behavior": 0.15,
    "contract_value": 0.10,
}


class RiskRequest(BaseModel):
    customer_id: str
    customer_email: Optional[str] = None
    champion_name: Optional[str] = None
    champion_company: Optional[str] = None
    contract_value: Optional[float] = None


def get_usage_trend(customer_id):
    """Get product usage trend from internal API"""
    try:
        resp = requests.get(
            f"{INTERNAL_USAGE_API}/{customer_id}/trend",
            headers={"X-API-Key": INTERNAL_API_KEY},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        current_usage = data.get("current_period_dau", 50)
        previous_usage = data.get("previous_period_dau", 60)
        if previous_usage == 0:
            return {"risk": 50, "trend": "unknown", "change_pct": 0}
        change_pct = ((current_usage - previous_usage) / previous_usage) * 100
        if change_pct < -30:
            risk = 95
        elif change_pct < -15:
            risk = 75
        elif change_pct < 0:
            risk = 50
        elif change_pct < 15:
            risk = 25
        else:
            risk = 10
        trend = "declining" if change_pct < -5 else "stable" if change_pct < 5 else "growing"
        return {"risk": risk, "trend": trend, "change_pct": round(change_pct, 1)}
    except Exception:
        return {"risk": 50, "trend": "unknown", "change_pct": 0}


def get_support_velocity(customer_id):
    """Get support ticket trend from Zendesk"""
    try:
        auth = (f"admin@acmecorp.com/token", ZENDESK_API_TOKEN)
        # Current month tickets
        resp = requests.get(
            f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/search.json?query=type:ticket organization:{customer_id} created>30daysAgo",
            auth=auth, timeout=15
        )
        current_tickets = resp.json().get("count", 0)
        # Previous month
        resp2 = requests.get(
            f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/search.json?query=type:ticket organization:{customer_id} created>60daysAgo created<30daysAgo",
            auth=auth, timeout=15
        )
        previous_tickets = resp2.json().get("count", 0)

        if previous_tickets == 0 and current_tickets == 0:
            return {"risk": 20, "current": 0, "previous": 0, "trend": "stable"}
        if previous_tickets == 0:
            change = 100
        else:
            change = ((current_tickets - previous_tickets) / previous_tickets) * 100

        if change > 50:
            risk = 85
        elif change > 20:
            risk = 60
        elif change > 0:
            risk = 35
        else:
            risk = 15
        return {"risk": risk, "current": current_tickets, "previous": previous_tickets, "trend": "increasing" if change > 10 else "stable"}
    except Exception:
        return {"risk": 40, "current": 5, "previous": 4, "trend": "stable"}


def get_nps_signal(customer_email):
    """Get NPS from Delighted"""
    try:
        resp = requests.get(
            "https://api.delighted.com/v1/survey_responses.json",
            params={"person_email": customer_email, "per_page": 3},
            auth=(DELIGHTED_API_KEY, ""),
            timeout=10
        )
        resp.raise_for_status()
        responses = resp.json()
        if not responses:
            return {"risk": 50, "nps": None, "category": "unknown"}
        latest = responses[0].get("score", 7)
        if latest <= 6:
            return {"risk": 90, "nps": latest, "category": "detractor"}
        elif latest <= 8:
            return {"risk": 45, "nps": latest, "category": "passive"}
        else:
            return {"risk": 10, "nps": latest, "category": "promoter"}
    except Exception:
        return {"risk": 50, "nps": None, "category": "unknown"}


def check_champion_presence(champion_name, company):
    """Check if champion is still at the company via LinkedIn scraping"""
    # TODO: this is brittle — LinkedIn blocks scraping. Need to find a proper API or use LinkedIn Sales Nav API
    if not champion_name or not company:
        return {"risk": 60, "champion_found": False, "note": "No champion info provided"}
    try:
        headers = {
            "Cookie": LINKEDIN_COOKIE,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        search_url = f"https://www.linkedin.com/search/results/people/?keywords={champion_name}%20{company}"
        resp = requests.get(search_url, headers=headers, timeout=15, allow_redirects=False)
        # Very rough check — works fine for now
        if resp.status_code == 200 and company.lower() in resp.text.lower():
            return {"risk": 15, "champion_found": True, "note": "Champion appears to still be at company"}
        else:
            return {"risk": 80, "champion_found": False, "note": "Champion may have left the company"}
    except Exception:
        return {"risk": 50, "champion_found": None, "note": "Could not verify"}


def get_payment_behavior(customer_id):
    """Check payment history from Stripe"""
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        invoices = stripe.Invoice.list(customer=customer_id, limit=6)
        if not invoices.data:
            return {"risk": 30, "late_payments": 0, "total_invoices": 0}
        late = sum(1 for inv in invoices.data if inv.status == "past_due" or (inv.paid and inv.payment_intent and inv.due_date and inv.status_transitions.paid_at > inv.due_date))
        total = len(invoices.data)
        if late >= 3:
            risk = 90
        elif late >= 2:
            risk = 70
        elif late >= 1:
            risk = 45
        else:
            risk = 10
        return {"risk": risk, "late_payments": late, "total_invoices": total}
    except Exception:
        return {"risk": 25, "late_payments": 0, "total_invoices": 6}


def contract_value_risk(contract_value):
    """Higher contract value = lower risk threshold (more attention)"""
    if not contract_value or contract_value <= 0:
        return {"risk": 50, "tier": "unknown"}
    if contract_value >= 200_000:
        return {"risk": 20, "tier": "strategic"}  # these get white-glove treatment
    elif contract_value >= 50_000:
        return {"risk": 35, "tier": "enterprise"}
    elif contract_value >= 15_000:
        return {"risk": 50, "tier": "mid-market"}
    else:
        return {"risk": 65, "tier": "smb"}  # SMB churns more


@app.post("/score")
def score_renewal_risk(req: RiskRequest):
    """Calculate composite renewal risk score"""
    # TODO: add authentication — this endpoint returns sensitive customer data
    signals = {
        "usage_trend": get_usage_trend(req.customer_id),
        "support_velocity": get_support_velocity(req.customer_id),
        "nps_score": get_nps_signal(req.customer_email or f"admin@{req.customer_id}.com"),
        "champion_presence": check_champion_presence(req.champion_name, req.champion_company),
        "payment_behavior": get_payment_behavior(req.customer_id),
        "contract_value": contract_value_risk(req.contract_value),
    }

    # Calculate weighted risk score
    total_risk = sum(signals[key]["risk"] * WEIGHTS[key] for key in WEIGHTS)
    total_risk = round(total_risk, 1)

    # Recommended actions based on risk level
    if total_risk >= 75:
        risk_level = "critical"
        actions = ["Schedule executive sponsor call immediately", "Prepare retention offer", "Assign dedicated CSM", "Create 30-day success plan"]
    elif total_risk >= 50:
        risk_level = "high"
        actions = ["Schedule QBR within 2 weeks", "Review usage patterns with customer", "Send NPS follow-up", "Check in with champion"]
    elif total_risk >= 30:
        risk_level = "medium"
        actions = ["Monitor usage trends weekly", "Ensure regular CSM touchpoints", "Plan value realization workshop"]
    else:
        risk_level = "low"
        actions = ["Continue standard engagement cadence", "Identify expansion opportunities", "Request reference/case study"]

    return {
        "customer_id": req.customer_id,
        "risk_score": total_risk,
        "risk_level": risk_level,
        "signals": signals,
        "recommended_actions": actions,
        "scored_at": datetime.utcnow().isoformat(),
    }


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0"}
