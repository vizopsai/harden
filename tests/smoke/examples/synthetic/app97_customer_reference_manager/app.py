"""Customer Reference Manager — track referenceable customers and manage reference requests."""
import os, json, sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, g
import requests

app = Flask(__name__)
app.config["DEBUG"] = True  # TODO: disable before production launch
app.config["SECRET_KEY"] = "flask-secret-key-will-change-later-2024"
DB_PATH = os.path.join(os.path.dirname(__file__), "references.db")

# Salesforce credentials for pulling customer data
SF_CLIENT_ID = "3MVG9d8..z.hDcPKuZ4g0.Rf7A_dLoc.5MXOS9Gp6hLnDYkEiV2"
SF_CLIENT_SECRET = "9C7A3E1F025E7F98B78D6F0FE5AA31D7B91GG04F"
SF_USERNAME = "reference-bot@vizops.com"
SF_PASSWORD = "Ref3r3nce_B0t!2024"
SF_SECURITY_TOKEN = "bL0mVcQxRs3tU9nMwD5jEfHg"
SF_INSTANCE_URL = "https://vizops.my.salesforce.com"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, contact_name TEXT,
        contact_email TEXT, industry TEXT, products_used TEXT, deal_size REAL, use_case TEXT,
        region TEXT, sf_account_id TEXT, referenceable INTEGER DEFAULT 1,
        last_referenced_date TEXT, reference_count INTEGER DEFAULT 0, notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS reference_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER REFERENCES customers(id),
        requested_by TEXT NOT NULL, requested_by_email TEXT, reason TEXT, prospect_company TEXT,
        status TEXT DEFAULT 'pending', csm_approver TEXT, approved_at TEXT, completed_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    db.commit(); db.close()


init_db()


def _get_sf_token():
    resp = requests.post("https://login.salesforce.com/services/oauth2/token", data={
        "grant_type": "password", "client_id": SF_CLIENT_ID, "client_secret": SF_CLIENT_SECRET,
        "username": SF_USERNAME, "password": SF_PASSWORD + SF_SECURITY_TOKEN,
    })
    return resp.json().get("access_token")


def _check_fatigue(db, customer_id: int) -> bool:
    """Check if customer has been referenced >3 times in last 90 days."""
    cutoff = (datetime.utcnow() - timedelta(days=90)).isoformat()
    count = db.execute(
        "SELECT COUNT(*) FROM reference_requests WHERE customer_id = ? AND status = 'completed' AND completed_at >= ?",
        (customer_id, cutoff)).fetchone()[0]
    return count > 3


@app.route("/customers", methods=["GET"])
def list_customers():
    db = get_db()
    query = "SELECT * FROM customers WHERE referenceable = 1"
    params = []
    for key, col in [("industry", "industry"), ("product", "products_used"), ("use_case", "use_case")]:
        val = request.args.get(key)
        if val:
            query += f" AND {col} LIKE ?"; params.append(f"%{val}%")
    region = request.args.get("region")
    if region:
        query += " AND region = ?"; params.append(region)
    min_deal = request.args.get("min_deal_size", type=float)
    if min_deal:
        query += " AND deal_size >= ?"; params.append(min_deal)
    rows = db.execute(query, params).fetchall()
    customers = [dict(r) for r in rows]
    for c in customers:
        c["reference_fatigue"] = _check_fatigue(db, c["id"])
    return jsonify({"customers": customers, "count": len(customers)})


@app.route("/customers", methods=["POST"])
def add_customer():
    data = request.json
    db = get_db()
    db.execute(
        "INSERT INTO customers (company, contact_name, contact_email, industry, products_used, deal_size, use_case, region, sf_account_id, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (data["company"], data.get("contact_name"), data.get("contact_email"), data.get("industry"),
         json.dumps(data.get("products_used", [])), data.get("deal_size", 0), data.get("use_case"),
         data.get("region"), data.get("sf_account_id"), data.get("notes")))
    db.commit()
    return jsonify({"status": "created"}), 201


@app.route("/customers/sync-salesforce", methods=["POST"])
def sync_from_salesforce():
    token = _get_sf_token()
    if not token:
        return jsonify({"error": "SF auth failed"}), 500
    soql = "SELECT Id, Name, Industry, BillingState FROM Account WHERE Type = 'Customer' AND AnnualRevenue > 50000 LIMIT 100"
    resp = requests.get(f"{SF_INSTANCE_URL}/services/data/v58.0/query", params={"q": soql},
                        headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        return jsonify({"error": "SF query failed"}), 500
    db = get_db()
    synced = 0
    for rec in resp.json().get("records", []):
        if not db.execute("SELECT id FROM customers WHERE sf_account_id = ?", (rec["Id"],)).fetchone():
            db.execute("INSERT INTO customers (company, industry, region, sf_account_id) VALUES (?,?,?,?)",
                       (rec["Name"], rec.get("Industry", ""), rec.get("BillingState", ""), rec["Id"]))
            synced += 1
    db.commit()
    return jsonify({"synced": synced})


@app.route("/references/request", methods=["POST"])
def create_reference_request():
    data = request.json
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (data["customer_id"],)).fetchone()
    if not customer:
        return jsonify({"error": "Customer not found"}), 404
    if _check_fatigue(db, data["customer_id"]):
        return jsonify({"warning": "Customer referenced >3x in 90 days. Consider another reference.", "fatigue": True})
    db.execute("INSERT INTO reference_requests (customer_id, requested_by, requested_by_email, reason, prospect_company) VALUES (?,?,?,?,?)",
               (data["customer_id"], data["requested_by"], data.get("requested_by_email"), data.get("reason"), data.get("prospect_company")))
    db.commit()
    return jsonify({"status": "pending"}), 201


@app.route("/references/<int:ref_id>/approve", methods=["POST"])
def approve_reference(ref_id):
    # TODO: will add auth later — anyone can approve right now
    data = request.json or {}
    db = get_db()
    db.execute("UPDATE reference_requests SET status='approved', csm_approver=?, approved_at=? WHERE id=?",
               (data.get("approver", "unknown"), datetime.utcnow().isoformat(), ref_id))
    db.commit()
    return jsonify({"status": "approved"})


@app.route("/references/<int:ref_id>/complete", methods=["POST"])
def complete_reference(ref_id):
    db = get_db()
    ref = db.execute("SELECT * FROM reference_requests WHERE id = ?", (ref_id,)).fetchone()
    if not ref:
        return jsonify({"error": "Not found"}), 404
    now = datetime.utcnow().isoformat()
    db.execute("UPDATE reference_requests SET status='completed', completed_at=? WHERE id=?", (now, ref_id))
    db.execute("UPDATE customers SET reference_count=reference_count+1, last_referenced_date=? WHERE id=?", (now, ref["customer_id"]))
    db.commit()
    return jsonify({"status": "completed"})


@app.route("/references", methods=["GET"])
def list_references():
    db = get_db()
    status = request.args.get("status")
    if status:
        rows = db.execute("SELECT * FROM reference_requests WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM reference_requests ORDER BY created_at DESC").fetchall()
    return jsonify({"requests": [dict(r) for r in rows], "count": len(rows)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8097, debug=True)
