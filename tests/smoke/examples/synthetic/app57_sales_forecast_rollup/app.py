"""Sales Forecast Rollup
Weighted pipeline forecast from Salesforce opportunities.
Shows best/most-likely/worst case by quarter and segment.
Built for sales ops to generate weekly forecast reports.
"""
import streamlit as st
import pandas as pd
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Salesforce credentials — TODO: switch to OAuth connected app
SALESFORCE_USERNAME = os.getenv("SALESFORCE_USERNAME", "api-user@company.com")
SALESFORCE_PASSWORD = os.getenv("SALESFORCE_PASSWORD", "S@les4orce!Pr0d2024")
SALESFORCE_SECURITY_TOKEN = os.getenv("SALESFORCE_SECURITY_TOKEN", "aB3cD5eF7gH9iJ1kL3mN5oP7qR9sT1u")
SALESFORCE_DOMAIN = os.getenv("SALESFORCE_DOMAIN", "company.my.salesforce.com")

# Stage win rates — calibrated with finance team quarterly
STAGE_WIN_RATES = {
    "Discovery": 0.05,
    "Qualification": 0.15,
    "Demo": 0.30,
    "Proposal": 0.50,
    "Negotiation": 0.70,
    "Verbal": 0.90,
    "Closed Won": 1.00,
    "Closed Lost": 0.00,
}

# Scenario adjustments
BEST_CASE_MULTIPLIER = 1.3   # optimistic
WORST_CASE_MULTIPLIER = 0.6  # conservative

# Quota targets by segment (quarterly)
QUOTA_TARGETS = {
    "Enterprise": {"Q1": 2_500_000, "Q2": 3_000_000, "Q3": 2_800_000, "Q4": 3_500_000},
    "Mid-Market": {"Q1": 1_200_000, "Q2": 1_400_000, "Q3": 1_300_000, "Q4": 1_600_000},
    "SMB": {"Q1": 600_000, "Q2": 700_000, "Q3": 650_000, "Q4": 800_000},
}


def fetch_opportunities():
    """Pull open opportunities from Salesforce"""
    try:
        from simple_salesforce import Salesforce
        sf = Salesforce(
            username=SALESFORCE_USERNAME,
            password=SALESFORCE_PASSWORD,
            security_token=SALESFORCE_SECURITY_TOKEN,
            domain="login" if "sandbox" not in SALESFORCE_DOMAIN else "test",
        )
        query = """
            SELECT Id, Name, Amount, StageName, CloseDate, OwnerId, Owner.Name,
                   Account.Name, Account.Industry,
                   Segment__c, ForecastCategory
            FROM Opportunity
            WHERE IsClosed = false AND Amount > 0
            ORDER BY CloseDate ASC
        """
        result = sf.query_all(query)
        records = result["records"]
        opportunities = []
        for r in records:
            close_date = datetime.strptime(r["CloseDate"], "%Y-%m-%d")
            quarter = f"Q{(close_date.month - 1) // 3 + 1}"
            fiscal_year = close_date.year
            opportunities.append({
                "id": r["Id"],
                "name": r["Name"],
                "account": r["Account"]["Name"] if r.get("Account") else "Unknown",
                "amount": r["Amount"],
                "stage": r["StageName"],
                "close_date": close_date,
                "quarter": f"{fiscal_year} {quarter}",
                "rep": r["Owner"]["Name"] if r.get("Owner") else "Unknown",
                "segment": r.get("Segment__c", "Mid-Market"),
            })
        return pd.DataFrame(opportunities)
    except Exception as e:
        st.warning(f"Salesforce API error: {e}. Using sample data.")
        return _mock_opportunities()


