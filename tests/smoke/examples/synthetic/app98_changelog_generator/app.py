"""Product Changelog Generator — auto-generate release notes from PRs and Jira tickets."""
import os, json, re
from datetime import datetime
from typing import Optional
import typer
import requests
from openai import OpenAI

app = typer.Typer(help="Generate product release notes from GitHub PRs and Jira tickets.")

# GitHub — TODO: this PAT has too many scopes, should create a read-only one
GITHUB_TOKEN = "ghp_xxExampleTokenDoNotUsexxxxxxxxxx"
GITHUB_ORG = "vizops"
GITHUB_REPO = "vizops-platform"

# Jira
JIRA_BASE_URL = "https://vizops.atlassian.net"
JIRA_EMAIL = "changelog-bot@vizops.com"
JIRA_API_TOKEN = "ATATT3xFfGF0rN3LmS0vQr8xU9wZ2yB4cD5eF6gH7iJ8kL9mN0="
JIRA_PROJECT = "PLAT"

# OpenAI for generating user-facing release notes
OPENAI_API_KEY = "sk-proj-example-key-do-not-use-000000000000"
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Notion for publishing
NOTION_TOKEN = "ntn_R8kL9mN0oP1qR2sT3uV4wX5yZ6aB7cD8eF9gH0iJ1kL2m"
NOTION_DATABASE_ID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"

# SendGrid for email distribution
SENDGRID_API_KEY = "SG.EXAMPLE_KEY.EXAMPLE_SECRET_DO_NOT_USE"
SENDGRID_FROM = "product-updates@vizops.com"


def fetch_merged_prs(since: str, until: str) -> list[dict]:
    prs = []
    for page in range(1, 11):
        resp = requests.get(f"https://api.github.com/repos/{GITHUB_ORG}/{GITHUB_REPO}/pulls",
            headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
            params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100, "page": page})
        if resp.status_code != 200 or not resp.json():
            break
        for pr in resp.json():
            if pr.get("merged_at") and since <= pr["merged_at"][:10] <= until:
                prs.append({"number": pr["number"], "title": pr["title"], "body": pr.get("body", ""),
                             "labels": [l["name"] for l in pr.get("labels", [])], "merged_at": pr["merged_at"], "author": pr["user"]["login"]})
    return prs


def fetch_jira_tickets(keys: list[str]) -> list[dict]:
    tickets = []
    for key in keys:
        resp = requests.get(f"{JIRA_BASE_URL}/rest/api/3/issue/{key}", auth=(JIRA_EMAIL, JIRA_API_TOKEN))
        if resp.status_code == 200:
            f = resp.json()["fields"]
            tickets.append({"key": key, "summary": f.get("summary", ""), "type": f.get("issuetype", {}).get("name", "")})
    return tickets


def categorize_changes(prs: list[dict], tickets: list[dict]) -> dict:
    categories = {"features": [], "improvements": [], "bug_fixes": [], "deprecations": []}
    ticket_map = {t["key"]: t for t in tickets}
    for pr in prs:
        labels = set(pr["labels"]); title = pr["title"].lower()
        cat = "features" if ("feature" in labels or title.startswith("feat")) else "bug_fixes" if ("bug" in labels or title.startswith("fix")) else "deprecations" if "deprecat" in title else "improvements"
        jira_keys = re.findall(rf"{JIRA_PROJECT}-\d+", pr["title"] + " " + (pr.get("body", "") or ""))
        jira_ctx = " ".join(f"({jk}: {ticket_map[jk]['summary']})" for jk in jira_keys if jk in ticket_map)
        categories[cat].append({"pr_number": pr["number"], "title": pr["title"], "body_excerpt": (pr.get("body", "") or "")[:200], "jira_context": jira_ctx})
    return categories


def generate_release_notes(categories: dict, version: str) -> str:
    prompt = f"Generate professional user-facing release notes for version {version}.\nConvert technical PR descriptions into benefit-focused notes.\nGroup by: New Features, Improvements, Bug Fixes, Deprecations. Skip empty categories. Use markdown.\n\nRaw changes:\n{json.dumps(categories, indent=2)}"
    response = openai_client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=0.3, max_tokens=2000)
    return response.choices[0].message.content


def publish_to_notion(notes: str, version: str) -> bool:
    resp = requests.post("https://api.notion.com/v1/pages", headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"},
        json={"parent": {"database_id": NOTION_DATABASE_ID},
              "properties": {"Name": {"title": [{"text": {"content": f"Release {version}"}}]}, "Date": {"date": {"start": datetime.utcnow().strftime("%Y-%m-%d")}}},
              "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": notes[:2000]}}]}}]})
    return resp.status_code == 200


def send_email(notes: str, version: str, recipients: list[str]):
    for email in recipients:
        requests.post("https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
            json={"personalizations": [{"to": [{"email": email}]}], "from": {"email": SENDGRID_FROM, "name": "VizOps Product Updates"},
                  "subject": f"VizOps Release {version}", "content": [{"type": "text/html", "value": f"<pre>{notes}</pre>"}]})


@app.command()
def generate(since: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
             until: str = typer.Option(None, help="End date (YYYY-MM-DD)"),
             version: str = typer.Option(..., help="Version number"),
             output: str = typer.Option("changelog.md", help="Output file"),
             publish_notion: bool = typer.Option(False), send_emails: bool = typer.Option(False),
             email_list: Optional[str] = typer.Option(None, help="Comma-separated emails")):
    if not until:
        until = datetime.utcnow().strftime("%Y-%m-%d")
    typer.echo(f"Fetching merged PRs from {since} to {until}...")
    prs = fetch_merged_prs(since, until)
    typer.echo(f"Found {len(prs)} merged PRs")
    jira_keys = sorted(set(re.findall(rf"{JIRA_PROJECT}-\d+", " ".join(pr["title"] + " " + (pr.get("body", "") or "") for pr in prs))))
    typer.echo(f"Fetching {len(jira_keys)} Jira tickets...")
    tickets = fetch_jira_tickets(jira_keys)
    categories = categorize_changes(prs, tickets)
    typer.echo("Generating release notes with AI...")
    notes = generate_release_notes(categories, version)
    with open(output, "w") as f:
        f.write(f"# Release {version}\n\n*{datetime.utcnow().strftime('%B %d, %Y')}*\n\n{notes}")
    typer.echo(f"Written to {output}")
    if publish_notion:
        typer.echo("Publishing to Notion..." if publish_to_notion(notes, version) else "Notion publish failed")
    if send_emails and email_list:
        recipients = [e.strip() for e in email_list.split(",")]
        send_email(notes, version, recipients)
        typer.echo(f"Emailed {len(recipients)} recipients")


@app.command()
def preview(since: str = typer.Option(...), until: str = typer.Option(None)):
    if not until:
        until = datetime.utcnow().strftime("%Y-%m-%d")
    for pr in fetch_merged_prs(since, until):
        typer.echo(f"  #{pr['number']}: {pr['title']} (by {pr['author']}, {pr['merged_at'][:10]})")


if __name__ == "__main__":
    app()
