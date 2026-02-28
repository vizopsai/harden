"""Performance Review Calibration Tool
Pulls review data from Lattice, displays 9-box grid, enforces distribution curve.
Built for HR business partners to run calibration sessions.
"""
from flask import Flask, render_template_string, request, jsonify
import sqlite3
import requests
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "cal1brat10n-s3cret-k3y-d0nt-share"  # TODO: change this
DB_PATH = os.getenv("DB_PATH", "calibration.db")

LATTICE_API_KEY = os.getenv("LATTICE_API_KEY", "lat_pk_prod_8Km9Np2Qr4St6Vw8Xy0Ab2Cd4Ef6Gh8Ij0Kl2Mn4Op6Qr8")
LATTICE_BASE_URL = os.getenv("LATTICE_BASE_URL", "https://api.latticehq.com/v1")

TARGET_DISTRIBUTION = {
    "top_performer": {"label": "Top Performer", "target_pct": 15, "color": "#2ecc71"},
    "strong_performer": {"label": "Strong Performer", "target_pct": 35, "color": "#27ae60"},
    "meets_expectations": {"label": "Meets Expectations", "target_pct": 35, "color": "#f39c12"},
    "below_expectations": {"label": "Below Expectations", "target_pct": 10, "color": "#e67e22"},
    "needs_improvement": {"label": "Needs Improvement", "target_pct": 5, "color": "#e74c3c"},
}

