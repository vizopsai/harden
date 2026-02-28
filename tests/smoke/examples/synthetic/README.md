# Synthetic Test Apps

This directory contains 30 synthetic "vibe-coded" Python applications that simulate realistic apps built quickly with AI assistants. These apps contain common security and configuration issues for testing the harden CLI tool.

## App Overview

### App 01: fastapi_openai_basic
FastAPI + OpenAI chat completion API
- **Security Issues**: Hardcoded API key in source code
- **Main File**: main.py
- **Stack**: FastAPI, OpenAI
- **Port**: 8000

### App 02: flask_anthropic_chatbot
Flask + Anthropic Claude chatbot
- **Security Issues**: .env file not in .gitignore, API key exposed
- **Main File**: app.py
- **Stack**: Flask, Anthropic
- **Port**: 5000

### App 03: streamlit_langchain_rag
Streamlit + LangChain RAG application
- **Security Issues**: API key in .streamlit/secrets.toml
- **Main File**: app.py
- **Stack**: Streamlit, LangChain, FAISS, OpenAI
- **Run**: `streamlit run app.py`

### App 04: gradio_huggingface_image
Gradio + HuggingFace image classification
- **Security Issues**: HF_TOKEN in environment
- **Main File**: app.py
- **Stack**: Gradio, Transformers, PyTorch
- **Port**: 7860

### App 05: django_postgres_crud
Django + PostgreSQL CRUD API
- **Security Issues**: Hardcoded database password, SECRET_KEY in settings.py
- **Main File**: manage.py
- **Stack**: Django, PostgreSQL, psycopg2
- **Port**: 8000

### App 06: fastapi_stripe_payments
FastAPI + Stripe payments integration
- **Security Issues**: Stripe keys in .env file
- **Main File**: main.py
- **Stack**: FastAPI, Stripe
- **Port**: 8000

### App 07: flask_aws_s3_upload
Flask + AWS S3 file upload service
- **Security Issues**: Hardcoded AWS credentials in source code
- **Main File**: app.py
- **Stack**: Flask, boto3
- **Port**: 5000

### App 08: fastapi_redis_cache
FastAPI + Redis caching layer
- **Security Issues**: Hardcoded Redis password, internal hostname exposed
- **Main File**: main.py
- **Stack**: FastAPI, Redis
- **Port**: 8000

### App 09: streamlit_cohere_summarizer
Streamlit + Cohere text summarization
- **Security Issues**: Cohere API key in .env file
- **Main File**: app.py
- **Stack**: Streamlit, Cohere
- **Run**: `streamlit run app.py`

### App 10: fastapi_multi_ai
FastAPI + Multiple AI providers (OpenAI, Anthropic, Google)
- **Security Issues**: Multiple API keys in .env file
- **Main File**: main.py
- **Stack**: FastAPI, OpenAI, Anthropic, Google Generative AI
- **Port**: 8000

### App 11: fastapi_mongodb_api
FastAPI + MongoDB CRUD REST API
- **Security Issues**: Hardcoded MongoDB connection string with credentials, no auth on delete
- **Main File**: main.py
- **Stack**: FastAPI, PyMongo
- **Port**: 8000
- **Lines**: 118

### App 12: flask_sqlalchemy_blog
Flask + SQLAlchemy blog application
- **Security Issues**: SQL injection in search, debug mode enabled, no authentication
- **Main File**: app.py
- **Stack**: Flask, SQLAlchemy, SQLite
- **Port**: 5000
- **Lines**: 141

### App 13: fastapi_elasticsearch_search
FastAPI + Elasticsearch search service
- **Security Issues**: Hardcoded Elasticsearch API key, no auth on deletion
- **Main File**: main.py
- **Stack**: FastAPI, Elasticsearch
- **Port**: 8000
- **Lines**: 162

### App 14: flask_celery_worker
Flask + Celery background task processing
- **Security Issues**: Hardcoded Redis URL, SSRF vulnerability, no rate limiting
- **Main File**: app.py, tasks.py
- **Stack**: Flask, Celery, Redis, Requests
- **Port**: 5000
- **Lines**: 159 total

### App 15: fastapi_kafka_producer
FastAPI + Kafka event producer
- **Security Issues**: No Kafka authentication, missing rate limiting, hardcoded brokers
- **Main File**: main.py
- **Stack**: FastAPI, Kafka
- **Port**: 8000
- **Lines**: 170

### App 16: streamlit_diffusers_art
Streamlit + Stable Diffusion image generation
- **Security Issues**: HuggingFace token in plaintext secrets, no content filtering
- **Main File**: app.py
- **Stack**: Streamlit, Diffusers, Torch
- **Run**: `streamlit run app.py`
- **Lines**: 148

### App 17: fastapi_gcp_storage
FastAPI + Google Cloud Storage file service
- **Security Issues**: Hardcoded service account path, no file validation, path traversal
- **Main File**: main.py
- **Stack**: FastAPI, google-cloud-storage
- **Port**: 8000
- **Lines**: 166

### App 18: flask_azure_blob
Flask + Azure Blob Storage file management
- **Security Issues**: Connection string in .env, no authentication, debug mode
- **Main File**: app.py
- **Stack**: Flask, azure-storage-blob
- **Port**: 5000
- **Lines**: 177

### App 19: fastapi_together_ai
FastAPI + Together AI LLM inference
- **Security Issues**: API key in .env, no rate limiting, prompt injection risks
- **Main File**: main.py
- **Stack**: FastAPI, Together AI
- **Port**: 8000
- **Lines**: 167

### App 20: flask_msal_graph
Flask + Microsoft Graph API integration
- **Security Issues**: Client secret in .env, weak Flask secret, no CSRF protection
- **Main File**: app.py
- **Stack**: Flask, MSAL, Microsoft Graph
- **Port**: 5000
- **Lines**: 184

## Common Security Issues

All apps contain one or more of these realistic security issues:

1. **Hardcoded Secrets**: API keys, passwords directly in source code
2. **Exposed .env Files**: .env files not properly gitignored
3. **Unpinned Dependencies**: requirements.txt without version numbers
4. **Missing .gitignore**: No .gitignore or incomplete entries
5. **CSRF Disabled**: Security features disabled "for now"
6. **Debug Mode**: Debug=True in production-like code
7. **Weak Authentication**: TODO comments about adding auth
8. **Internal Hostnames**: Exposed internal infrastructure details

## Usage

Each app can be analyzed with the harden CLI:

```bash
# Analyze a single app
cd app01_fastapi_openai_basic
harden analyze

# Generate security artifacts
harden generate --all
```

## Characteristics of "Vibe-Coded" Apps

These apps exhibit typical patterns of AI-assisted rapid development:

- Minimal error handling with TODO comments
- Comments like "works fine for now" and "will add later"
- Security features disabled or postponed
- Unpinned dependencies
- Mix of environment variables and hardcoded values
- Basic functionality works but lacks production hardening
- No comprehensive .gitignore files
