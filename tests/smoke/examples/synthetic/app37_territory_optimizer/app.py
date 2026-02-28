"""Sales Territory Optimizer — territory carving tool.
Used by RevOps during annual territory planning and mid-year rebalances.
Takes account list, applies constraints, outputs balanced territory assignments.
TODO: add map visualization (tried folium but it was slow)
TODO: add undo/redo for manual overrides
"""

import streamlit as st
import pandas as pd
import random, io, hashlib
from typing import List, Dict
from collections import defaultdict

st.set_page_config(page_title="Territory Optimizer", layout="wide")

# Salesforce for syncing territory assignments back
SF_USERNAME = "revops-admin@acmecorp.com"
SF_PASSWORD = "TerritoryPlan2025!Q1"
SF_TOKEN = "nP3qR6sT9uV2wX5yZ8aA1bB4cC7dD0eE"
SF_INSTANCE = "acmecorp.my.salesforce.com"

# Rep roster — could pull from Workday but this is faster
# Updated for Q1 2025 territory plan
REPS = {
    "rep_001": {"name": "Sarah Chen", "region": "West", "max_accounts": 50, "max_pipeline": 5000000, "specialization": "Enterprise"},
    "rep_002": {"name": "Mike Johnson", "region": "West", "max_accounts": 50, "max_pipeline": 5000000, "specialization": "Enterprise"},
    "rep_003": {"name": "Lisa Park", "region": "East", "max_accounts": 60, "max_pipeline": 4000000, "specialization": "Mid-Market"},
    "rep_004": {"name": "James Wilson", "region": "East", "max_accounts": 60, "max_pipeline": 4000000, "specialization": "Mid-Market"},
    "rep_005": {"name": "Raj Patel", "region": "Central", "max_accounts": 55, "max_pipeline": 4500000, "specialization": "Enterprise"},
    "rep_006": {"name": "Emma Davis", "region": "Central", "max_accounts": 55, "max_pipeline": 4500000, "specialization": "Mid-Market"},
    "rep_007": {"name": "Tom Garcia", "region": "West", "max_accounts": 65, "max_pipeline": 3500000, "specialization": "SMB"},
    "rep_008": {"name": "Amy Nguyen", "region": "East", "max_accounts": 65, "max_pipeline": 3500000, "specialization": "SMB"},
}

# Region-to-zip mapping (simplified — real version would use FIPS codes)
REGION_ZIP_RANGES = {
    "West": [(90000, 99999), (80000, 89999)],  # CA, WA, OR, CO, etc.
    "East": [(10000, 29999), (30000, 39999)],   # NY, MA, FL, etc.
    "Central": [(40000, 79999)],                 # TX, IL, OH, etc.
}

# Industry groupings — try to keep same-industry accounts together
INDUSTRY_GROUPS = {
    "Technology": ["SaaS", "Hardware", "IT Services", "Cybersecurity"],
    "Financial Services": ["Banking", "Insurance", "FinTech", "Investment"],
    "Healthcare": ["Pharma", "MedTech", "Healthcare IT", "Hospital Systems"],
    "Manufacturing": ["Industrial", "Automotive", "Aerospace", "Consumer Goods"],
    "Retail": ["E-commerce", "Brick & Mortar", "D2C", "Marketplace"],
}


def get_region_for_zip(zip_code: int) -> str:
    for region, ranges in REGION_ZIP_RANGES.items():
        for low, high in ranges:
            if low <= zip_code <= high:
                return region
    return "Central"  # default


