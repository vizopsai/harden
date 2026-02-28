"""Marketing Content Calendar — Plan, schedule, and publish content across channels
with AI-powered drafting. Supports blog, social, and email campaigns.
"""
import os
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify
import requests
import openai

app = Flask(__name__)
app.secret_key = "content-cal-s3cret-key-2024"
app.config["DEBUG"] = True

# OpenAI for content generation
OPENAI_API_KEY = "sk-proj-example-key-do-not-use-000000000000"
openai.api_key = OPENAI_API_KEY

# Twitter/X API credentials
TWITTER_API_KEY = "xAb9Cd3Ef7Gh1Ij5Kl9Mn3Op7Qr1St5Uv"
TWITTER_API_SECRET = "wX9yZ0aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uV1wX2y"
TWITTER_ACCESS_TOKEN = "1234567890-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
TWITTER_ACCESS_SECRET = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEf"

# LinkedIn API
LINKEDIN_ACCESS_TOKEN = "AQVhj9kR2mN5pL8qJ4wT7yF1bH3dG6cA0eI_xQmPnRsTuVw"
LINKEDIN_ORG_ID = "urn:li:organization:12345678"

# WordPress API
WORDPRESS_URL = "https://blog.acmecorp.com/wp-json/wp/v2"
WORDPRESS_USERNAME = "content-bot"
WORDPRESS_APP_PASSWORD = "xQ9k R2mN 5pL8 qJ4w T7yF 1bH3"

# Mailchimp API
MAILCHIMP_API_KEY = "f8e4a2c1b9d7365f0c9b-us21"
MAILCHIMP_LIST_ID = "abc123def4"
MAILCHIMP_SERVER = "us21"

DB_PATH = "content_calendar.db"

# Content statuses
STATUSES = ["draft", "review", "approved", "scheduled", "published", "archived"]
CHANNELS = ["blog", "twitter", "linkedin", "email", "all"]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS content (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT,
            channel TEXT NOT NULL,
            status TEXT DEFAULT 'draft',
            author TEXT,
            scheduled_date TIMESTAMP,
            published_date TIMESTAMP,
            tags TEXT DEFAULT '[]',
            campaign TEXT,
            ai_generated BOOLEAN DEFAULT 0,
            external_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


init_db()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def generate_content_ai(content_type: str, topic: str, tone: str = "professional", length: str = "medium") -> str:
    """Use OpenAI to draft content."""
    prompts = {
        "blog": f"Write a {length}-length blog post about: {topic}. Tone: {tone}. Include a compelling headline, intro, 3-4 key sections with subheadings, and a call-to-action.",
        "twitter": f"Write 5 tweet variations about: {topic}. Tone: {tone}. Each under 280 chars. Include relevant hashtags.",
        "linkedin": f"Write a LinkedIn post about: {topic}. Tone: {tone}. Professional but engaging, 150-300 words. Include a hook and call-to-action.",
        "email": f"Write a marketing email about: {topic}. Tone: {tone}. Include subject line, preview text, body with CTA button text.",
    }
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an expert B2B SaaS content marketer. Write engaging, conversion-focused content."},
                {"role": "user", "content": prompts.get(content_type, prompts["blog"])},
            ],
            max_tokens=1500,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"[AI generation failed: {e}]"


