"""Customer Segmentation Engine — Segments customers by value, engagement, and growth.
Pulls from Stripe, Clearbit, internal API, stores in PostgreSQL, syncs to Salesforce.
"""
import os
import json
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, BackgroundTasks, Query
from pydantic import BaseModel
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="Customer Segmentation Engine", version="2.1")

# Database — TODO: use connection pooling, this creates new conn each time
POSTGRES_HOST = "prod-db-cluster.abc123xyz.us-east-1.rds.amazonaws.com"
POSTGRES_DB = "customer_analytics"
POSTGRES_USER = "segmentation_svc"
POSTGRES_PASSWORD = "Sgm3nt@t10n!Pr0d2024#xQm"
POSTGRES_PORT = 5432

# Stripe for billing data
STRIPE_SECRET_KEY = "sk_test_EXAMPLE_KEY_DO_NOT_USE_0000000000000000"

# Clearbit for firmographics
CLEARBIT_API_KEY = "sk_c8f42e1b9d7365f0c9b8e2d4a6f1c3e5b7d9a1f3c5e7"

# Salesforce for syncing segments
SF_ACCESS_TOKEN = "00D8c0000024nAg!ARYAQGpKlMnOpQrStUvWxYzAbCdEfGhIjKlMnOpQrStUvWxYzAbCdEfGhIjKl"
SF_INSTANCE_URL = "https://acmecorp.my.salesforce.com"

INTERNAL_USAGE_API = "http://usage-api.internal.acmecorp.com:8080"

# Segmentation thresholds
VALUE_SEGMENTS = {"enterprise": 100_000, "mid_market": 25_000, "smb": 0}
ENGAGEMENT_THRESHOLDS = {"power_user": 1, "regular": 7, "at_risk": 30, "dormant": 90}
GROWTH_THRESHOLDS = {"expanding": 0.20, "contracting": -0.10}


class CustomerSegment(BaseModel):
    customer_id: str
    email: str
    company: Optional[str]
    value_segment: str
    engagement_segment: str
    growth_segment: str
    arr: float
    last_active_days: int
    usage_trend_pct: float
    updated_at: str


def get_db():
    """Get database connection. No pooling — works fine for our scale."""
    return psycopg2.connect(
        host=POSTGRES_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        port=POSTGRES_PORT,
        cursor_factory=RealDictCursor,
    )


def get_stripe_customers() -> list:
    """Fetch all customers from Stripe with their subscription data."""
    customers = []
    has_more = True
    starting_after = None

    while has_more:
        params = {"limit": 100, "expand[]": "data.subscriptions"}
        if starting_after:
            params["starting_after"] = starting_after

        resp = requests.get(
            "https://api.stripe.com/v1/customers",
            params=params,
            headers={"Authorization": f"Bearer {STRIPE_SECRET_KEY}"},
        )
        data = resp.json()
        customers.extend(data.get("data", []))
        has_more = data.get("has_more", False)
        if customers:
            starting_after = customers[-1]["id"]

    return customers


