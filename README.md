# Harden (OSS Core)

Minimal open‑source subset of Harden. It **only** provides:
- `analyze` — static risk report
- `lock` — deterministic dependency lock
- `generate` — Dockerfile‑only + SBOM

No runtime loop, no deploy/export, no enterprise features.

## Enterprise Edition

The Enterprise Edition extends Harden with:
- Runtime profiling + policy tightening
- Deployment artifacts (K8s, CI/CD, auth, etc.)
- Enterprise buyer workflows and reporting

If you need those capabilities, request access to the Enterprise Edition.

## Installation

```bash
pip install -e .
```

Or run directly:

```bash
python3 -m harden [command]
```

## Commands

### analyze

```bash
harden analyze <path>
```

Produces:
- Terminal report
- JSON report at `<path>/.harden/state/harden-report.json`

Highlights:
- Framework + entrypoint detection
- **Entry command** inference (best‑effort) — shown in terminal and JSON report
- Python version detection
- Secrets scanning (regex + entropy)
- Dependency listing (requirements/pyproject/bare imports)
- OSV CVE checks with severity
- AI usage + external services detection
- Risk score (0–100)

### lock

```bash
harden lock <path> [--strategy auto|uv|pip-compile|pip-freeze]
```

Produces:
- `<path>/requirements.lock`
- `<path>/build_report.json`

If no manifest exists, `lock` infers dependencies from imports and writes
`.harden/state/requirements.inferred.txt` as the lock input.

### generate

```bash
harden generate <path> [--fail-on-critical]
```

Produces:
- `<path>/.harden/Dockerfile`
- `<path>/.harden/sbom.json`
- `<path>/.dockerignore` (only if missing)

Behavior:
- Uses `requirements.lock` when present (preferred)
- Falls back to `requirements.txt`
- If only `pyproject.toml` exists, installs the project (`pip install .`)

`--fail-on-critical` exits non‑zero if critical CVEs are detected.

## OSV Cache Behavior

OSV responses are cached at:
`<path>/.harden/state/osv_cache.json`

Default TTL: **24 hours**. Override with:

```bash
export HARDEN_OSV_CACHE_TTL_SECONDS=0   # disable cache
```

## Risk Scoring (high‑level)

- Critical secrets: +20 each
- Hardcoded AI keys: +25 each
- Critical CVEs: +15 each
- High‑severity issues: +8–10 each
- Unpinned dependencies: +2 each

Risk levels:
- 0–24: LOW
- 25–49: MEDIUM
- 50–74: HIGH
- 75+: CRITICAL

## Project Structure (OSS)

```
harden/
├── __init__.py
├── __main__.py
├── cli.py
├── locker.py
├── pipeline.py
├── analyzer/
│   ├── models.py
│   ├── detector.py
│   ├── secrets.py
│   ├── dependencies.py
│   ├── ai_usage.py
│   └── report.py
└── generators/
    ├── dockerfile.py
    └── sbom.py
```

## Requirements

- Python 3.8+
- click >= 8.0.0
- pyyaml >= 6.0
- rich >= 13.0.0

## License

Apache-2.0. See `LICENSE`.
