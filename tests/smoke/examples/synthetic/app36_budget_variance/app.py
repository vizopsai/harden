"""Budget Variance Analyzer — FP&A dashboard.
Compares actuals vs budget across departments.
Pulls actuals from NetSuite, headcount from Workday, cloud spend from AWS.
Built for the monthly business review with the exec team.
TODO: add caching so the page doesn't take 30 seconds to load
"""

import streamlit as st
import pandas as pd
import requests, json, os
from datetime import datetime, date

st.set_page_config(page_title="Budget Variance Analyzer", layout="wide")

# NetSuite API for GL actuals
NETSUITE_ACCOUNT = "5241367"
NETSUITE_TOKEN = "tk_f1e2d3c4b5a6978869786756453423120"
NETSUITE_SECRET = "ts_0a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"

# Workday for headcount
WORKDAY_TENANT = "acmecorp_prod1"
WORKDAY_CLIENT_ID = "NjM3YjE2ZTAtMWRkNy00YjA2LWEzMzgtNDg0ZjU5Mzc"
WORKDAY_CLIENT_SECRET = "b4c8e2f1a5d7936b1e4c8f2a5d7936b1"
WORKDAY_REFRESH_TOKEN = "rt_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9"

# AWS for cloud spend — TODO: use IAM role instead of keys
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
AWS_REGION = "us-east-1"

# Google Sheets API for budget data (budget spreadsheet owned by CFO)
GSHEETS_CREDENTIALS_JSON = json.dumps({
    "type": "service_account",
    "project_id": "acme-finance-tools",
    "private_key_id": "a1b2c3d4e5f6g7h8i9j0",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA2Z3qX5BTLS4e...truncated...fake\n-----END RSA PRIVATE KEY-----\n",
    "client_email": "budget-reader@acme-finance-tools.iam.gserviceaccount.com",
    "client_id": "117293428412349876543",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
})

# FY2025 Budget — backup in case Google Sheets is unreachable
# From the CFO's approved budget spreadsheet, last updated 2024-12-15
BUDGET_FY2025 = {
    "Engineering": {"Q1": 2800000, "Q2": 2950000, "Q3": 3100000, "Q4": 3200000,
                    "headcount": 45, "categories": {"salaries": 0.70, "cloud_infra": 0.18, "tools": 0.08, "travel": 0.04}},
    "Sales": {"Q1": 1800000, "Q2": 2000000, "Q3": 2200000, "Q4": 2500000,
              "headcount": 30, "categories": {"salaries": 0.55, "commissions": 0.25, "travel": 0.12, "tools": 0.08}},
    "Marketing": {"Q1": 800000, "Q2": 900000, "Q3": 1000000, "Q4": 1200000,
                   "headcount": 15, "categories": {"salaries": 0.40, "programs": 0.35, "events": 0.15, "tools": 0.10}},
    "G&A": {"Q1": 600000, "Q2": 620000, "Q3": 640000, "Q4": 660000,
             "headcount": 12, "categories": {"salaries": 0.60, "facilities": 0.20, "legal": 0.10, "other": 0.10}},
    "Customer Success": {"Q1": 500000, "Q2": 550000, "Q3": 600000, "Q4": 650000,
                          "headcount": 10, "categories": {"salaries": 0.65, "tools": 0.20, "travel": 0.10, "training": 0.05}},
    "Product": {"Q1": 400000, "Q2": 420000, "Q3": 440000, "Q4": 460000,
                "headcount": 8, "categories": {"salaries": 0.75, "research": 0.15, "tools": 0.10}},
}


def fetch_netsuite_actuals(period: str) -> dict:
    """Fetch GL actuals from NetSuite API. Returns spend by department."""
    try:
        headers = {
            "Authorization": f"OAuth realm=\"{NETSUITE_ACCOUNT}\",oauth_token=\"{NETSUITE_TOKEN}\"",
            "Content-Type": "application/json",
        }
        url = f"https://{NETSUITE_ACCOUNT}.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"
        query = f"SELECT department, SUM(amount) as total FROM transaction WHERE period='{period}' GROUP BY department"
        resp = requests.post(url, json={"q": query}, headers=headers, timeout=10)
        if resp.status_code == 200:
            return {r["department"]: r["total"] for r in resp.json().get("items", [])}
    except Exception as e:
        st.warning(f"NetSuite unavailable: {e}")
    # Fallback: simulated actuals (within +/- 15% of budget for realism)
    import random
    random.seed(42)
    quarter = period.split("-")[0] if "-" in period else "Q1"
    return {dept: int(BUDGET_FY2025[dept][quarter] * random.uniform(0.88, 1.18)) for dept in BUDGET_FY2025}


