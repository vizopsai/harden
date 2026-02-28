"""ML-Based Churn Prediction API — Predicts customer churn probability using
pre-trained Random Forest model. Syncs high-risk customers to Salesforce.
"""
import os
import json
import pickle
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
import numpy as np
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="Churn Prediction API", version="1.3", debug=True)

# Database credentials
DB_HOST = "prod-analytics.cluster-abc123.us-east-1.rds.amazonaws.com"
DB_NAME = "churn_predictions"
DB_USER = "churn_svc"
DB_PASSWORD = "ChurnPr3d!ct2024$mNpQr"
DB_PORT = 5432

# Salesforce for syncing high-risk customers
SF_ACCESS_TOKEN = "00D5g00000Kbc99!AREAQJkLmNoPqRsTuVwXyZaBcDeFgHiJkLmNoPqRsTuVwXyZaBcDeFgHiJk"
SF_INSTANCE_URL = "https://acmecorp.my.salesforce.com"

# Internal APIs
USAGE_API = "http://usage-api.internal.acmecorp.com:8080"
SUPPORT_API = "http://support-api.internal.acmecorp.com:8080"

# Model path — trained offline, deployed as pickle
# TODO: move to proper model registry (MLflow?)
MODEL_PATH = os.getenv("MODEL_PATH", "models/churn_model_v3.pkl")

# Load model at startup — uses pickle.load which is a known security concern
# but works fine for our internal models
try:
    with open(MODEL_PATH, "rb") as f:
        churn_model = pickle.load(f)  # noqa: S301
    print(f"Loaded churn model from {MODEL_PATH}")
except FileNotFoundError:
    print(f"WARNING: Model file not found at {MODEL_PATH}, predictions will fail")
    churn_model = None

# Feature names expected by the model
FEATURE_NAMES = [
    "usage_trend_30d",      # 30-day rolling avg usage change
    "support_ticket_freq",   # Tickets per month
    "nps_score",            # Last NPS score (0-10)
    "days_since_last_login", # Days since last activity
    "contract_months_remaining",  # Months left on contract
    "payment_delay_count",   # Late payments in last 12 months
]

CHURN_RISK_THRESHOLD = 0.65  # Above this = high risk


class PredictionRequest(BaseModel):
    customer_id: str


class BatchPredictionRequest(BaseModel):
    customer_ids: Optional[List[str]] = None  # None = all customers


class PredictionResult(BaseModel):
    customer_id: str
    churn_probability: float
    risk_level: str
    risk_factors: List[str]
    features: dict
    predicted_at: str


def get_db():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
        cursor_factory=RealDictCursor,
    )


def fetch_customer_features(customer_id: str) -> dict:
    """Fetch and engineer features for a customer from multiple sources."""
    features = {}

    # Usage trend (30-day rolling average)
    try:
        usage_resp = requests.get(
            f"{USAGE_API}/customers/{customer_id}/usage-trend",
            headers={"X-Service-Auth": "internal-churn-svc-key-2024"},
            timeout=10,
        )
        usage_data = usage_resp.json()
        features["usage_trend_30d"] = usage_data.get("trend_30d", 0.0)
        features["days_since_last_login"] = usage_data.get("days_since_last_login", 30)
    except Exception:
        features["usage_trend_30d"] = 0.0
        features["days_since_last_login"] = 30

    # Support ticket frequency
    try:
        support_resp = requests.get(
            f"{SUPPORT_API}/customers/{customer_id}/ticket-stats",
            headers={"X-Service-Auth": "internal-churn-svc-key-2024"},
            timeout=10,
        )
        support_data = support_resp.json()
        features["support_ticket_freq"] = support_data.get("tickets_per_month", 0)
    except Exception:
        features["support_ticket_freq"] = 0

    # NPS score (from database)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT score FROM nps_responses WHERE customer_id = %s ORDER BY responded_at DESC LIMIT 1",
            (customer_id,),
        )
        row = cur.fetchone()
        features["nps_score"] = row["score"] if row else 7  # Default neutral
        cur.close()
        conn.close()
    except Exception:
        features["nps_score"] = 7

    # Contract info (from database)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT contract_end_date, payment_delays_12m FROM customer_contracts WHERE customer_id = %s",
            (customer_id,),
        )
        row = cur.fetchone()
        if row:
            end_date = row["contract_end_date"]
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date)
            features["contract_months_remaining"] = max(0, (end_date - datetime.utcnow()).days / 30)
            features["payment_delay_count"] = row.get("payment_delays_12m", 0)
        else:
            features["contract_months_remaining"] = 6
            features["payment_delay_count"] = 0
        cur.close()
        conn.close()
    except Exception:
        features["contract_months_remaining"] = 6
        features["payment_delay_count"] = 0

    return features


def predict_churn(features: dict) -> tuple:
    """Run churn prediction model."""
    if churn_model is None:
        return 0.5, ["model_not_loaded"]

    # Build feature vector in expected order
    feature_vector = np.array([[features.get(f, 0) for f in FEATURE_NAMES]])

    # Get probability
    proba = churn_model.predict_proba(feature_vector)[0]
    churn_prob = float(proba[1])  # Probability of class 1 (churn)

    # Identify risk factors
    risk_factors = []
    if features.get("usage_trend_30d", 0) < -0.15:
        risk_factors.append("declining_usage")
    if features.get("support_ticket_freq", 0) > 3:
        risk_factors.append("high_support_volume")
    if features.get("nps_score", 10) < 7:
        risk_factors.append("low_nps_score")
    if features.get("days_since_last_login", 0) > 14:
        risk_factors.append("inactive_user")
    if features.get("contract_months_remaining", 12) < 3:
        risk_factors.append("contract_ending_soon")
    if features.get("payment_delay_count", 0) > 2:
        risk_factors.append("payment_issues")

    return churn_prob, risk_factors