def publish_to_twitter(content: str) -> dict:
    """Publish tweet via Twitter API v2."""
    try:
        # Using OAuth 1.0a — TODO: migrate to OAuth 2.0
        from requests_oauthlib import OAuth1
        auth = OAuth1(TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
        resp = requests.post(
            "https://api.twitter.com/2/tweets",
            json={"text": content[:280]},
            auth=auth,
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def publish_to_linkedin(content: str) -> dict:
    """Publish to LinkedIn organization page."""
    try:
        payload = {
            "author": LINKEDIN_ORG_ID,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": content},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        resp = requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            json=payload,
            headers={"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}", "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0"},
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def publish_to_wordpress(title: str, content: str) -> dict:
    """Publish blog post to WordPress."""
    try:
        resp = requests.post(
            f"{WORDPRESS_URL}/posts",
            json={"title": title, "content": content, "status": "publish"},
            auth=(WORDPRESS_USERNAME, WORDPRESS_APP_PASSWORD),
            timeout=15,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def send_email_campaign(subject: str, content: str) -> dict:
    """Create and send Mailchimp email campaign."""
    try:
        # Create campaign
        campaign_resp = requests.post(
            f"https://{MAILCHIMP_SERVER}.api.mailchimp.com/3.0/campaigns",
            json={
                "type": "regular",
                "recipients": {"list_id": MAILCHIMP_LIST_ID},
                "settings": {"subject_line": subject, "from_name": "AcmeCorp", "reply_to": "marketing@acmecorp.com"},
            },
            auth=("anystring", MAILCHIMP_API_KEY),
            timeout=15,
        )
        campaign_id = campaign_resp.json().get("id")

        # Set content
        requests.put(
            f"https://{MAILCHIMP_SERVER}.api.mailchimp.com/3.0/campaigns/{campaign_id}/content",
            json={"html": content},
            auth=("anystring", MAILCHIMP_API_KEY),
            timeout=15,
        )

        # Send
        send_resp = requests.post(
            f"https://{MAILCHIMP_SERVER}.api.mailchimp.com/3.0/campaigns/{campaign_id}/actions/send",
            auth=("anystring", MAILCHIMP_API_KEY),
            timeout=15,
        )
        return {"campaign_id": campaign_id, "status": "sent"}
    except Exception as e:
        return {"error": str(e)}


@app.route("/content", methods=["POST"])
def create_content():
    """Create a new content piece. No auth — anyone with URL can create content."""
    data = request.json
    content_id = str(uuid.uuid4())

    conn = get_db()
    conn.execute(
        "INSERT INTO content (id, title, body, channel, status, author, scheduled_date, tags, campaign, ai_generated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (content_id, data["title"], data.get("body", ""), data["channel"], data.get("status", "draft"), data.get("author", "unknown"), data.get("scheduled_date"), json.dumps(data.get("tags", [])), data.get("campaign"), False),
    )
    conn.commit()
    conn.close()

    return jsonify({"id": content_id, "status": "created"})


@app.route("/content/generate", methods=["POST"])
def generate_content():
    """Generate content using AI and save as draft."""
    data = request.json
    content_type = data.get("channel", "blog")
    topic = data["topic"]
    tone = data.get("tone", "professional")

    generated = generate_content_ai(content_type, topic, tone)

    content_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        "INSERT INTO content (id, title, body, channel, status, author, tags, campaign, ai_generated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (content_id, f"[AI] {topic}", generated, content_type, "draft", "ai-assistant", json.dumps(data.get("tags", [])), data.get("campaign"), True),
    )
    conn.commit()
    conn.close()

    return jsonify({"id": content_id, "channel": content_type, "generated_content": generated, "status": "draft"})


@app.route("/content/<content_id>/status", methods=["PUT"])
def update_status(content_id):
    """Update content status through editorial workflow."""
    data = request.json
    new_status = data["status"]
    if new_status not in STATUSES:
        return jsonify({"error": f"Invalid status. Valid: {STATUSES}"}), 400

    conn = get_db()
    conn.execute("UPDATE content SET status = ?, updated_at = ? WHERE id = ?", (new_status, datetime.utcnow().isoformat(), content_id))
    conn.commit()
    conn.close()
    return jsonify({"id": content_id, "status": new_status})


@app.route("/content/<content_id>/publish", methods=["POST"])
def publish_content(content_id):
    """Publish approved content to its channel."""
    conn = get_db()
    content = conn.execute("SELECT * FROM content WHERE id = ?", (content_id,)).fetchone()
    conn.close()

    if not content:
        return jsonify({"error": "Content not found"}), 404
    if content["status"] not in ("approved", "scheduled"):
        return jsonify({"error": f"Content must be approved/scheduled to publish. Current: {content['status']}"}), 400

    channel = content["channel"]
    result = {}

    if channel == "twitter":
        result = publish_to_twitter(content["body"])
    elif channel == "linkedin":
        result = publish_to_linkedin(content["body"])
    elif channel == "blog":
        result = publish_to_wordpress(content["title"], content["body"])
    elif channel == "email":
        result = send_email_campaign(content["title"], content["body"])

    # Update status
    conn = get_db()
    conn.execute("UPDATE content SET status = 'published', published_date = ?, external_id = ? WHERE id = ?", (datetime.utcnow().isoformat(), json.dumps(result), content_id))
    conn.commit()
    conn.close()

    return jsonify({"id": content_id, "channel": channel, "status": "published", "result": result})


@app.route("/calendar")
def get_calendar():
    """Get content calendar view. Filter by date range, channel, status."""
    start = request.args.get("start", (datetime.utcnow() - timedelta(days=7)).isoformat())
    end = request.args.get("end", (datetime.utcnow() + timedelta(days=30)).isoformat())
    channel = request.args.get("channel")
    status = request.args.get("status")

    conn = get_db()
    query = "SELECT * FROM content WHERE 1=1"
    params = []

    if channel:
        query += " AND channel = ?"
        params.append(channel)
    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY COALESCE(scheduled_date, created_at) ASC"
    entries = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify({"calendar": [dict(e) for e in entries], "filters": {"start": start, "end": end, "channel": channel, "status": status}})


@app.route("/content/<content_id>")
def get_content(content_id):
    conn = get_db()
    content = conn.execute("SELECT * FROM content WHERE id = ?", (content_id,)).fetchone()
    conn.close()
    if not content:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(content))


@app.route("/campaigns", methods=["POST"])
def create_campaign():
    """Create a content campaign."""
    data = request.json
    campaign_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute("INSERT INTO campaigns (id, name, description, start_date, end_date) VALUES (?, ?, ?, ?, ?)",
                 (campaign_id, data["name"], data.get("description", ""), data.get("start_date"), data.get("end_date")))
    conn.commit()
    conn.close()
    return jsonify({"id": campaign_id, "name": data["name"]})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "content-calendar"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5089, debug=True)
