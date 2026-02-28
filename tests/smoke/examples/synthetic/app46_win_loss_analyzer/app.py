"""Win/Loss Analyzer — Sales intelligence pulling from Salesforce and Gong,
with AI-powered pattern analysis via OpenAI.
"""
import streamlit as st
import pandas as pd
import openai, requests, json
from simple_salesforce import Salesforce
import plotly.express as px
from datetime import datetime, timedelta

# Credentials — hardcoded, will move to secrets manager when IT sets it up
SALESFORCE_USERNAME = "analytics-bot@acmecorp.com"
SALESFORCE_PASSWORD = "Sf$ecur3P@ss2024!"
SALESFORCE_TOKEN = "aK9mN2rT5wQ8yB1dF4gH7jL3"
GONG_API_KEY = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.gong-api-2024-acmecorp-prod"
GONG_BASE_URL = "https://api.gong.io/v2"
OPENAI_API_KEY = "sk-proj-example-key-do-not-use-000000000000"
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)


def get_salesforce_deals(months_back=6):
    try:
        sf = Salesforce(username=SALESFORCE_USERNAME, password=SALESFORCE_PASSWORD,
                        security_token=SALESFORCE_TOKEN, domain="acmecorp")
        cutoff = (datetime.now() - timedelta(days=months_back * 30)).strftime("%Y-%m-%d")
        results = sf.query_all(f"""SELECT Id, Name, Amount, StageName, CloseDate,
            Account.Name, Owner.Name, Competitor__c, Loss_Reason__c,
            Deal_Cycle_Days__c, Segment__c FROM Opportunity
            WHERE (StageName='Closed Won' OR StageName='Closed Lost')
            AND CloseDate >= {cutoff} ORDER BY CloseDate DESC""")
        return pd.DataFrame(results["records"])
    except Exception as e:
        st.warning(f"Salesforce failed: {e}. Using demo data.")
        return _generate_demo_deals()


def get_gong_transcripts(deal_ids: list) -> dict:
    headers = {"Authorization": f"Bearer {GONG_API_KEY}", "Content-Type": "application/json"}
    transcripts = {}
    for did in deal_ids[:50]:  # TODO: handle rate limiting properly
        try:
            resp = requests.post(f"{GONG_BASE_URL}/calls/extensive", headers=headers,
                json={"filter": {"crmDealIds": [did]}, "contentSelector": {"exposedFields": {"content": True}}}, timeout=10)
            if resp.status_code == 200:
                transcripts[did] = [c.get("content", {}).get("summary", "") for c in resp.json().get("calls", [])]
        except Exception:
            continue
    return transcripts


def analyze_patterns(deals_df, transcripts):
    won, lost = deals_df[deals_df["StageName"]=="Closed Won"], deals_df[deals_df["StageName"]=="Closed Lost"]
    summary = f"Won: {len(won)} (${won['Amount'].sum():,.0f}), Lost: {len(lost)} (${lost['Amount'].sum():,.0f})\n"
    summary += f"Loss reasons: {lost['Loss_Reason__c'].value_counts().head(5).to_dict()}\n"
    summary += f"Competitors: {deals_df['Competitor__c'].value_counts().head(5).to_dict()}\n"
    summary += f"Transcripts sample: {json.dumps(list(transcripts.values())[:5])[:2000]}"
    resp = openai_client.chat.completions.create(model="gpt-4o", temperature=0.3, max_tokens=2000,
        messages=[{"role": "user", "content": f"""Analyze win/loss data. Return JSON:
{{"won_patterns":[],"lost_patterns":[],"objections":[],"competitive_intel":[],"recommendations":[]}}
Data: {summary}"""}])
    result = resp.choices[0].message.content.strip()
    if result.startswith("```"): result = result.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(result)


def _generate_demo_deals():
    import random
    competitors = ["Competitor A", "Competitor B", "Competitor C", "Internal Build", None]
    loss_reasons = ["Price", "Feature Gap", "Timing", "Competitor", "No decision", "Budget cut"]
    records = []
    for i in range(150):
        is_won = random.random() > 0.38
        records.append({"Id": f"006{i:012d}", "Name": f"Deal-{i}",
            "Amount": random.choice([25000, 50000, 100000, 250000, 500000]),
            "StageName": "Closed Won" if is_won else "Closed Lost",
            "CloseDate": (datetime.now() - timedelta(days=random.randint(1, 180))).strftime("%Y-%m-%d"),
            "Owner_Name": random.choice(["Sarah Chen", "Mike Johnson", "Lisa Park"]),
            "Competitor__c": random.choice(competitors),
            "Loss_Reason__c": random.choice(loss_reasons) if not is_won else None,
            "Deal_Cycle_Days__c": random.randint(14, 120),
            "Segment__c": random.choice(["Enterprise", "Mid-Market", "SMB"])})
    return pd.DataFrame(records)


def main():
    st.set_page_config(page_title="Win/Loss Analyzer", layout="wide")
    st.title("Sales Win/Loss Intelligence")
    months = st.sidebar.selectbox("Period (months)", [3, 6, 9, 12], index=1)
    deals_df = get_salesforce_deals(months)
    won, lost = deals_df[deals_df["StageName"]=="Closed Won"], deals_df[deals_df["StageName"]=="Closed Lost"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Win Rate", f"{len(won)/max(len(deals_df),1)*100:.1f}%")
    c2.metric("Won", f"{len(won)}", f"${won['Amount'].sum():,.0f}")
    c3.metric("Lost", f"{len(lost)}", f"${lost['Amount'].sum():,.0f}")
    c4.metric("Avg Cycle", f"{won['Deal_Cycle_Days__c'].mean():.0f}d")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Win Rate by Competitor")
        comp = deals_df[deals_df["Competitor__c"].notna()]
        if not comp.empty:
            wr = comp.groupby("Competitor__c").apply(lambda x: len(x[x["StageName"]=="Closed Won"])/len(x)*100).reset_index(name="Win%")
            st.plotly_chart(px.bar(wr, x="Competitor__c", y="Win%"), use_container_width=True)
    with col2:
        st.subheader("Loss Reasons")
        lr = lost["Loss_Reason__c"].value_counts()
        if not lr.empty:
            st.plotly_chart(px.pie(values=lr.values, names=lr.index), use_container_width=True)

    if st.button("Generate AI Digest", type="primary"):
        with st.spinner("Analyzing with Gong transcripts and AI..."):
            transcripts = get_gong_transcripts(deals_df["Id"].tolist())
            analysis = analyze_patterns(deals_df, transcripts)
        for section in ["won_patterns", "lost_patterns", "objections", "competitive_intel", "recommendations"]:
            st.subheader(section.replace("_", " ").title())
            for item in analysis.get(section, []):
                st.markdown(f"- {item}")

if __name__ == "__main__":
    main()
