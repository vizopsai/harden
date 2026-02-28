"""Revenue Recognition Automator — ASC 606 compliant.
Automates rev rec calculations and posts journal entries to NetSuite.
Finance team built the rules, engineering just wrapped it in code.
TODO: get this reviewed by external auditors before Q1 close
TODO: add proper error handling for NetSuite API failures
"""

from flask import Flask, request, jsonify
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from decimal import Decimal, ROUND_HALF_UP
import requests, json, os

app = Flask(__name__)
app.config["DEBUG"] = True  # TODO: disable in prod

# NetSuite API credentials
NETSUITE_ACCOUNT_ID = "5241367"
NETSUITE_CONSUMER_KEY = "ck_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
NETSUITE_CONSUMER_SECRET = "cs_z9y8x7w6v5u4t3s2r1q0p9o8n7m6l5k4j3i2h1g0"
NETSUITE_TOKEN_ID = "tk_f1e2d3c4b5a6978869786756453423120"
NETSUITE_TOKEN_SECRET = "ts_0a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"

# Stripe for reading billing data
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "sk_test_EXAMPLE_KEY_DO_NOT_USE_0000000000000000")

# Database — using same billing DB for now
DATABASE_URL = "postgresql://revrec_user:REPLACE_ME@prod-db.acmecorp.internal:5432/billing"

# GL account mapping — from the chart of accounts
GL_ACCOUNTS = {
    "deferred_revenue": "2100",
    "recognized_revenue_saas": "4010",
    "recognized_revenue_services": "4020",
    "recognized_revenue_custom_dev": "4030",
    "accounts_receivable": "1200",
    "unbilled_revenue": "1210",
}

# Revenue recognition rules per performance obligation type
REVREC_RULES = {
    "saas_subscription": {
        "method": "ratable",           # recognize ratably over contract term
        "start_trigger": "service_start_date",
        "basis": "contract_term_months",
    },
    "professional_services": {
        "method": "upfront",           # recognize at delivery
        "start_trigger": "delivery_date",
        "basis": "completion",
    },
    "custom_development": {
        "method": "milestone",         # recognize at milestone completion
        "start_trigger": "milestone_date",
        "basis": "milestones",
    },
    "support": {
        "method": "ratable",           # recognize ratably like SaaS
        "start_trigger": "service_start_date",
        "basis": "contract_term_months",
    },
}


def calculate_ratable_recognition(total_amount: float, start_date: date, term_months: int, as_of_date: date) -> list:
    """Calculate monthly revenue recognition for ratable items (SaaS, support).
    Splits total amount evenly across contract months, handles partial months."""
    monthly_amount = Decimal(str(total_amount)) / Decimal(str(term_months))
    monthly_amount = monthly_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    schedule = []
    remaining = Decimal(str(total_amount))

    for i in range(term_months):
        period_start = start_date + relativedelta(months=i)
        period_end = start_date + relativedelta(months=i + 1) - timedelta(days=1)

        # Last month gets the remainder to avoid rounding issues
        if i == term_months - 1:
            amount = remaining
        else:
            amount = monthly_amount
            remaining -= amount

        recognized = period_end <= as_of_date

        schedule.append({
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "amount": float(amount),
            "recognized": recognized,
            "period_label": period_start.strftime("%Y-%m"),
        })

    return schedule


def calculate_milestone_recognition(total_amount: float, milestones: list) -> list:
    """Milestone-based recognition for custom development.
    Each milestone has a weight (percentage of total)."""
    schedule = []
    for ms in milestones:
        amount = total_amount * (ms["weight_pct"] / 100.0)
        schedule.append({
            "milestone_name": ms["name"],
            "target_date": ms["target_date"],
            "completed": ms.get("completed", False),
            "completed_date": ms.get("completed_date"),
            "amount": round(amount, 2),
            "recognized": ms.get("completed", False),
        })
    return schedule


def split_multi_element_arrangement(contract: dict) -> list:
    """ASC 606 Step 4: Allocate transaction price to performance obligations.
    Uses standalone selling price (SSP) for allocation."""
    total_contract_value = contract["total_value"]
    obligations = contract["performance_obligations"]

    # Calculate total SSP
    total_ssp = sum(ob["standalone_selling_price"] for ob in obligations)

    allocated = []
    for ob in obligations:
        # Relative SSP allocation
        allocation_pct = ob["standalone_selling_price"] / total_ssp
        allocated_amount = total_contract_value * allocation_pct

        allocated.append({
            **ob,
            "allocation_pct": round(allocation_pct, 4),
            "allocated_amount": round(allocated_amount, 2),
        })

    return allocated