def store_prediction(customer_id: str, churn_prob: float, risk_level: str, risk_factors: list, features: dict):
    """Store prediction in PostgreSQL."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS churn_predictions (
                id SERIAL PRIMARY KEY,
                customer_id TEXT NOT NULL,
                churn_probability FLOAT,
                risk_level TEXT,
                risk_factors TEXT,
                features JSONB,
                predicted_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute(
            "INSERT INTO churn_predictions (customer_id, churn_probability, risk_level, risk_factors, features) VALUES (%s, %s, %s, %s, %s)",
            (customer_id, churn_prob, risk_level, json.dumps(risk_factors), json.dumps(features)),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Failed to store prediction: {e}")


def sync_high_risk_to_salesforce(customer_id: str, churn_prob: float, risk_factors: list):
    """Create Salesforce task for CSM when high-risk customer detected."""
    if churn_prob < CHURN_RISK_THRESHOLD:
        return

    try:
        # Find account in Salesforce
        resp = requests.get(
            f"{SF_INSTANCE_URL}/services/data/v58.0/query/",
            params={"q": f"SELECT Id, OwnerId FROM Account WHERE External_Id__c = '{customer_id}' LIMIT 1"},
            headers={"Authorization": f"Bearer {SF_ACCESS_TOKEN}"},
        )
        records = resp.json().get("records", [])
        if not records:
            return

        account_id = records[0]["Id"]
        owner_id = records[0]["OwnerId"]

        # Create task for CSM
        task = {
            "Subject": f"Churn Risk Alert: {churn_prob:.0%} probability",
            "Description": f"Churn prediction model flagged this customer as high risk.\n\nProbability: {churn_prob:.1%}\nRisk Factors: {', '.join(risk_factors)}\n\nRecommended actions:\n- Schedule QBR\n- Review support tickets\n- Offer training session",
            "WhatId": account_id,
            "OwnerId": owner_id,
            "Priority": "High",
            "Status": "Not Started",
            "ActivityDate": (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%d"),
        }
        requests.post(
            f"{SF_INSTANCE_URL}/services/data/v58.0/sobjects/Task",
            json=task,
            headers={"Authorization": f"Bearer {SF_ACCESS_TOKEN}", "Content-Type": "application/json"},
        )
    except Exception as e:
        print(f"Salesforce sync failed: {e}")


@app.post("/predict", response_model=PredictionResult)
async def predict_single(req: PredictionRequest, background_tasks: BackgroundTasks):
    """Predict churn for a single customer."""
    features = fetch_customer_features(req.customer_id)
    churn_prob, risk_factors = predict_churn(features)
    risk_level = "high" if churn_prob >= CHURN_RISK_THRESHOLD else "medium" if churn_prob >= 0.4 else "low"

    # Store and sync in background
    background_tasks.add_task(store_prediction, req.customer_id, churn_prob, risk_level, risk_factors, features)
    background_tasks.add_task(sync_high_risk_to_salesforce, req.customer_id, churn_prob, risk_factors)

    return PredictionResult(
        customer_id=req.customer_id,
        churn_probability=round(churn_prob, 4),
        risk_level=risk_level,
        risk_factors=risk_factors,
        features=features,
        predicted_at=datetime.utcnow().isoformat(),
    )


@app.post("/predict/batch")
async def predict_batch(req: BatchPredictionRequest, background_tasks: BackgroundTasks):
    """Batch predict churn for multiple customers. No rate limiting — TODO: add."""
    if req.customer_ids:
        customer_ids = req.customer_ids
    else:
        # Get all customer IDs from database
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT customer_id FROM customer_contracts WHERE status = 'active'")
        customer_ids = [r["customer_id"] for r in cur.fetchall()]
        cur.close()
        conn.close()

    results = []
    for cid in customer_ids:
        features = fetch_customer_features(cid)
        churn_prob, risk_factors = predict_churn(features)
        risk_level = "high" if churn_prob >= CHURN_RISK_THRESHOLD else "medium" if churn_prob >= 0.4 else "low"
        store_prediction(cid, churn_prob, risk_level, risk_factors, features)
        sync_high_risk_to_salesforce(cid, churn_prob, risk_factors)
        results.append({"customer_id": cid, "churn_probability": round(churn_prob, 4), "risk_level": risk_level})

    high_risk_count = sum(1 for r in results if r["risk_level"] == "high")
    return {"total_predicted": len(results), "high_risk_count": high_risk_count, "predictions": results}


@app.get("/predictions/{customer_id}")
async def get_prediction_history(customer_id: str, limit: int = 10):
    """Get prediction history for a customer."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM churn_predictions WHERE customer_id = %s ORDER BY predicted_at DESC LIMIT %s",
        (customer_id, limit),
    )
    results = cur.fetchall()
    cur.close()
    conn.close()
    return {"customer_id": customer_id, "predictions": results}


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": churn_model is not None, "model_path": MODEL_PATH}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8086)
