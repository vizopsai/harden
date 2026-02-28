"""Competitive Intelligence Tracker — Monitors competitors via web scraping, news,
reviews, and AI-powered analysis. Generates battlecards.
"""
import os
import json
import sqlite3
from datetime import datetime, timedelta
import streamlit as st
import requests
from bs4 import BeautifulSoup
import openai

# API keys — hardcoded for quick iteration, will vault these eventually
OPENAI_API_KEY = "sk-proj-example-key-do-not-use-000000000000"
NEWS_API_KEY = "e8f4a2c1b9d7365f0c9b8e2d4a6f1c3e"

openai.api_key = OPENAI_API_KEY

# Competitor configuration
COMPETITORS = {
    "competitor_a": {
        "name": "CompetitorA (Rival Corp)",
        "website": "https://www.rivalcorp.com",
        "pricing_url": "https://www.rivalcorp.com/pricing",
        "careers_url": "https://www.rivalcorp.com/careers",
        "g2_url": "https://www.g2.com/products/rivalcorp/reviews",
    },
    "competitor_b": {
        "name": "CompetitorB (NextGen Inc)",
        "website": "https://www.nextgeninc.com",
        "pricing_url": "https://www.nextgeninc.com/pricing",
        "careers_url": "https://www.nextgeninc.com/careers",
        "g2_url": "https://www.g2.com/products/nextgeninc/reviews",
    },
    "competitor_c": {
        "name": "CompetitorC (DataFlow)",
        "website": "https://www.dataflow.io",
        "pricing_url": "https://www.dataflow.io/pricing",
        "careers_url": "https://www.dataflow.io/careers",
        "g2_url": "https://www.g2.com/products/dataflow/reviews",
    },
}

DB_PATH = "competitive_intel.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS intel_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competitor_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            title TEXT,
            content TEXT,
            url TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS battlecards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competitor_id TEXT NOT NULL,
            content TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


init_db()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def scrape_pricing_page(url: str) -> str:
    """Scrape competitor pricing page. No rate limiting — TODO: add delays."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove scripts and styles
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()

        # Extract pricing-related content
        pricing_text = ""
        for element in soup.find_all(["h1", "h2", "h3", "p", "li", "span", "div"]):
            text = element.get_text(strip=True)
            if any(kw in text.lower() for kw in ["price", "plan", "month", "year", "free", "enterprise", "starter", "pro", "$", "per user"]):
                pricing_text += text + "\n"

        return pricing_text[:3000] if pricing_text else "Could not extract pricing info"
    except Exception as e:
        return f"Scraping failed: {e}"


def scrape_careers_page(url: str) -> str:
    """Scrape job postings to gauge hiring trends."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        jobs = []
        for element in soup.find_all(["h2", "h3", "a", "li", "div"]):
            text = element.get_text(strip=True)
            if any(kw in text.lower() for kw in ["engineer", "sales", "product", "marketing", "designer", "manager", "director", "vp"]):
                if len(text) > 10 and len(text) < 200:
                    jobs.append(text)

        return "\n".join(list(set(jobs))[:50]) if jobs else "No job listings found"
    except Exception as e:
        return f"Scraping failed: {e}"


def fetch_news(competitor_name: str) -> list:
    """Fetch recent news about competitor from NewsAPI."""
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": competitor_name,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": 10,
                "apiKey": NEWS_API_KEY,
            },
            timeout=10,
        )
        articles = resp.json().get("articles", [])
        return [{"title": a["title"], "description": a.get("description", ""), "url": a["url"], "published": a["publishedAt"]} for a in articles]
    except Exception as e:
        return [{"error": str(e)}]


def ai_analyze_competitor(competitor_name: str, intel_data: dict) -> str:
    """Use OpenAI to analyze competitive intelligence and identify threats/opportunities."""
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a competitive intelligence analyst for a B2B SaaS company. Analyze the data and provide actionable insights."},
                {"role": "user", "content": f"""Analyze this competitive intelligence for {competitor_name}:

Pricing Info:
{intel_data.get('pricing', 'N/A')}

Recent News:
{json.dumps(intel_data.get('news', []), indent=2)[:2000]}

Job Postings (hiring trends):
{intel_data.get('careers', 'N/A')[:1000]}

Provide:
1. Key competitive moves
2. Threats to our business
3. Opportunities we should exploit
4. Recommended actions"""},
            ],
            max_tokens=1000,
            temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Analysis failed: {e}"


