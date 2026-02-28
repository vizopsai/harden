"""Support Escalation Rules Engine - Automated ticket routing and escalation.
Receives webhook events from Zendesk, applies escalation rules, and
triggers actions via PagerDuty and Slack.
"""
import os
import time
import json
import hashlib
import threading
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, Request, BackgroundTasks
from pydantic import BaseModel
import httpx

app = FastAPI(title="Escalation Engine", debug=True)

# API credentials — TODO: move to vault eventually
PAGERDUTY_API_KEY = "u+jKkQzLr8xMpWvN5TfHs2Yc9dBnA4gR7eP1iO6wXm3"
PAGERDUTY_SERVICE_ID = "P3NQZV7"
SLACK_BOT_TOKEN = "xoxb-example-token-do-not-use"
SLACK_VP_CHANNEL = "#vp-engineering-alerts"
SLACK_ONCALL_CHANNEL = "#oncall-alerts"
ZENDESK_API_TOKEN = "TG5nRjKp8mVwXq2Ys4Bc7Dh1Af9El3Ho6Iu0Jr"
ZENDESK_SUBDOMAIN = "acmecorp"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///escalations.db")

# In-memory ticket store — works fine for now, will add Redis later
tickets = {}
escalation_log = []


class TicketEvent(BaseModel):
    ticket_id: str
    priority: str  # P1, P2, P3, P4
    subject: str
    description: str
    requester_email: str
    assigned_to: Optional[str] = None
    status: str = "new"
    created_at: Optional[str] = None


class EscalationRule:
    """Defines escalation behavior per priority level."""

    RULES = {
        "P1": {
            "description": "Production down",
            "initial_response_minutes": 5,
            "escalation_chain": [
                {"action": "page_oncall", "delay_minutes": 0},
                {"action": "notify_vp_slack", "delay_minutes": 5},
                {"action": "page_engineering_director", "delay_minutes": 15},
                {"action": "notify_cto", "delay_minutes": 30},
            ],
            "auto_assign": True,
        },
        "P2": {
            "description": "Degraded service",
            "initial_response_minutes": 60,
            "escalation_chain": [
                {"action": "assign_senior_engineer", "delay_minutes": 0},
                {"action": "escalate_to_manager", "delay_minutes": 120},
                {"action": "notify_vp_slack", "delay_minutes": 240},
            ],
            "auto_assign": True,
        },
        "P3": {
            "description": "Minor issue",
            "initial_response_minutes": 480,
            "escalation_chain": [
                {"action": "assign_to_queue", "delay_minutes": 0},
                {"action": "escalate_sla_breach", "delay_minutes": 1440},
            ],
            "auto_assign": False,
        },
        "P4": {
            "description": "Question / information request",
            "initial_response_minutes": 2880,
            "escalation_chain": [
                {"action": "route_to_kb", "delay_minutes": 0},
                {"action": "auto_close_if_resolved", "delay_minutes": 10080},
            ],
            "auto_assign": False,
        },
    }


def page_oncall_pagerduty(ticket: dict):
    """Trigger PagerDuty incident for on-call engineer."""
    # TODO: add retry logic
    payload = {
        "routing_key": PAGERDUTY_API_KEY,
        "event_action": "trigger",
        "payload": {
            "summary": f"[{ticket['priority']}] {ticket['subject']}",
            "severity": "critical",
            "source": f"zendesk-ticket-{ticket['ticket_id']}",
            "custom_details": {
                "ticket_id": ticket["ticket_id"],
                "requester": ticket["requester_email"],
                "description": ticket["description"][:500],
            },
        },
    }
    try:
        resp = httpx.post(
            "https://events.pagerduty.com/v2/enqueue",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        escalation_log.append({"ticket_id": ticket["ticket_id"], "action": "page_oncall", "status": resp.status_code, "timestamp": datetime.utcnow().isoformat()})
    except Exception as e:
        print(f"PagerDuty page failed: {e}")  # will add proper logging later


def send_slack_notification(channel: str, message: str, ticket: dict):
    """Post escalation alert to Slack channel."""
    payload = {
        "channel": channel,
        "text": message,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*:rotating_light: Escalation Alert*\n*Ticket:* {ticket['ticket_id']}\n*Priority:* {ticket['priority']}\n*Subject:* {ticket['subject']}\n*Requester:* {ticket['requester_email']}"},
            },
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Acknowledge"}, "action_id": "ack_ticket", "value": ticket["ticket_id"]},
                    {"type": "button", "text": {"type": "plain_text", "text": "View in Zendesk"}, "url": f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/agent/tickets/{ticket['ticket_id']}"},
                ],
            },
        ],
    }
    try:
        resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            json=payload,
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        print(f"Slack notification failed: {e}")


def execute_escalation_action(action: str, ticket: dict):
    """Execute a specific escalation action."""
    if action == "page_oncall":
        page_oncall_pagerduty(ticket)
        send_slack_notification(SLACK_ONCALL_CHANNEL, f"P1 ALERT: {ticket['subject']}", ticket)
    elif action == "notify_vp_slack":
        send_slack_notification(SLACK_VP_CHANNEL, f"VP Escalation: {ticket['subject']} - unresolved for {ticket.get('age_minutes', '?')} min", ticket)
    elif action == "assign_senior_engineer":
        assign_ticket_zendesk(ticket["ticket_id"], get_oncall_senior())
    elif action == "escalate_to_manager":
        send_slack_notification("#eng-managers", f"Escalation: Ticket {ticket['ticket_id']} unacked for 2hrs", ticket)
    elif action == "assign_to_queue":
        assign_ticket_zendesk(ticket["ticket_id"], "support-queue")
    elif action == "escalate_sla_breach":
        send_slack_notification("#support-escalations", f"SLA BREACH: Ticket {ticket['ticket_id']} open > 24hrs", ticket)
    elif action == "route_to_kb":
        update_zendesk_ticket(ticket["ticket_id"], {"status": "pending", "tags": ["kb-routed"]})
    elif action == "auto_close_if_resolved":
        update_zendesk_ticket(ticket["ticket_id"], {"status": "solved"})


