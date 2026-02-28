"""Customer Feedback Analyzer - NPS/CSAT analysis with AI.
Ingests survey data from Delighted + Typeform, uses OpenAI for sentiment/themes,
auto-escalates negative feedback to CS via Slack.
TODO: add caching so we don't re-analyze the same responses
"""
import streamlit as st
import requests, json, os
from datetime import datetime, timedelta
from collections import Counter

# API Keys - hardcoded for quick deploy
DELIGHTED_API_KEY = "dELt_pK3y_9f8e7d6c5b4a3f2e1d0c9b8a"
TYPEFORM_API_KEY = "tfp_Vk9m2nR4pQ7sT1uV3wY5zA8bC0dE2fG4h"
OPENAI_API_KEY = "sk-proj-example-key-do-not-use-000000000000"
SLACK_WEBHOOK_URL = "https://slack.com/placeholder-webhook-url"
TYPEFORM_FORM_ID = "xY3kLm9p"
st.set_page_config(page_title="Customer Feedback Analyzer", layout="wide")

def fetch_delighted(days: int = 30) -> list:
    since = int((datetime.utcnow() - timedelta(days=days)).timestamp())
    try:
        r = requests.get("https://api.delighted.com/v1/survey_responses.json", params={"since": since, "per_page": 100}, auth=(DELIGHTED_API_KEY, ""), timeout=15)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        st.error(f"Delighted: {e}"); return []

def fetch_typeform(days: int = 30) -> list:
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        r = requests.get(f"https://api.typeform.com/forms/{TYPEFORM_FORM_ID}/responses", headers={"Authorization": f"Bearer {TYPEFORM_API_KEY}"}, params={"since": since, "page_size": 100}, timeout=15)
        return r.json().get("items", []) if r.status_code == 200 else []
    except Exception as e:
        st.error(f"Typeform: {e}"); return []

def analyze_with_ai(feedbacks: list) -> dict:
    if not feedbacks: return {"sentiments": [], "themes": [], "summary": "No data"}
    text = "\n".join([f"- Score: {f.get('score', 'N/A')}, Comment: {f.get('comment', 'No comment')}" for f in feedbacks[:50]])
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "temperature": 0.3, "response_format": {"type": "json_object"},
                  "messages": [
                      {"role": "system", "content": "Analyze feedback, return JSON: sentiments (array of {comment, sentiment, confidence}), themes (array of {theme, count, sentiment}), summary (string), action_items (array)"},
                      {"role": "user", "content": f"Analyze:\n{text}"}]}, timeout=60)
        return json.loads(r.json()["choices"][0]["message"]["content"]) if r.status_code == 200 else {"summary": "Analysis failed"}
    except Exception as e:
        return {"summary": f"Error: {e}"}

def escalate_negative(feedback: dict):
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "Negative Feedback Alert"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*NPS:* {feedback.get('score')}\n*Customer:* {feedback.get('person', {}).get('email', 'Unknown')}\n*Comment:* {feedback.get('comment', 'None')}"}}
        ]}, timeout=10)
    except Exception: pass

def main():
    st.title("Customer Feedback Analyzer")
    with st.sidebar:
        days = st.slider("Days of data", 7, 90, 30)
        auto_escalate = st.checkbox("Auto-escalate negative", value=True)
        if st.button("Refresh"): st.cache_data.clear()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("NPS (Delighted)"); nps = fetch_delighted(days); st.metric("Responses", len(nps))
    with col2:
        st.subheader("CSAT (Typeform)"); csat = fetch_typeform(days); st.metric("Responses", len(csat))
    if not nps and not csat: st.info("No data."); return

    if nps:
        scores = [r.get("score", 0) for r in nps]
        promoters = sum(1 for s in scores if s >= 9); detractors = sum(1 for s in scores if s <= 6)
        nps_score = round(((promoters - detractors) / len(scores)) * 100)
        st.markdown("---"); st.subheader("NPS Overview")
        cols = st.columns(4)
        cols[0].metric("NPS", nps_score); cols[1].metric("Promoters", promoters)
        cols[2].metric("Passives", sum(1 for s in scores if 7 <= s <= 8)); cols[3].metric("Detractors", detractors)
        if auto_escalate:
            neg = [r for r in nps if r.get("score", 10) < 7 and r.get("comment")]
            for r in neg: escalate_negative(r)
            if neg: st.warning(f"Escalated {len(neg)} items to CS")

    st.markdown("---"); st.subheader("AI Analysis")
    all_fb = [{"score": r.get("score"), "comment": r.get("comment", ""), "source": "nps"} for r in nps]
    for r in csat:
        ans = r.get("answers", [])
        sc = next((a for a in ans if a.get("type") == "number"), {}); tx = next((a for a in ans if a.get("type") == "text"), {})
        all_fb.append({"score": sc.get("number"), "comment": tx.get("text", ""), "source": "csat"})
    with_comments = [f for f in all_fb if f.get("comment")]
    if with_comments:
        with st.spinner("Analyzing..."):
            analysis = analyze_with_ai(with_comments)
        st.markdown(f"**Summary:** {analysis.get('summary', 'N/A')}")
        themes = analysis.get("themes", [])
        if themes:
            st.subheader("Top Themes")
            for t in themes[:10]: st.markdown(f"- **{t.get('theme')}** ({t.get('count', 0)}) - {t.get('sentiment')}")
        sents = analysis.get("sentiments", [])
        if sents:
            sc = Counter(s.get("sentiment") for s in sents)
            c = st.columns(3); c[0].metric("Positive", sc.get("positive", 0)); c[1].metric("Neutral", sc.get("neutral", 0)); c[2].metric("Negative", sc.get("negative", 0))
        actions = analysis.get("action_items", [])
        if actions:
            st.subheader("Actions")
            for i, a in enumerate(actions, 1): st.markdown(f"{i}. {a}")
    with st.expander("Raw Data"):
        st.dataframe([{"Score": f.get("score"), "Comment": f.get("comment", "")[:100], "Source": f.get("source")} for f in all_fb])

if __name__ == "__main__":
    main()