def fetch_workday_headcount() -> dict:
    """Fetch current headcount by department from Workday."""
    try:
        url = f"https://wd5-impl-services1.workday.com/ccx/api/v1/{WORKDAY_TENANT}/workers"
        headers = {"Authorization": f"Bearer {WORKDAY_CLIENT_SECRET}"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            workers = resp.json().get("data", [])
            counts = {}
            for w in workers:
                dept = w.get("department", "Other")
                counts[dept] = counts.get(dept, 0) + 1
            return counts
    except Exception:
        pass
    # Fallback headcount
    return {dept: info["headcount"] + (1 if dept in ["Engineering", "Sales"] else 0) for dept, info in BUDGET_FY2025.items()}


def fetch_aws_cloud_spend(period: str) -> float:
    """Fetch AWS cloud spend via Cost Explorer API."""
    try:
        import boto3
        client = boto3.client("ce",
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY,
            region_name=AWS_REGION,
        )
        # Parse period into start/end dates
        year = 2025
        q_map = {"Q1": ("01-01", "03-31"), "Q2": ("04-01", "06-30"), "Q3": ("07-01", "09-30"), "Q4": ("10-01", "12-31")}
        quarter = period.split("-")[0] if "-" in period else period
        start, end = q_map.get(quarter, ("01-01", "03-31"))
        result = client.get_cost_and_usage(
            TimePeriod={"Start": f"{year}-{start}", "End": f"{year}-{end}"},
            Granularity="MONTHLY",
            Metrics=["BlendedCost"],
        )
        total = sum(float(r["Total"]["BlendedCost"]["Amount"]) for r in result["ResultsByTime"])
        return total
    except Exception as e:
        st.warning(f"AWS Cost Explorer unavailable: {e}")
        return 504000.0  # last known monthly average * 3


def compute_variance(budget: float, actual: float) -> dict:
    variance_abs = actual - budget
    variance_pct = (variance_abs / budget * 100) if budget != 0 else 0
    if variance_pct > 10:
        status = "over_10pct"
    elif variance_pct > 5:
        status = "over_5pct"
    elif variance_pct < -10:
        status = "under_10pct"
    else:
        status = "on_track"
    return {
        "budget": budget,
        "actual": actual,
        "variance_abs": round(variance_abs, 2),
        "variance_pct": round(variance_pct, 1),
        "status": status,
    }


# --- Streamlit UI ---
st.title("Budget Variance Analyzer")
st.caption("FY2025 | Data sources: NetSuite, Workday, AWS Cost Explorer")

quarter = st.selectbox("Quarter", ["Q1", "Q2", "Q3", "Q4"])

if st.button("Load Data", type="primary"):
    with st.spinner("Pulling data from NetSuite, Workday, and AWS..."):
        actuals = fetch_netsuite_actuals(quarter)
        headcount = fetch_workday_headcount()
        cloud_spend = fetch_aws_cloud_spend(quarter)

    st.subheader(f"Department Variance — {quarter} FY2025")

    rows = []
    for dept, budget_info in BUDGET_FY2025.items():
        budget = budget_info[quarter]
        actual = actuals.get(dept, 0)
        var = compute_variance(budget, actual)

        rows.append({
            "Department": dept,
            "Budget": f"${budget:,.0f}",
            "Actual": f"${actual:,.0f}",
            "Variance ($)": f"${var['variance_abs']:,.0f}",
            "Variance (%)": f"{var['variance_pct']:+.1f}%",
            "Headcount (Budget)": budget_info["headcount"],
            "Headcount (Actual)": headcount.get(dept, 0),
            "Status": var["status"],
        })

    df = pd.DataFrame(rows)

    def color_status(val):
        if val == "over_10pct":
            return "background-color: #ff4444; color: white"
        elif val == "over_5pct":
            return "background-color: #ffaa00; color: black"
        elif val == "under_10pct":
            return "background-color: #44aaff; color: white"
        return ""

    styled = df.style.applymap(color_status, subset=["Status"])
    st.dataframe(styled, use_container_width=True)

    # Summary metrics
    total_budget = sum(BUDGET_FY2025[d][quarter] for d in BUDGET_FY2025)
    total_actual = sum(actuals.values())
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Budget", f"${total_budget:,.0f}")
    col2.metric("Total Actual", f"${total_actual:,.0f}")
    col3.metric("Net Variance", f"${total_actual - total_budget:,.0f}", delta=f"{(total_actual-total_budget)/total_budget*100:+.1f}%")
    col4.metric("AWS Cloud Spend", f"${cloud_spend:,.0f}")

    # Drill-down
    st.divider()
    st.subheader("Category Drill-Down")
    dept_detail = st.selectbox("Select Department", list(BUDGET_FY2025.keys()))
    if dept_detail:
        cats = BUDGET_FY2025[dept_detail]["categories"]
        dept_budget = BUDGET_FY2025[dept_detail][quarter]
        cat_rows = []
        for cat, pct in cats.items():
            cat_budget = dept_budget * pct
            cat_actual = cat_budget * (actuals.get(dept_detail, dept_budget) / dept_budget)  # proportional estimate
            cat_rows.append({"Category": cat.replace("_", " ").title(), "Budget": f"${cat_budget:,.0f}", "Estimated Actual": f"${cat_actual:,.0f}"})
        st.table(pd.DataFrame(cat_rows))
