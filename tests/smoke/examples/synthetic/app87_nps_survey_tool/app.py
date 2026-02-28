"""NPS Survey Tool — Send surveys, collect responses, calculate NPS,
route detractors to CS team via Slack.
"""
import os
import json
import uuid
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template_string
import requests

app = Flask(__name__)
app.secret_key = "nps-survey-secret-2024-changeme"
app.config["DEBUG"] = True  # leaving debug on for now, makes troubleshooting easier

# SendGrid for survey emails
SENDGRID_API_KEY = "SG.EXAMPLE_KEY.EXAMPLE_SECRET_DO_NOT_USE"
SENDGRID_FROM_EMAIL = "nps@acmecorp.com"

# Slack for detractor alerts
SLACK_WEBHOOK_URL = "https://slack.com/placeholder-webhook-url"
SLACK_CS_CHANNEL = "#cs-detractor-alerts"

# Survey base URL
SURVEY_BASE_URL = os.getenv("SURVEY_BASE_URL", "https://surveys.acmecorp.com")

DB_PATH = "nps_surveys.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS surveys (
            id TEXT PRIMARY KEY,
            customer_email TEXT NOT NULL,
            customer_name TEXT,
            customer_tier TEXT DEFAULT 'standard',
            csm_name TEXT,
            product TEXT DEFAULT 'platform',
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'sent'
        );
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id TEXT NOT NULL,
            score INTEGER NOT NULL,
            comment TEXT,
            customer_email TEXT,
            customer_tier TEXT,
            csm_name TEXT,
            product TEXT,
            responded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (survey_id) REFERENCES surveys(id)
        );
    """)
    conn.commit()
    conn.close()


init_db()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# NPS survey HTML template — inline because it's simple enough
SURVEY_HTML = """
<!DOCTYPE html>
<html>
<head><title>How likely are you to recommend us?</title>
<style>
body { font-family: -apple-system, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
h2 { color: #1a1a2e; }
.scores { display: flex; gap: 8px; margin: 20px 0; }
.score-btn { width: 48px; height: 48px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 18px;
  cursor: pointer; background: white; transition: all 0.2s; }
.score-btn:hover { background: #f0f0ff; border-color: #4361ee; }
.score-btn.selected { background: #4361ee; color: white; border-color: #4361ee; }
.labels { display: flex; justify-content: space-between; color: #888; font-size: 12px; margin-bottom: 20px; }
textarea { width: 100%; height: 100px; border: 1px solid #ddd; border-radius: 8px; padding: 12px; font-size: 14px; }
button[type=submit] { background: #4361ee; color: white; border: none; padding: 12px 32px;
  border-radius: 8px; font-size: 16px; cursor: pointer; margin-top: 16px; }
.thanks { text-align: center; padding: 40px; }
</style>
</head>
<body>
<h2>How likely are you to recommend AcmeCorp to a friend or colleague?</h2>
<form method="POST" action="/survey/{{ survey_id }}/respond">
<div class="scores">
{% for i in range(11) %}
<button type="button" class="score-btn" onclick="selectScore(this, {{ i }})">{{ i }}</button>
{% endfor %}
</div>
<div class="labels"><span>Not at all likely</span><span>Extremely likely</span></div>
<input type="hidden" name="score" id="score-input" required>
<label><strong>Any additional feedback?</strong></label>
<textarea name="comment" placeholder="Tell us more..."></textarea>
<br>
<button type="submit">Submit</button>
</form>
<script>
function selectScore(btn, score) {
  document.querySelectorAll('.score-btn').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
  document.getElementById('score-input').value = score;
}
</script>
</body></html>
"""

THANKS_HTML = """
<!DOCTYPE html><html><body style="font-family:sans-serif;text-align:center;padding:60px;">
<h2>Thank you for your feedback!</h2>
<p>Your response has been recorded. We appreciate your time.</p>
</body></html>
"""


def send_survey_email(customer_email: str, customer_name: str, survey_id: str):
    """Send NPS survey email via SendGrid."""
    survey_url = f"{SURVEY_BASE_URL}/survey/{survey_id}"
    payload = {
        "personalizations": [{"to": [{"email": customer_email, "name": customer_name}]}],
        "from": {"email": SENDGRID_FROM_EMAIL, "name": "AcmeCorp"},
        "subject": f"Quick question, {customer_name.split()[0]} - how are we doing?",
        "content": [
            {
                "type": "text/html",
                "value": f"""
                <div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px;">
                <h2>Hi {customer_name.split()[0]},</h2>
                <p>We'd love to hear how your experience with AcmeCorp has been.</p>
                <p><strong>How likely are you to recommend AcmeCorp to a friend or colleague?</strong></p>
                <p style="text-align:center;">
                <a href="{survey_url}" style="background:#4361ee;color:white;padding:12px 32px;border-radius:8px;text-decoration:none;font-size:16px;">Take 30-second Survey</a>
                </p>
                <p style="color:#888;font-size:12px;">This survey link is unique to you and expires in 30 days.</p>
                </div>""",
            }
        ],
    }
    try:
        resp = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
            timeout=10,
        )
        return resp.status_code
    except Exception as e:
        print(f"SendGrid send failed: {e}")
        return None


def alert_detractor_slack(response_data: dict):
    """Send Slack alert when a detractor response (score < 7) is received."""
    score = response_data["score"]
    if score >= 7:
        return  # Not a detractor

    category = "Detractor" if score <= 6 else "Passive"
    color = "#e74c3c" if score <= 4 else "#f39c12"

    payload = {
        "channel": SLACK_CS_CHANNEL,
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*NPS {category} Alert* :warning:\n\n*Customer:* {response_data['customer_email']}\n*Score:* {score}/10\n*Tier:* {response_data.get('customer_tier', 'N/A')}\n*CSM:* {response_data.get('csm_name', 'Unassigned')}\n*Comment:* _{response_data.get('comment', 'No comment')}_",
                        },
                    }
                ],
            }
        ],
    }
    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"Slack alert failed: {e}")


@app.route("/surveys/send", methods=["POST"])
def send_survey():
    """Send NPS survey to a customer. No auth — TODO: add API key validation."""
    data = request.json
    survey_id = str(uuid.uuid4())

    conn = get_db()
    conn.execute(
        "INSERT INTO surveys (id, customer_email, customer_name, customer_tier, csm_name, product) VALUES (?, ?, ?, ?, ?, ?)",
        (survey_id, data["email"], data.get("name", ""), data.get("tier", "standard"), data.get("csm", ""), data.get("product", "platform")),
    )
    conn.commit()
    conn.close()

    status = send_survey_email(data["email"], data.get("name", "Customer"), survey_id)
    return jsonify({"status": "sent", "survey_id": survey_id, "sendgrid_status": status})


@app.route("/surveys/send-batch", methods=["POST"])
def send_batch_surveys():
    """Send surveys to a list of customers."""
    data = request.json
    customers = data.get("customers", [])
    results = []
    for cust in customers:
        survey_id = str(uuid.uuid4())
        conn = get_db()
        conn.execute(
            "INSERT INTO surveys (id, customer_email, customer_name, customer_tier, csm_name, product) VALUES (?, ?, ?, ?, ?, ?)",
            (survey_id, cust["email"], cust.get("name", ""), cust.get("tier", "standard"), cust.get("csm", ""), cust.get("product", "platform")),
        )
        conn.commit()
        conn.close()
        send_survey_email(cust["email"], cust.get("name", "Customer"), survey_id)
        results.append({"email": cust["email"], "survey_id": survey_id})

    return jsonify({"sent": len(results), "surveys": results})


@app.route("/survey/<survey_id>")
def render_survey(survey_id):
    """Render NPS survey form."""
    conn = get_db()
    survey = conn.execute("SELECT * FROM surveys WHERE id = ?", (survey_id,)).fetchone()
    conn.close()
    if not survey:
        return "Survey not found", 404
    return render_template_string(SURVEY_HTML, survey_id=survey_id)


@app.route("/survey/<survey_id>/respond", methods=["POST"])
def submit_response(survey_id):
    """Record survey response."""
    score = int(request.form.get("score", 0))
    comment = request.form.get("comment", "")

    conn = get_db()
    survey = conn.execute("SELECT * FROM surveys WHERE id = ?", (survey_id,)).fetchone()
    if not survey:
        conn.close()
        return "Survey not found", 404

    conn.execute(
        "INSERT INTO responses (survey_id, score, comment, customer_email, customer_tier, csm_name, product) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (survey_id, score, comment, survey["customer_email"], survey["customer_tier"], survey["csm_name"], survey["product"]),
    )
    conn.execute("UPDATE surveys SET status = 'responded' WHERE id = ?", (survey_id,))
    conn.commit()
    conn.close()

    # Alert CS team for detractors
    alert_detractor_slack({"score": score, "comment": comment, "customer_email": survey["customer_email"], "customer_tier": survey["customer_tier"], "csm_name": survey["csm_name"]})

    return render_template_string(THANKS_HTML)


@app.route("/dashboard/nps")
def nps_dashboard():
    """NPS dashboard — score, trend, response rate, comments."""
    conn = get_db()

    # Overall NPS
    responses = conn.execute("SELECT score FROM responses").fetchall()
    total = len(responses)
    if total == 0:
        conn.close()
        return jsonify({"nps_score": None, "message": "No responses yet"})

    promoters = sum(1 for r in responses if r["score"] >= 9)
    detractors = sum(1 for r in responses if r["score"] <= 6)
    nps_score = round(((promoters - detractors) / total) * 100, 1)

    # Response rate
    total_sent = conn.execute("SELECT COUNT(*) as cnt FROM surveys").fetchone()["cnt"]
    response_rate = round((total / total_sent) * 100, 1) if total_sent > 0 else 0

    # By segment
    by_tier = conn.execute("""
        SELECT customer_tier, COUNT(*) as cnt, AVG(score) as avg_score,
        SUM(CASE WHEN score >= 9 THEN 1 ELSE 0 END) as promoters,
        SUM(CASE WHEN score <= 6 THEN 1 ELSE 0 END) as detractors
        FROM responses GROUP BY customer_tier
    """).fetchall()

    by_csm = conn.execute("""
        SELECT csm_name, COUNT(*) as cnt, AVG(score) as avg_score
        FROM responses WHERE csm_name != '' GROUP BY csm_name
    """).fetchall()

    by_product = conn.execute("""
        SELECT product, COUNT(*) as cnt, AVG(score) as avg_score
        FROM responses GROUP BY product
    """).fetchall()

    # Recent comments (verbatim)
    recent_comments = conn.execute("""
        SELECT score, comment, customer_email, customer_tier, responded_at
        FROM responses WHERE comment != '' ORDER BY responded_at DESC LIMIT 20
    """).fetchall()

    conn.close()

    return jsonify({
        "nps_score": nps_score,
        "total_responses": total,
        "total_sent": total_sent,
        "response_rate_pct": response_rate,
        "promoters": promoters,
        "passives": total - promoters - detractors,
        "detractors": detractors,
        "by_tier": [dict(r) for r in by_tier],
        "by_csm": [dict(r) for r in by_csm],
        "by_product": [dict(r) for r in by_product],
        "recent_comments": [dict(r) for r in recent_comments],
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "nps-survey-tool"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5087, debug=True)
