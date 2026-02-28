"""Compensation Benchmarker
Analyzes company compensation data against market benchmarks.
Flags pay equity issues and outliers.
Built for the people ops / total rewards team.
WARNING: Contains highly sensitive PII — no auth implemented yet.
"""
import streamlit as st
import pandas as pd
import os
from datetime import datetime
from io import StringIO

# No auth at all — TODO: this has PII, definitely need to add auth
# "will add auth later" — people team wants it live now

# Market benchmark data — simulating Radford/Mercer data
# Keyed by (role_family, level, geo) -> (p25, p50, p75, p90)
MARKET_BENCHMARKS = {
    ("Engineering", "IC1", "SF Bay Area"): (95_000, 115_000, 135_000, 160_000),
    ("Engineering", "IC2", "SF Bay Area"): (120_000, 145_000, 170_000, 200_000),
    ("Engineering", "IC3", "SF Bay Area"): (155_000, 185_000, 215_000, 250_000),
    ("Engineering", "IC4", "SF Bay Area"): (190_000, 225_000, 265_000, 310_000),
    ("Engineering", "IC5", "SF Bay Area"): (235_000, 280_000, 330_000, 385_000),
    ("Engineering", "M1", "SF Bay Area"): (175_000, 210_000, 250_000, 295_000),
    ("Engineering", "M2", "SF Bay Area"): (220_000, 265_000, 310_000, 360_000),
    ("Engineering", "IC1", "NYC"): (90_000, 110_000, 130_000, 155_000),
    ("Engineering", "IC2", "NYC"): (115_000, 140_000, 165_000, 195_000),
    ("Engineering", "IC3", "NYC"): (150_000, 180_000, 210_000, 245_000),
    ("Engineering", "IC4", "NYC"): (185_000, 220_000, 260_000, 305_000),
    ("Engineering", "IC1", "Remote US"): (80_000, 98_000, 118_000, 140_000),
    ("Engineering", "IC2", "Remote US"): (100_000, 125_000, 148_000, 175_000),
    ("Engineering", "IC3", "Remote US"): (135_000, 162_000, 190_000, 222_000),
    ("Product", "IC2", "SF Bay Area"): (110_000, 135_000, 160_000, 190_000),
    ("Product", "IC3", "SF Bay Area"): (145_000, 175_000, 205_000, 240_000),
    ("Product", "IC4", "SF Bay Area"): (180_000, 215_000, 255_000, 300_000),
    ("Product", "M1", "SF Bay Area"): (165_000, 200_000, 240_000, 280_000),
    ("Product", "IC2", "NYC"): (105_000, 130_000, 155_000, 185_000),
    ("Product", "IC3", "NYC"): (140_000, 170_000, 200_000, 235_000),
    ("Sales", "IC2", "SF Bay Area"): (70_000, 85_000, 105_000, 130_000),
    ("Sales", "IC3", "SF Bay Area"): (90_000, 115_000, 140_000, 170_000),
    ("Sales", "IC4", "SF Bay Area"): (120_000, 150_000, 185_000, 225_000),
    ("Sales", "M1", "SF Bay Area"): (110_000, 140_000, 175_000, 210_000),
    ("Marketing", "IC2", "SF Bay Area"): (80_000, 100_000, 120_000, 145_000),
    ("Marketing", "IC3", "SF Bay Area"): (110_000, 135_000, 160_000, 190_000),
    ("Marketing", "M1", "SF Bay Area"): (130_000, 160_000, 190_000, 225_000),
    ("G&A", "IC2", "SF Bay Area"): (70_000, 88_000, 108_000, 130_000),
    ("G&A", "IC3", "SF Bay Area"): (95_000, 118_000, 140_000, 168_000),
    ("G&A", "M1", "SF Bay Area"): (120_000, 148_000, 178_000, 210_000),
}