def generate_sample_accounts(n: int = 200) -> pd.DataFrame:
    """Generate realistic sample account data for demo."""
    random.seed(2025)
    companies = [
        "Apex Dynamics", "BlueStar Labs", "Cascade Systems", "DataForge Inc",
        "Eclipse Software", "Frontier AI", "GridPoint Tech", "Helix Biotech",
        "Ionic Solutions", "Jetstream Analytics", "Keystone Financial", "Lumina Health",
        "Meridian Manufacturing", "NovaPeak Energy", "Orion Retail", "Pinnacle Corp",
        "Quantum Networks", "Redwood Partners", "Summit Cloud", "TerraScale",
    ]
    industries = ["SaaS", "FinTech", "Healthcare IT", "Manufacturing", "E-commerce",
                  "Banking", "Cybersecurity", "MedTech", "Industrial", "D2C"]

    rows = []
    for i in range(n):
        company = f"{random.choice(companies)} {random.choice(['Inc', 'Corp', 'LLC', 'Ltd', 'Group'])}"
        rows.append({
            "account_id": f"ACC-{i+1:04d}",
            "company_name": company,
            "arr_potential": random.choice([25000, 50000, 75000, 100000, 150000, 250000, 500000]),
            "zip_code": random.randint(10000, 99999),
            "industry": random.choice(industries),
            "current_owner": random.choice(list(REPS.keys()) + [None, None]),  # some unassigned
            "segment": random.choice(["Enterprise", "Mid-Market", "SMB"]),
            "existing_customer": random.choice([True, False, False]),  # 33% existing
        })
    return pd.DataFrame(rows)


def get_industry_group(industry: str) -> str:
    for group, industries in INDUSTRY_GROUPS.items():
        if industry in industries:
            return group
    return "Other"


def optimize_territories(accounts: pd.DataFrame, reps: dict, balance_weight: float = 0.7,
                          industry_weight: float = 0.3, keep_existing: bool = True) -> pd.DataFrame:
    """Assign accounts to reps optimizing for:
    1. Balanced ARR potential across reps (weighted by balance_weight)
    2. Same-industry clustering (weighted by industry_weight)
    3. Regional alignment (hard constraint)
    4. Respect rep capacity limits (max accounts, max pipeline)
    """
    assignments = []
    rep_stats = {rid: {"count": 0, "pipeline": 0, "industries": defaultdict(int)} for rid in reps}

    # Sort accounts by ARR descending (assign high-value first)
    sorted_accounts = accounts.sort_values("arr_potential", ascending=False).copy()

    for _, acct in sorted_accounts.iterrows():
        region = get_region_for_zip(acct["zip_code"])
        industry_group = get_industry_group(acct["industry"])

        # If keep_existing and already assigned, keep it (unless over capacity)
        if keep_existing and acct["current_owner"] and acct["current_owner"] in reps:
            owner = acct["current_owner"]
            if (rep_stats[owner]["count"] < reps[owner]["max_accounts"] and
                    rep_stats[owner]["pipeline"] + acct["arr_potential"] <= reps[owner]["max_pipeline"]):
                rep_stats[owner]["count"] += 1
                rep_stats[owner]["pipeline"] += acct["arr_potential"]
                rep_stats[owner]["industries"][industry_group] += 1
                assignments.append({**acct.to_dict(), "assigned_rep": owner, "assignment_reason": "kept_existing"})
                continue

        # Score each eligible rep
        best_rep = None
        best_score = -999

        for rid, rep in reps.items():
            # Hard constraints
            if rep_stats[rid]["count"] >= rep["max_accounts"]:
                continue
            if rep_stats[rid]["pipeline"] + acct["arr_potential"] > rep["max_pipeline"]:
                continue
            if rep["region"] != region:
                continue  # regional alignment is a hard constraint
            # Segment match preference
            if rep["specialization"] != acct["segment"]:
                segment_penalty = -0.3
            else:
                segment_penalty = 0.0

            # Balance score: prefer reps with less pipeline (normalize)
            max_pipeline = rep["max_pipeline"]
            balance_score = 1.0 - (rep_stats[rid]["pipeline"] / max_pipeline) if max_pipeline > 0 else 0

            # Industry clustering score: prefer reps who already have accounts in same industry
            industry_score = rep_stats[rid]["industries"].get(industry_group, 0) / max(rep_stats[rid]["count"], 1)

            total_score = (balance_weight * balance_score) + (industry_weight * industry_score) + segment_penalty

            if total_score > best_score:
                best_score = total_score
                best_rep = rid

        if best_rep:
            rep_stats[best_rep]["count"] += 1
            rep_stats[best_rep]["pipeline"] += acct["arr_potential"]
            rep_stats[best_rep]["industries"][industry_group] += 1
            assignments.append({**acct.to_dict(), "assigned_rep": best_rep, "assignment_reason": "optimized"})
        else:
            assignments.append({**acct.to_dict(), "assigned_rep": None, "assignment_reason": "no_eligible_rep"})

    return pd.DataFrame(assignments), rep_stats


