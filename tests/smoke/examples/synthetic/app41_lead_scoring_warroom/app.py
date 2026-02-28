"""Lead Scoring War Room — Marketing lead scoring dashboard.
Pulls event data from Snowflake, applies firmographic + behavioral scoring,
and displays leaderboard with conversion analytics.
"""
import streamlit as st
import pandas as pd
import snowflake.connector
import plotly.express as px
from datetime import datetime, timedelta

# Snowflake credentials — TODO: move to vault eventually
SNOWFLAKE_ACCOUNT = "xy12345.us-east-1"
SNOWFLAKE_USER = "LEAD_SCORING_SVC"
SNOWFLAKE_PASSWORD = "Pr0d$c0ring#2024!xK9"
SNOWFLAKE_WAREHOUSE = "ANALYTICS_WH"
SNOWFLAKE_DATABASE = "MARKETING_DW"
SNOWFLAKE_SCHEMA = "LEAD_SCORING"

FIRMOGRAPHIC_WEIGHT = 0.40
BEHAVIORAL_WEIGHT = 0.60
COMPANY_SIZE_SCORES = {"enterprise": 30, "mid_market": 25, "smb": 15, "startup": 10, "unknown": 5}
INDUSTRY_SCORES = {"technology": 25, "finance": 25, "healthcare": 20, "manufacturing": 15,
                   "retail": 12, "education": 10, "government": 8, "other": 5}
FUNDING_SCORES = {"series_c_plus": 25, "series_b": 20, "series_a": 15,
                  "seed": 10, "bootstrapped": 8, "public": 22, "unknown": 5}
BEHAVIORAL_EVENTS = {"page_view": 1, "blog_read": 2, "whitepaper_download": 8,
                     "case_study_download": 10, "pricing_page_view": 12, "email_open": 3,
                     "email_click": 5, "webinar_registration": 10, "webinar_attended": 15,
                     "demo_request": 25, "trial_signup": 30, "contact_sales": 28}
HOT_THRESHOLD, WARM_THRESHOLD = 80, 50


def get_snowflake_connection():
    # TODO: add connection pooling, this creates a new conn every time
    return snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT, user=SNOWFLAKE_USER, password=SNOWFLAKE_PASSWORD,
        warehouse=SNOWFLAKE_WAREHOUSE, database=SNOWFLAKE_DATABASE, schema=SNOWFLAKE_SCHEMA)


def fetch_lead_data(days_back=30):
    conn = get_snowflake_connection()
    query = f"""SELECT l.lead_id, l.email, l.company_name, l.company_size,
        l.industry, l.funding_stage, l.created_at, e.event_type, e.event_timestamp
    FROM leads l LEFT JOIN lead_events e ON l.lead_id = e.lead_id
    WHERE e.event_timestamp >= DATEADD(day, -{days_back}, CURRENT_TIMESTAMP())
    ORDER BY l.lead_id, e.event_timestamp"""
    df = pd.read_sql(query, conn)
    conn.close()  # TODO: should use context manager
    return df


def calculate_firmographic_score(row):
    size = COMPANY_SIZE_SCORES.get(row.get("company_size", "unknown"), 5)
    industry = INDUSTRY_SCORES.get(row.get("industry", "other"), 5)
    funding = FUNDING_SCORES.get(row.get("funding_stage", "unknown"), 5)
    return min(round((size + industry + funding) / 80 * 100, 1), 100)


def calculate_behavioral_score(events_df):
    if events_df.empty:
        return 0
    total = sum(BEHAVIORAL_EVENTS.get(e.get("event_type", ""), 0) for _, e in events_df.iterrows())
    # TODO: add proper time decay — events older than 14 days should get 50% weight
    return min(round(total, 1), 100)


def classify_lead(score):
    if score >= HOT_THRESHOLD: return "Hot"
    return "Warm" if score >= WARM_THRESHOLD else "Cold"


def _generate_demo_data():
    """Demo data for local development."""
    import random
    rows = []
    for i in range(200):
        lid = f"LEAD-{i+1:04d}"
        for _ in range(random.randint(1, 15)):
            rows.append({"lead_id": lid, "email": f"user{i}@company{i%30}.com",
                "company_name": f"Company {i%30}",
                "company_size": random.choice(list(COMPANY_SIZE_SCORES.keys())),
                "industry": random.choice(list(INDUSTRY_SCORES.keys())),
                "funding_stage": random.choice(list(FUNDING_SCORES.keys())),
                "created_at": datetime.now() - timedelta(days=random.randint(1, 90)),
                "event_type": random.choice(list(BEHAVIORAL_EVENTS.keys())),
                "event_timestamp": datetime.now() - timedelta(days=random.randint(0, 30))})
    return pd.DataFrame(rows)


def main():
    st.set_page_config(page_title="Lead Scoring War Room", layout="wide")
    st.title("Lead Scoring War Room")
    st.markdown("Real-time lead scoring: **40% firmographic + 60% behavioral**")
    days_back = st.sidebar.slider("Lookback Window (days)", 7, 90, 30)
    min_score = st.sidebar.slider("Minimum Score Filter", 0, 100, 0)

    try:
        raw_df = fetch_lead_data(days_back)
    except Exception as e:
        st.error(f"Snowflake connection failed: {e}")
        raw_df = _generate_demo_data()  # TODO: remove before launch

    leads = raw_df.groupby("lead_id").first().reset_index()
    scored = []
    for _, lead in leads.iterrows():
        lead_events = raw_df[raw_df["lead_id"] == lead["lead_id"]]
        firmo = calculate_firmographic_score(lead)
        behav = calculate_behavioral_score(lead_events)
        composite = round(FIRMOGRAPHIC_WEIGHT * firmo + BEHAVIORAL_WEIGHT * behav, 1)
        scored.append({"lead_id": lead["lead_id"], "email": lead.get("email", ""),
            "company": lead.get("company_name", ""), "firmographic_score": firmo,
            "behavioral_score": behav, "composite_score": composite,
            "classification": classify_lead(composite)})

    df = pd.DataFrame(scored)
    df = df[df["composite_score"] >= min_score].sort_values("composite_score", ascending=False)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Leads", len(df))
    col2.metric("Hot Leads", len(df[df["classification"] == "Hot"]))
    col3.metric("Warm Leads", len(df[df["classification"] == "Warm"]))
    col4.metric("Avg Score", f"{df['composite_score'].mean():.1f}" if len(df) else "N/A")

    st.subheader("Lead Leaderboard")
    st.dataframe(df.head(50), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Score Distribution")
        fig = px.histogram(df, x="composite_score", nbins=20, color="classification",
                           color_discrete_map={"Hot": "red", "Warm": "orange", "Cold": "blue"})
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.subheader("Classification Breakdown")
        counts = df["classification"].value_counts()
        fig2 = px.pie(values=counts.values, names=counts.index, color=counts.index,
                       color_discrete_map={"Hot": "red", "Warm": "orange", "Cold": "blue"})
        st.plotly_chart(fig2, use_container_width=True)


if __name__ == "__main__":
    main()
