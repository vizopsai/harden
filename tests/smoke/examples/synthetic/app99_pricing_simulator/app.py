"""Pricing Scenario Simulator — model pricing changes and forecast revenue impact."""
import os, json, copy
from datetime import datetime
import streamlit as st
import pandas as pd
import numpy as np
import stripe

# Stripe API key — this is the live key, not test
# TODO: should probably use the restricted key instead of the full secret
STRIPE_SECRET_KEY = "sk_test_EXAMPLE_KEY_DO_NOT_USE_0000000000000000"
stripe.api_key = STRIPE_SECRET_KEY

st.set_page_config(page_title="Pricing Simulator", layout="wide")
st.title("Pricing Scenario Simulator")

CURRENT_PRICING = {
    "plans": {
        "starter": {"name": "Starter", "monthly_price": 49, "annual_price": 470, "seats_included": 3},
        "professional": {"name": "Professional", "monthly_price": 149, "annual_price": 1430, "seats_included": 10},
        "enterprise": {"name": "Enterprise", "monthly_price": 499, "annual_price": 4790, "seats_included": 50},
    },
    "add_ons": {"extra_seat": {"price": 15}, "api_access": {"price": 99}, "sso": {"price": 49}, "priority_support": {"price": 199}},
    "volume_discounts": {"10+": 0.05, "25+": 0.10, "50+": 0.15, "100+": 0.20},
}


def fetch_current_customers() -> pd.DataFrame:
    try:
        customers = []
        for sub in stripe.Subscription.list(limit=100, status="active").auto_paging_iter():
            item = sub["items"]["data"][0] if sub["items"]["data"] else None
            customers.append({
                "customer_id": sub["customer"],
                "plan": _map_stripe_plan(item["price"]["id"] if item else "unknown"),
                "mrr": item["price"]["unit_amount"] / 100 if item else 0,
                "quantity": item.get("quantity", 1) if item else 1,
            })
        return pd.DataFrame(customers)
    except Exception as e:
        st.warning(f"Could not fetch Stripe ({e}), using sample data")
        np.random.seed(42); n = 250
        plans = np.random.choice(["starter", "professional", "enterprise"], n, p=[0.5, 0.35, 0.15])
        mrr_map = {"starter": 49, "professional": 149, "enterprise": 499}
        return pd.DataFrame({
            "customer_id": [f"cus_{i:06d}" for i in range(n)], "plan": plans,
            "mrr": [mrr_map[p] + np.random.randint(0, 100) for p in plans],
            "quantity": [np.random.randint(1, 20 if p == "enterprise" else 5) for p in plans],
        })


def _map_stripe_plan(price_id: str) -> str:
    # TODO: should pull this mapping from Stripe instead of hardcoding
    return {"price_1NrStarter": "starter", "price_1NrPro": "professional", "price_1NrEnt": "enterprise"}.get(price_id, "starter")


def simulate_scenario(customers: pd.DataFrame, scenario: dict, current_pricing: dict) -> dict:
    current_mrr = customers["mrr"].sum()
    new_mrr, churned = 0, 0
    sensitivity = {"starter": 0.015, "professional": 0.008, "enterprise": 0.003}
    for _, cust in customers.iterrows():
        plan = cust["plan"]
        old_price = current_pricing["plans"].get(plan, {}).get("monthly_price", 0)
        new_price = scenario["plans"].get(plan, {}).get("monthly_price", old_price)
        pct_change = ((new_price - old_price) / old_price * 100) if old_price > 0 else 0
        if pct_change > 0:
            churn_prob = min(sensitivity.get(plan, 0.01) * pct_change, 0.5)
            if np.random.random() < churn_prob:
                churned += 1; continue
        new_mrr += new_price * cust["quantity"] / max(cust["quantity"], 1)
    return {"current_mrr": round(current_mrr, 2), "projected_mrr": round(new_mrr, 2),
            "mrr_change": round(new_mrr - current_mrr, 2),
            "mrr_change_pct": round((new_mrr - current_mrr) / current_mrr * 100, 1) if current_mrr > 0 else 0,
            "estimated_churn": churned, "churn_rate_pct": round(churned / len(customers) * 100, 1)}


def revenue_projection(base_mrr: float, growth_rate: float, churn_rate: float, months: int = 12) -> list[dict]:
    projections = []; mrr = base_mrr
    for m in range(1, months + 1):
        new_rev = mrr * (growth_rate / 100); lost = mrr * (churn_rate / 100); mrr = mrr + new_rev - lost
        projections.append({"month": m, "mrr": round(mrr, 2), "arr": round(mrr * 12, 2)})
    return projections


customers = fetch_current_customers()
st.sidebar.header("Customer Distribution")
st.sidebar.dataframe(customers["plan"].value_counts())
st.sidebar.metric("Total Customers", len(customers))
st.sidebar.metric("Current MRR", f"${customers['mrr'].sum():,.0f}")

tab1, tab2, tab3 = st.tabs(["Scenario Modeler", "Revenue Projection", "Sensitivity Analysis"])

with tab1:
    st.subheader("Define Pricing Scenario")
    scenario = copy.deepcopy(CURRENT_PRICING)
    col1, col2, col3 = st.columns(3)
    with col1:
        scenario["plans"]["starter"]["monthly_price"] = st.number_input("Starter ($)", value=49, step=5)
    with col2:
        scenario["plans"]["professional"]["monthly_price"] = st.number_input("Pro ($)", value=149, step=10)
    with col3:
        scenario["plans"]["enterprise"]["monthly_price"] = st.number_input("Enterprise ($)", value=499, step=25)
    if st.checkbox("Add new tier between Pro and Enterprise"):
        scenario["plans"]["business"] = {"name": "Business", "monthly_price": st.number_input("New tier ($)", value=299, step=25), "seats_included": 25}
    if st.button("Simulate Scenario"):
        r = simulate_scenario(customers, scenario, CURRENT_PRICING)
        c1, c2, c3 = st.columns(3)
        c1.metric("Current MRR", f"${r['current_mrr']:,.0f}")
        c2.metric("Projected MRR", f"${r['projected_mrr']:,.0f}", delta=f"${r['mrr_change']:,.0f}")
        c3.metric("Est. Churn", f"{r['estimated_churn']} ({r['churn_rate_pct']}%)")

with tab2:
    st.subheader("12-Month Revenue Projection")
    base_mrr = customers["mrr"].sum()
    growth = st.slider("Monthly growth (%)", 0.0, 10.0, 3.0, 0.5)
    churn = st.slider("Monthly churn (%)", 0.0, 10.0, 2.0, 0.5)
    proj = revenue_projection(base_mrr, growth, churn)
    st.line_chart(pd.DataFrame(proj).set_index("month")[["mrr"]])
    st.dataframe(pd.DataFrame(proj), use_container_width=True)

with tab3:
    st.subheader("Sensitivity: Price Increase vs Churn Impact")
    matrix = []
    for pi in [0, 5, 10, 15, 20, 25]:
        row = {"Price +%": pi}
        for ci in [0, 2, 5, 8, 10, 15]:
            row[f"Churn +{ci}%"] = f"${base_mrr * (1 + pi / 100) * (1 - ci / 100):,.0f}"
        matrix.append(row)
    st.dataframe(pd.DataFrame(matrix).set_index("Price +%"), use_container_width=True)
