# Tutorial: Harden SparkyBudget for Local Use

This tutorial walks through hardening [SparkyBudget](https://github.com/CodeWithCJ/SparkyBudget),
an open-source personal finance app, so it runs safely on your laptop inside a
container with pinned dependencies, network isolation, and a known security posture.

**Time**: ~10 minutes
**Requirements**: Python 3.8+, Docker Desktop, git

## What is SparkyBudget?

SparkyBudget is a self-hosted Flask app for personal budgeting. It connects to
your bank accounts via [SimpleFin](https://www.simplefin.org/) and stores
transaction data in a local SQLite database. It's a great example of a
"vibe-coded" personal project: useful, functional, but shipped without
production hardening.

## Why harden a personal app?

Even on your laptop, running inside a hardened container is better than
`python app.py`:

- **Pinned dependencies** — same versions every time, no surprise CVEs
- **Container isolation** — the app can't read your `~/.ssh`, `~/.aws`, or browser cookies
- **Egress proxy** — the app can only reach domains you've approved; a compromised dependency can't phone home
- **Known CVE posture** — you see every vulnerability in your dependency tree before you run
- **Non-root execution** — even if compromised, the app can't escalate to your host user

## Step 0: Install harden

```bash
# From the harden_oss directory:
pip install -e .

# Or run without installing:
python3 -m harden --help
```

## Step 1: Clone SparkyBudget

```bash
git clone https://github.com/CodeWithCJ/SparkyBudget.git
cd SparkyBudget
```

## Step 2: Analyze

```bash
harden analyze .
```

Harden scans the project and produces a security report:

```
╭────────────────────────── Overall Security Posture ──────────────────────────╮
│ Risk Score: 26.0/100                                                         │
│ Risk Level: MEDIUM                                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

**What it finds:**

| Finding | Details |
|---------|---------|
| Framework | Flask 3.1.0, entry via gunicorn on port 5000 |
| Secrets | `.env-example` file detected (no hardcoded secrets in source) |
| External services | SQLite (local database) |
| Vulnerable deps | flask, requests, gunicorn — all MEDIUM severity |
| Risk items | Debug mode enabled, missing health endpoints, no rate limiting |

The full report is saved to `.harden/state/harden-report.json`.

## Step 3: Lock dependencies

```bash
harden lock .
```

You may see a warning about incomplete `pyproject.toml` coverage. If so,
lock from `requirements.txt` instead:

```bash
uv pip compile requirements.txt -o requirements.lock --quiet
```

This pins every dependency to an exact version (20 packages).

## Step 4: Generate hardened artifacts

```bash
harden generate .
```

This produces four artifacts in `.harden/`:

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build, non-root user, pinned deps, HEALTHCHECK |
| `sbom.json` | CycloneDX 1.5 SBOM with CVE metadata |
| `docker-compose.yml` | App + egress proxy sidecar with network isolation |
| `squid.conf` | Domain allowlist for the egress proxy |

The key output is the **docker-compose.yml** which wires the app behind a
Squid egress proxy:

```
[you] --> localhost:5000 --> [app container] --HTTP_PROXY--> [squid:3128] --> [internet]
                                  |                               |
                            internal network              domain allowlist
                            (no direct internet)          enforced here
```

The app container is on an isolated Docker network with **no direct internet
access**. All outbound HTTP(S) traffic routes through the Squid proxy, which
only allows domains detected during analysis.

## Step 5: Configure and run

```bash
# Create your .env file
cp .env-example .env
# Edit .env with your actual values:
#   SPARKY_USER=your_username
#   SPARKY_PASS=your_password
#   FLASK_SECRET_KEY=some-long-random-string

# Run the hardened stack
cd .harden
docker compose up --build -d
```

Open http://localhost:5000 and log in.

## Step 6: Verify egress enforcement

The egress proxy blocks any outbound traffic to domains NOT on the allowlist.
You can verify this:

```bash
# This should FAIL — evil.com is not on the allowlist
docker compose exec app curl -x http://egress-proxy:3128 https://evil.com 2>&1
# Expected: Access Denied

# This should SUCCEED — pypi.org is on the allowlist
docker compose exec app curl -x http://egress-proxy:3128 https://pypi.org 2>&1
# Expected: 200 OK
```

Check the proxy logs to see what's being allowed/denied:

```bash
docker compose logs egress-proxy
```

## Step 7: Customize the allowlist

If the app needs to reach additional domains (e.g., SimpleFin for bank sync),
edit `.harden/squid.conf`:

```squid
# Add SimpleFin API access
acl allowed_domains dstdomain beta-bridge.simplefin.org
```

Then restart the proxy:

```bash
docker compose restart egress-proxy
```

## What's different from `python app.py`

| Aspect | `python app.py` | `docker compose up` (hardened) |
|--------|-----------------|-------------------------------|
| Dependencies | Whatever pip resolves today | Pinned to exact versions |
| File access | Your entire home directory | Only `/app` and mounted volumes |
| User | Your user (full privileges) | `appuser` (UID 1000, no sudo) |
| Outbound network | Unrestricted | Only allowlisted domains |
| CVE posture | Unknown | Documented in `sbom.json` |
| Compromised dep | Can reach any server | Blocked by egress proxy |

## What comes next: the `harden run` vision

Today, the OSS CLI gives you `analyze` → `lock` → `generate` — three commands
to produce a hardened stack with an egress proxy.

The enterprise edition will add a **learning mode**:

```bash
harden run .
```

This will:

1. Run the stack in **learning mode** — the egress proxy allows all traffic but logs every domain
2. You exercise the app (log in, sync bank data, browse budgets)
3. `harden tighten` reads the proxy logs and auto-generates the allowlist
4. Restart in **enforce mode** — only observed domains are allowed

For SparkyBudget, `harden run` would automatically discover `beta-bridge.simplefin.org`
during bank sync and add it to the allowlist — no manual squid.conf editing needed.

## Cleanup

```bash
docker compose down -v
cd ..
```

## Summary

| Step | Command | What it does |
|------|---------|-------------|
| Analyze | `harden analyze .` | Risk report, framework detection, CVE scan |
| Lock | `harden lock .` | Pin all deps to exact versions |
| Generate | `harden generate .` | Dockerfile + SBOM + docker-compose + squid allowlist |
| Run | `docker compose up` | App behind egress proxy with network isolation |
| Verify | `curl` through proxy | Confirm allowlist enforcement |
