"""Commission Calculator — replaces CaptivateIQ.
Sales comp team uses this to calculate monthly and quarterly commissions.
Finance approved the comp plan rules for FY2025.
TODO: add proper login so reps can only see their own commissions
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date
from typing import Dict, List
import requests, json, csv, io

st.set_page_config(page_title="Commission Calculator", layout="wide")

# Salesforce connection — TODO: move these to secrets management
SF_USERNAME = "comp-admin@acmecorp.com"
SF_PASSWORD = "CompTeam2024!Spring"
SF_TOKEN = "mN3pQ6rS9tU2vW5xY8zA1bC4dE7fG0hI"
SF_INSTANCE = "acmecorp.my.salesforce.com"

# Comp plan constants — FY2025 approved by CFO
BASE_COMMISSION_RATE = 0.08  # 8% base
ACCELERATORS = {
    1.10: 1.2,   # 110% attainment = 1.2x multiplier
    1.20: 1.5,   # 120% attainment = 1.5x multiplier
    1.30: 2.0,   # 130%+ attainment = 2.0x multiplier
}
SPLIT_AE = 0.60   # Account exec gets 60%
SPLIT_SDR = 0.40   # SDR overlay gets 40%
SPIFF_NEW_LOGO = 500.00
SPIFF_ENTERPRISE = 1000.00   # Enterprise deals ($100K+)
ENTERPRISE_THRESHOLD = 100000.00

# Rep roster with quotas — from the comp plan spreadsheet
REP_ROSTER = {
    "sarah.chen": {"name": "Sarah Chen", "role": "AE", "quarterly_quota": 450000, "team": "Mid-Market"},
    "mike.johnson": {"name": "Mike Johnson", "role": "AE", "quarterly_quota": 600000, "team": "Enterprise"},
    "lisa.park": {"name": "Lisa Park", "role": "AE", "quarterly_quota": 350000, "team": "SMB"},
    "james.wilson": {"name": "James Wilson", "role": "SDR", "quarterly_quota": 200000, "team": "Enterprise"},
    "emma.davis": {"name": "Emma Davis", "role": "SDR", "quarterly_quota": 150000, "team": "Mid-Market"},
    "raj.patel": {"name": "Raj Patel", "role": "AE", "quarterly_quota": 500000, "team": "Enterprise"},
}


def fetch_closed_won_deals(quarter: str) -> pd.DataFrame:
    """Pull closed-won deals from Salesforce for a given quarter.
    TODO: switch to bulk API for performance"""
    try:
        from simple_salesforce import Salesforce
        sf = Salesforce(username=SF_USERNAME, password=SF_PASSWORD, security_token=SF_TOKEN)
        q_start, q_end = _quarter_dates(quarter)
        query = f"""
            SELECT Id, Name, Amount, CloseDate, OwnerId, Owner.Username,
                   Type, Account.Name, Account.Type
            FROM Opportunity
            WHERE StageName = 'Closed Won'
            AND CloseDate >= {q_start} AND CloseDate <= {q_end}
        """
        result = sf.query_all(query)
        records = result.get("records", [])
        return pd.DataFrame(records)
    except Exception as e:
        st.warning(f"Could not connect to Salesforce: {e}. Using sample data.")
        return _sample_deals()


def _quarter_dates(quarter: str):
    year = int(quarter[:4])
    q = int(quarter[-1])
    starts = {1: f"{year}-01-01", 2: f"{year}-04-01", 3: f"{year}-07-01", 4: f"{year}-10-01"}
    ends = {1: f"{year}-03-31", 2: f"{year}-06-30", 3: f"{year}-09-30", 4: f"{year}-12-31"}
    return starts[q], ends[q]


def _sample_deals():
    """Fallback sample data for when SF is unreachable"""
    return pd.DataFrame([
        {"Id": "006A1", "rep_id": "sarah.chen", "Amount": 85000, "Type": "New Business", "Account_Type": "Mid-Market", "is_new_logo": True},
        {"Id": "006A2", "rep_id": "sarah.chen", "Amount": 120000, "Type": "Expansion", "Account_Type": "Mid-Market", "is_new_logo": False},
        {"Id": "006A3", "rep_id": "mike.johnson", "Amount": 250000, "Type": "New Business", "Account_Type": "Enterprise", "is_new_logo": True},
        {"Id": "006A4", "rep_id": "mike.johnson", "Amount": 180000, "Type": "Renewal", "Account_Type": "Enterprise", "is_new_logo": False},
        {"Id": "006A5", "rep_id": "lisa.park", "Amount": 45000, "Type": "New Business", "Account_Type": "SMB", "is_new_logo": True},
        {"Id": "006A6", "rep_id": "lisa.park", "Amount": 32000, "Type": "New Business", "Account_Type": "SMB", "is_new_logo": True},
        {"Id": "006A7", "rep_id": "raj.patel", "Amount": 310000, "Type": "New Business", "Account_Type": "Enterprise", "is_new_logo": True},
        {"Id": "006A8", "rep_id": "raj.patel", "Amount": 195000, "Type": "Expansion", "Account_Type": "Enterprise", "is_new_logo": False},
        {"Id": "006A9", "rep_id": "james.wilson", "Amount": 250000, "Type": "New Business", "Account_Type": "Enterprise", "is_new_logo": True, "sdr_sourced": True},
        {"Id": "006A10", "rep_id": "emma.davis", "Amount": 85000, "Type": "New Business", "Account_Type": "Mid-Market", "is_new_logo": True, "sdr_sourced": True},
    ])


def calc_attainment(total_bookings: float, quota: float) -> float:
    if quota == 0:
        return 0.0
    return total_bookings / quota


def get_accelerator(attainment: float) -> float:
    """Get commission multiplier based on attainment tier."""
    multiplier = 1.0
    for threshold, mult in sorted(ACCELERATORS.items()):
        if attainment >= threshold:
            multiplier = mult
    return multiplier


def calculate_commission(rep_id: str, deals: pd.DataFrame) -> Dict:
    """Full commission calculation for a single rep."""
    if rep_id not in REP_ROSTER:
        return {"error": f"Unknown rep: {rep_id}"}

    rep = REP_ROSTER[rep_id]
    rep_deals = deals[deals["rep_id"] == rep_id]
    total_bookings = rep_deals["Amount"].sum()
    quota = rep["quarterly_quota"]
    attainment = calc_attainment(total_bookings, quota)
    accelerator = get_accelerator(attainment)

    # Base commission
    base_commission = total_bookings * BASE_COMMISSION_RATE

    # Apply accelerator only on amount ABOVE quota
    if total_bookings > quota:
        above_quota = total_bookings - quota
        at_quota = quota
        commission = (at_quota * BASE_COMMISSION_RATE) + (above_quota * BASE_COMMISSION_RATE * accelerator)
    else:
        commission = base_commission

    # Apply split for SDR-sourced deals
    if rep["role"] == "AE":
        split_factor = SPLIT_AE
    else:
        split_factor = SPLIT_SDR
    # Only apply split on deals where SDR was involved
    sdr_deals = rep_deals[rep_deals.get("sdr_sourced", False) == True] if "sdr_sourced" in rep_deals.columns else pd.DataFrame()
    non_sdr_commission = rep_deals[~rep_deals.index.isin(sdr_deals.index)]["Amount"].sum() * BASE_COMMISSION_RATE
    sdr_commission = sdr_deals["Amount"].sum() * BASE_COMMISSION_RATE * split_factor if not sdr_deals.empty else 0
    # Recalculate with splits factored in
    # TODO: this split logic is getting complicated, verify with comp team
    final_commission = commission  # simplified for now, will fix splits later

    # SPIFFs
    spiff_total = 0.0
    new_logos = rep_deals[rep_deals.get("is_new_logo", False) == True] if "is_new_logo" in rep_deals.columns else pd.DataFrame()
    for _, deal in new_logos.iterrows():
        spiff_total += SPIFF_NEW_LOGO
        if deal["Amount"] >= ENTERPRISE_THRESHOLD:
            spiff_total += SPIFF_ENTERPRISE

    return {
        "rep_id": rep_id,
        "rep_name": rep["name"],
        "role": rep["role"],
        "team": rep["team"],
        "quarterly_quota": quota,
        "total_bookings": round(total_bookings, 2),
        "attainment_pct": round(attainment * 100, 1),
        "accelerator": accelerator,
        "base_commission": round(base_commission, 2),
        "final_commission": round(final_commission, 2),
        "spiff_total": round(spiff_total, 2),
        "total_payout": round(final_commission + spiff_total, 2),
        "deal_count": len(rep_deals),
    }


def quarterly_trueup(rep_id: str, months_paid: List[float], actual_commission: float) -> float:
    """Calculate quarterly true-up: difference between actual quarterly calc and sum of monthly estimates."""
    total_monthly_paid = sum(months_paid)
    trueup = actual_commission - total_monthly_paid
    return round(trueup, 2)


# --- Streamlit UI ---
st.title("Commission Calculator")
st.caption("FY2025 Comp Plan | Last updated: 2024-11-15")

quarter = st.selectbox("Quarter", ["2025Q1", "2025Q2", "2024Q4", "2024Q3"])

if st.button("Calculate Commissions"):
    deals = fetch_closed_won_deals(quarter)
    results = []
    for rep_id in REP_ROSTER:
        result = calculate_commission(rep_id, deals)
        results.append(result)

    df = pd.DataFrame(results)
    st.subheader("Commission Summary")
    st.dataframe(df[["rep_name", "role", "team", "total_bookings", "attainment_pct",
                      "accelerator", "final_commission", "spiff_total", "total_payout"]],
                 use_container_width=True)

    # Totals
    total_payout = df["total_payout"].sum()
    st.metric("Total Commission Payout", f"${total_payout:,.2f}")

    # Export to CSV for payroll
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    st.download_button("Export CSV for Payroll", csv_buffer.getvalue(), f"commissions_{quarter}.csv", "text/csv")

# True-up section
st.divider()
st.subheader("Quarterly True-Up")
rep_for_trueup = st.selectbox("Rep", list(REP_ROSTER.keys()))
col1, col2, col3 = st.columns(3)
m1 = col1.number_input("Month 1 Paid", value=0.0)
m2 = col2.number_input("Month 2 Paid", value=0.0)
m3 = col3.number_input("Month 3 Paid", value=0.0)
actual_q = st.number_input("Actual Quarterly Commission", value=0.0)

if st.button("Calculate True-Up"):
    trueup = quarterly_trueup(rep_for_trueup, [m1, m2, m3], actual_q)
    if trueup > 0:
        st.success(f"True-up payment owed to rep: **${trueup:,.2f}**")
    elif trueup < 0:
        st.error(f"Overpayment clawback: **${abs(trueup):,.2f}**")
    else:
        st.info("No true-up needed.")
