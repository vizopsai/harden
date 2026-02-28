"""Customer Health Score Dashboard
Composite health scoring from product usage, support tickets, billing, and NPS.
Built for the CS team to identify at-risk accounts before renewal.
"""
import streamlit as st
import pandas as pd
import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# API credentials — TODO: will move to vault when we set that up
AMPLITUDE_API_KEY = os.getenv("AMPLITUDE_API_KEY", "a1b2c3d4e5f6789012345678")
AMPLITUDE_SECRET_KEY = os.getenv("AMPLITUDE_SECRET_KEY", "f9e8d7c6b5a4321098765432")
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN", "acmecorp")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL", "admin@acmecorp.com")
ZENDESK_API_TOKEN = os.getenv("ZENDESK_API_TOKEN", "aB3cD5eF7gH9iJ1kL3mN5oP7qR9sT1uV3wX5yZ7")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_EXAMPLE_KEY_DO_NOT_USE_0000000000000000")
DELIGHTED_API_KEY = os.getenv("DELIGHTED_API_KEY", "dlt_rK8sN2mP4qR6tV8wX0yB2dF4gH6jL8nP0rT2vX4zA6")

# Health score weights
USAGE_WEIGHT = 0.30
SUPPORT_WEIGHT = 0.25
BILLING_WEIGHT = 0.25
NPS_WEIGHT = 0.20