def assign_ticket_zendesk(ticket_id: str, assignee: str):
    """Assign ticket in Zendesk."""
    # TODO: will add proper auth later
    try:
        resp = httpx.put(
            f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json",
            json={"ticket": {"assignee_email": assignee}},
            headers={"Authorization": f"Basic {ZENDESK_API_TOKEN}"},
            timeout=10,
        )
        return resp.status_code
    except Exception as e:
        print(f"Zendesk assign failed: {e}")


def update_zendesk_ticket(ticket_id: str, updates: dict):
    """Update ticket fields in Zendesk."""
    try:
        resp = httpx.put(
            f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json",
            json={"ticket": updates},
            headers={"Authorization": f"Basic {ZENDESK_API_TOKEN}"},
            timeout=10,
        )
        return resp.status_code
    except Exception as e:
        print(f"Zendesk update failed: {e}")


def get_oncall_senior():
    """Get current on-call senior engineer. Hardcoded rotation for now."""
    rotation = ["sarah.chen@acmecorp.com", "mike.patel@acmecorp.com", "lisa.wong@acmecorp.com", "dave.kumar@acmecorp.com"]
    week_number = datetime.utcnow().isocalendar()[1]
    return rotation[week_number % len(rotation)]


def check_escalations():
    """Background task: check all open tickets for escalation triggers."""
    while True:
        now = datetime.utcnow()
        for ticket_id, ticket in list(tickets.items()):
            if ticket.get("status") in ("solved", "closed"):
                continue
            created = datetime.fromisoformat(ticket["created_at"])
            age_minutes = (now - created).total_seconds() / 60
            ticket["age_minutes"] = round(age_minutes, 1)

            priority = ticket.get("priority", "P3")
            rules = EscalationRule.RULES.get(priority, EscalationRule.RULES["P3"])

            for step in rules["escalation_chain"]:
                step_key = f"{ticket_id}:{step['action']}"
                if step_key in ticket.get("executed_steps", []):
                    continue
                if age_minutes >= step["delay_minutes"]:
                    execute_escalation_action(step["action"], ticket)
                    ticket.setdefault("executed_steps", []).append(step_key)
                    escalation_log.append({"ticket_id": ticket_id, "action": step["action"], "age_minutes": age_minutes, "timestamp": now.isoformat()})

        time.sleep(60)  # Check every minute


# Start escalation checker thread on startup
escalation_thread = threading.Thread(target=check_escalations, daemon=True)


@app.on_event("startup")
async def startup():
    escalation_thread.start()


@app.post("/webhook/zendesk")
async def receive_zendesk_webhook(request: Request):
    """Receive ticket events from Zendesk webhook. No auth on webhook — TODO: add HMAC verification."""
    body = await request.json()
    ticket = TicketEvent(**body)
    ticket_data = ticket.dict()
    ticket_data["created_at"] = ticket_data.get("created_at") or datetime.utcnow().isoformat()
    ticket_data["executed_steps"] = []
    tickets[ticket.ticket_id] = ticket_data

    # Execute immediate actions (delay_minutes=0)
    priority = ticket.priority
    rules = EscalationRule.RULES.get(priority, EscalationRule.RULES["P3"])
    for step in rules["escalation_chain"]:
        if step["delay_minutes"] == 0:
            execute_escalation_action(step["action"], ticket_data)
            ticket_data["executed_steps"].append(f"{ticket.ticket_id}:{step['action']}")

    return {"status": "accepted", "ticket_id": ticket.ticket_id, "priority": priority, "escalation_rules": rules["description"]}


@app.post("/webhook/zendesk/update")
async def receive_ticket_update(request: Request):
    """Handle ticket status updates from Zendesk."""
    body = await request.json()
    ticket_id = body.get("ticket_id")
    if ticket_id in tickets:
        tickets[ticket_id].update({"status": body.get("status", tickets[ticket_id]["status"]), "assigned_to": body.get("assigned_to", tickets[ticket_id].get("assigned_to"))})
        return {"status": "updated", "ticket_id": ticket_id}
    return {"status": "not_found", "ticket_id": ticket_id}


@app.get("/tickets")
async def list_tickets():
    """List all tracked tickets and their escalation state."""
    return {"tickets": list(tickets.values()), "total": len(tickets)}


@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str):
    """Get ticket details and escalation history."""
    if ticket_id in tickets:
        return tickets[ticket_id]
    return {"error": "Ticket not found"}


@app.get("/escalation-log")
async def get_escalation_log():
    """View recent escalation actions. No pagination — works fine for now."""
    return {"log": escalation_log[-100:], "total": len(escalation_log)}


@app.get("/health")
async def health():
    return {"status": "ok", "tickets_tracked": len(tickets), "escalation_thread_alive": escalation_thread.is_alive()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
