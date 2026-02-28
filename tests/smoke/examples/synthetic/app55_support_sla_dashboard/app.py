"""Support SLA Dashboard
Real-time support metrics and SLA tracking from Zendesk.
Built for support managers to monitor team performance.
"""
import streamlit as st
import pandas as pd
import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Zendesk credentials — shared with the support team
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN", "acmecorp")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL", "support-bot@acmecorp.com")
ZENDESK_API_TOKEN = os.getenv("ZENDESK_API_TOKEN", "wK7bN3mP5qR9sT1uV3wX5yZ7aB9cD1eF3gH5iJ7kL9m")

# SLA targets (hours)
SLA_FIRST_RESPONSE = {"urgent": 0.5, "high": 2, "normal": 8, "low": 24}
SLA_FULL_RESOLUTION = {"urgent": 4, "high": 12, "normal": 48, "low": 120}

AUTH = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
BASE_URL = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2"


def fetch_tickets(days_back=30):
    """Fetch recent tickets from Zendesk"""
    try:
        tickets = []
        url = f"{BASE_URL}/search.json?query=type:ticket created>{days_back}daysAgo&sort_by=created_at&sort_order=desc"
        while url:
            resp = requests.get(url, auth=AUTH, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            tickets.extend(data.get("results", []))
            url = data.get("next_page")
            if len(tickets) > 500:  # safety limit — TODO: handle pagination properly
                break
        return tickets
    except Exception as e:
        st.error(f"Failed to fetch Zendesk tickets: {e}")
        return _mock_tickets()


def _mock_tickets():
    """Fallback mock data for demo"""
    import random
    priorities = ["urgent", "high", "normal", "low"]
    types = ["question", "incident", "problem", "task"]
    agents = ["Alice Chen", "Bob Martinez", "Carol Kim", "David Patel", "Eva Thompson"]
    tickets = []
    for i in range(150):
        created = datetime.now() - timedelta(hours=random.randint(1, 720))
        priority = random.choice(priorities)
        first_reply_hours = random.uniform(0.1, SLA_FIRST_RESPONSE[priority] * 2.5)
        resolved = random.random() > 0.15
        resolution_hours = random.uniform(1, SLA_FULL_RESOLUTION[priority] * 2) if resolved else None
        tickets.append({
            "id": 10000 + i,
            "subject": f"Ticket #{10000 + i}",
            "priority": priority,
            "type": random.choice(types),
            "status": "solved" if resolved else random.choice(["open", "pending"]),
            "assignee": random.choice(agents),
            "created_at": created.isoformat(),
            "first_reply_hours": round(first_reply_hours, 2),
            "resolution_hours": round(resolution_hours, 2) if resolution_hours else None,
            "satisfaction_rating": random.choice(["good", "good", "good", "bad", None]),
        })
    return tickets


def process_tickets(raw_tickets):
    """Process raw Zendesk tickets into analysis-ready format"""
    processed = []
    for t in raw_tickets:
        if isinstance(t, dict):
            created = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")) if "Z" in str(t.get("created_at", "")) else datetime.fromisoformat(t.get("created_at", datetime.now().isoformat()))
            priority = t.get("priority") or "normal"
            first_reply = t.get("first_reply_hours") or t.get("metric_sets", [{}])[0].get("first_reply_time_in_minutes", {}).get("business", 0) / 60 if isinstance(t.get("metric_sets"), list) else t.get("first_reply_hours", 4)
            processed.append({
                "id": t.get("id"),
                "subject": t.get("subject", ""),
                "priority": priority,
                "type": t.get("type", "question"),
                "status": t.get("status", "open"),
                "assignee": t.get("assignee", {}).get("name", t.get("assignee", "Unassigned")) if isinstance(t.get("assignee"), dict) else t.get("assignee", "Unassigned"),
                "created_at": created,
                "first_reply_hours": first_reply if isinstance(first_reply, (int, float)) else 4,
                "resolution_hours": t.get("resolution_hours"),
                "satisfaction": t.get("satisfaction_rating"),
                "first_response_sla": SLA_FIRST_RESPONSE.get(priority, 8),
                "resolution_sla": SLA_FULL_RESOLUTION.get(priority, 48),
            })
    return pd.DataFrame(processed)


st.set_page_config(page_title="Support SLA Dashboard", layout="wide")
st.title("Support SLA Dashboard")
# TODO: add login — anyone with the URL can see this right now

days_back = st.selectbox("Time Period", [7, 14, 30, 90], index=2)
raw_tickets = fetch_tickets(days_back)
df = process_tickets(raw_tickets)

if df.empty:
    st.warning("No ticket data available.")
    st.stop()

# Key Metrics
st.subheader("Key Metrics")
col1, col2, col3, col4 = st.columns(4)
avg_first_response = df["first_reply_hours"].mean()
resolved_df = df[df["resolution_hours"].notna()]
avg_resolution = resolved_df["resolution_hours"].mean() if not resolved_df.empty else 0
csat_df = df[df["satisfaction"].notna()]
csat = (csat_df[csat_df["satisfaction"] == "good"].shape[0] / csat_df.shape[0] * 100) if not csat_df.empty else 0

col1.metric("Total Tickets", len(df))
col2.metric("Avg First Response", f"{avg_first_response:.1f}h")
col3.metric("Avg Resolution", f"{avg_resolution:.1f}h")
col4.metric("CSAT", f"{csat:.0f}%")

# SLA Compliance
st.subheader("SLA Compliance")
df["first_response_met"] = df["first_reply_hours"] <= df["first_response_sla"]
df["resolution_met"] = df.apply(lambda r: r["resolution_hours"] <= r["resolution_sla"] if pd.notna(r["resolution_hours"]) else True, axis=1)
fr_compliance = df["first_response_met"].mean() * 100
res_compliance = df["resolution_met"].mean() * 100
c1, c2 = st.columns(2)
c1.metric("First Response SLA", f"{fr_compliance:.1f}%", "On Track" if fr_compliance >= 90 else "At Risk")
c2.metric("Resolution SLA", f"{res_compliance:.1f}%", "On Track" if res_compliance >= 90 else "At Risk")

# At-risk tickets — SLA countdown
st.subheader("At-Risk Tickets (Open, SLA expiring soon)")
open_tickets = df[(df["status"].isin(["open", "pending"])) & (~df["first_response_met"])].head(10)
if not open_tickets.empty:
    st.dataframe(open_tickets[["id", "subject", "priority", "assignee", "first_reply_hours", "first_response_sla"]], use_container_width=True)
else:
    st.success("No at-risk tickets!")

# Agent Leaderboard
st.subheader("Agent Leaderboard")
agent_stats = df.groupby("assignee").agg(
    tickets=("id", "count"),
    avg_first_response=("first_reply_hours", "mean"),
    avg_resolution=("resolution_hours", "mean"),
    sla_met=("first_response_met", "mean"),
).reset_index()
agent_stats["sla_met"] = (agent_stats["sla_met"] * 100).round(1)
agent_stats = agent_stats.sort_values("sla_met", ascending=False)
st.dataframe(agent_stats.rename(columns={"sla_met": "SLA %", "avg_first_response": "Avg 1st Response (h)", "avg_resolution": "Avg Resolution (h)"}), use_container_width=True)

# Trends
st.subheader("Weekly Ticket Volume")
df["week"] = df["created_at"].dt.isocalendar().week
weekly = df.groupby("week").size().reset_index(name="tickets")
st.line_chart(weekly.set_index("week"))