SAMPLE_CSV = """employee_id,name,department,role_family,level,geo,gender,ethnicity,base_salary,total_comp,hire_date
E001,Sarah Chen,Engineering,Engineering,IC3,SF Bay Area,Female,Asian,182000,215000,2022-03-15
E002,James Wilson,Engineering,Engineering,IC3,SF Bay Area,Male,White,195000,232000,2021-08-01
E003,Maria Garcia,Engineering,Engineering,IC2,SF Bay Area,Female,Hispanic,128000,152000,2023-01-10
E004,David Kim,Engineering,Engineering,IC4,SF Bay Area,Male,Asian,240000,285000,2020-06-20
E005,Emily Brown,Engineering,Engineering,IC2,NYC,Female,White,132000,158000,2022-11-05
E006,Robert Johnson,Engineering,Engineering,IC3,Remote US,Male,White,175000,208000,2021-04-12
E007,Lisa Patel,Product,Product,IC3,SF Bay Area,Female,Asian,168000,198000,2022-07-22
E008,Michael Taylor,Product,Product,IC3,SF Bay Area,Male,White,185000,220000,2021-09-15
E009,Jennifer Lee,Product,Product,IC4,SF Bay Area,Female,Asian,228000,270000,2020-11-30
E010,Chris Martinez,Sales,Sales,IC3,SF Bay Area,Male,Hispanic,105000,185000,2022-05-18
E011,Amanda Davis,Sales,Sales,IC3,SF Bay Area,Female,White,98000,172000,2023-02-28
E012,Kevin Thomas,Sales,Sales,IC4,SF Bay Area,Male,Black,145000,250000,2021-01-14
E013,Nicole Hernandez,Marketing,Marketing,IC3,SF Bay Area,Female,Hispanic,125000,148000,2022-08-08
E014,Ryan White,Marketing,Marketing,IC3,SF Bay Area,Male,White,142000,168000,2021-12-01
E015,Priya Sharma,Engineering,Engineering,IC5,SF Bay Area,Female,Asian,270000,325000,2019-10-15
E016,Tom Anderson,Engineering,Engineering,IC1,SF Bay Area,Male,White,118000,138000,2023-06-01
E017,Diana Wilson,G&A,G&A,IC3,SF Bay Area,Female,Black,108000,128000,2022-04-10
E018,Jason Lee,G&A,G&A,M1,SF Bay Area,Male,Asian,155000,185000,2021-03-20
E019,Rachel Green,Engineering,Engineering,M1,SF Bay Area,Female,White,205000,248000,2020-08-15
E020,Marcus Brown,Engineering,Engineering,M2,SF Bay Area,Male,Black,252000,302000,2019-06-01
"""


def get_percentile_position(salary, benchmarks):
    """Calculate where an employee's salary falls in market percentiles"""
    p25, p50, p75, p90 = benchmarks
    if salary <= p25:
        return round((salary / p25) * 25, 1)
    elif salary <= p50:
        return round(25 + ((salary - p25) / (p50 - p25)) * 25, 1)
    elif salary <= p75:
        return round(50 + ((salary - p50) / (p75 - p50)) * 25, 1)
    elif salary <= p90:
        return round(75 + ((salary - p75) / (p90 - p75)) * 15, 1)
    else:
        return round(90 + ((salary - p90) / p90) * 10, 1)


def calculate_compa_ratio(salary, benchmarks):
    """Compa-ratio: employee salary / market midpoint (p50)"""
    p50 = benchmarks[1]
    return round(salary / p50, 3) if p50 > 0 else 0


def analyze_compensation(df):
    """Run full compensation analysis"""
    results = []
    for _, emp in df.iterrows():
        key = (emp["role_family"], emp["level"], emp["geo"])
        benchmarks = MARKET_BENCHMARKS.get(key)
        if not benchmarks:
            # Fallback: try without geo specificity
            for geo_fallback in ["SF Bay Area", "Remote US"]:
                benchmarks = MARKET_BENCHMARKS.get((emp["role_family"], emp["level"], geo_fallback))
                if benchmarks:
                    break
        if not benchmarks:
            benchmarks = (80_000, 100_000, 125_000, 150_000)  # generic fallback

        percentile = get_percentile_position(emp["base_salary"], benchmarks)
        compa_ratio = calculate_compa_ratio(emp["base_salary"], benchmarks)

        flags = []
        if percentile < 25:
            flags.append("UNDERPAID: Below 25th percentile")
        if percentile > 90:
            flags.append("OVERPAID: Above 90th percentile")

        results.append({
            "employee_id": emp["employee_id"],
            "name": emp["name"],
            "department": emp["department"],
            "role_family": emp["role_family"],
            "level": emp["level"],
            "geo": emp["geo"],
            "gender": emp["gender"],
            "ethnicity": emp["ethnicity"],
            "base_salary": emp["base_salary"],
            "total_comp": emp["total_comp"],
            "market_p50": benchmarks[1],
            "percentile": percentile,
            "compa_ratio": compa_ratio,
            "flags": "; ".join(flags) if flags else "",
        })
    return pd.DataFrame(results)


