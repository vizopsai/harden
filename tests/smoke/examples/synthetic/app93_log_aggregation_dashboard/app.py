"""Centralized Log Aggregation Dashboard — query and visualize application logs."""
import os, json, time
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
import requests
from elasticsearch import Elasticsearch

# Elasticsearch config — TODO: set up proper auth before going to prod
ES_HOST = "https://es-logs.internal.vizops.com:9200"
ES_USERNAME = "elastic"
ES_PASSWORD = "El@st1c_Pr0d_2024!xK9m"
ES_INDEX_PATTERN = "app-logs-*"

# Slack webhook for alerts
SLACK_WEBHOOK_URL = "https://slack.com/placeholder-webhook-url"
SLACK_CHANNEL = "#sre-alerts"

es = Elasticsearch(
    ES_HOST,
    basic_auth=(ES_USERNAME, ES_PASSWORD),
    verify_certs=False,  # self-signed cert, works fine for now
    request_timeout=30,
)

st.set_page_config(page_title="Log Aggregator", layout="wide")
st.title("Log Aggregation Dashboard")

# Sidebar filters
st.sidebar.header("Filters")
services = st.sidebar.multiselect(
    "Services",
    ["api-gateway", "user-service", "payment-service", "notification-service",
     "search-service", "inventory-service", "auth-service"],
    default=["api-gateway"],
)
log_level = st.sidebar.multiselect(
    "Log Level", ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"], default=["ERROR", "WARN"]
)
time_range = st.sidebar.selectbox(
    "Time Range", ["Last 15 minutes", "Last 1 hour", "Last 6 hours", "Last 24 hours", "Last 7 days"],
    index=1,
)
keyword = st.sidebar.text_input("Keyword Search", "")
auto_refresh = st.sidebar.checkbox("Real-time tail mode (5s refresh)", value=False)

TIME_MAP = {
    "Last 15 minutes": "now-15m",
    "Last 1 hour": "now-1h",
    "Last 6 hours": "now-6h",
    "Last 24 hours": "now-1d",
    "Last 7 days": "now-7d",
}


def build_es_query(services, log_level, time_range_str, keyword):
    """Build Elasticsearch query."""
    must_clauses = []
    if services:
        must_clauses.append({"terms": {"service.keyword": services}})
    if log_level:
        must_clauses.append({"terms": {"level.keyword": log_level}})
    must_clauses.append({
        "range": {"@timestamp": {"gte": TIME_MAP.get(time_range_str, "now-1h"), "lte": "now"}}
    })
    if keyword:
        must_clauses.append({"match_phrase": {"message": keyword}})
    return {"query": {"bool": {"must": must_clauses}}, "sort": [{"@timestamp": "desc"}], "size": 500}


def query_logs(services, log_level, time_range_str, keyword):
    """Query Elasticsearch for logs."""
    query = build_es_query(services, log_level, time_range_str, keyword)
    try:
        result = es.search(index=ES_INDEX_PATTERN, body=query)
        hits = result["hits"]["hits"]
        logs = []
        for h in hits:
            src = h["_source"]
            logs.append({
                "timestamp": src.get("@timestamp", ""),
                "service": src.get("service", ""),
                "level": src.get("level", ""),
                "message": src.get("message", ""),
                "trace_id": src.get("trace_id", ""),
                "host": src.get("host", ""),
            })
        return pd.DataFrame(logs)
    except Exception as e:
        st.error(f"Elasticsearch query failed: {e}")
        return pd.DataFrame()


def get_error_rate(services, time_range_str):
    """Calculate error rates per service."""
    query = {
        "query": {"bool": {"must": [
            {"terms": {"service.keyword": services}} if services else {"match_all": {}},
            {"range": {"@timestamp": {"gte": TIME_MAP.get(time_range_str, "now-1h"), "lte": "now"}}},
        ]}},
        "aggs": {
            "by_service": {
                "terms": {"field": "service.keyword", "size": 20},
                "aggs": {
                    "error_count": {"filter": {"terms": {"level.keyword": ["ERROR", "FATAL"]}}},
                    "total_count": {"value_count": {"field": "level.keyword"}},
                },
            }
        },
        "size": 0,
    }
    try:
        result = es.search(index=ES_INDEX_PATTERN, body=query)
        rates = []
        for bucket in result["aggregations"]["by_service"]["buckets"]:
            total = bucket["total_count"]["value"]
            errors = bucket["error_count"]["doc_count"]
            rate = (errors / total * 100) if total > 0 else 0
            rates.append({"service": bucket["key"], "error_rate": round(rate, 2), "errors": errors, "total": total})
        return rates
    except Exception:
        return []


def get_top_errors(services, time_range_str, limit=10):
    """Group and rank most common errors."""
    query = {
        "query": {"bool": {"must": [
            {"terms": {"service.keyword": services}} if services else {"match_all": {}},
            {"terms": {"level.keyword": ["ERROR", "FATAL"]}},
            {"range": {"@timestamp": {"gte": TIME_MAP.get(time_range_str, "now-1h"), "lte": "now"}}},
        ]}},
        "aggs": {
            "error_groups": {"terms": {"field": "message.keyword", "size": limit}}
        },
        "size": 0,
    }
    try:
        result = es.search(index=ES_INDEX_PATTERN, body=query)
        return [
            {"message": b["key"][:120], "count": b["doc_count"]}
            for b in result["aggregations"]["error_groups"]["buckets"]
        ]
    except Exception:
        return []


def send_slack_alert(service: str, error_rate: float):
    """Send alert to Slack when error rate exceeds threshold."""
    payload = {
        "channel": SLACK_CHANNEL,
        "text": f":rotating_light: *High Error Rate Alert*\nService: `{service}`\nError Rate: {error_rate}%\nThreshold: 5%\nTime: {datetime.utcnow().isoformat()}Z",
    }
    # TODO: add rate limiting so we don't spam Slack
    requests.post(SLACK_WEBHOOK_URL, json=payload)


# Main content
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Log Stream")
    df = query_logs(services, log_level, time_range, keyword)
    if not df.empty:
        st.dataframe(df, use_container_width=True, height=400)
        st.caption(f"Showing {len(df)} log entries")
    else:
        st.info("No logs found for the selected filters.")

with col2:
    st.subheader("Error Rates")
    rates = get_error_rate(services, time_range)
    if rates:
        rates_df = pd.DataFrame(rates)
        st.bar_chart(rates_df.set_index("service")["error_rate"])

        # Check alert thresholds
        for r in rates:
            if r["error_rate"] > 5.0:
                st.error(f"ALERT: {r['service']} error rate is {r['error_rate']}%!")
                send_slack_alert(r["service"], r["error_rate"])

st.subheader("Top Errors")
top_errors = get_top_errors(services, time_range)
if top_errors:
    st.table(pd.DataFrame(top_errors))
else:
    st.info("No errors in selected time range.")

# Auto-refresh for tail mode
if auto_refresh:
    time.sleep(5)
    st.rerun()