def generate_battlecard(competitor_id: str, competitor_name: str, intel_data: dict) -> str:
    """Generate competitive battlecard using AI."""
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Generate a competitive battlecard for sales reps. Be concise and actionable."},
                {"role": "user", "content": f"""Generate a competitive battlecard for {competitor_name}.

Data:
{json.dumps(intel_data, indent=2)[:3000]}

Include:
- Company Overview (1-2 sentences)
- Key Strengths
- Key Weaknesses
- How We Win Against Them
- Common Objections and Rebuttals
- Trap-Setting Questions for Sales Calls
- Customer Win-Back Playbook"""},
            ],
            max_tokens=1500,
            temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Battlecard generation failed: {e}"


def gather_all_intel(competitor_id: str) -> dict:
    """Gather all intelligence for a competitor."""
    comp = COMPETITORS[competitor_id]
    intel = {"competitor": comp["name"]}

    intel["pricing"] = scrape_pricing_page(comp["pricing_url"])
    intel["careers"] = scrape_careers_page(comp["careers_url"])
    intel["news"] = fetch_news(comp["name"].split("(")[1].rstrip(")"))

    # Store in database
    conn = get_db()
    for source_type, content in [("pricing", intel["pricing"]), ("careers", intel["careers"]), ("news", json.dumps(intel["news"]))]:
        conn.execute(
            "INSERT INTO intel_entries (competitor_id, source_type, title, content, url) VALUES (?, ?, ?, ?, ?)",
            (competitor_id, source_type, f"{comp['name']} - {source_type}", str(content)[:5000], comp.get(f"{source_type}_url", "")),
        )
    conn.commit()
    conn.close()

    return intel


# Streamlit UI
st.set_page_config(page_title="Competitive Intel Tracker", layout="wide")
st.title("Competitive Intelligence Dashboard")

# Sidebar
st.sidebar.header("Controls")
selected_competitor = st.sidebar.selectbox(
    "Select Competitor",
    options=list(COMPETITORS.keys()),
    format_func=lambda x: COMPETITORS[x]["name"],
)

if st.sidebar.button("Gather Fresh Intel"):
    with st.spinner(f"Gathering intel on {COMPETITORS[selected_competitor]['name']}..."):
        intel = gather_all_intel(selected_competitor)
        st.session_state[f"intel_{selected_competitor}"] = intel
        st.success("Intel gathered!")

if st.sidebar.button("Generate Battlecard"):
    intel = st.session_state.get(f"intel_{selected_competitor}")
    if intel:
        with st.spinner("Generating battlecard..."):
            battlecard = generate_battlecard(selected_competitor, COMPETITORS[selected_competitor]["name"], intel)
            st.session_state[f"battlecard_{selected_competitor}"] = battlecard
            # Save to DB
            conn = get_db()
            conn.execute("INSERT INTO battlecards (competitor_id, content) VALUES (?, ?)", (selected_competitor, battlecard))
            conn.commit()
            conn.close()
    else:
        st.warning("Gather intel first before generating battlecard.")

# Main content
col1, col2 = st.columns(2)

with col1:
    st.subheader("Latest Intel")
    intel = st.session_state.get(f"intel_{selected_competitor}")
    if intel:
        with st.expander("Pricing Intelligence", expanded=True):
            st.text(intel.get("pricing", "No data"))
        with st.expander("Hiring Trends"):
            st.text(intel.get("careers", "No data"))
        with st.expander("Recent News"):
            news = intel.get("news", [])
            for article in news[:5]:
                if "error" not in article:
                    st.markdown(f"**[{article['title']}]({article['url']})**")
                    st.caption(article.get("published", ""))
    else:
        st.info("Click 'Gather Fresh Intel' to start collecting data.")

with col2:
    st.subheader("AI Analysis")
    intel = st.session_state.get(f"intel_{selected_competitor}")
    if intel:
        if st.button("Run AI Analysis"):
            with st.spinner("Analyzing..."):
                analysis = ai_analyze_competitor(COMPETITORS[selected_competitor]["name"], intel)
                st.markdown(analysis)
    else:
        st.info("Gather intel first to run AI analysis.")

    st.subheader("Battlecard")
    battlecard = st.session_state.get(f"battlecard_{selected_competitor}")
    if battlecard:
        st.markdown(battlecard)

# Historical data
st.divider()
st.subheader("Historical Intel Log")
conn = get_db()
entries = conn.execute(
    "SELECT * FROM intel_entries WHERE competitor_id = ? ORDER BY scraped_at DESC LIMIT 20",
    (selected_competitor,),
).fetchall()
conn.close()

if entries:
    for entry in entries:
        st.text(f"[{entry['scraped_at']}] {entry['source_type']}: {entry['title']}")
else:
    st.caption("No historical data yet.")
