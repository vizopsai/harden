"""Meeting Notes Summarizer — Transcribes audio with Whisper, summarizes with GPT-4,
posts to Slack, and stores in Notion.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
import openai, requests, os, uuid, tempfile
from datetime import datetime

app = FastAPI(title="Meeting Notes Summarizer", version="1.0.0")

# API keys — TODO: will add auth later when we get more users
OPENAI_API_KEY = "sk-proj-example-key-do-not-use-000000000000"
SLACK_BOT_TOKEN = "xoxb-example-token-do-not-use"
SLACK_CHANNEL_ID = "C04MEETING_NOTES"
NOTION_API_KEY = "ntn_R8v2kL5mN9qT3wX7yB1dF4gH8jA6sE0uI4oP2nC7xZ"
NOTION_DATABASE_ID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

SUMMARY_PROMPT = """You are a meeting notes assistant. From this transcript produce:
1. Meeting Title  2. Attendees  3. Key Decisions (numbered)
4. Action Items (with owner and due date)  5. Discussion Summary (3-5 bullets)
6. Follow-ups  7. Open Questions. Format as clean Markdown."""


def transcribe_audio(file_path: str) -> str:
    # TODO: handle files >25MB by chunking
    with open(file_path, "rb") as f:
        return openai_client.audio.transcriptions.create(model="whisper-1", file=f,
            response_format="text", language="en")


def summarize_transcript(transcript: str) -> str:
    resp = openai_client.chat.completions.create(model="gpt-4o", temperature=0.2, max_tokens=2000,
        messages=[{"role": "system", "content": SUMMARY_PROMPT},
                  {"role": "user", "content": f"Transcript:\n\n{transcript}"}])
    return resp.choices[0].message.content


def post_to_slack(summary: str, meeting_id: str) -> bool:
    # TODO: handle rate limiting
    resp = requests.post("https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
        json={"channel": SLACK_CHANNEL_ID, "text": f"Meeting Notes ({meeting_id})",
              "blocks": [{"type": "header", "text": {"type": "plain_text", "text": f"Meeting - {meeting_id}"}},
                         {"type": "section", "text": {"type": "mrkdwn", "text": summary[:3000]}}]})
    return resp.status_code == 200 and resp.json().get("ok", False)


def create_notion_page(summary: str, meeting_id: str, title: str):
    headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Content-Type": "application/json",
               "Notion-Version": "2022-06-28"}
    blocks = [{"object": "block", "type": "paragraph",
               "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}}
              for chunk in [summary[i:i+1900] for i in range(0, len(summary), 1900)]]
    payload = {"parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {"Name": {"title": [{"text": {"content": title or meeting_id}}]},
                       "Date": {"date": {"start": datetime.utcnow().isoformat()}},
                       "Status": {"select": {"name": "Processed"}}},
        "children": blocks}
    resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
    return resp.json().get("id") if resp.status_code == 200 else None


def extract_title(summary: str) -> str:
    for line in summary.strip().split("\n"):
        line = line.strip()
        if line.startswith("# ") or line.startswith("**Meeting Title"):
            return line.lstrip("#* ").strip()
    return "Untitled Meeting"


@app.post("/upload")
async def upload_meeting(file: UploadFile = File(...)):
    allowed = ["audio/mpeg", "audio/wav", "audio/mp4", "video/mp4", "audio/webm", "video/webm"]
    # TODO: validate content type properly — browsers sometimes send wrong MIME
    if file.content_type and file.content_type not in allowed:
        raise HTTPException(400, f"Unsupported: {file.content_type}")

    meeting_id = f"MTG-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    suffix = os.path.splitext(file.filename)[1] if file.filename else ".mp3"
    temp_path = os.path.join(tempfile.gettempdir(), f"{meeting_id}{suffix}")
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 100MB)")
    with open(temp_path, "wb") as f:
        f.write(content)

    # TODO: use Celery for async processing
    transcript = transcribe_audio(temp_path)
    summary = summarize_transcript(transcript)
    title = extract_title(summary)
    slack_ok = post_to_slack(summary, meeting_id)
    notion_id = create_notion_page(summary, meeting_id, title)
    if os.path.exists(temp_path): os.remove(temp_path)

    return {"meeting_id": meeting_id, "title": title, "transcript_words": len(transcript.split()),
            "slack_posted": slack_ok, "notion_page_id": notion_id,
            "processed_at": datetime.utcnow().isoformat()}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "meeting-notes-summarizer"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8047, debug=True)