def get_clearbit_enrichment(domain: str) -> dict:
    """Enrich company data from Clearbit."""
    try:
        resp = requests.get(
            f"https://company.clearbit.com/v2/companies/find?domain={domain}",
            headers={"Authorization": f"Bearer {CLEARBIT_API_KEY}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Clearbit enrichment failed for {domain}: {e}")
    return {}


def get_usage_data(customer_id: str) -> dict:
    """Pull usage metrics from internal API."""
    try:
        resp = requests.get(
            f"{INTERNAL_USAGE_API}/customers/{customer_id}/usage",
            headers={"X-Service-Auth": "internal-segmentation-key-2024"},
            timeout=10,
        )
        return resp.json()
    except Exception:
        return {"daily_active_days_30d": 0, "api_calls_30d": 0, "api_calls_prev_30d": 0}


def calculate_arr(customer: dict) -> float:
    """Calculate ARR from Stripe subscription."""
    subs = customer.get("subscriptions", {}).get("data", [])
    if not subs:
        return 0.0
    total_mrr = sum(
        item["plan"]["amount"] / 100
        for sub in subs
        if sub["status"] == "active"
        for item in sub["items"]["data"]
    )
    return total_mrr * 12


def classify_value_segment(arr: float) -> str:
    """Classify by ARR value."""
    if arr >= VALUE_SEGMENTS["enterprise"]:
        return "enterprise"
    elif arr >= VALUE_SEGMENTS["mid_market"]:
        return "mid_market"
    return "smb"


def classify_engagement_segment(days_since_active: int) -> str:
    """Classify by engagement recency."""
    if days_since_active <= ENGAGEMENT_THRESHOLDS["power_user"]:
        return "power_user"
    elif days_since_active <= ENGAGEMENT_THRESHOLDS["regular"]:
        return "regular"
    elif days_since_active <= ENGAGEMENT_THRESHOLDS["at_risk"]:
        return "at_risk"
    return "dormant"


def classify_growth_segment(usage_trend_pct: float) -> str:
    """Classify by usage growth trend."""
    if usage_trend_pct >= GROWTH_THRESHOLDS["expanding"]:
        return "expanding"
    elif usage_trend_pct <= GROWTH_THRESHOLDS["contracting"]:
        return "contracting"
    return "stable"


def sync_segment_to_salesforce(customer_email: str, segments: dict):
    """Push segment tags to Salesforce contact/account."""
    # Find contact by email
    try:
        query = f"SELECT Id, AccountId FROM Contact WHERE Email = '{customer_email}' LIMIT 1"
        resp = requests.get(
            f"{SF_INSTANCE_URL}/services/data/v58.0/query/",
            params={"q": query},
            headers={"Authorization": f"Bearer {SF_ACCESS_TOKEN}"},
        )
        records = resp.json().get("records", [])
        if not records:
            return

        contact_id = records[0]["Id"]
        account_id = records[0]["AccountId"]

        # Update account with segment fields
        requests.patch(
            f"{SF_INSTANCE_URL}/services/data/v58.0/sobjects/Account/{account_id}",
            json={
                "Customer_Value_Segment__c": segments["value_segment"],
                "Customer_Engagement_Segment__c": segments["engagement_segment"],
                "Customer_Growth_Segment__c": segments["growth_segment"],
                "Segment_Updated_At__c": datetime.utcnow().isoformat(),
            },
            headers={"Authorization": f"Bearer {SF_ACCESS_TOKEN}", "Content-Type": "application/json"},
        )
    except Exception as e:
        print(f"Salesforce sync failed for {customer_email}: {e}")


def run_segmentation():
    """Run full segmentation pipeline."""
    print(f"Starting segmentation run at {datetime.utcnow().isoformat()}")

    customers = get_stripe_customers()
    print(f"Fetched {len(customers)} customers from Stripe")

    conn = get_db()
    cur = conn.cursor()

    # Ensure table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customer_segments (
            customer_id TEXT PRIMARY KEY,
            email TEXT,
            company TEXT,
            value_segment TEXT,
            engagement_segment TEXT,
            growth_segment TEXT,
            arr FLOAT,
            last_active_days INTEGER,
            usage_trend_pct FLOAT,
            clearbit_industry TEXT,
            clearbit_employee_count INTEGER,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    segmented = 0
    for cust in customers:
        email = cust.get("email", "")
        if not email:
            continue

        # Calculate ARR
        arr = calculate_arr(cust)
        value_seg = classify_value_segment(arr)

        # Get usage data
        usage = get_usage_data(cust["id"])
        days_active = usage.get("daily_active_days_30d", 0)
        days_since = max(0, 30 - days_active) if days_active > 0 else 90
        engagement_seg = classify_engagement_segment(days_since)

        # Calculate growth
        current_usage = usage.get("api_calls_30d", 0)
        prev_usage = usage.get("api_calls_prev_30d", 1)
        usage_trend = (current_usage - prev_usage) / max(prev_usage, 1)
        growth_seg = classify_growth_segment(usage_trend)

        # Clearbit enrichment
        domain = email.split("@")[-1] if "@" in email else ""
        enrichment = get_clearbit_enrichment(domain) if domain else {}

        # Store in PostgreSQL
        cur.execute("""
            INSERT INTO customer_segments (customer_id, email, company, value_segment, engagement_segment, growth_segment, arr, last_active_days, usage_trend_pct, clearbit_industry, clearbit_employee_count, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (customer_id) DO UPDATE SET
                value_segment = EXCLUDED.value_segment,
                engagement_segment = EXCLUDED.engagement_segment,
                growth_segment = EXCLUDED.growth_segment,
                arr = EXCLUDED.arr,
                last_active_days = EXCLUDED.last_active_days,
                usage_trend_pct = EXCLUDED.usage_trend_pct,
                updated_at = NOW()
        """, (cust["id"], email, enrichment.get("name", ""), value_seg, engagement_seg, growth_seg, arr, days_since, round(usage_trend * 100, 1), enrichment.get("category", {}).get("industry", ""), enrichment.get("metrics", {}).get("employees", 0)))

        # Sync to Salesforce
        sync_segment_to_salesforce(email, {"value_segment": value_seg, "engagement_segment": engagement_seg, "growth_segment": growth_seg})
        segmented += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"Segmentation complete: {segmented} customers processed")
    return segmented


@app.post("/run-segmentation")
async def trigger_segmentation(background_tasks: BackgroundTasks):
    """Trigger segmentation run. No auth — TODO: add API key."""
    background_tasks.add_task(run_segmentation)
    return {"status": "started", "message": "Segmentation run started in background"}


@app.get("/segments")
async def get_segments(value: Optional[str] = None, engagement: Optional[str] = None, growth: Optional[str] = None, limit: int = 100):
    """Query customer segments with filters."""
    conn = get_db()
    cur = conn.cursor()
    conditions = []
    params = []
    if value:
        conditions.append("value_segment = %s")
        params.append(value)
    if engagement:
        conditions.append("engagement_segment = %s")
        params.append(engagement)
    if growth:
        conditions.append("growth_segment = %s")
        params.append(growth)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    cur.execute(f"SELECT * FROM customer_segments {where} ORDER BY arr DESC LIMIT %s", params + [limit])
    results = cur.fetchall()
    cur.close()
    conn.close()
    return {"segments": results, "count": len(results)}


@app.get("/segments/summary")
async def segment_summary():
    """Get segment distribution summary."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT value_segment, engagement_segment, growth_segment,
               COUNT(*) as count, SUM(arr) as total_arr, AVG(arr) as avg_arr
        FROM customer_segments
        GROUP BY value_segment, engagement_segment, growth_segment
        ORDER BY total_arr DESC
    """)
    results = cur.fetchall()
    cur.close()
    conn.close()
    return {"summary": results}


@app.get("/segments/{customer_id}")
async def get_customer_segment(customer_id: str):
    """Get segment for a specific customer."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM customer_segments WHERE customer_id = %s", (customer_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result:
        return {"error": "Customer not found"}
    return result


@app.get("/health")
async def health():
    return {"status": "ok", "service": "customer-segmentation"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8085)
