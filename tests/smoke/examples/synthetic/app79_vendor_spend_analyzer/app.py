"""
Vendor Spend Analyzer — Procurement spend analytics from NetSuite AP data.
Identifies consolidation opportunities and renegotiation candidates.
TODO: add proper date range picker, right now it's always last 12 months
"""

import streamlit as st
import requests
import json
import hashlib
from datetime import datetime, timedelta
from collections import defaultdict

# NetSuite API credentials
# TODO: use OAuth 2.0 instead of token-based auth, NetSuite is deprecating this
NETSUITE_ACCOUNT_ID = "5432198"
NETSUITE_CONSUMER_KEY = "c8f2e4a6b0d1937f5e8c2a4b6d0f1937e5c8a2b4"
NETSUITE_CONSUMER_SECRET = "a1b3c5d7e9f0a2b4c6d8e0f1a3b5c7d9e1f3a5b7"
NETSUITE_TOKEN_ID = "t9k7m5n3p1q8r6s4u2v0w7x5y3z1a8b6c4d2e0f"
NETSUITE_TOKEN_SECRET = "f0e2d4c6b8a1f3e5d7c9b0a2f4e6d8c1b3a5f7e9"
NETSUITE_BASE_URL = f"https://{NETSUITE_ACCOUNT_ID}.suitetalk.api.netsuite.com/services/rest/record/v1"

TAIL_SPEND_THRESHOLD = 10000  # vendors under $10K/year

def fetch_ap_data():
    """Fetch accounts payable data from NetSuite"""
    headers = {
        "Authorization": f"Bearer {NETSUITE_TOKEN_SECRET}",  # TODO: implement proper OAuth signature
        "Content-Type": "application/json",
    }
    # Simulated AP data — in production this calls NetSuite SuiteTalk REST API
    # TODO: paginate properly, we're only getting first 1000 records
    return [
        {"vendor": "AWS", "invoice_amount": 45230.00, "date": "2024-01-15", "category": "Cloud Infrastructure", "department": "Engineering", "po_number": "PO-2024-001"},
        {"vendor": "AWS", "invoice_amount": 47890.00, "date": "2024-02-15", "category": "Cloud Infrastructure", "department": "Engineering", "po_number": "PO-2024-015"},
        {"vendor": "AWS", "invoice_amount": 52100.00, "date": "2024-03-15", "category": "Cloud Infrastructure", "department": "Engineering", "po_number": "PO-2024-031"},
        {"vendor": "Google Cloud", "invoice_amount": 12300.00, "date": "2024-01-20", "category": "Cloud Infrastructure", "department": "Data Science", "po_number": "PO-2024-003"},
        {"vendor": "Google Cloud", "invoice_amount": 13100.00, "date": "2024-02-20", "category": "Cloud Infrastructure", "department": "Data Science", "po_number": "PO-2024-018"},
        {"vendor": "Salesforce", "invoice_amount": 84000.00, "date": "2024-01-01", "category": "CRM", "department": "Sales", "po_number": "PO-2024-002"},
        {"vendor": "HubSpot", "invoice_amount": 36000.00, "date": "2024-01-01", "category": "Marketing Automation", "department": "Marketing", "po_number": "PO-2024-004"},
        {"vendor": "Slack Technologies", "invoice_amount": 28800.00, "date": "2024-01-01", "category": "Collaboration", "department": "IT", "po_number": "PO-2024-005"},
        {"vendor": "Datadog", "invoice_amount": 42000.00, "date": "2024-01-01", "category": "Monitoring", "department": "Engineering", "po_number": "PO-2024-006"},
        {"vendor": "New Relic", "invoice_amount": 18500.00, "date": "2024-03-01", "category": "Monitoring", "department": "Engineering", "po_number": "PO-2024-032"},
        {"vendor": "Snyk", "invoice_amount": 15000.00, "date": "2024-01-15", "category": "Security", "department": "Engineering", "po_number": "PO-2024-008"},
        {"vendor": "Okta", "invoice_amount": 24000.00, "date": "2024-01-01", "category": "Security", "department": "IT", "po_number": "PO-2024-009"},
        {"vendor": "Zoom", "invoice_amount": 9600.00, "date": "2024-01-01", "category": "Collaboration", "department": "IT", "po_number": "PO-2024-010"},
        {"vendor": "Microsoft 365", "invoice_amount": 52000.00, "date": "2024-01-01", "category": "Productivity", "department": "IT", "po_number": "PO-2024-011"},
        {"vendor": "Figma", "invoice_amount": 7200.00, "date": "2024-01-01", "category": "Design", "department": "Product", "po_number": "PO-2024-012"},
        {"vendor": "Notion", "invoice_amount": 4800.00, "date": "2024-01-01", "category": "Productivity", "department": "Product", "po_number": "PO-2024-013"},
        {"vendor": "Vercel", "invoice_amount": 3600.00, "date": "2024-02-01", "category": "Cloud Infrastructure", "department": "Engineering", "po_number": "PO-2024-016"},
        {"vendor": "CircleCI", "invoice_amount": 8400.00, "date": "2024-01-01", "category": "CI/CD", "department": "Engineering", "po_number": "PO-2024-014"},
        {"vendor": "Greenhouse", "invoice_amount": 18000.00, "date": "2024-01-01", "category": "HR Tech", "department": "HR", "po_number": "PO-2024-007"},
        {"vendor": "Gusto", "invoice_amount": 12000.00, "date": "2024-01-01", "category": "Payroll", "department": "HR", "po_number": "PO-2024-017"},
        {"vendor": "Office Supplies Co", "invoice_amount": 2340.00, "date": "2024-01-10", "category": "Office Supplies", "department": "Operations", "po_number": "PO-2024-019"},
        {"vendor": "Staples", "invoice_amount": 1890.00, "date": "2024-02-05", "category": "Office Supplies", "department": "Operations", "po_number": "PO-2024-020"},
        {"vendor": "WeWork", "invoice_amount": 45000.00, "date": "2024-01-01", "category": "Real Estate", "department": "Operations", "po_number": "PO-2024-021"},
    ]