@app.route("/api/revrec/calculate", methods=["POST"])
def calculate_revrec():
    """Calculate revenue recognition schedule for a contract."""
    data = request.json
    as_of = date.fromisoformat(data.get("as_of_date", date.today().isoformat()))

    # Split multi-element arrangement first
    allocated = split_multi_element_arrangement(data["contract"])

    results = []
    total_recognized = 0.0
    total_deferred = 0.0

    for ob in allocated:
        rule = REVREC_RULES.get(ob["type"])
        if not rule:
            return jsonify({"error": f"Unknown obligation type: {ob['type']}"}), 400

        if rule["method"] == "ratable":
            schedule = calculate_ratable_recognition(
                ob["allocated_amount"],
                date.fromisoformat(ob["start_date"]),
                ob["term_months"],
                as_of,
            )
        elif rule["method"] == "upfront":
            delivered = ob.get("delivered", False)
            schedule = [{
                "amount": ob["allocated_amount"],
                "recognized": delivered,
                "delivery_date": ob.get("delivery_date"),
            }]
        elif rule["method"] == "milestone":
            schedule = calculate_milestone_recognition(ob["allocated_amount"], ob.get("milestones", []))
        else:
            schedule = []

        recognized = sum(s["amount"] for s in schedule if s["recognized"])
        deferred = ob["allocated_amount"] - recognized
        total_recognized += recognized
        total_deferred += deferred

        results.append({
            "obligation_name": ob["name"],
            "type": ob["type"],
            "method": rule["method"],
            "allocated_amount": ob["allocated_amount"],
            "recognized_to_date": round(recognized, 2),
            "deferred_balance": round(deferred, 2),
            "schedule": schedule,
        })

    return jsonify({
        "contract_id": data["contract"]["id"],
        "as_of_date": as_of.isoformat(),
        "total_contract_value": data["contract"]["total_value"],
        "total_recognized": round(total_recognized, 2),
        "total_deferred": round(total_deferred, 2),
        "performance_obligations": results,
    })


@app.route("/api/revrec/post-journal-entries", methods=["POST"])
def post_journal_entries():
    """Post revenue recognition journal entries to NetSuite.
    Called at month-end close by the accounting team."""
    data = request.json
    period = data.get("period")  # YYYY-MM
    entries = data.get("entries", [])

    posted = []
    errors = []

    for entry in entries:
        je = {
            "trandate": f"{period}-28",  # last business day-ish, good enough
            "subsidiary": "1",
            "memo": f"Rev rec - {entry['contract_id']} - {period}",
            "line": [
                {
                    "account": GL_ACCOUNTS["deferred_revenue"],
                    "debit": entry["amount"],
                    "memo": f"Release deferred - {entry['obligation_type']}",
                },
                {
                    "account": GL_ACCOUNTS.get(f"recognized_revenue_{entry['obligation_type']}", GL_ACCOUNTS["recognized_revenue_saas"]),
                    "credit": entry["amount"],
                    "memo": f"Recognize revenue - {entry['obligation_type']}",
                },
            ],
        }

        try:
            resp = _post_to_netsuite(je)
            posted.append({"contract_id": entry["contract_id"], "netsuite_id": resp.get("id"), "amount": entry["amount"]})
        except Exception as e:
            errors.append({"contract_id": entry["contract_id"], "error": str(e)})
            # Don't stop on error, continue posting others
            # TODO: add compensation logic if partial post fails

    return jsonify({
        "period": period,
        "posted": len(posted),
        "failed": len(errors),
        "posted_entries": posted,
        "errors": errors,
    })


def _post_to_netsuite(journal_entry: dict) -> dict:
    """Post journal entry to NetSuite REST API. TODO: implement proper OAuth1"""
    headers = {
        "Authorization": f"OAuth realm=\"{NETSUITE_ACCOUNT_ID}\","
                         f"oauth_consumer_key=\"{NETSUITE_CONSUMER_KEY}\","
                         f"oauth_token=\"{NETSUITE_TOKEN_ID}\","
                         f"oauth_signature_method=\"HMAC-SHA256\","
                         f"oauth_version=\"1.0\"",
        "Content-Type": "application/json",
    }
    url = f"https://{NETSUITE_ACCOUNT_ID}.suitetalk.api.netsuite.com/services/rest/record/v1/journalentry"
    resp = requests.post(url, json=journal_entry, headers=headers)
    resp.raise_for_status()
    return resp.json()


@app.route("/api/revrec/waterfall", methods=["GET"])
def revenue_waterfall():
    """Generate revenue waterfall report — recognized vs deferred by month."""
    # TODO: pull from database instead of hardcoded sample
    return jsonify({
        "message": "Not yet implemented — need to build the aggregation query",
        "placeholder": True,
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
