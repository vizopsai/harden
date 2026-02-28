# Harden Test Plan

Test cases that verify the harden CLI produces correct, complete, and secure
artifacts. These tests exercise the gaps identified in `../northstar/05_gap_analysis.md`.

## Test Structure

| File | What it tests | Gaps covered |
|------|--------------|-------------|
| `test_equivalence.py` | Golden set capture, replay, comparison with external deps | GAP-1 |
| `test_negative_security.py` | Hardening controls actually block things | GAP-6 |
| `test_policy_generation.py` | Policy derived from analysis + profiling is correct | GAP-2, GAP-11 |
| `test_breakglass.py` | Breakglass mechanism activates and deactivates correctly | GAP-4 |
| `test_fail_modes.py` | Each component fails in the documented mode | GAP-5 |
| `test_credential_rotation.py` | Health checks detect expired credentials | GAP-9 |
| `test_day2_reharden.py` | Re-running pipeline after code changes works correctly | GAP-12 |
| `test_log_integrity.py` | Enforcement logs are separate from app logs | GAP-10 |
| `test_monitoring.py` | OTel metrics are emitted correctly | GAP-8 |
| `test_generated_artifacts.py` | Generated Dockerfile, compose, k8s manifests are valid | All |
| `test_ai_enhance.py` | AI-powered audit and fix of generated artifacts | GAP-20 |
| `conftest.py` | Shared fixtures (sample apps, temp dirs, mock servers) | - |

## Running Tests

```bash
# All tests (unit + integration)
pytest tests/ -v

# Just unit tests (no containers needed)
pytest tests/ -v -m "not integration"

# Just integration tests (requires Docker)
pytest tests/ -v -m integration

# Specific gap
pytest tests/test_breakglass.py -v
```

## Fixtures

- `tests/fixtures/fastapi_salesforce/` — Canonical vibe-coded app
  (FastAPI + Salesforce + OpenAI + Microsoft Graph)

## Test Categories

- **Unit**: Tests that verify logic in isolation (policy generation, schema
  comparison, cassette matching). No external services needed.
- **Integration** (marked `@pytest.mark.integration`): Tests that build
  containers, start processes, or hit network. Require Docker.