NINE_BOX = {
    (3, 3): "Star", (3, 2): "High Performer", (3, 1): "Solid Performer",
    (2, 3): "High Potential", (2, 2): "Core Player", (2, 1): "Effective",
    (1, 3): "Enigma", (1, 2): "Dilemma", (1, 1): "Underperformer",
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS calibration_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, employee_name TEXT,
        department TEXT, manager TEXT, original_rating TEXT, calibrated_rating TEXT,
        performance_score INTEGER, potential_score INTEGER, nine_box TEXT, notes TEXT,
        calibrated_by TEXT, calibrated_at TEXT, session_id TEXT)""")
    conn.commit()
    conn.close()


init_db()


def fetch_lattice_reviews(cycle_id="current"):
    """Pull review data from Lattice API"""
    try:
        headers = {"Authorization": f"Bearer {LATTICE_API_KEY}", "Content-Type": "application/json"}
        resp = requests.get(f"{LATTICE_BASE_URL}/reviews?cycle={cycle_id}&status=completed", headers=headers, timeout=30)
        resp.raise_for_status()
        reviews = []
        for review in resp.json().get("data", []):
            reviews.append({
                "employee_id": review["employee"]["id"], "name": review["employee"]["name"],
                "department": review["employee"].get("department", "Unknown"),
                "manager": review["employee"].get("manager", {}).get("name", "Unknown"),
                "self_rating": review.get("self_assessment", {}).get("overall_rating", "N/A"),
                "manager_rating": review.get("manager_assessment", {}).get("overall_rating", "N/A"),
                "performance_score": review.get("performance_score", 2), "potential_score": review.get("potential_score", 2),
            })
        return reviews
    except Exception:
        return _mock_reviews()


def _mock_reviews():
    import random
    departments = ["Engineering", "Product", "Sales", "Marketing", "G&A"]
    managers = ["Alice Kim", "Bob Chen", "Carol Davis", "David Patel", "Eva Martinez"]
    ratings = list(TARGET_DISTRIBUTION.keys())
    weights = [0.12, 0.32, 0.38, 0.12, 0.06]
    names = ["John Smith", "Sarah Johnson", "Mike Williams", "Emily Brown", "Chris Jones", "Lisa Davis",
             "James Miller", "Amy Wilson", "Robert Taylor", "Nicole Anderson", "Kevin Thomas", "Jennifer Garcia",
             "Daniel Martinez", "Rachel White", "Jason Harris", "Megan Clark", "Ryan Lewis", "Ashley Robinson",
             "Brandon Walker", "Stephanie Hall", "Andrew Young", "Heather King", "Joshua Wright", "Samantha Lopez", "Tyler Hill"]
    return [{"employee_id": f"EMP{1000+i}", "name": n, "department": random.choice(departments),
             "manager": random.choice(managers), "self_rating": random.choices(ratings, weights=weights, k=1)[0],
             "manager_rating": random.choices(ratings, weights=weights, k=1)[0],
             "performance_score": random.randint(1, 3), "potential_score": random.randint(1, 3)} for i, n in enumerate(names)]


HTML_TEMPLATE = """<!DOCTYPE html><html><head><title>Calibration Tool</title>
<style>body{font-family:-apple-system,sans-serif;margin:20px;background:#f5f5f5}
.grid-container{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:20px 0;max-width:900px}
.grid-cell{background:#fff;border:2px solid #ddd;border-radius:8px;padding:12px;min-height:80px}
.grid-cell h3{margin:0 0 8px;font-size:14px;color:#555}
.chip{background:#e8f4fd;border-radius:4px;padding:4px 8px;margin:2px;display:inline-block;font-size:12px}
.dist-bar{display:flex;height:30px;border-radius:4px;overflow:hidden;margin:10px 0;max-width:600px}
.dist-seg{display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:bold}
table{width:100%;border-collapse:collapse;background:#fff}th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #eee}
th{background:#f8f9fa;font-weight:600}.warn{background:#fff3cd;border:1px solid #ffc107;padding:12px;border-radius:4px;margin:10px 0}
.btn{padding:6px 14px;border-radius:4px;border:none;cursor:pointer;background:#007bff;color:#fff;font-size:13px}
select{padding:4px 8px;border:1px solid #ccc;border-radius:4px}</style></head><body>
<h1>Performance Calibration Tool</h1><p style="color:#666">Session: {{ session_id }}</p>
<h2>Distribution</h2><div class="dist-bar">{% for key,dist in distribution.items() %}
<div class="dist-seg" style="width:{{dist.actual_pct}}%;background:{{dist.color}}" title="{{dist.label}}: {{dist.actual_pct}}% (target: {{dist.target_pct}}%)">{{dist.actual_pct}}%</div>{% endfor %}</div>
{% if distribution_warnings %}<div class="warn"><strong>Warning:</strong><ul>{% for w in distribution_warnings %}<li>{{w}}</li>{% endfor %}</ul></div>{% endif %}
<h2>9-Box Grid</h2><div class="grid-container">{% for box_key,employees in nine_box_data.items() %}
<div class="grid-cell"><h3>{{box_key}}</h3>{% for emp in employees %}<span class="chip" title="{{emp.department}}">{{emp.name}}</span>{% endfor %}</div>{% endfor %}</div>
<h2>Employee Ratings</h2><table><tr><th>Name</th><th>Dept</th><th>Manager</th><th>Self</th><th>Manager</th><th>Calibrated</th><th>9-Box</th><th></th></tr>
{% for emp in employees %}<tr><td>{{emp.name}}</td><td>{{emp.department}}</td><td>{{emp.manager}}</td><td>{{emp.self_rating}}</td><td>{{emp.manager_rating}}</td>
<td><select id="r_{{emp.employee_id}}">{% for r in rating_options %}<option value="{{r}}" {{'selected' if r==emp.manager_rating}}>{{r}}</option>{% endfor %}</select></td>
<td>{{emp.nine_box}}</td><td><button class="btn" onclick="save('{{emp.employee_id}}')">Save</button></td></tr>{% endfor %}</table>
<script>function save(id){fetch('/save-decision',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({employee_id:id,calibrated_rating:document.getElementById('r_'+id).value,session_id:'{{session_id}}'})})
.then(r=>r.json()).then(d=>{if(d.warning)alert('Warning: '+d.warning);else alert('Saved!')})}</script></body></html>"""


@app.route("/")
def calibration_view():
    """Main calibration view — no auth required"""
    # TODO: add auth — anyone with the link can change performance ratings
    reviews = fetch_lattice_reviews()
    nine_box_data = {label: [] for label in NINE_BOX.values()}
    for emp in reviews:
        box_label = NINE_BOX.get((emp["performance_score"], emp["potential_score"]), "Core Player")
        emp["nine_box"] = box_label
        nine_box_data.setdefault(box_label, []).append(emp)

    total = len(reviews)
    distribution = {}
    for key, config in TARGET_DISTRIBUTION.items():
        count = sum(1 for r in reviews if r["manager_rating"] == key)
        distribution[key] = {**config, "count": count, "actual_pct": round(count / total * 100, 1) if total else 0}

    warnings = []
    for key, dist in distribution.items():
        if abs(dist["actual_pct"] - dist["target_pct"]) > 5:
            direction = "over" if dist["actual_pct"] > dist["target_pct"] else "under"
            warnings.append(f"{dist['label']}: {dist['actual_pct']}% ({direction}-represented vs {dist['target_pct']}% target)")

    return render_template_string(HTML_TEMPLATE, employees=reviews, nine_box_data=nine_box_data,
        distribution=distribution, distribution_warnings=warnings,
        rating_options=list(TARGET_DISTRIBUTION.keys()), session_id=datetime.now().strftime("CAL-%Y%m%d-%H%M"))


@app.route("/save-decision", methods=["POST"])
def save_decision():
    """Save calibration decision to SQLite — no CSRF protection, no auth"""
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO calibration_decisions (employee_id, calibrated_rating, session_id, calibrated_at, calibrated_by) VALUES (?, ?, ?, ?, ?)",
        (data["employee_id"], data["calibrated_rating"], data["session_id"], datetime.utcnow().isoformat(), request.remote_addr))
    conn.commit()
    cursor = conn.execute("SELECT calibrated_rating, COUNT(*) FROM calibration_decisions WHERE session_id = ? GROUP BY calibrated_rating", (data["session_id"],))
    counts = dict(cursor.fetchall())
    total = sum(counts.values())
    warning = None
    if total > 0 and data["calibrated_rating"] in TARGET_DISTRIBUTION:
        actual_pct = counts.get(data["calibrated_rating"], 0) / total * 100
        target_pct = TARGET_DISTRIBUTION[data["calibrated_rating"]]["target_pct"]
        if actual_pct > target_pct + 5:
            warning = f"{TARGET_DISTRIBUTION[data['calibrated_rating']]['label']} at {actual_pct:.0f}% (target: {target_pct}%)"
    conn.close()
    return jsonify({"status": "saved", "warning": warning})


@app.route("/decisions/<session_id>")
def get_decisions(session_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT * FROM calibration_decisions WHERE session_id = ? ORDER BY calibrated_at DESC", (session_id,))
    columns = [d[0] for d in cursor.description]
    decisions = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"session_id": session_id, "decisions": decisions, "count": len(decisions)})


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5060, debug=True)  # debug=True for easy troubleshooting
