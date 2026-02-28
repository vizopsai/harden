# Security Issues Reference

This document catalogs all intentional security issues in the synthetic test apps for testing the harden CLI.

## App 01: fastapi_openai_basic

**File**: `main.py`

| Issue Type | Location | Details |
|------------|----------|---------|
| Hardcoded API Key | Line 11 | `OPENAI_API_KEY = "sk-fake-key-..."` |
| Unpinned Dependencies | requirements.txt | No version pins |
| Missing .gitignore | N/A | No .gitignore file |

## App 02: flask_anthropic_chatbot

**File**: `app.py`

| Issue Type | Location | Details |
|------------|----------|---------|
| API Key in .env | .env | `ANTHROPIC_API_KEY=sk-ant-fake-key...` |
| .env Not Gitignored | .gitignore | .env missing from .gitignore |
| Unpinned Dependencies | requirements.txt | No version pins |
| Debug Mode | Line 104 | `debug=True` in production-like code |

## App 03: streamlit_langchain_rag

**File**: `app.py`

| Issue Type | Location | Details |
|------------|----------|---------|
| API Key in Secrets | .streamlit/secrets.toml | `openai_api_key = "sk-fake-..."` |
| Unpinned Dependencies | requirements.txt | No version pins |
| Secrets File in Repo | .streamlit/secrets.toml | Committed secrets file |

## App 04: gradio_huggingface_image

**File**: `app.py`

| Issue Type | Location | Details |
|------------|----------|---------|
| Token from Environment | Line 12 | `HF_TOKEN = os.getenv("HF_TOKEN", "")` with no validation |
| Unpinned Dependencies | requirements.txt | No version pins |
| Missing Auth | Line 102 | TODO comment about auth |

## App 05: django_postgres_crud

**File**: `myapp/settings.py`

| Issue Type | Location | Details |
|------------|----------|---------|
| Hardcoded SECRET_KEY | Line 11 | Django SECRET_KEY in source |
| Hardcoded DB Password | Line 66 | `'PASSWORD': 'postgres123'` |
| Debug Mode | Line 15 | `DEBUG = True` |
| ALLOWED_HOSTS Wildcard | Line 17 | `ALLOWED_HOSTS = ['*']` |
| CSRF Exempt | views.py:51 | `@csrf_exempt` decorator |
| Unpinned Dependencies | requirements.txt | No version pins |

## App 06: fastapi_stripe_payments

**File**: `main.py`

| Issue Type | Location | Details |
|------------|----------|---------|
| Stripe Keys in .env | .env | Secret and webhook keys exposed |
| .env Not Gitignored | N/A | Missing .gitignore |
| Unpinned Dependencies | requirements.txt | No version pins |

## App 07: flask_aws_s3_upload

**File**: `app.py`

| Issue Type | Location | Details |
|------------|----------|---------|
| Hardcoded AWS Keys | Lines 13-14 | `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` |
| S3 Bucket Name | Line 16 | Hardcoded bucket name |
| Debug Mode | Line 142 | `debug=True` |
| Unpinned Dependencies | requirements.txt | No version pins |
| Missing .gitignore | N/A | No .gitignore file |

## App 08: fastapi_redis_cache

**File**: `main.py`

| Issue Type | Location | Details |
|------------|----------|---------|
| Hardcoded Redis Password | Line 21 | `password="secret123"` |
| Internal Hostname | Line 19 | `redis.internal.company.com` exposed |
| Unpinned Dependencies | requirements.txt | No version pins |
| Missing Auth on Admin Endpoint | Line 113 | `/cache` DELETE endpoint TODO |
| Missing .gitignore | N/A | No .gitignore file |

## App 09: streamlit_cohere_summarizer

**File**: `app.py`

| Issue Type | Location | Details |
|------------|----------|---------|
| API Key in .env | .env | `COHERE_API_KEY=fake-cohere-key...` |
| .env Not Gitignored | N/A | Missing .gitignore |
| Unpinned Dependencies | requirements.txt | No version pins |

## App 10: fastapi_multi_ai

**File**: `main.py`

| Issue Type | Location | Details |
|------------|----------|---------|
| Multiple API Keys in .env | .env | OpenAI, Anthropic, Google keys |
| .env Not Gitignored | N/A | Missing .gitignore |
| Unpinned Dependencies | requirements.txt | No version pins |
| Missing Auth on /compare | Line 140 | TODO comment about auth |

## Summary Statistics

- **Total Apps**: 10
- **Hardcoded Secrets**: 6 apps (01, 05, 07, 08)
- **Secrets in .env**: 5 apps (02, 06, 09, 10)
- **Secrets in Config Files**: 1 app (03)
- **Missing .gitignore**: 6 apps (01, 06, 07, 08, 09, 10)
- **.env Not Gitignored**: 1 app (02)
- **Unpinned Dependencies**: 10 apps (all)
- **Debug Mode Enabled**: 3 apps (02, 05, 07)
- **Missing Auth**: 3 apps (04, 08, 10)
- **CSRF Disabled**: 1 app (05)

## Testing Checklist

When testing harden CLI, verify it detects:

- [ ] Hardcoded API keys (sk-*, sk-ant-*, AIza*, AKIA*)
- [ ] Database passwords in config files
- [ ] Django SECRET_KEY
- [ ] AWS credentials
- [ ] Redis passwords
- [ ] .env files not in .gitignore
- [ ] Secrets files committed to repo
- [ ] Unpinned dependencies
- [ ] Debug mode in production
- [ ] Missing authentication
- [ ] CSRF protection disabled
- [ ] Internal hostnames exposed
- [ ] Wildcard ALLOWED_HOSTS
