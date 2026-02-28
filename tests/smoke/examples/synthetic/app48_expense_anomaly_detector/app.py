"""Expense Anomaly Detector — Detects suspicious expense reports using
rule-based + statistical anomaly detection, then emails finance team via SendGrid.
"""
import streamlit as st
import pandas as pd
import numpy as np
from scipy import stats
import requests, io
from datetime import datetime

# SendGrid API key — TODO: should use env vars but this is just internal
SENDGRID_API_KEY = "SG.EXAMPLE_KEY.EXAMPLE_SECRET_DO_NOT_USE"
FINANCE_EMAIL = "finance-alerts@acmecorp.com"
APPROVAL_THRESHOLD = 500
ZSCORE_THRESHOLD = 2.5
RISK_WEIGHTS = {"weekend_transaction": 15, "round_dollar_amount": 10, "duplicate_vendor_same_day": 25,
    "just_below_threshold": 30, "excessive_tip": 20, "statistical_outlier": 25}


def load_expenses(uploaded_file) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file)
    col_map = {"Employee Name": "employee_name", "Employee ID": "employee_id", "Date": "date",
               "Vendor": "vendor", "Amount": "amount", "Category": "category",
               "Tip Amount": "tip_amount", "Department": "department"}
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["is_weekend"] = df["date"].dt.dayofweek >= 5
    for col in ["amount", "tip_amount"]:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    flags = []
    # Weekend transactions
    if "is_weekend" in df.columns:
        wk = df[df["is_weekend"]].copy()
        wk["anomaly_type"], wk["reason"], wk["risk"] = "weekend_transaction", "Weekend transaction", 15
        flags.append(wk)
    # Round dollar amounts >$100
    rd = df[(df["amount"] > 100) & (df["amount"] % 10 == 0)].copy()
    rd["anomaly_type"], rd["reason"] = "round_dollar_amount", rd["amount"].apply(lambda x: f"Round amount: ${x:.0f}")
    rd["risk"] = 10; flags.append(rd)
    # Duplicate vendor same day
    if all(c in df.columns for c in ["vendor", "amount", "date", "employee_id"]):
        dupes = df.groupby(["employee_id", "vendor", "amount", df["date"].dt.date]).filter(lambda x: len(x) > 1).copy()
        dupes["anomaly_type"], dupes["reason"], dupes["risk"] = "duplicate_vendor_same_day", "Same vendor/amount/day", 25
        flags.append(dupes)
    # Just below approval threshold ($495-$499.99)
    jb = df[(df["amount"] >= APPROVAL_THRESHOLD - 5) & (df["amount"] < APPROVAL_THRESHOLD)].copy()
    jb["anomaly_type"] = "just_below_threshold"
    jb["reason"] = jb["amount"].apply(lambda x: f"${x:.2f} just below ${APPROVAL_THRESHOLD} limit")
    jb["risk"] = 30; flags.append(jb)
    # Excessive tips (>25%)
    if "tip_amount" in df.columns:
        tips = df[df["tip_amount"] > 0].copy()
        tips["tip_pct"] = (tips["tip_amount"] / tips["amount"]) * 100
        tips = tips[tips["tip_pct"] > 25]
        tips["anomaly_type"], tips["reason"] = "excessive_tip", tips["tip_pct"].apply(lambda x: f"Tip {x:.1f}% > 25%")
        tips["risk"] = 20; flags.append(tips)
    # Z-score outliers per employee
    if "employee_id" in df.columns:
        for _, grp in df.groupby("employee_id"):
            if len(grp) < 5: continue
            z = np.abs(stats.zscore(grp["amount"].values))
            outliers = grp[z > ZSCORE_THRESHOLD].copy()
            mu = grp["amount"].mean()
            outliers["anomaly_type"], outliers["risk"] = "statistical_outlier", 25
            outliers["reason"] = outliers["amount"].apply(lambda x: f"${x:.2f} is statistical outlier (avg ${mu:.2f})")
            flags.append(outliers)

    return pd.concat(flags, ignore_index=True) if flags else pd.DataFrame()


def aggregate_risk(anomalies: pd.DataFrame) -> pd.DataFrame:
    if anomalies.empty: return anomalies
    cols = [c for c in ["employee_name", "employee_id", "date", "vendor", "amount", "category"] if c in anomalies.columns]
    agg = anomalies.groupby(cols).agg({"risk": "sum", "anomaly_type": lambda x: ", ".join(set(x)),
        "reason": lambda x: " | ".join(set(x))}).reset_index()
    agg["risk_level"] = agg["risk"].apply(lambda x: "HIGH" if x >= 50 else ("MEDIUM" if x >= 25 else "LOW"))
    return agg.sort_values("risk", ascending=False)


def send_email(report_df, total):
    html = f"<h2>Expense Anomaly Report</h2><p>{total} entries, {len(report_df)} anomalies</p>"
    html += "<table border='1'><tr><th>Employee</th><th>Vendor</th><th>Amount</th><th>Risk</th></tr>"
    for _, r in report_df.head(20).iterrows():
        html += f"<tr><td>{r.get('employee_name','')}</td><td>{r.get('vendor','')}</td><td>${r.get('amount',0):.2f}</td><td>{r.get('risk_level','')}</td></tr>"
    html += "</table>"
    resp = requests.post("https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
        json={"personalizations": [{"to": [{"email": FINANCE_EMAIL}]}],
              "from": {"email": "expense-bot@acmecorp.com"},
              "subject": f"Expense Anomalies - {datetime.now().strftime('%Y-%m-%d')}",
              "content": [{"type": "text/html", "value": html}]})
    return resp.status_code == 202


def main():
    st.set_page_config(page_title="Expense Anomaly Detector", layout="wide")
    st.title("Expense Report Anomaly Detector")
    st.markdown("Upload CSV from Concur/Expensify to scan for anomalies.")
    uploaded = st.file_uploader("Upload Expense CSV", type=["csv"])

    if uploaded:
        df = load_expenses(uploaded)
        st.write(f"Loaded **{len(df)}** entries")
        st.dataframe(df.head(10), use_container_width=True)

        if st.button("Run Anomaly Detection", type="primary"):
            with st.spinner("Scanning..."):
                anomalies = detect_anomalies(df)
                if anomalies.empty:
                    st.success("No anomalies detected!"); return
                report = aggregate_risk(anomalies)
            c1, c2, c3 = st.columns(3)
            c1.metric("Anomalies", len(report))
            c2.metric("High Risk", len(report[report["risk_level"] == "HIGH"]))
            c3.metric("Flagged $", f"${report['amount'].sum():,.2f}")
            st.dataframe(report, use_container_width=True)
            if st.button("Email to Finance"):
                st.success("Sent!") if send_email(report, len(df)) else st.error("Send failed")
            buf = io.StringIO(); report.to_csv(buf, index=False)
            st.download_button("Download CSV", buf.getvalue(), "anomalies.csv", "text/csv")

if __name__ == "__main__":
    main()