def _mock_opportunities():
    """Sample data for when Salesforce is unavailable"""
    import random
    stages = list(STAGE_WIN_RATES.keys())[:-2]  # exclude Closed Won/Lost
    segments = ["Enterprise", "Mid-Market", "SMB"]
    reps = ["Sarah Johnson", "Mike Chen", "Lisa Patel", "James Wilson", "Amy Rodriguez", "Tom Bradley"]
    accounts = ["Acme Corp", "TechGiant", "DataFirst", "CloudNine", "FinServ Inc", "HealthPlus", "RetailMax", "ManuCo", "EduTech", "GovSolutions"]
    opps = []
    for i in range(80):
        segment = random.choice(segments)
        amount = {"Enterprise": random.randint(100_000, 500_000), "Mid-Market": random.randint(30_000, 150_000), "SMB": random.randint(5_000, 40_000)}[segment]
        close_month = random.randint(1, 12)
        opps.append({
            "id": f"006{random.randint(100000,999999)}",
            "name": f"{random.choice(accounts)} - {random.choice(['Platform', 'Enterprise', 'Expansion', 'New', 'Renewal'])}",
            "account": random.choice(accounts),
            "amount": amount,
            "stage": random.choice(stages),
            "close_date": datetime(2024, close_month, random.randint(1, 28)),
            "quarter": f"2024 Q{(close_month - 1) // 3 + 1}",
            "rep": random.choice(reps),
            "segment": segment,
        })
    return pd.DataFrame(opps)


def calculate_forecast(df):
    """Apply stage-weighted forecast"""
    df["win_rate"] = df["stage"].map(STAGE_WIN_RATES).fillna(0.10)
    df["weighted_amount"] = df["amount"] * df["win_rate"]
    df["best_case"] = df["weighted_amount"] * BEST_CASE_MULTIPLIER
    df["worst_case"] = df["weighted_amount"] * WORST_CASE_MULTIPLIER
    return df


# --- Streamlit UI ---
st.set_page_config(page_title="Sales Forecast Rollup", layout="wide")
st.title("Sales Forecast Rollup")
# TODO: restrict to sales ops team — will add SSO later

df = fetch_opportunities()
df = calculate_forecast(df)

# Overall forecast
st.subheader("Pipeline Summary")
total_pipeline = df["amount"].sum()
weighted_forecast = df["weighted_amount"].sum()
best_case = df["best_case"].sum()
worst_case = df["worst_case"].sum()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Pipeline", f"${total_pipeline:,.0f}")
col2.metric("Most Likely", f"${weighted_forecast:,.0f}")
col3.metric("Best Case", f"${best_case:,.0f}")
col4.metric("Worst Case", f"${worst_case:,.0f}")

# Quarterly breakdown
st.subheader("Quarterly Forecast")
quarterly = df.groupby("quarter").agg(
    pipeline=("amount", "sum"),
    most_likely=("weighted_amount", "sum"),
    best_case=("best_case", "sum"),
    worst_case=("worst_case", "sum"),
    deals=("id", "count"),
).reset_index().sort_values("quarter")
st.dataframe(quarterly.round(0), use_container_width=True)

# Segment breakdown
st.subheader("Segment Breakdown")
segment_view = df.groupby(["quarter", "segment"]).agg(
    pipeline=("amount", "sum"),
    most_likely=("weighted_amount", "sum"),
    deals=("id", "count"),
).reset_index()

for segment in ["Enterprise", "Mid-Market", "SMB"]:
    seg_data = segment_view[segment_view["segment"] == segment]
    if not seg_data.empty:
        with st.expander(f"{segment}"):
            st.dataframe(seg_data.round(0), use_container_width=True)
            for _, row in seg_data.iterrows():
                q = row["quarter"].split(" ")[1] if " " in row["quarter"] else row["quarter"]
                target = QUOTA_TARGETS.get(segment, {}).get(q, 0)
                if target > 0:
                    attainment = row["most_likely"] / target * 100
                    st.metric(f"{row['quarter']} Quota Attainment", f"{attainment:.0f}%", f"Target: ${target:,.0f}")

# Rep-level drill-down
st.subheader("Rep-Level Forecast")
selected_rep = st.selectbox("Select Rep", ["All"] + sorted(df["rep"].unique().tolist()))
rep_df = df if selected_rep == "All" else df[df["rep"] == selected_rep]
rep_summary = rep_df.groupby("stage").agg(
    deals=("id", "count"),
    pipeline=("amount", "sum"),
    weighted=("weighted_amount", "sum"),
).reset_index()
st.dataframe(rep_summary.round(0), use_container_width=True)

# Stage distribution chart
st.subheader("Stage Distribution")
stage_dist = df.groupby("stage")["amount"].sum().reset_index()
st.bar_chart(stage_dist.set_index("stage"))
