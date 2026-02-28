# Synthetic Test Apps - Complete Overview

## Purpose

This collection of 10 synthetic Python applications simulates realistic "vibe-coded" apps built quickly with AI assistants like Claude or ChatGPT. Each app contains intentional security vulnerabilities and configuration issues typical of rapid prototyping, making them ideal for testing the `harden` CLI tool.

## Quick Start

```bash
# Analyze a single app
cd app01_fastapi_openai_basic
harden analyze

# Test all apps
./test_all_apps.sh

# Generate artifacts for an app
cd app05_django_postgres_crud
harden generate --all
```

## App Catalog

| # | Name | Framework | Lines | Key Security Issues |
|---|------|-----------|-------|---------------------|
| 01 | fastapi_openai_basic | FastAPI + OpenAI | 71 | Hardcoded API key, no .gitignore |
| 02 | flask_anthropic_chatbot | Flask + Anthropic | 104 | .env exposed, debug mode |
| 03 | streamlit_langchain_rag | Streamlit + LangChain | 88 | Secrets in repo, unpinned deps |
| 04 | gradio_huggingface_image | Gradio + HuggingFace | 107 | Missing auth, unpinned deps |
| 05 | django_postgres_crud | Django + PostgreSQL | 246 | Hardcoded DB password, CSRF off |
| 06 | fastapi_stripe_payments | FastAPI + Stripe | 154 | Keys in .env, no .gitignore |
| 07 | flask_aws_s3_upload | Flask + AWS S3 | 142 | Hardcoded AWS credentials |
| 08 | fastapi_redis_cache | FastAPI + Redis | 190 | Hardcoded Redis password |
| 09 | streamlit_cohere_summarizer | Streamlit + Cohere | 131 | API key in .env |
| 10 | fastapi_multi_ai | FastAPI + Multi-AI | 208 | Multiple API keys in .env |

**Total Lines of Code**: 1,441

## Frameworks Covered

- **FastAPI**: 6 apps (01, 06, 08, 10)
- **Flask**: 2 apps (02, 07)
- **Streamlit**: 2 apps (03, 09)
- **Gradio**: 1 app (04)
- **Django**: 1 app (05)

## AI Providers Tested

- OpenAI (apps 01, 03, 10)
- Anthropic Claude (apps 02, 10)
- Cohere (app 09)
- Google Gemini (app 10)
- HuggingFace (app 04)

## Security Issue Categories

### 1. Hardcoded Secrets (6 apps)
- **App 01**: OpenAI API key in main.py
- **App 05**: Django SECRET_KEY and DB password in settings.py
- **App 07**: AWS credentials in app.py
- **App 08**: Redis password in main.py

### 2. Secrets in .env Files (5 apps)
- **App 02**: Anthropic API key
- **App 06**: Stripe keys
- **App 09**: Cohere API key
- **App 10**: Multiple AI provider keys

### 3. Secrets in Config Files (1 app)
- **App 03**: OpenAI key in .streamlit/secrets.toml

### 4. Missing or Incomplete .gitignore (7 apps)
- **Apps 01, 06, 07, 08, 09, 10**: No .gitignore
- **App 02**: .gitignore exists but doesn't include .env

### 5. Unpinned Dependencies (10 apps)
All apps have unpinned requirements.txt

### 6. Debug Mode Enabled (3 apps)
- **App 02**: Flask debug=True
- **App 05**: Django DEBUG=True
- **App 07**: Flask debug=True

### 7. Missing Authentication (3 apps)
- **App 04**: TODO comment about auth
- **App 08**: Admin endpoint without auth
- **App 10**: /compare endpoint without auth

### 8. Security Features Disabled (1 app)
- **App 05**: CSRF exempt decorator

### 9. Insecure Configurations (2 apps)
- **App 05**: ALLOWED_HOSTS = ['*']
- **App 08**: Internal hostname exposed

## Expected Harden CLI Detections

When running `harden analyze` on these apps, the tool should detect:

### Secret Detection
- [x] API key patterns: `sk-*`, `sk-ant-*`, `AIza*`, `AKIA*`
- [x] Hardcoded passwords in source code
- [x] Connection strings with embedded credentials
- [x] Django SECRET_KEY
- [x] Stripe API keys and webhook secrets