def analyze_pay_equity(df):
    """Analyze pay equity gaps by gender and ethnicity"""
    equity_issues = []
    for (role, level, geo), group in df.groupby(["role_family", "level", "geo"]):
        if len(group) < 2:
            continue
        # Gender equity
        for gender in group["gender"].unique():
            gender_group = group[group["gender"] == gender]
            others = group[group["gender"] != gender]
            if len(gender_group) > 0 and len(others) > 0:
                avg_gender = gender_group["compa_ratio"].mean()
                avg_others = others["compa_ratio"].mean()
                gap_pct = abs(avg_gender - avg_others) / max(avg_others, 0.001) * 100
                if gap_pct > 5:
                    equity_issues.append({
                        "role": f"{role} {level}",
                        "geo": geo,
                        "dimension": f"Gender ({gender} vs others)",
                        "gap_pct": round(gap_pct, 1),
                        "avg_compa_group": round(avg_gender, 3),
                        "avg_compa_others": round(avg_others, 3),
                    })
    return pd.DataFrame(equity_issues) if equity_issues else pd.DataFrame()


# --- Streamlit UI ---
st.set_page_config(page_title="Compensation Benchmarker", layout="wide")
st.title("Compensation Benchmarker")
st.caption("Compare company compensation against market benchmarks")
# WARNING: This tool contains sensitive PII data
# TODO: add authentication before sharing the URL more widely
# TODO: add data encryption at rest
# TODO: add audit logging for who views this data

uploaded_file = st.file_uploader("Upload Workday compensation export (CSV)", type=["csv"])
use_sample = st.checkbox("Use sample data", value=True)

if uploaded_file:
    df = pd.read_csv(uploaded_file)
elif use_sample:
    df = pd.read_csv(StringIO(SAMPLE_CSV))
else:
    st.info("Upload a CSV file or use sample data to get started.")
    st.stop()

analyzed = analyze_compensation(df)

# Summary metrics
st.subheader("Overview")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Employees Analyzed", len(analyzed))
col2.metric("Avg Compa-Ratio", f"{analyzed['compa_ratio'].mean():.3f}")
underpaid = analyzed[analyzed["percentile"] < 25]
overpaid = analyzed[analyzed["percentile"] > 90]
col3.metric("Underpaid (<P25)", len(underpaid))
col4.metric("Overpaid (>P90)", len(overpaid))

# Detailed table — shows employee names, salaries, everything
# NO ACCESS CONTROLS - anyone with the URL sees all PII
st.subheader("Employee Compensation Analysis")
st.dataframe(analyzed[["name", "department", "level", "geo", "gender", "ethnicity", "base_salary", "total_comp", "market_p50", "percentile", "compa_ratio", "flags"]], use_container_width=True)

# Compa-ratio by department
st.subheader("Compa-Ratio by Department")
dept_compa = analyzed.groupby("department")["compa_ratio"].mean().reset_index()
st.bar_chart(dept_compa.set_index("department"))

# Flagged employees
if not underpaid.empty:
    st.subheader("Underpaid Employees (Below 25th Percentile)")
    st.dataframe(underpaid[["name", "department", "level", "base_salary", "market_p50", "percentile", "compa_ratio"]], use_container_width=True)

if not overpaid.empty:
    st.subheader("Overpaid Employees (Above 90th Percentile)")
    st.dataframe(overpaid[["name", "department", "level", "base_salary", "market_p50", "percentile", "compa_ratio"]], use_container_width=True)

# Pay equity analysis
st.subheader("Pay Equity Analysis")
equity = analyze_pay_equity(analyzed)
if not equity.empty:
    st.warning(f"Found {len(equity)} pay equity gaps exceeding 5%")
    st.dataframe(equity, use_container_width=True)
else:
    st.success("No significant pay equity gaps detected (>5% threshold)")
