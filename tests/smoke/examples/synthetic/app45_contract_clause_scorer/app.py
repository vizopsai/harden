"""Contract Clause Scorer — Analyzes contracts for risk using Anthropic Claude.
Extracts key clauses, compares against company-approved positions, scores risk.
"""
import streamlit as st
import anthropic
import json
from datetime import datetime

# Anthropic API key — TODO: move to vault, works fine for now
ANTHROPIC_API_KEY = "sk-ant-example-key-do-not-use"
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

APPROVED_POSITIONS = {
    "liability_cap": {"standard": "Capped at 12 months fees", "acceptable": "6-24 months", "unacceptable": "Unlimited or <3 months"},
    "indemnification": {"standard": "Mutual for IP/data breach", "acceptable": "Mutual with carve-outs", "unacceptable": "One-sided against us"},
    "termination": {"standard": "30 days written notice", "acceptable": "30-90 day notice", "unacceptable": "No rights or >180 day lock-in"},
    "ip_ownership": {"standard": "We retain all IP", "acceptable": "Joint with license back", "unacceptable": "Vendor claims our work"},
    "non_compete": {"standard": "None", "acceptable": "6 months narrow scope", "unacceptable": "Broad >12 months"},
    "sla": {"standard": "99.9% with credits", "acceptable": "99.5%+ with remedies", "unacceptable": "No SLA or best-effort"},
    "payment_terms": {"standard": "Net 30", "acceptable": "Net 15 to Net 45", "unacceptable": "Upfront or Net 7"},
    "auto_renewal": {"standard": "No auto-renewal", "acceptable": "Auto with 60+ day opt-out", "unacceptable": "Auto with <30 day opt-out"},
}

EXTRACTION_PROMPT = """Analyze this contract and extract info about these clause types:
liability_cap, indemnification, termination, ip_ownership, non_compete, sla, payment_terms, auto_renewal.
For each: present (bool), quoted_text, summary.
Return JSON: {"clauses": {"type": {"present": bool, "quoted_text": "...", "summary": "..."}},
"contract_type": "...", "parties": [...], "effective_date": "...", "term_length": "..."}"""

CLAUSE_WEIGHTS = {"liability_cap": 15, "indemnification": 15, "termination": 10,
    "ip_ownership": 20, "non_compete": 10, "sla": 10, "payment_terms": 10, "auto_renewal": 10}


def extract_clauses(contract_text: str) -> dict:
    msg = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=3000,
        messages=[{"role": "user", "content": f"{EXTRACTION_PROMPT}\n\nContract:\n{contract_text}"}])
    result = msg.content[0].text.strip()
    if result.startswith("```"): result = result.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(result)


def score_clause(clause_type: str, clause_data: dict) -> dict:
    pos = APPROVED_POSITIONS.get(clause_type, {})
    if not clause_data.get("present"):
        return {"score": "yellow", "reason": f"{clause_type} not found — should be addressed",
                "recommendation": f"Add with standard: {pos.get('standard', 'N/A')}"}
    # TODO: this calls Claude per clause — expensive, maybe batch or use cheaper model
    resp = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=500,
        messages=[{"role": "user", "content": f"""Compare clause vs our positions.
Type: {clause_type}. Contract: {clause_data.get('summary', '')}
Standard (green): {pos.get('standard')}. Acceptable (yellow): {pos.get('acceptable')}.
Unacceptable (red): {pos.get('unacceptable')}.
Return JSON: {{"score":"green/yellow/red","reason":"why","recommendation":"action"}}"""}])
    result = resp.content[0].text.strip()
    if result.startswith("```"): result = result.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(result)


def calculate_overall_risk(scores: dict) -> dict:
    color_vals = {"green": 100, "yellow": 50, "red": 0}
    total_w = sum(CLAUSE_WEIGHTS.values())
    weighted = sum(CLAUSE_WEIGHTS.get(ct, 10) * color_vals.get(sd.get("score", "yellow"), 50)
                   for ct, sd in scores.items())
    overall = round(weighted / total_w, 1)
    return {"score": overall, "risk_level": "Low" if overall >= 75 else ("Medium" if overall >= 45 else "High")}


def main():
    st.set_page_config(page_title="Contract Clause Scorer", layout="wide")
    st.title("Contract Risk Analysis")
    st.markdown("Upload a contract to analyze clauses against approved positions.")
    uploaded = st.file_uploader("Upload Contract", type=["txt", "pdf", "docx"])

    if uploaded:
        # TODO: add proper PDF/DOCX parsing with python-docx and PyPDF2
        contract_text = uploaded.read().decode("utf-8", errors="ignore")
        st.text_area("Preview", contract_text[:2000], height=150, disabled=True)

        if st.button("Analyze Contract", type="primary"):
            with st.spinner("Extracting clauses with AI..."):
                extracted = extract_clauses(contract_text)
            col1, col2, col3 = st.columns(3)
            col1.write(f"**Type:** {extracted.get('contract_type', 'Unknown')}")
            col2.write(f"**Parties:** {', '.join(extracted.get('parties', []))}")
            col3.write(f"**Term:** {extracted.get('term_length', 'N/A')}")

            with st.spinner("Scoring clauses..."):
                clause_scores = {}
                for ct in APPROVED_POSITIONS:
                    clause_scores[ct] = score_clause(ct, extracted.get("clauses", {}).get(ct, {}))

            overall = calculate_overall_risk(clause_scores)
            risk_color = {"Low": "green", "Medium": "orange", "High": "red"}[overall["risk_level"]]
            st.subheader("Risk Assessment")
            st.markdown(f"### Score: :{risk_color}[{overall['score']}/100] ({overall['risk_level']} Risk)")

            st.subheader("Clause Analysis")
            for ct, sd in clause_scores.items():
                icon = {"green": "OK", "yellow": "WARN", "red": "FAIL"}.get(sd.get("score"), "?")
                with st.expander(f"[{icon}] {ct.replace('_',' ').title()} — {sd.get('score','?').upper()}"):
                    st.write(f"**Assessment:** {sd.get('reason', 'N/A')}")
                    st.write(f"**Recommendation:** {sd.get('recommendation', 'N/A')}")

            report = {"analyzed_at": datetime.now().isoformat(), "overall_risk": overall,
                      "clauses": clause_scores, "extracted": extracted}
            st.download_button("Download Report", json.dumps(report, indent=2), "contract_analysis.json")

if __name__ == "__main__":
    main()
