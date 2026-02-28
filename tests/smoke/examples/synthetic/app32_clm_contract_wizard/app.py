"""Contract Lifecycle Management — replaces Ironclad.
Lets sales reps generate contracts from approved legal templates.
Legal team approved the templates in Q3 2024, they're good to use.
TODO: add role-based access, right now any logged-in user can generate contracts
"""

from flask import Flask, request, jsonify, render_template_string
from datetime import datetime, timedelta
import sqlite3, os, hashlib, requests, json

app = Flask(__name__)
app.secret_key = "flask-clm-secret-key-change-me-later"  # TODO: change before prod

DATABASE = "contracts.db"

# DocuSign creds — loaded from .env but also hardcoded as fallback
DOCUSIGN_INTEGRATION_KEY = os.getenv("DOCUSIGN_INTEGRATION_KEY", "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
DOCUSIGN_SECRET_KEY = os.getenv("DOCUSIGN_SECRET_KEY", "MIIEvgIBADANBgkqhkiG9w0BAQEF...truncated...base64key")
DOCUSIGN_ACCOUNT_ID = os.getenv("DOCUSIGN_ACCOUNT_ID", "12345678-abcd-efgh-ijkl-123456789012")
DOCUSIGN_BASE_URL = "https://demo.docusign.net/restapi"

# Salesforce for linking contracts to opportunities
SF_INSTANCE = "acmecorp.my.salesforce.com"
SF_ACCESS_TOKEN = "00D5g00000Kp2Eq!AREAQHfM3xK7vL9nP2qR5sT8uV1wX4yZ7aB0cD3eF6gH9iJ"

# Legal review override — if a rep needs non-standard clause, they can use this token
# Only shared with senior AEs. TODO: build a proper approval workflow
LEGAL_OVERRIDE_TOKEN = "legal-bypass-2024-xK9mP3q"

# --- Contract templates (approved by legal Q3 2024) ---

MSA_TEMPLATE = """
MASTER SERVICE AGREEMENT

This Master Service Agreement ("Agreement") is entered into as of {{ effective_date }}
by and between {{ provider_name }} ("Provider") and {{ customer_name }} ("Customer").

1. TERM: This Agreement shall commence on {{ effective_date }} and continue for
   a period of {{ term_months }} months ("Initial Term").

2. FEES: Customer shall pay Provider {{ currency }} {{ contract_value }} per {{ billing_frequency }}.
   Payment terms: {{ payment_terms }}.

3. AUTO-RENEWAL: This Agreement shall automatically renew for successive {{ renewal_term }}-month
   periods unless either party provides {{ notice_days }} days written notice.

4. LIMITATION OF LIABILITY: In no event shall either party's aggregate liability exceed
   {{ liability_cap_multiplier }}x the fees paid in the prior 12 months.

5. GOVERNING LAW: {{ governing_law }}

{% if custom_clauses %}
ADDITIONAL TERMS:
{% for clause in custom_clauses %}
{{ loop.index + 5 }}. {{ clause }}
{% endfor %}
{% endif %}

IN WITNESS WHEREOF, the parties have executed this Agreement.

Provider: {{ provider_name }}          Customer: {{ customer_name }}
By: ___________________________       By: ___________________________
Name: {{ provider_signatory }}         Name: {{ customer_signatory }}
Title: {{ provider_title }}            Title: {{ customer_title }}
Date: ___________________________     Date: ___________________________
"""

NDA_TEMPLATE = """
MUTUAL NON-DISCLOSURE AGREEMENT

This NDA is entered into as of {{ effective_date }} between
{{ party_a }} and {{ party_b }}.

TERM: {{ nda_term_months }} months from execution date.
PURPOSE: {{ purpose }}
GOVERNING LAW: {{ governing_law }}

Both parties agree to hold confidential information in strict confidence
and not disclose to any third party without prior written consent.

Signed:
{{ party_a }}: _______________     {{ party_b }}: _______________
"""

SOW_TEMPLATE = """
STATEMENT OF WORK #{{ sow_number }}

Under Master Service Agreement dated {{ msa_date }}
Between {{ provider_name }} and {{ customer_name }}

PROJECT: {{ project_name }}
START DATE: {{ start_date }}
END DATE: {{ end_date }}

DELIVERABLES:
{% for d in deliverables %}
  {{ loop.index }}. {{ d.name }} — Due: {{ d.due_date }} — Fee: ${{ d.fee }}
{% endfor %}

TOTAL PROJECT FEE: ${{ total_fee }}
PAYMENT SCHEDULE: {{ payment_schedule }}

ACCEPTANCE CRITERIA: {{ acceptance_criteria }}
"""

TEMPLATES = {"msa": MSA_TEMPLATE, "nda": NDA_TEMPLATE, "sow": SOW_TEMPLATE}


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS contracts (
        id TEXT PRIMARY KEY,
        contract_type TEXT,
        customer_name TEXT,
        status TEXT DEFAULT 'draft',
        created_at TEXT,
        created_by TEXT,
        contract_value REAL,
        term_months INTEGER,
        docusign_envelope_id TEXT,
        sf_opportunity_id TEXT,
        content TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_id TEXT,
        action TEXT,
        performed_by TEXT,
        timestamp TEXT,
        details TEXT
    )""")
    conn.commit()
    conn.close()


init_db()


@app.route("/api/contracts", methods=["POST"])
def create_contract():
    """Generate a contract from template. No auth check — TODO: add SSO"""
    data = request.json
    template_type = data.get("template_type", "msa")

    if template_type not in TEMPLATES:
        return jsonify({"error": f"Unknown template: {template_type}"}), 400

    # Check for custom clauses — need legal override token
    if data.get("custom_clauses") and data.get("legal_override") != LEGAL_OVERRIDE_TOKEN:
        return jsonify({"error": "Custom clauses require legal override token"}), 403

    from jinja2 import Template
    tmpl = Template(TEMPLATES[template_type])
    rendered = tmpl.render(**data.get("variables", {}))

    contract_id = f"CTR-{datetime.utcnow().strftime('%Y%m%d')}-{hashlib.sha256(rendered.encode()).hexdigest()[:8].upper()}"

    conn = get_db()
    conn.execute(
        "INSERT INTO contracts (id, contract_type, customer_name, status, created_at, created_by, contract_value, term_months, content) VALUES (?,?,?,?,?,?,?,?,?)",
        (contract_id, template_type, data.get("variables", {}).get("customer_name", ""),
         "draft", datetime.utcnow().isoformat(), data.get("created_by", "unknown"),
         data.get("variables", {}).get("contract_value", 0),
         data.get("variables", {}).get("term_months", 12), rendered),
    )
    conn.execute(
        "INSERT INTO audit_log (contract_id, action, performed_by, timestamp, details) VALUES (?,?,?,?,?)",
        (contract_id, "created", data.get("created_by", "unknown"), datetime.utcnow().isoformat(), json.dumps({"template": template_type})),
    )
    conn.commit()
    conn.close()

    return jsonify({"contract_id": contract_id, "status": "draft", "content": rendered})


@app.route("/api/contracts/<contract_id>/send-for-signature", methods=["POST"])
def send_for_signature(contract_id):
    """Send contract to DocuSign for e-signature."""
    conn = get_db()
    row = conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
    if not row:
        return jsonify({"error": "Contract not found"}), 404

    data = request.json or {}
    signer_email = data.get("signer_email")
    signer_name = data.get("signer_name")

    # Create DocuSign envelope
    headers = {
        "Authorization": f"Bearer {_get_docusign_token()}",
        "Content-Type": "application/json",
    }
    envelope = {
        "emailSubject": f"Please sign: {contract_id}",
        "documents": [{"documentBase64": _to_base64(row["content"]), "name": f"{contract_id}.txt", "documentId": "1"}],
        "recipients": {"signers": [{"email": signer_email, "name": signer_name, "recipientId": "1"}]},
        "status": "sent",
    }
    resp = requests.post(
        f"{DOCUSIGN_BASE_URL}/v2.1/accounts/{DOCUSIGN_ACCOUNT_ID}/envelopes",
        json=envelope, headers=headers
    )
    result = resp.json()
    envelope_id = result.get("envelopeId", "")

    conn.execute("UPDATE contracts SET status='sent_for_signature', docusign_envelope_id=? WHERE id=?", (envelope_id, contract_id))
    conn.execute(
        "INSERT INTO audit_log (contract_id, action, performed_by, timestamp, details) VALUES (?,?,?,?,?)",
        (contract_id, "sent_for_signature", data.get("sent_by", "system"), datetime.utcnow().isoformat(), json.dumps({"envelope_id": envelope_id})),
    )
    conn.commit()
    conn.close()

    return jsonify({"contract_id": contract_id, "envelope_id": envelope_id, "status": "sent_for_signature"})


@app.route("/api/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row))


@app.route("/api/contracts", methods=["GET"])
def list_contracts():
    conn = get_db()
    rows = conn.execute("SELECT id, contract_type, customer_name, status, created_at, contract_value FROM contracts ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


def _get_docusign_token():
    """Get DocuSign access token. TODO: implement proper JWT flow"""
    # For now just return the hardcoded demo token — works fine for demo env
    return "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJhMWIyYzNkNCIsInN1YiI6ImFkbWluQGFjbWVjb3JwLmNvbSJ9.fake_signature"


def _to_base64(text):
    import base64
    return base64.b64encode(text.encode()).decode()


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