# Contracted rates for compliance checking
CONTRACTED_RATES = {
    "AWS": {"annual_commit": 500000, "discount": 0.15},
    "Salesforce": {"annual_commit": 84000, "discount": 0.10},
    "Datadog": {"annual_commit": 42000, "discount": 0.20},
    "Slack Technologies": {"annual_commit": 28800, "discount": 0.05},
}

def analyze_spend(ap_data):
    """Analyze AP data for insights"""
    by_vendor = defaultdict(float)
    by_category = defaultdict(float)
    by_department = defaultdict(float)
    by_month = defaultdict(float)

    for inv in ap_data:
        by_vendor[inv["vendor"]] += inv["invoice_amount"]
        by_category[inv["category"]] += inv["invoice_amount"]
        by_department[inv["department"]] += inv["invoice_amount"]
        month = inv["date"][:7]
        by_month[month] += inv["invoice_amount"]

    # Top 10 vendors
    top_vendors = sorted(by_vendor.items(), key=lambda x: -x[1])[:10]

    # Tail spend
    tail_vendors = [(v, amt) for v, amt in by_vendor.items() if amt < TAIL_SPEND_THRESHOLD]

    # Duplicate detection — vendors in same category
    category_vendors = defaultdict(list)
    for inv in ap_data:
        if inv["vendor"] not in [v for v, _ in category_vendors[inv["category"]]]:
            category_vendors[inv["category"]].append((inv["vendor"], by_vendor[inv["vendor"]]))
    duplicates = {cat: vendors for cat, vendors in category_vendors.items() if len(vendors) > 1}

    # Contract compliance
    compliance = {}
    for vendor, contract in CONTRACTED_RATES.items():
        actual = by_vendor.get(vendor, 0)
        committed = contract["annual_commit"]
        compliance[vendor] = {
            "committed": committed, "actual_ytd": actual,
            "utilization": round(actual / committed * 100, 1) if committed else 0,
            "on_track": actual <= committed * 1.1,
        }

    return {
        "by_vendor": dict(by_vendor), "by_category": dict(by_category),
        "by_department": dict(by_department), "by_month": dict(by_month),
        "top_vendors": top_vendors, "tail_vendors": tail_vendors,
        "duplicate_categories": duplicates, "contract_compliance": compliance,
        "total_spend": sum(by_vendor.values()),
    }

