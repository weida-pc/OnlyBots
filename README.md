# OnlyBots — Trust Registry for Agent-First Services

A public registry that tests and publishes whether third-party services can be fully operated by autonomous AI agents — without any human in the loop.

Live: **http://34-28-191-224.sslip.io**

---

## What It Does

OnlyBots runs automated verifications against submitted services to answer three questions:

1. **Autonomous signup** — Can an AI agent create an account via API/form without CAPTCHA, phone verification, or manual approval?
2. **Persistent account ownership** — Can the agent authenticate and prove ownership on a return visit?
3. **Core workflow autonomy** — Can the agent complete the primary service workflow end-to-end via API?

Services that pass all three tests earn **Verified** status. Failures are published with the specific blocker so developers know exactly what to fix.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│  Next.js frontend (App Router)              │
│  app/  components/  lib/                    │
└───────────────────┬─────────────────────────┘
                    │ reads
┌───────────────────▼─────────────────────────┐
│  PostgreSQL  (onlybots DB)                  │
│  services · verification_runs · test_results│
└───────────────────▲─────────────────────────┘
                    │ writes
┌───────────────────┴─────────────────────────┐
│  Python verifier  (verifier/)               │
│  executor.py · harness.py · tests/          │
│  Runs via onlybots-verifier.service         │
└─────────────────────────────────────────────┘
```

Deployed on a single GCP VM (`34.28.191.224`). Frontend is served by Next.js standalone build behind nginx. Verifier runs as a systemd service, polling the DB for pending jobs.

---

## API

All endpoints return JSON. No authentication required for reads.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/services` | List all services. Supports `?q=`, `?status=`, `?category=` |
| GET | `/api/services/{slug}` | Single service with full verification history |
| POST | `/api/services/submit` | Submit a new service for verification |
| GET | `/api/schema` | JSON Schema for the submission payload |
| GET | `/api/methodology` | Verification methodology in machine-readable JSON |
| GET | `/.well-known/onlybots.json` | Registry discovery endpoint |

Full docs: `http://34-28-191-224.sslip.io/api-docs`

---

## Verifier

The verifier is a Python service in `verifier/`. It uses the Gemini CLI as its agent harness.

```
verifier/
  executor.py          # orchestrates runs, pulls pending services from DB
  harness.py           # wraps Gemini CLI, parses structured output
  tests/
    test_signup.py     # Test 1: autonomous signup
    test_persistence.py # Test 2: account ownership
    test_workflow.py   # Test 3: core workflow
```

Each test calls `harness.py` with a prompt, which shells out to:
```
gemini -m gemini-2.5-pro-preview-03-25 -p "<prompt>"
```

Results are parsed for `passed`, `confidence`, `reason`, and `blocker`, then written to `test_results` and `verification_runs` tables.

### Pre-provisioned keys

For Tier-3 services whose signup is browser-dashboard-only (Stytch, Privy, OAuth, Stripe-gated), the operator can put a key in `/opt/onlybots/verifier/.env`:

```
NVM_API_KEY=sandbox:eyJ...
SKYFIRE_API_KEY=017d...
```

**Those keys are for `persistence` and `workflow` tests only.** They do NOT satisfy the `signup` test, and the service's roll-up status still fails at signup. This is on purpose: the registry measures signup autonomy, not whether curl works when a human hands the agent a credential.

See [`docs/VERIFIER_DESIGN.md`](docs/VERIFIER_DESIGN.md) for the rationale and the anti-patterns that drove the rule.

---

## Local Development

```bash
npm install
npm run dev
```

Requires a local PostgreSQL database. Copy `.env.example` to `.env.local` and set `DATABASE_URL`.

### Database schema

```bash
psql $DATABASE_URL < schema.sql
```

---

## Deployment

Build and copy to VM:

```bash
npm run build
tar -czf onlybots-frontend.tar.gz .next/standalone .next/static public
scp onlybots-frontend.tar.gz t@34.28.191.224:/opt/onlybots/
ssh t@34.28.191.224 "cd /opt/onlybots && tar -xzf onlybots-frontend.tar.gz && sudo systemctl restart onlybots-frontend"
```

Verifier is managed via:

```bash
sudo systemctl status onlybots-verifier
sudo systemctl restart onlybots-verifier
journalctl -u onlybots-verifier -f
```

---

## License

MIT
