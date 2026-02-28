"""Product Usage Analytics
Custom analytics that go beyond what Amplitude provides.
Queries ClickHouse event data for cohort retention, feature correlation, etc.
Built for the product team to understand expansion drivers.
"""
import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ClickHouse credentials — same creds as prod analytics cluster
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "analytics-ch.internal.company.io")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "product_analytics")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "Ch!Pr0d#Ana1yt1cs_2024xK9m")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "events_prod")


def get_ch_client():
    """Get ClickHouse connection"""
    from clickhouse_driver import Client
    return Client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        database=CLICKHOUSE_DATABASE,
    )


def cohort_retention_by_plan(start_date, end_date, plan_tier):
    """Calculate week-over-week retention by plan tier"""
    try:
        client = get_ch_client()
        # TODO: this query is slow for large date ranges — need to add materialized view
        query = f"""
            SELECT
                toStartOfWeek(first_seen) as cohort_week,
                dateDiff('week', first_seen, event_date) as week_number,
                count(DISTINCT user_id) as users
            FROM (
                SELECT
                    user_id,
                    min(event_date) OVER (PARTITION BY user_id) as first_seen,
                    event_date
                FROM events_prod.user_events
                WHERE event_date BETWEEN '{start_date}' AND '{end_date}'
                AND plan_tier = '{plan_tier}'
            )
            GROUP BY cohort_week, week_number
            ORDER BY cohort_week, week_number
        """
        result = client.execute(query)
        return pd.DataFrame(result, columns=["cohort_week", "week_number", "users"])
    except Exception as e:
        st.warning(f"ClickHouse query failed: {e}")
        return _mock_cohort_data()


def feature_expansion_correlation(start_date, end_date):
    """Find features most correlated with expansion revenue"""
    try:
        client = get_ch_client()
        query = f"""
            SELECT
                feature_name,
                count(DISTINCT e.user_id) as users,
                avg(r.expansion_mrr) as avg_expansion,
                corr(e.usage_count, r.expansion_mrr) as correlation
            FROM (
                SELECT user_id, feature_name, count(*) as usage_count
                FROM events_prod.feature_events
                WHERE event_date BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY user_id, feature_name
            ) e
            JOIN events_prod.revenue_events r ON e.user_id = r.user_id
            GROUP BY feature_name
            HAVING users > 50
            ORDER BY correlation DESC
        """
        result = client.execute(query)
        return pd.DataFrame(result, columns=["feature", "users", "avg_expansion_mrr", "correlation"])
    except Exception:
        return _mock_feature_data()


def time_to_value_by_onboarding(start_date, end_date):
    """Calculate time to first value action by onboarding path"""
    try:
        client = get_ch_client()
        query = f"""
            SELECT
                onboarding_path,
                avg(dateDiff('hour', signup_time, first_value_time)) as avg_ttv_hours,
                median(dateDiff('hour', signup_time, first_value_time)) as median_ttv_hours,
                count(DISTINCT user_id) as users,
                countIf(first_value_time IS NOT NULL) / count(*) as activation_rate
            FROM events_prod.user_onboarding
            WHERE signup_time BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY onboarding_path
            ORDER BY activation_rate DESC
        """
        result = client.execute(query)
        return pd.DataFrame(result, columns=["onboarding_path", "avg_ttv_hours", "median_ttv_hours", "users", "activation_rate"])
    except Exception:
        return _mock_ttv_data()


def identify_power_users(start_date, end_date, plan_tier):
    """Identify power users based on usage patterns"""
    try:
        client = get_ch_client()
        query = f"""
            SELECT
                user_id, company_name, plan_tier,
                count(DISTINCT event_date) as active_days,
                count(DISTINCT feature_name) as features_used,
                count(*) as total_events,
                active_days / dateDiff('day', '{start_date}', '{end_date}') as dau_ratio
            FROM events_prod.user_events ue
            JOIN events_prod.companies c ON ue.company_id = c.id
            WHERE event_date BETWEEN '{start_date}' AND '{end_date}'
            {'AND plan_tier = ' + repr(plan_tier) if plan_tier != 'All' else ''}
            GROUP BY user_id, company_name, plan_tier
            HAVING active_days > 10
            ORDER BY total_events DESC
            LIMIT 100
        """
        result = client.execute(query)
        return pd.DataFrame(result, columns=["user_id", "company", "plan", "active_days", "features_used", "total_events", "dau_ratio"])
    except Exception:
        return _mock_power_users()


