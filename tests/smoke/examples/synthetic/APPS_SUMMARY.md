# Synthetic Test Apps Summary

This directory contains 10 realistic "vibe-coded" Python applications for testing the harden CLI.

## Apps Created

### App 21: monorepo_fullstack
**Path:** `/Users/p/w/vx/expt/sre_reading/test_apps/synthetic/app21_monorepo_fullstack/`

Monorepo with backend/ and frontend/ subdirectories
- backend/main.py: FastAPI app with /api/users, /api/chat endpoints
- backend/requirements.txt: fastapi, uvicorn, openai, sqlalchemy
- backend/.env: DATABASE_URL, OPENAI_API_KEY
- frontend/package.json: placeholder
- README.md at root

**External Services:** PostgreSQL, OpenAI
**Secrets:** OPENAI_API_KEY=your-openai-api-key-here

---

### App 22: fastapi_microservice_auth
**Path:** `/Users/p/w/vx/expt/sre_reading/test_apps/synthetic/app22_fastapi_microservice_auth/`

Microservice with JWT auth
- main.py: FastAPI with /login, /protected endpoints
- Uses PyJWT with hardcoded SECRET_KEY = "super-secret-jwt-key-do-not-share"
- Calls external auth service: https://auth.company.com/verify
- requirements.txt: fastapi, uvicorn, pyjwt, requests, passlib

**External Services:** https://auth.company.com/verify
**Secrets:** Hardcoded SECRET_KEY in source code

---

### App 23: cli_data_pipeline
**Path:** `/Users/p/w/vx/expt/sre_reading/test_apps/synthetic/app23_cli_data_pipeline/`

CLI tool (not a web app) using click + OpenAI
- pipeline.py: Click CLI with @click.command() that reads CSV, sends to OpenAI
- import click, import openai, import pandas
- OPENAI_API_KEY from env
- requirements.txt: click, openai, pandas

**Type:** CLI (no web server)
**External Services:** OpenAI
**Secrets:** OPENAI_API_KEY from environment

---

### App 24: fastapi_websocket_chat
**Path:** `/Users/p/w/vx/expt/sre_reading/test_apps/synthetic/app24_fastapi_websocket_chat/`

WebSocket chat with AI
- main.py: FastAPI with WebSocket /ws endpoint
- Uses openai for responses
- Async handlers with asyncio
- requirements.txt: fastapi, uvicorn, openai, websockets

**External Services:** OpenAI
**Secrets:** OPENAI_API_KEY from environment

---

### App 25: flask_rabbitmq_notifications
**Path:** `/Users/p/w/vx/expt/sre_reading/test_apps/synthetic/app25_flask_rabbitmq_notifications/`

Flask + RabbitMQ + SendGrid email
- app.py: Flask with /notify endpoint
- Uses pika to publish to RabbitMQ
- Uses SendGrid API for emails
- .env: SENDGRID_API_KEY, RABBITMQ_URL
- requirements.txt: flask, pika, requests

**External Services:** RabbitMQ, SendGrid (https://api.sendgrid.com/v3/mail/send)
**Secrets:** SENDGRID_API_KEY=your-sendgrid-api-key-here

---

### App 26: gradio_langchain_agent
**Path:** `/Users/p/w/vx/expt/sre_reading/test_apps/synthetic/app26_gradio_langchain_agent/`

Gradio + LangChain agent with tools
- app.py: Gradio chat interface backed by LangChain AgentExecutor
- from langchain.agents import initialize_agent, Tool
- from langchain_openai import ChatOpenAI
- from langchain_community.tools import DuckDuckGoSearchRun
- requirements.txt: gradio, langchain, langchain-openai, langchain-community, duckduckgo-search

**External Services:** OpenAI, DuckDuckGo (search)
**Secrets:** OPENAI_API_KEY from environment

---

### App 27: fastapi_multi_db
**Path:** `/Users/p/w/vx/expt/sre_reading/test_apps/synthetic/app27_fastapi_multi_db/`

FastAPI using both PostgreSQL and Redis
- main.py: /users (postgres), /cache (redis), /health endpoints
- Uses psycopg2 and redis
- DATABASE_URL and REDIS_URL in .env
- requirements.txt: fastapi, uvicorn, psycopg2-binary, redis

**External Services:** PostgreSQL, Redis
**Secrets:** DATABASE_URL, REDIS_URL in .env

---

### App 28: streamlit_pandas_gsheet
**Path:** `/Users/p/w/vx/expt/sre_reading/test_apps/synthetic/app28_streamlit_pandas_gsheet/`

Streamlit + Google Sheets data viz
- app.py: Streamlit dashboard reading from Google Sheets API
- Uses requests.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range}", params={"key": GOOGLE_API_KEY})
- GOOGLE_API_KEY hardcoded as AIzaSyFakeKeyHere1234567890abcdefghij
- requirements.txt: streamlit, pandas, requests

**External Services:** Google Sheets API
**Secrets:** GOOGLE_API_KEY=AIzaSyFakeKeyHere1234567890abcdefghij (hardcoded in source)

---

### App 29: fastapi_salesforce_hubspot
**Path:** `/Users/p/w/vx/expt/sre_reading/test_apps/synthetic/app29_fastapi_salesforce_hubspot/`

FastAPI CRM integration
- main.py: /leads (Salesforce), /contacts (HubSpot) endpoints
- from simple_salesforce import Salesforce
- Uses hubspot SDK
- .env: SALESFORCE_TOKEN, HUBSPOT_API_KEY
- requirements.txt: fastapi, uvicorn, simple-salesforce, hubspot-api-client

**External Services:** Salesforce, HubSpot
**Secrets:** SALESFORCE_TOKEN=fake-security-token-abcdefg, HUBSPOT_API_KEY=fake-hubspot-key-12345678

---

### App 30: flask_bigquery_dashboard
**Path:** `/Users/p/w/vx/expt/sre_reading/test_apps/synthetic/app30_flask_bigquery_dashboard/`

Flask + BigQuery analytics
- app.py: Flask dashboard with /analytics endpoint
- from google.cloud import bigquery
- GOOGLE_APPLICATION_CREDENTIALS path hardcoded
- Also uses https://api.exchangerate-api.com/v4/latest/USD
- requirements.txt: flask, google-cloud-bigquery, requests

**External Services:** Google BigQuery, Exchange Rate API (https://api.exchangerate-api.com)
**Secrets:** GOOGLE_APPLICATION_CREDENTIALS path

---

## Characteristics

All apps feature:
- Realistic "vibe-coded" style with comments like "this works for now"
- TODO comments for future improvements
- Mix of hardcoded secrets and environment variables
- External service dependencies
- Between 50-150 lines of Python code
- Valid Python syntax
- requirements.txt files with specific versions

## Testing the harden CLI

These apps can be used to test the harden analyzer's ability to detect:
- External service dependencies
- Hardcoded secrets and credentials
- Database connections
- API endpoints
- Environment variables
- Third-party service integrations