def generate_recommendations(analysis):
    """Generate spend optimization recommendations"""
    recs = []

    # Consolidation opportunities
    for category, vendors in analysis["duplicate_categories"].items():
        if len(vendors) > 1:
            vendor_names = [v[0] for v in vendors]
            total = sum(v[1] for v in vendors)
            recs.append({
                "type": "Consolidation", "category": category,
                "description": f"Multiple vendors in {category}: {', '.join(vendor_names)}. "
                              f"Consider consolidating (total spend: ${total:,.0f})",
                "potential_savings": round(total * 0.15, 2),
            })

    # Renegotiation candidates — vendors over committed amounts
    for vendor, data in analysis["contract_compliance"].items():
        if data["utilization"] > 100:
            recs.append({
                "type": "Renegotiation", "category": "Contract",
                "description": f"{vendor} spend (${data['actual_ytd']:,.0f}) exceeds committed amount (${data['committed']:,.0f}). "
                              f"Renegotiate for better rates.",
                "potential_savings": round(data["actual_ytd"] * 0.10, 2),
            })

    # Tail spend cleanup
    if analysis["tail_vendors"]:
        total_tail = sum(v[1] for v in analysis["tail_vendors"])
        recs.append({
            "type": "Tail Spend", "category": "Procurement",
            "description": f"{len(analysis['tail_vendors'])} vendors with spend under ${TAIL_SPEND_THRESHOLD:,}/yr "
                          f"(total: ${total_tail:,.0f}). Review for consolidation or elimination.",
            "potential_savings": round(total_tail * 0.20, 2),
        })

    return recs

def main():
    st.set_page_config(page_title="Vendor Spend Analyzer", layout="wide")
    st.title("Vendor Spend Analytics")

    ap_data = fetch_ap_data()
    analysis = analyze_spend(ap_data)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Spend", f"${analysis['total_spend']:,.0f}")
    col2.metric("Unique Vendors", len(analysis["by_vendor"]))
    col3.metric("Tail Spend Vendors", len(analysis["tail_vendors"]))
    col4.metric("Categories", len(analysis["by_category"]))

    tab1, tab2, tab3, tab4 = st.tabs(["By Vendor", "By Category", "Contract Compliance", "Recommendations"])

    with tab1:
        st.subheader("Top 10 Vendors by Spend")
        for vendor, amount in analysis["top_vendors"]:
            pct = amount / analysis["total_spend"] * 100
            st.write(f"**{vendor}**: ${amount:,.0f} ({pct:.1f}%)")
            st.progress(min(pct / 30, 1.0))

        st.subheader("Tail Spend (< $10K/yr)")
        for vendor, amount in analysis["tail_vendors"]:
            st.write(f"  {vendor}: ${amount:,.0f}")

    with tab2:
        st.subheader("Spend by Category")
        for cat, amount in sorted(analysis["by_category"].items(), key=lambda x: -x[1]):
            st.write(f"**{cat}**: ${amount:,.0f}")

        st.subheader("Spend by Department")
        for dept, amount in sorted(analysis["by_department"].items(), key=lambda x: -x[1]):
            st.write(f"**{dept}**: ${amount:,.0f}")

    with tab3:
        st.subheader("Contract Compliance")
        for vendor, data in analysis["contract_compliance"].items():
            status = "On Track" if data["on_track"] else "Over Committed"
            color = "green" if data["on_track"] else "red"
            st.markdown(f"**{vendor}**: Committed ${data['committed']:,.0f} | "
                       f"Actual ${data['actual_ytd']:,.0f} | "
                       f"Utilization: :{color}[{data['utilization']}%] — {status}")

    with tab4:
        recommendations = generate_recommendations(analysis)
        st.subheader(f"Recommendations ({len(recommendations)})")
        total_savings = sum(r["potential_savings"] for r in recommendations)
        st.metric("Total Potential Savings", f"${total_savings:,.0f}")

        for rec in recommendations:
            st.markdown(f"**[{rec['type']}]** {rec['description']}")
            st.caption(f"Estimated savings: ${rec['potential_savings']:,.0f}")
            st.markdown("---")

if __name__ == "__main__":
    main()