### Configuration Issues
- [x] .env files not in .gitignore
- [x] Secrets files committed to repo
- [x] Debug mode enabled
- [x] CSRF protection disabled
- [x] Missing authentication on sensitive endpoints
- [x] Wildcard host configurations

### Dependency Issues
- [x] Unpinned dependencies in requirements.txt
- [x] Known vulnerable packages (if any)

### Infrastructure Exposure
- [x] Internal hostnames in code
- [x] Database connection details
- [x] Cloud provider configurations

## Realistic "Vibe-Code" Patterns

These apps exhibit authentic patterns of AI-assisted development:

### Code Comments
- "TODO: move to environment variable"
- "works fine for now"
- "will add auth later"
- "add proper error handling"
- "add proper logging"

### Development Practices
- Minimal error handling with try/except pass
- Security features postponed with TODOs
- Mix of environment variables and hardcoded values
- Basic functionality without production hardening
- Debug mode left enabled
- No comprehensive .gitignore files

### Common Shortcuts
- Hardcoded credentials "for testing"
- CSRF disabled "temporarily"
- Auth marked as "TODO"
- Unpinned dependencies
- Wildcard configurations

## File Structure Examples

### Simple App (App 01)
```
app01_fastapi_openai_basic/
├── main.py
└── requirements.txt
```

### App with Secrets (App 02)
```
app02_flask_anthropic_chatbot/
├── app.py
├── .env (not in .gitignore!)
├── .gitignore (incomplete)
└── requirements.txt
```

### Complex App (App 05)
```
app05_django_postgres_crud/
├── manage.py
├── myapp/
│   ├── __init__.py
│   ├── settings.py (hardcoded secrets)
│   ├── urls.py
│   ├── views.py
│   ├── models.py
│   └── wsgi.py
└── requirements.txt
```

## Testing Workflow

1. **Individual App Analysis**
   ```bash
   cd app01_fastapi_openai_basic
   harden analyze
   ```

2. **Generate Security Artifacts**
   ```bash
   harden generate --dockerfile
   harden generate --k8s
   harden generate --gitignore
   ```

3. **Batch Testing**
   ```bash
   ./test_all_apps.sh
   ```

4. **Verify Detections**
   Check against SECURITY_ISSUES.md for expected findings

## Key Files

- **README.md**: App descriptions and usage
- **SECURITY_ISSUES.md**: Detailed vulnerability catalog
- **OVERVIEW.md**: This file - comprehensive guide
- **test_all_apps.sh**: Automated testing script

## Validation Checklist

When testing the harden CLI, verify it:

- [ ] Detects all 6 types of hardcoded API keys
- [ ] Identifies database credentials in config files
- [ ] Flags .env files not in .gitignore
- [ ] Detects committed secrets files
- [ ] Reports unpinned dependencies (all 10 apps)
- [ ] Warns about debug mode (3 apps)
- [ ] Identifies missing authentication (3 apps)
- [ ] Detects CSRF protection issues (1 app)
- [ ] Flags wildcard host configurations (1 app)
- [ ] Reports internal hostname exposure (1 app)

## Statistics

- **Total Apps**: 10
- **Total Python Files**: 23
- **Total Lines of Code**: 1,441
- **Average Lines per App**: 144
- **Range**: 71-246 lines
- **Security Issues per App**: 3-6
- **Total Known Issues**: 43

## Usage Notes

1. These apps are intentionally insecure for testing purposes
2. All API keys are fake and non-functional
3. Apps may not run without proper dependencies and services
4. Focus is on static analysis, not runtime behavior
5. Patterns simulate real-world AI-assisted development

## Next Steps

After testing with these apps:

1. Verify all expected issues are detected
2. Check for false positives
3. Test artifact generation (Dockerfile, K8s, etc.)
4. Validate recommendations are actionable
5. Ensure output is clear and helpful

## Contributing

To add more test apps:

1. Follow the naming convention: `appNN_description`
2. Keep code between 50-250 lines
3. Include realistic security issues
4. Add "vibe-code" comments
5. Update README.md and SECURITY_ISSUES.md
6. Test with harden CLI
