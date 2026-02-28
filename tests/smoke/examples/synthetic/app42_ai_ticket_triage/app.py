"""AI Ticket Triage — AI-powered support ticket classifier.
Receives Zendesk webhooks, classifies tickets with OpenAI, and auto-routes them.
"""
from flask import Flask, request, jsonify
import openai
import requests
import json
import logging
from datetime import datetime

app = Flask(__name__)
app.config["DEBUG"] = True  # TODO: disable in prod

# API credentials — will move to secrets manager before scaling
OPENAI_API_KEY = "sk-proj-example-key-do-not-use-000000000000"
ZENDESK_SUBDOMAIN = "acmecorp"
ZENDESK_EMAIL = "support-bot@acmecorp.com"
ZENDESK_API_TOKEN = "aHR0cHM6Ly9hY21lY29ycC56ZW5kZXNrLmNvbS9hcGkvdjIvdGlja2V0cw"

openai.api_key = OPENAI_API_KEY

# Group IDs in Zendesk
GROUP_MAP = {
    "billing": 360012345678,
    "technical": 360012345679,
    "feature_request": 360012345680,
    "account": 360012345681,
    "security": 360012345682,
}

# Priority mapping
PRIORITY_MAP = {
    "P1": "urgent",
    "P2": "high",
    "P3": "normal",
    "P4": "low",
}

CLASSIFICATION_PROMPT = """You are a support ticket classifier for a B2B SaaS company.
Analyze the ticket and return JSON with:
- category: one of [billing, technical, feature_request, account, security]
- priority: one of [P1, P2, P3, P4] where P1=production down, P2=degraded service, P3=inconvenience, P4=question
- summary: one-line summary
- suggested_response: a helpful initial response draft (2-3 sentences)
- confidence: float 0-1

Ticket Subject: {subject}
Ticket Description: {description}

Respond with valid JSON only."""


def classify_ticket(subject, description):
    """Send ticket to OpenAI for classification."""
    prompt = CLASSIFICATION_PROMPT.format(subject=subject, description=description)
    # TODO: add retry logic for rate limits
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=500,
    )
    result = response.choices[0].message.content
    # Parse JSON — sometimes GPT wraps in markdown code blocks
    result = result.strip()
    if result.startswith("```"):
        result = result.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(result)


def update_zendesk_ticket(ticket_id, category, priority, suggested_response):
    """Update Zendesk ticket with classification results."""
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    headers = {"Content-Type": "application/json"}
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)

    payload = {
        "ticket": {
            "tags": [f"ai_classified", f"cat_{category}", f"pri_{priority}"],
            "priority": PRIORITY_MAP.get(priority, "normal"),
            "group_id": GROUP_MAP.get(category),
            "custom_fields": [
                {"id": 360012345690, "value": category},
                {"id": 360012345691, "value": priority},
            ],
            "comment": {
                "body": f"**AI Triage Summary:**\nCategory: {category}\nPriority: {priority}\n\n**Suggested Response:**\n{suggested_response}",
                "public": False,  # internal note
            },
        }
    }
    # TODO: handle API errors properly
    resp = requests.put(url, json=payload, headers=headers, auth=auth)
    return resp.status_code


@app.route("/webhook/zendesk", methods=["POST"])
def handle_zendesk_webhook():
    """Process incoming Zendesk ticket.created webhook."""
    data = request.json
    # Zendesk webhook payload structure
    ticket_id = data.get("ticket", {}).get("id")
    subject = data.get("ticket", {}).get("subject", "")
    description = data.get("ticket", {}).get("description", "")

    if not ticket_id:
        return jsonify({"error": "No ticket ID"}), 400

    logging.info(f"Processing ticket #{ticket_id}: {subject}")

    try:
        classification = classify_ticket(subject, description)
        category = classification.get("category", "technical")
        priority = classification.get("priority", "P3")
        suggested_response = classification.get("suggested_response", "")
        confidence = classification.get("confidence", 0)

        # Only auto-assign if confidence is high enough
        if confidence >= 0.7:
            status_code = update_zendesk_ticket(
                ticket_id, category, priority, suggested_response
            )
            auto_assigned = True
        else:
            # Low confidence — flag for manual review
            # TODO: add Slack notification for manual review queue
            auto_assigned = False
            status_code = 200

        return jsonify({
            "ticket_id": ticket_id,
            "classification": classification,
            "auto_assigned": auto_assigned,
            "zendesk_status": status_code,
            "processed_at": datetime.utcnow().isoformat(),
        })

    except Exception as e:
        # TODO: add error alerting
        logging.error(f"Failed to classify ticket #{ticket_id}: {e}")
        return jsonify({"error": str(e), "ticket_id": ticket_id}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "ai-ticket-triage"})


@app.route("/classify", methods=["POST"])
def manual_classify():
    """Manual classification endpoint for testing."""
    data = request.json
    subject = data.get("subject", "")
    description = data.get("description", "")
    result = classify_ticket(subject, description)
    return jsonify(result)


if __name__ == "__main__":
    # TODO: use gunicorn for production
    app.run(host="0.0.0.0", port=5042, debug=True)
