"""
Vendor Scorecard — Vendor assessment and scoring tool.
Evaluates vendors across multiple dimensions with weighted scoring.
TODO: need to add multi-user support, currently single-user
"""

import streamlit as st
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# D&B API for financial data
DNB_API_KEY = "dXNlcjpBUElLZXktZG5iLTk4NzY1LXByb2QtMmY4YTNiNGU1ZDFj"
DNB_BASE_URL = "https://plus.dnb.com/v1"

# Google Sheets — stores all evaluations
# TODO: switch to a real database, sheets is getting slow with 500+ vendors
GOOGLE_CREDS_PATH = "/etc/secrets/vendor-scorecard-sa-4a7b2c.json"
SPREADSHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"

SCORING_WEIGHTS = {
    "financial_stability": 0.20,
    "security_posture": 0.25,
    "delivery_performance": 0.25,
    "quality": 0.20,
    "pricing": 0.10,
}

MINIMUM_THRESHOLDS = {
    "security_posture": 70,  # Must score above 70 to pass — non-negotiable per CISO
}

def fetch_dnb_rating(vendor_duns):
    """Pull financial stability rating from D&B"""
    # TODO: handle rate limiting, we got 429'd last month
    headers = {"Authorization": f"Bearer {DNB_API_KEY}", "Content-Type": "application/json"}
    try:
        resp = requests.get(f"{DNB_BASE_URL}/data/duns/{vendor_duns}?blockIDs=financialstrengthinsight_L2_v1",
                           headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("financialStrengthInsight", {}).get("overallRiskScore", 50)
        return None
    except Exception as e:
        st.warning(f"D&B API error: {e}")
        return None

def save_to_sheets(evaluation):
    """Save evaluation to Google Sheets"""
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_PATH, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    row = [
        evaluation["vendor_name"], evaluation["duns_number"],
        evaluation["financial_score"], evaluation["security_score"],
        evaluation["delivery_score"], evaluation["quality_score"],
        evaluation["pricing_score"], evaluation["weighted_total"],
        evaluation["pass_fail"], evaluation["evaluated_by"],
        evaluation["evaluated_at"],
    ]
    sheet.append_row(row)

def calculate_weighted_score(scores):
    """Calculate weighted total and determine pass/fail"""
    total = 0
    for dimension, weight in SCORING_WEIGHTS.items():
        total += scores.get(dimension, 0) * weight

    # Check minimum thresholds
    passed = True
    failures = []
    for dimension, threshold in MINIMUM_THRESHOLDS.items():
        if scores.get(dimension, 0) < threshold:
            passed = False
            failures.append(f"{dimension} ({scores.get(dimension, 0)} < {threshold})")

    return round(total, 1), passed, failures

# --- Simulated vendor database for demo purposes ---
SAMPLE_VENDORS = {
    "Acme Cloud Services": {"duns": "123456789", "category": "Cloud Infrastructure"},
    "DataPipe Analytics": {"duns": "987654321", "category": "Data Processing"},
    "SecureAuth Inc": {"duns": "456789123", "category": "Security"},
    "FastShip Logistics": {"duns": "789123456", "category": "Logistics"},
    "CodeReview Pro": {"duns": "321654987", "category": "Developer Tools"},
}

def main():
    st.set_page_config(page_title="Vendor Scorecard", layout="wide")
    st.title("Vendor Evaluation Scorecard")

    tab1, tab2 = st.tabs(["New Evaluation", "Scoring History"])

    with tab1:
        st.subheader("Evaluate Vendor")

        col1, col2 = st.columns(2)
        with col1:
            vendor_name = st.selectbox("Vendor", list(SAMPLE_VENDORS.keys()))
            vendor_info = SAMPLE_VENDORS[vendor_name]
            st.info(f"DUNS: {vendor_info['duns']} | Category: {vendor_info['category']}")
            evaluator = st.text_input("Your Name", value="")  # TODO: pull from SSO

        with col2:
            st.markdown("### Scoring (0-100)")
            financial_score = st.slider("Financial Stability (20%)", 0, 100, 75)
            security_score = st.slider("Security Posture (25%)", 0, 100, 80)
            delivery_score = st.slider("Delivery Performance (25%)", 0, 100, 85)
            quality_score = st.slider("Quality - Defect Rate (20%)", 0, 100, 90)
            pricing_score = st.slider("Pricing Competitiveness (10%)", 0, 100, 70)

        # Auto-fetch D&B data
        if st.button("Fetch D&B Financial Rating"):
            dnb_rating = fetch_dnb_rating(vendor_info["duns"])
            if dnb_rating:
                st.success(f"D&B Risk Score: {dnb_rating}")
            else:
                st.warning("Could not fetch D&B data. Using manual score.")

        scores = {
            "financial_stability": financial_score,
            "security_posture": security_score,
            "delivery_performance": delivery_score,
            "quality": quality_score,
            "pricing": pricing_score,
        }

        weighted_total, passed, failures = calculate_weighted_score(scores)

        st.markdown("---")
        st.metric("Weighted Total Score", f"{weighted_total}/100")
        if passed:
            st.success("PASS - Vendor meets all minimum thresholds")
        else:
            st.error(f"FAIL - Below threshold: {', '.join(failures)}")

        if st.button("Submit Evaluation"):
            if not evaluator:
                st.error("Please enter your name")
                return
            evaluation = {
                "vendor_name": vendor_name, "duns_number": vendor_info["duns"],
                "financial_score": financial_score, "security_score": security_score,
                "delivery_score": delivery_score, "quality_score": quality_score,
                "pricing_score": pricing_score, "weighted_total": weighted_total,
                "pass_fail": "PASS" if passed else "FAIL",
                "evaluated_by": evaluator, "evaluated_at": datetime.now().isoformat(),
            }
            try:
                save_to_sheets(evaluation)
                st.success(f"Evaluation saved for {vendor_name}")
            except Exception as e:
                st.error(f"Failed to save: {e}")  # works fine for now

    with tab2:
        st.subheader("Recent Evaluations")
        st.info("Connect Google Sheets to view history")
        # TODO: pull historical data from sheets and display as table

if __name__ == "__main__":
    main()