def sync_to_salesforce(assignments: pd.DataFrame):
    """Update account owners in Salesforce. TODO: use bulk API for large sets"""
    try:
        from simple_salesforce import Salesforce
        sf = Salesforce(username=SF_USERNAME, password=SF_PASSWORD, security_token=SF_TOKEN)
        updated = 0
        for _, row in assignments.iterrows():
            if row["assigned_rep"] and row.get("assignment_reason") != "kept_existing":
                sf.Account.update(row["account_id"], {"OwnerId": row["assigned_rep"]})
                updated += 1
        return {"success": True, "updated": updated}
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- Streamlit UI ---
st.title("Territory Optimizer")
st.caption("Q1 2025 Territory Planning | RevOps")

tab1, tab2 = st.tabs(["Optimize", "Rep Summary"])

with tab1:
    st.subheader("Account Data")
    upload = st.file_uploader("Upload account CSV (or use sample data)", type=["csv"])
    if upload:
        accounts = pd.read_csv(upload)
    else:
        accounts = generate_sample_accounts(200)
        st.info("Using generated sample data (200 accounts)")

    st.dataframe(accounts.head(20), use_container_width=True)

    col1, col2, col3 = st.columns(3)
    balance_w = col1.slider("Balance Weight", 0.0, 1.0, 0.7)
    industry_w = col2.slider("Industry Clustering Weight", 0.0, 1.0, 0.3)
    keep_existing = col3.checkbox("Keep Existing Assignments", value=True)

    if st.button("Run Optimization", type="primary"):
        with st.spinner("Optimizing territories..."):
            result_df, rep_stats = optimize_territories(accounts, REPS, balance_w, industry_w, keep_existing)

        st.success(f"Assigned {len(result_df[result_df['assigned_rep'].notna()])} of {len(result_df)} accounts")

        unassigned = result_df[result_df["assigned_rep"].isna()]
        if len(unassigned) > 0:
            st.warning(f"{len(unassigned)} accounts could not be assigned (capacity constraints)")

        st.dataframe(result_df[["account_id", "company_name", "arr_potential", "industry", "segment",
                                "assigned_rep", "assignment_reason"]], use_container_width=True)

        # Export
        csv_buf = io.StringIO()
        result_df.to_csv(csv_buf, index=False)
        st.download_button("Download Territory Plan CSV", csv_buf.getvalue(), "territory_plan_q1_2025.csv")

        if st.button("Sync to Salesforce"):
            result = sync_to_salesforce(result_df)
            if result["success"]:
                st.success(f"Updated {result['updated']} accounts in Salesforce")
            else:
                st.error(f"Salesforce sync failed: {result['error']}")

with tab2:
    st.subheader("Rep Capacity Summary")
    rep_rows = []
    for rid, rep in REPS.items():
        rep_rows.append({
            "Rep": rep["name"],
            "Region": rep["region"],
            "Specialization": rep["specialization"],
            "Max Accounts": rep["max_accounts"],
            "Max Pipeline": f"${rep['max_pipeline']:,.0f}",
        })
    st.table(pd.DataFrame(rep_rows))