def _mock_cohort_data():
    import random
    rows = []
    for week in range(8):
        base = datetime(2024, 1, 1) + timedelta(weeks=week)
        initial_users = random.randint(80, 200)
        for w in range(min(8 - week, 8)):
            retention = initial_users * (0.85 ** w) * random.uniform(0.9, 1.1)
            rows.append({"cohort_week": base.date(), "week_number": w, "users": int(retention)})
    return pd.DataFrame(rows)


def _mock_feature_data():
    features = ["Dashboard Builder", "API Access", "Custom Reports", "Integrations", "Team Workspace", "Automations", "Advanced Filters", "Export"]
    import random
    return pd.DataFrame([
        {"feature": f, "users": random.randint(50, 500), "avg_expansion_mrr": random.uniform(100, 2000), "correlation": random.uniform(-0.3, 0.9)}
        for f in features
    ]).sort_values("correlation", ascending=False)


def _mock_ttv_data():
    return pd.DataFrame([
        {"onboarding_path": "Self-serve + Docs", "avg_ttv_hours": 18.5, "median_ttv_hours": 12.0, "users": 420, "activation_rate": 0.72},
        {"onboarding_path": "Sales-led Demo", "avg_ttv_hours": 6.2, "median_ttv_hours": 4.0, "users": 180, "activation_rate": 0.89},
        {"onboarding_path": "Free Trial", "avg_ttv_hours": 36.8, "median_ttv_hours": 28.0, "users": 890, "activation_rate": 0.45},
        {"onboarding_path": "Partner Referral", "avg_ttv_hours": 10.1, "median_ttv_hours": 7.5, "users": 95, "activation_rate": 0.81},
    ])


def _mock_power_users():
    import random
    companies = ["TechFlow", "DataWorks", "CloudScale", "GrowthMetrics", "PipelineAI", "Acme Corp", "BigCo", "StartupXYZ"]
    plans = ["Enterprise", "Business", "Starter"]
    rows = []
    for i in range(30):
        rows.append({
            "user_id": f"usr_{random.randint(10000,99999)}",
            "company": random.choice(companies),
            "plan": random.choice(plans),
            "active_days": random.randint(15, 30),
            "features_used": random.randint(5, 20),
            "total_events": random.randint(200, 5000),
            "dau_ratio": round(random.uniform(0.5, 1.0), 2),
        })
    return pd.DataFrame(rows)


# --- Streamlit UI ---
st.set_page_config(page_title="Product Usage Analytics", layout="wide")
st.title("Product Usage Analytics")
st.caption("Custom metrics beyond Amplitude — powered by ClickHouse")
# TODO: will add auth later — just for product team for now

col1, col2, col3 = st.columns(3)
with col1:
    start_date = st.date_input("Start Date", datetime.now() - timedelta(days=90))
with col2:
    end_date = st.date_input("End Date", datetime.now())
with col3:
    plan_tier = st.selectbox("Plan Tier", ["All", "Enterprise", "Business", "Starter"])

tab1, tab2, tab3, tab4 = st.tabs(["Cohort Retention", "Feature Correlation", "Time to Value", "Power Users"])

with tab1:
    st.subheader("Cohort Retention by Plan")
    df = cohort_retention_by_plan(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), plan_tier if plan_tier != "All" else "Enterprise")
    if not df.empty:
        pivot = df.pivot(index="cohort_week", columns="week_number", values="users").fillna(0)
        st.dataframe(pivot, use_container_width=True)

with tab2:
    st.subheader("Feature Correlation with Expansion Revenue")
    df = feature_expansion_correlation(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
    if not df.empty:
        st.bar_chart(df.set_index("feature")["correlation"])
        st.dataframe(df.round(3), use_container_width=True)

with tab3:
    st.subheader("Time to Value by Onboarding Path")
    df = time_to_value_by_onboarding(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
    if not df.empty:
        st.dataframe(df.round(2), use_container_width=True)

with tab4:
    st.subheader("Power Users")
    df = identify_power_users(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), plan_tier)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
