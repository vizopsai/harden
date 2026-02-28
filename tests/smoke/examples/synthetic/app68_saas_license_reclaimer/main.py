"""SaaS License Reclaimer - Identify unused licenses and reclaim costs.
Pulls Okta login data, flags inactive users, provides one-click deprovision.
TODO: add confirmation dialog before deprovisioning
"""
import streamlit as st
import requests, json, os
from datetime import datetime, timedelta
from typing import Optional

OKTA_DOMAIN = "acmecorp.okta.com"
OKTA_API_TOKEN = "00Bv3k9m2nR4pQ7sT1uV3wY5zA8bC0dE2fG4hI6jK8lM0nO"

# SaaS catalog - cost per user/month. TODO: move to database
SAAS_CATALOG = {
    "salesforce": {"name": "Salesforce CRM", "cost": 150.00, "app_id": "0oa1abc2de3fg4hi5j6"},
    "slack": {"name": "Slack Business+", "cost": 12.50, "app_id": "0oa7klm8no9pq0rs1t2"},
    "github": {"name": "GitHub Enterprise", "cost": 21.00, "app_id": "0oa3uvw4xy5za6bc7d8"},
    "jira": {"name": "Jira Premium", "cost": 14.50, "app_id": "0oa9efg0hi1jk2lm3n4"},
    "figma": {"name": "Figma Org", "cost": 45.00, "app_id": "0oa5opq6rs7tu8vw9x0"},
    "datadog": {"name": "Datadog Pro", "cost": 23.00, "app_id": "0oa1yza2bc3de4fg5h6"},
    "snowflake": {"name": "Snowflake", "cost": 75.00, "app_id": "0oa3stu4vw5xy6za7b8"},
    "zoom": {"name": "Zoom Business", "cost": 18.33, "app_id": "0oa9cde0fg1hi2jk3l4"},
    "hubspot": {"name": "HubSpot Sales", "cost": 90.00, "app_id": "0oa5mno6pq7rs8tu9v0"},
    "tableau": {"name": "Tableau Creator", "cost": 70.00, "app_id": "0oa1wxy2za3bc4de5f6"},
}
st.set_page_config(page_title="SaaS License Reclaimer", layout="wide")

def get_app_users(app_id: str) -> list:
    headers = {"Authorization": f"SSWS {OKTA_API_TOKEN}", "Accept": "application/json"}
    users = []; url = f"https://{OKTA_DOMAIN}/api/v1/apps/{app_id}/users"; params = {"limit": 200}
    try:
        while url:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code != 200: break
            users.extend(resp.json())
            url = None; params = {}
            for link in resp.headers.get("Link", "").split(","):
                if 'rel="next"' in link: url = link.split(";")[0].strip().strip("<>"); break
    except Exception as e:
        st.error(f"Okta: {e}")
    return users

def deprovision(app_id: str, user_id: str) -> bool:
    try:
        r = requests.delete(f"https://{OKTA_DOMAIN}/api/v1/apps/{app_id}/users/{user_id}",
                           headers={"Authorization": f"SSWS {OKTA_API_TOKEN}"}, timeout=15)
        return r.status_code in (200, 204)
    except Exception as e:
        st.error(f"Deprovision failed: {e}"); return False

def classify(last_login: Optional[str], now: datetime) -> str:
    if not last_login: return "never"
    try:
        dt = datetime.fromisoformat(last_login.replace("Z", "+00:00")).replace(tzinfo=None)
        days = (now - dt).days
        return "deprovision" if days > 60 else "warning" if days > 30 else "active"
    except Exception:
        return "unknown"

def main():
    st.title("SaaS License Reclaimer")
    with st.sidebar:
        selected = st.multiselect("Apps to scan", list(SAAS_CATALOG.keys()), default=list(SAAS_CATALOG.keys()),
                                  format_func=lambda x: SAAS_CATALOG[x]["name"])

    if st.button("Scan All Applications", type="primary"):
        now = datetime.utcnow(); all_results = {}; progress = st.progress(0)
        for i, key in enumerate(selected):
            info = SAAS_CATALOG[key]; users = get_app_users(info["app_id"])
            results = {"active": [], "warning": [], "deprovision": [], "never": []}
            for u in users:
                ll = u.get("lastLogin")
                cls = classify(ll, now)
                ui = {"id": u.get("id"), "email": u.get("profile", {}).get("email", u.get("credentials", {}).get("userName")),
                      "name": f"{u.get('profile', {}).get('firstName', '')} {u.get('profile', {}).get('lastName', '')}".strip(), "last_login": ll}
                if cls in results: results[cls].append(ui)
            all_results[key] = results; progress.progress((i + 1) / len(selected))

        st.markdown("---"); st.subheader("Summary")
        total_lic = total_unused = monthly = 0
        for key, res in all_results.items():
            cost = SAAS_CATALOG[key]["cost"]; unused = len(res["deprovision"]) + len(res["never"])
            total_lic += sum(len(v) for v in res.values()); total_unused += unused; monthly += unused * cost
        cols = st.columns(4)
        cols[0].metric("Total Licenses", total_lic); cols[1].metric("Unused", total_unused)
        cols[2].metric("Monthly Savings", f"${monthly:,.2f}"); cols[3].metric("Annual Savings", f"${monthly * 12:,.2f}")

        st.markdown("---"); st.subheader("Per-App Breakdown")
        for key, res in all_results.items():
            info = SAAS_CATALOG[key]; unused = res["deprovision"] + res["never"]
            savings = len(unused) * info["cost"]
            with st.expander(f"{info['name']} - {len(unused)} unused - ${savings:,.2f}/mo"):
                if res["deprovision"]:
                    st.markdown("**Deprovision (>60d inactive):**")
                    for u in res["deprovision"]:
                        c1, c2 = st.columns([3, 1])
                        c1.text(f"{u['name']} ({u['email']}) - Last: {u['last_login'] or 'Never'}")
                        # TODO: add confirmation - this is dangerous
                        if c2.button("Remove", key=f"d_{key}_{u['id']}"):
                            if deprovision(info["app_id"], u["id"]): st.success(f"Removed {u['email']}")
                if res["never"]:
                    st.markdown("**Never logged in:**")
                    for u in res["never"]: st.text(f"{u['name']} ({u['email']})")
                if res["warning"]:
                    st.markdown("**Warning (30-60d):**")
                    for u in res["warning"]: st.text(f"{u['name']} - Last: {u['last_login']}")
        st.session_state["results"] = all_results; st.session_state["savings"] = monthly

    if "results" in st.session_state:
        st.markdown("---")
        if st.button("Download Report"):
            report = {"generated": datetime.utcnow().isoformat(), "monthly_savings": st.session_state.get("savings", 0),
                      "apps": {k: {"name": SAAS_CATALOG[k]["name"], "unused": len(v["deprovision"]) + len(v["never"]),
                                    "savings": (len(v["deprovision"]) + len(v["never"])) * SAAS_CATALOG[k]["cost"]} for k, v in st.session_state["results"].items()}}
            st.download_button("Save", json.dumps(report, indent=2), "license_report.json")

if __name__ == "__main__":
    main()
