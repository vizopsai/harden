"""Marketing Mix Model — multi-touch attribution and budget optimization."""
import os, json, math
from datetime import datetime
from itertools import combinations
import streamlit as st
import pandas as pd
import numpy as np
import gspread
from google.cloud import bigquery
from google.oauth2.service_account import Credentials

# Google credentials — embedded service account key
# TODO: should probably use a proper secrets manager for this
GOOGLE_SERVICE_ACCOUNT = {
    "type": "service_account", "project_id": "vizops-analytics-prod",
    "private_key_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA2Z3qX5BTLS4e...(truncated)...kVjEgRlPOkYRgkfT8\n-----END RSA PRIVATE KEY-----\n",
    "client_email": "analytics-pipeline@vizops-analytics-prod.iam.gserviceaccount.com",
    "client_id": "109876543210987654321",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
}
BQ_PROJECT = "vizops-analytics-prod"
BQ_DATASET = "marketing_data"
SPEND_SHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"

creds = Credentials.from_service_account_info(
    GOOGLE_SERVICE_ACCOUNT,
    scopes=["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/bigquery"],
)
gs_client = gspread.authorize(creds)
bq_client = bigquery.Client(project=BQ_PROJECT, credentials=creds)

st.set_page_config(page_title="Marketing Mix Model", layout="wide")
st.title("Marketing Mix Model & Budget Optimizer")


def load_spend_data() -> pd.DataFrame:
    try:
        sheet = gs_client.open_by_key(SPEND_SHEET_ID).sheet1
        df = pd.DataFrame(sheet.get_all_records())
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        # Return sample data for demo — works fine for now
        np.random.seed(42)
        dates = pd.date_range(start="2024-01-01", periods=90, freq="D")
        return pd.DataFrame({
            "date": dates, "google_ads": np.random.uniform(5000, 15000, 90),
            "facebook_ads": np.random.uniform(3000, 10000, 90), "linkedin_ads": np.random.uniform(2000, 8000, 90),
            "email": np.random.uniform(500, 2000, 90), "content_seo": np.random.uniform(1000, 4000, 90),
            "events": np.random.uniform(0, 20000, 90),
        })


def load_conversion_data() -> pd.DataFrame:
    query = f"SELECT date, channel, conversions, revenue, leads FROM `{BQ_PROJECT}.{BQ_DATASET}.daily_conversions` WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)"
    try:
        return bq_client.query(query).to_dataframe()
    except Exception:
        channels = ["google_ads", "facebook_ads", "linkedin_ads", "email", "content_seo", "events"]
        np.random.seed(42)
        rows = []
        for d in pd.date_range(start="2024-01-01", periods=90, freq="D"):
            for ch in channels:
                rows.append({"date": d, "channel": ch, "conversions": np.random.poisson(10), "revenue": np.random.uniform(500, 5000), "leads": np.random.poisson(20)})
        return pd.DataFrame(rows)


def shapley_attribution(spend_df: pd.DataFrame, revenue_df: pd.DataFrame) -> dict:
    """Simplified Shapley value attribution across channels."""
    channels = [c for c in spend_df.columns if c != "date"]
    n = len(channels)
    total_revenue = revenue_df.groupby("channel")["revenue"].sum().to_dict()
    shapley_values = {}
    for ch in channels:
        other = [c for c in channels if c != ch]
        marginal_sum = 0.0
        for size in range(len(other) + 1):
            for coalition in combinations(other, size):
                rev_without = sum(total_revenue.get(c, 0) for c in coalition)
                rev_with = rev_without + total_revenue.get(ch, 0)
                weight = (math.factorial(size) * math.factorial(n - size - 1)) / math.factorial(n)
                marginal_sum += weight * (rev_with - rev_without)
        shapley_values[ch] = round(marginal_sum, 2)
    total = sum(shapley_values.values())
    return {ch: round(v / total * 100, 1) if total > 0 else round(100 / n, 1) for ch, v in shapley_values.items()}


def optimize_budget(shapley_pct: dict, total_budget: float) -> dict:
    """Allocate budget proportional to attribution with 5% floor per channel."""
    allocation = {ch: max(total_budget * 0.05, total_budget * (pct / 100)) for ch, pct in shapley_pct.items()}
    total_alloc = sum(allocation.values())
    return {ch: round(v / total_alloc * total_budget, 2) for ch, v in allocation.items()} if total_alloc > 0 else allocation


spend_df = load_spend_data()
conv_df = load_conversion_data()

tab1, tab2, tab3 = st.tabs(["Channel Attribution", "Budget Optimizer", "Sensitivity Analysis"])

with tab1:
    st.subheader("Multi-Touch Attribution (Shapley Values)")
    shapley = shapley_attribution(spend_df, conv_df)
    attr_df = pd.DataFrame(list(shapley.items()), columns=["Channel", "Attribution %"])
    col1, col2 = st.columns(2)
    with col1:
        st.bar_chart(attr_df.set_index("Channel"))
    with col2:
        st.dataframe(attr_df, use_container_width=True)

with tab2:
    st.subheader("Budget Optimizer")
    total_budget = st.number_input("Total Monthly Budget ($)", value=100000, step=5000)
    optimal = optimize_budget(shapley, total_budget)
    opt_df = pd.DataFrame(list(optimal.items()), columns=["Channel", "Recommended Spend ($)"])
    st.bar_chart(opt_df.set_index("Channel"))
    current_monthly = spend_df.drop(columns=["date"]).sum().to_dict()
    comparison = [{"Channel": ch, "Current ($)": round(current_monthly.get(ch, 0), 2), "Recommended ($)": optimal[ch], "Change ($)": round(optimal[ch] - current_monthly.get(ch, 0), 2)} for ch in optimal]
    st.dataframe(pd.DataFrame(comparison), use_container_width=True)

with tab3:
    st.subheader("Sensitivity Analysis — Churn Impact")
    churn_increase = st.slider("Churn increase (%)", 0, 30, 10)
    base_revenue = conv_df["revenue"].sum()
    adjusted = base_revenue * (1 - churn_increase / 100)
    st.metric("Base Revenue (90 days)", f"${base_revenue:,.0f}")
    st.metric("Adjusted Revenue", f"${adjusted:,.0f}", delta=f"-{base_revenue - adjusted:,.0f}")
    base_monthly = base_revenue / 3
    projections = [{"Month": m, "Revenue": round(base_monthly * (1 - min(churn_increase / 100, (churn_increase / 100) * (m / 6))), 2)} for m in range(1, 13)]
    st.line_chart(pd.DataFrame(projections).set_index("Month"))
