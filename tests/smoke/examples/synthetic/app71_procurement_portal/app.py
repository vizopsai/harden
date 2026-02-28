"""
Procurement Portal — Internal purchase request system.
Handles PO creation, budget checks, and approval routing.
TODO: will add SSO login later, for now anyone can submit
"""

import sqlite3
import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
import sendgrid
from sendgrid.helpers.mail import Mail

app = Flask(__name__)
app.secret_key = "procurement-secret-2024"
app.config["DEBUG"] = True  # TODO: turn off before go-live

# SendGrid for approval emails
SENDGRID_API_KEY = "SG.EXAMPLE_KEY.EXAMPLE_SECRET_DO_NOT_USE"

# Budget data — pulled from ERP nightly (simulated)
# TODO: hook this up to SAP API instead of hardcoding
DEPARTMENT_BUDGETS = {
    "Engineering": {"total": 500000, "spent": 312450, "remaining": 187550},
    "Marketing": {"total": 350000, "spent": 298000, "remaining": 52000},
    "Sales": {"total": 275000, "spent": 143200, "remaining": 131800},
    "HR": {"total": 150000, "spent": 89000, "remaining": 61000},
    "Finance": {"total": 100000, "spent": 67300, "remaining": 32700},
    "Operations": {"total": 200000, "spent": 156800, "remaining": 43200},
}

APPROVAL_ROUTING = {
    "auto": {"max": 1000, "approver": "system"},
    "manager": {"max": 10000, "approver": "department_manager"},
    "director": {"max": 50000, "approver": "department_director"},
    "vp_finance": {"max": float("inf"), "approver": "vp_finance"},
}

MANAGERS = {
    "Engineering": {"manager": "sarah.chen@company.com", "director": "mike.rodriguez@company.com"},
    "Marketing": {"manager": "lisa.park@company.com", "director": "james.wilson@company.com"},
    "Sales": {"manager": "tom.baker@company.com", "director": "amanda.lee@company.com"},
    "HR": {"manager": "nancy.kim@company.com", "director": "david.brown@company.com"},
    "Finance": {"manager": "carol.white@company.com", "director": "robert.jones@company.com"},
    "Operations": {"manager": "kevin.garcia@company.com", "director": "patricia.taylor@company.com"},
}

VP_FINANCE_EMAIL = "cfo@company.com"

def init_db():
    conn = sqlite3.connect("procurement.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS purchase_orders (
        po_number TEXT PRIMARY KEY,
        requester TEXT, department TEXT, item_description TEXT,
        vendor TEXT, amount REAL, justification TEXT,
        status TEXT DEFAULT 'pending',
        approval_level TEXT, approver_email TEXT,
        created_at TEXT, updated_at TEXT
    )""")
    conn.commit()
    conn.close()

def generate_po_number():
    return f"PO-{datetime.now().strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"

def get_approval_level(amount):
    if amount < 1000:
        return "auto"
    elif amount < 10000:
        return "manager"
    elif amount < 50000:
        return "director"
    else:
        return "vp_finance"

def send_approval_email(po_number, approver_email, requester, amount, item_description):
    """Send approval request email via SendGrid"""
    # TODO: add HTML template, this plain text is ugly
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    message = Mail(
        from_email="procurement@company.com",
        to_emails=approver_email,
        subject=f"Purchase Approval Required: {po_number} (${amount:,.2f})",
        plain_text_content=f"Purchase request from {requester} for {item_description}. Amount: ${amount:,.2f}. "
                          f"Approve at: https://procurement.internal.company.com/approve/{po_number}"
    )
    try:
        sg.send(message)
    except Exception as e:
        print(f"Email failed: {e}")  # TODO: add proper error handling

@app.route("/")
def index():
    return render_template_string("""
    <h1>Procurement Portal</h1>
    <p><a href="/submit">Submit Purchase Request</a> | <a href="/orders">View Orders</a></p>
    """)

# TODO: add CSRF protection
@app.route("/submit", methods=["GET", "POST"])
def submit_request():
    if request.method == "POST":
        data = request.form
        department = data["department"]
        amount = float(data["amount"])

        # Budget check
        budget = DEPARTMENT_BUDGETS.get(department)
        if not budget:
            return jsonify({"error": "Unknown department"}), 400
        if amount > budget["remaining"]:
            return jsonify({"error": f"Insufficient budget. Remaining: ${budget['remaining']:,.2f}"}), 400

        po_number = generate_po_number()
        approval_level = get_approval_level(amount)
        status = "approved" if approval_level == "auto" else "pending"

        # Determine approver
        approver_email = None
        if approval_level == "manager":
            approver_email = MANAGERS[department]["manager"]
        elif approval_level == "director":
            approver_email = MANAGERS[department]["director"]
        elif approval_level == "vp_finance":
            approver_email = VP_FINANCE_EMAIL

        conn = sqlite3.connect("procurement.db")
        c = conn.cursor()
        c.execute("""INSERT INTO purchase_orders
            (po_number, requester, department, item_description, vendor, amount, justification,
             status, approval_level, approver_email, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (po_number, data["requester"], department, data["item_description"],
             data["vendor"], amount, data["justification"], status, approval_level,
             approver_email, datetime.now().isoformat(), datetime.now().isoformat()))
        conn.commit()
        conn.close()

        if approver_email:
            send_approval_email(po_number, approver_email, data["requester"], amount, data["item_description"])

        return jsonify({"po_number": po_number, "status": status, "approval_level": approval_level})

    departments = list(DEPARTMENT_BUDGETS.keys())
    return render_template_string("""
    <h1>Submit Purchase Request</h1>
    <form method="post">
        <label>Requester: <input name="requester" required></label><br>
        <label>Department: <select name="department">
            {% for d in departments %}<option>{{d}}</option>{% endfor %}
        </select></label><br>
        <label>Item Description: <input name="item_description" required></label><br>
        <label>Vendor: <input name="vendor" required></label><br>
        <label>Amount ($): <input name="amount" type="number" step="0.01" required></label><br>
        <label>Justification: <textarea name="justification" required></textarea></label><br>
        <button type="submit">Submit Request</button>
    </form>
    """, departments=departments)

@app.route("/orders")
def list_orders():
    conn = sqlite3.connect("procurement.db")
    conn.row_factory = sqlite3.Row
    orders = conn.execute("SELECT * FROM purchase_orders ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template_string("""
    <h1>Purchase Orders</h1>
    <table border="1"><tr><th>PO#</th><th>Requester</th><th>Dept</th><th>Item</th><th>Amount</th><th>Status</th></tr>
    {% for o in orders %}
    <tr><td>{{o.po_number}}</td><td>{{o.requester}}</td><td>{{o.department}}</td>
        <td>{{o.item_description}}</td><td>${{"%.2f"|format(o.amount)}}</td><td>{{o.status}}</td></tr>
    {% endfor %}</table>
    """, orders=orders)

# TODO: add authentication check — anyone with the link can approve right now
@app.route("/approve/<po_number>", methods=["POST"])
def approve_order(po_number):
    action = request.json.get("action", "approved")  # approved or rejected
    conn = sqlite3.connect("procurement.db")
    conn.execute("UPDATE purchase_orders SET status=?, updated_at=? WHERE po_number=?",
                 (action, datetime.now().isoformat(), po_number))
    conn.commit()
    conn.close()
    return jsonify({"status": action, "po_number": po_number})

@app.route("/budget/<department>")
def check_budget(department):
    budget = DEPARTMENT_BUDGETS.get(department)
    if not budget:
        return jsonify({"error": "Department not found"}), 404
    return jsonify(budget)

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5071, debug=True)  # works fine for now