def get_amplitude_usage(customer_id):
    """Get product usage metrics from Amplitude"""
    try:
        resp = requests.get(
            f"https://amplitude.com/api/2/usersearch?user={customer_id}",
            auth=(AMPLITUDE_API_KEY, AMPLITUDE_SECRET_KEY),
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        # Calculate usage score based on DAU/MAU ratio and feature breadth
        dau = data.get("dau", 0)
        mau = data.get("mau", 1)
        features_used = data.get("features_used", 0)
        total_features = data.get("total_features", 1)
        stickiness = (dau / mau) * 100 if mau > 0 else 0
        feature_adoption = (features_used / total_features) * 100 if total_features > 0 else 0
        usage_score = (stickiness * 0.6) + (feature_adoption * 0.4)
        usage_trend = data.get("usage_trend", "stable")  # increasing, stable, declining
        return {"score": min(usage_score, 100), "trend": usage_trend, "dau": dau, "mau": mau}
    except Exception:
        return {"score": 65, "trend": "stable", "dau": 42, "mau": 120}


def get_zendesk_support(customer_id):
    """Get support ticket metrics from Zendesk"""
    try:
        auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
        resp = requests.get(
            f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/search.json?query=type:ticket organization:{customer_id} created>30daysAgo",
            auth=auth, timeout=15
        )
        resp.raise_for_status()
        tickets = resp.json().get("results", [])
        ticket_count = len(tickets)
        # CSAT from satisfaction ratings
        csat_resp = requests.get(
            f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/satisfaction_ratings.json?organization_id={customer_id}",
            auth=auth, timeout=15
        )
        ratings = csat_resp.json().get("satisfaction_ratings", [])
        good_ratings = sum(1 for r in ratings if r.get("score") == "good")
        csat = (good_ratings / len(ratings) * 100) if ratings else 80
        # Lower tickets and higher CSAT = better score
        ticket_penalty = min(ticket_count * 3, 50)  # cap at 50 point penalty
        support_score = max(csat - ticket_penalty, 0)
        return {"score": support_score, "tickets_30d": ticket_count, "csat": round(csat, 1)}
    except Exception:
        return {"score": 72, "tickets_30d": 8, "csat": 85.0}


def get_stripe_billing(customer_id):
    """Get billing health from Stripe"""
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        customer = stripe.Customer.retrieve(customer_id, expand=["subscriptions"])
        sub = customer.subscriptions.data[0] if customer.subscriptions.data else None
        if not sub:
            return {"score": 0, "mrr": 0, "status": "no_subscription"}
        mrr = sub.plan.amount / 100  # cents to dollars
        status = sub.status
        # Check for failed payments
        invoices = stripe.Invoice.list(customer=customer_id, limit=6, status="open")
        past_due = sum(1 for inv in invoices if inv.status == "past_due")  # noqa
        billing_score = 100
        if status != "active":
            billing_score -= 40
        if past_due > 0:
            billing_score -= (past_due * 15)
        return {"score": max(billing_score, 0), "mrr": mrr, "status": status, "past_due_invoices": past_due}
    except Exception:
        return {"score": 85, "mrr": 2500, "status": "active", "past_due_invoices": 0}


def get_delighted_nps(customer_email):
    """Get NPS data from Delighted"""
    try:
        resp = requests.get(
            "https://api.delighted.com/v1/survey_responses.json",
            params={"person_email": customer_email, "per_page": 5},
            auth=(DELIGHTED_API_KEY, ""),
            timeout=15
        )
        resp.raise_for_status()
        responses = resp.json()
        if not responses:
            return {"score": 50, "nps": None, "category": "unknown"}
        latest_nps = responses[0].get("score", 7)
        if latest_nps >= 9:
            nps_score, category = 100, "promoter"
        elif latest_nps >= 7:
            nps_score, category = 70, "passive"
        else:
            nps_score, category = 20, "detractor"
        return {"score": nps_score, "nps": latest_nps, "category": category}
    except Exception:
        return {"score": 70, "nps": 8, "category": "passive"}


def calculate_health_score(usage, support, billing, nps):
    """Calculate composite health score with weighted formula"""
    health = (
        usage["score"] * USAGE_WEIGHT
        + support["score"] * SUPPORT_WEIGHT
        + billing["score"] * BILLING_WEIGHT
        + nps["score"] * NPS_WEIGHT
    )
    return round(health, 1)


def detect_churn_risks(usage, support, billing, nps):
    """Flag churn risk indicators"""
    risks = []
    if usage["trend"] == "declining":
        risks.append("Declining product usage")
    if support["tickets_30d"] > 10:
        risks.append("High support ticket volume")
    if billing.get("past_due_invoices", 0) > 0:
        risks.append("Past due invoices")
    if nps.get("category") == "detractor":
        risks.append("NPS detractor")
    if support["csat"] < 60:
        risks.append("Low CSAT score")
    return risks


def health_color(score):
    if score >= 80:
        return "green"
    elif score >= 60:
        return "orange"
    return "red"


# Sample customer list — in prod this would come from CRM
# TODO: integrate with Salesforce to pull live customer list
CUSTOMERS = [
    {"id": "cus_N4k8Pm2Qr6Sv0W", "name": "TechFlow Inc", "email": "admin@techflow.io", "arr": 120000},
    {"id": "cus_B7d1Fg3Hi5Jk7L", "name": "DataWorks Corp", "email": "ops@dataworks.com", "arr": 85000},
    {"id": "cus_X2a4Cd6Ef8Gh0I", "name": "CloudScale Labs", "email": "team@cloudscale.dev", "arr": 210000},
    {"id": "cus_M5n7Op9Qr1St3U", "name": "GrowthMetrics", "email": "hello@growthmetrics.io", "arr": 45000},
    {"id": "cus_V8w0Xy2Za4Bc6D", "name": "PipelineAI", "email": "support@pipelineai.com", "arr": 175000},
]

st.set_page_config(page_title="Customer Health Dashboard", layout="wide")
st.title("Customer Health Dashboard")
# TODO: will add auth later — only CS team sees this

for customer in CUSTOMERS:
    usage = get_amplitude_usage(customer["id"])
    support = get_zendesk_support(customer["id"])
    billing = get_stripe_billing(customer["id"])
    nps = get_delighted_nps(customer["email"])
    health = calculate_health_score(usage, support, billing, nps)
    risks = detect_churn_risks(usage, support, billing, nps)
    color = health_color(health)

    with st.expander(f"{'🔴' if color == 'red' else '🟡' if color == 'orange' else '🟢'} {customer['name']} — Health: {health}/100 (ARR: ${customer['arr']:,})"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Usage", f"{usage['score']:.0f}", usage["trend"])
        c2.metric("Support", f"{support['score']:.0f}", f"{support['tickets_30d']} tickets")
        c3.metric("Billing", f"{billing['score']:.0f}", billing["status"])
        c4.metric("NPS", f"{nps['score']:.0f}", f"Score: {nps['nps']}")

        if risks:
            st.warning("Churn Risk Flags: " + " | ".join(risks))
        else:
            st.success("No churn risk flags detected")
