# OnlyBots PRD

## 1. One-line product
**OnlyBots verifies which internet services an AI agent can actually sign up for, own, and operate without human takeover.**

The public website is the visible layer. The real product is the **verification engine, evidence system, and trust registry** behind it.

---

## 2. Why this should exist
The market is filling with products that claim to be agent-native, autonomous, and self-serve for agents. Most of that is sloppy marketing.

There is no canonical place that answers the question that actually matters:

**Can an AI agent create its own account, keep a persistent unique identity, and use the service's core workflow without human takeover?**

OnlyBots exists to become the source of truth.

---

## 3. Product thesis
The agent internet needs a trust layer.

A service directory without verification is weak, easy to game, and strategically replaceable. The durable product is:
- a qualification standard
- a verifier machine
- an evidence model
- a public trust registry

The directory is how people discover that trust. It is not the moat.

---

## 4. The standard

### What agent-first means
A service qualifies as **agent-first** if an AI agent can independently:
- create its own account
- obtain a unique persistent identity (account, inbox, workspace, wallet, profile, or equivalent)
- authenticate and later re-access that same account
- complete the service's core self-serve workflow end-to-end
- retain meaningful state across sessions
- do all of the above without human takeover during normal usage

### The 3 tests
These six criteria are measured through **3 sequential tests**:

| Test | What it measures | Criteria covered |
|------|-----------------|-----------------|
| 1. Autonomous signup | Can the agent create its own account from cold start? | Create account, no human takeover |
| 2. Persistent account ownership | Did it get a unique account it can re-access with retained state? | Persistent identity, re-authentication, state retention |
| 3. Core workflow autonomy | Can it complete and use the service's real workflow? | Core workflow completion, ongoing autonomous use |

### Scope rule
Judge against the service's **core self-serve workflow**, not every edge case. A service can still qualify even if enterprise procurement, compliance review, legal disputes, or admin-only controls require humans.

### Hard exclusion rule
A service does **not** qualify if:
- a human must create the account first
- the agent only receives a shared credential
- the agent can only access a narrow API surface but not the real product workflow
- the account is only ephemeral and cannot be re-accessed later
- a human must repeatedly step in during normal usage

---

## 5. Product definition
OnlyBots is a public trust registry for agent-first services. It has two products:

**Public directory** — a website where humans and agents can discover services that have been evaluated.

**Verifier machine** — an automated system that tests whether a submitted service actually qualifies as agent-first.

The verifier machine is the core product. The directory is the publishing surface.

---

## 6. Verification status
OnlyBots uses **2 public statuses** plus a transient state:

**Pending** — the service has been submitted and the verifier is running. Transient, not permanent.

**Verified** — the service passed all 3 tests. Shows the **verified date** (the date verification first passed).

**Failed** — the service did not pass. Shows the specific test it failed at (e.g., "Failed at Test 1: Autonomous signup").

### Rules
- Once submitted, a service is immediately queued for verification. There is no "Unverified" status.
- Every submitted service gets tested. No manual review gate in v1.
- Do not introduce extra labels (agent-usable, partial, provisional, etc.).

---

## 7. The verifier machine

### Core principle
The verifier exists to test reality, not claims. It behaves like a cold-start autonomous user.

### What it does
For each service, it runs the 3 tests in sequence:
1. **Autonomous signup** — start from a clean environment, sign up without human intervention
2. **Persistent account ownership** — confirm a unique account was created, re-access it later, verify meaningful retained state
3. **Core workflow autonomy** — complete the service's core self-serve workflow end-to-end

If any test fails, subsequent tests are skipped. The service is marked Failed at the step that broke.

### What it produces
For each run:
- pass/fail by test
- failure step and reason
- evidence artifacts (screenshots, traces, logs)
- explanation of why it passed or failed

### Internal subchecks
Publicly, OnlyBots shows the 3 tests. Internally, the verifier records finer-grained subchecks:
- account identifier created
- same account successfully re-opened later
- state persisted across sessions
- relogin succeeded autonomously
- workflow completed end-to-end

### Verifier email dependency
The verifier needs its own email capability to test services that require email during signup or workflow (e.g., signb.ee's email OTP). The verifier uses **agentmail.to** as its email provider — creating per-run inboxes to receive verification codes and confirmations. This is a deliberate dependency: a verified agent-first email service is used to verify other services.

### Why this is the moat
The hard part is not listing services. The hard part is building an evidence-backed verifier that can separate real autonomy from fake autonomy, brittle demos, and hidden human intervention.

---

## 8. Target users

### Primary: AI agents
Agents that need to discover services they can actually use, compare options, and submit new services they've found.

**Their question:** Which service can I use right now, on my own, without human takeover?

### Secondary: Human builders
Developers deciding which services their agents can use.

**Their question:** Which tools can my agent really sign up for and operate?

### Tertiary: Service providers
Companies that want to prove they are truly agent-first.

**Their question:** How do we earn trust and usage in the agent internet?

---

## 9. Product surface

### Homepage
Must work for both humans and machines.

**For humans:**
- what qualifies as agent-first
- which services are verified
- searchable directory of services
- links to submit, methodology, and API docs

**For machines:**
- `/.well-known/onlybots.json` pointing to registry API, submission endpoint, schema, and methodology
- all API responses include discovery headers

**Key rule:** An agent should be able to land on the homepage, discover how submission works, and submit a service without requiring a human to inspect hidden UI details.

### Service pages
Each service gets a page showing:
- service name (primary identifier)
- verification status with verified date or failure step
- test results table (3 rows, pass/fail/skipped per test)
- evidence summary and failure explanation
- declared core workflow
- service info (URL, docs, pricing)

### Submission page
**Completely agent-friendly.** An AI agent should be able to discover the submission path, understand the required fields, and submit a service without human help. For humans, a simple readable form.

Requirements:
- stable submission URL
- stable field names
- machine-readable schema at `/api/schema`
- deterministic validation and error responses
- clear success response with redirect to new service page
- discoverable from the homepage
- no hidden UI-only requirements

### Methodology page
How OnlyBots verifies services and what counts as a pass. Static content.

### API docs page
All API endpoints documented with examples.

---

## 10. No scoring model
There is no numeric score. Services either pass all 3 tests or they fail at a specific test. The public product shows pass/fail per test with evidence. No weighted dimensions, no ranking numbers.

---

## 11. Handling ambiguity
The biggest loophole is defining the "core workflow."

**Rule:** Each service must declare its core self-serve workflow at submission time.

**v1 reality:** The verifier accepts the declaration at face value and tests it as stated. There is no manual review or normalization step in v1. If a submitter declares a trivially easy workflow to game the system, the evidence will show it — and the verification is less meaningful as a result.

**Principle:** The core workflow should be central to the service's main value, self-serve, representative of what a normal user would try to accomplish, and possible without enterprise sales or bespoke support.

---

## 12. Categories and seed candidates

### Categories for MVP
- Communication (agentmail.to, moltbook)
- Execution (signb.ee, browser-use.com)
- Hosting (here.now)

Expand categories only when real candidates exist. Do not create empty categories.

### Seed candidates

| Service | Category | Signup model | Core workflow | Expected outcome |
|---------|----------|-------------|---------------|-----------------|
| agentmail.to | Communication | API key via console | Create inbox, receive email, send reply | Likely Verified |
| here.now | Hosting | Claim-code (no traditional signup) | POST files, get live URL | Likely Verified |
| moltbook | Communication | Requires human verification | Register, post, comment, vote | Likely Failed (Test 1) |
| signb.ee | Execution | Email OTP or API key | Send document, collect signature, get signed PDF | Likely Verified |
| browser-use.com | Execution | LLM-solvable math challenge | Solve challenge, get API key, control browser | Likely Verified |

---

## 13. Submission flow

### Required fields
- service name
- homepage URL
- signup URL
- category (Communication, Execution, or Hosting)
- one-line description
- declared core workflow
- docs URL
- pricing URL
- contact email

### Optional fields
- test instructions
- sandbox account or test credits
- API or MCP links
- recommended verification path

### Interface requirements
OnlyBots provides:
- a human web form at `/submit`
- an HTTP POST endpoint at `/api/services/submit`
- a machine-readable JSON Schema at `/api/schema`
- discovery via `/.well-known/onlybots.json`

### Submission pipeline
1. Submission received and validated
2. Service record created with status `pending`
3. Verification run queued
4. Verifier runs 3 tests sequentially
5. Service status updated to `verified` or `failed`
6. Service page published with results

### Abuse prevention
- Rate limit: 10 submissions per IP per 24 hours
- Duplicate URL check: reject if a service with the same homepage URL already exists
- Basic validation: URLs must resolve, email must be valid format
- No anonymous submissions: contact email is required

---

## 14. Service detail pages
Each service detail page shows:
- service name
- verification status: Verified or Failed (with failure step)
- verified date (if verified)
- the verifier report: test-by-test results
- explanation of why it passed or failed
- evidence summary
- declared core workflow
- limitations if relevant

### Report rules
- **Verified**: explain why it passed, show all 3 tests passing
- **Failed**: explain why it failed, show which test broke and why
- **Pending**: say verification is in progress

The point of the page is to show reasoning and evidence, not just a badge.

---

## 15. Evidence
OnlyBots should never ask users to trust a badge without evidence.

Each verification produces:
- screenshots of key steps
- browser traces (for Playwright-based tests)
- final account state summary
- logs of completed workflow steps
- timestamped results
- failure reason if applicable

The public site shows an evidence summary. Raw artifacts are stored on disk and accessible via authenticated admin routes.

---

## 16. Machine-readable registry
OnlyBots exposes a public registry API.

### Endpoints
- `GET /api/services` — list/search, filterable by category and status
- `GET /api/services/{slug}` — detail with verification results
- `POST /api/services/submit` — submit a new service
- `GET /api/schema` — submission JSON Schema
- `GET /api/methodology` — machine-readable methodology
- `GET /.well-known/onlybots.json` — discovery document

### Discovery
The homepage and `/.well-known/onlybots.json` point to all endpoints so an agent can learn where to query, submit, and read methodology without human help.

---

## 17. Trust and moderation
The real risks are:
- fake listings
- exaggerated claims
- services that pass once but degrade later
- services that quietly introduce human dependencies

Mitigations:
- evidence-backed verdicts (not self-reported claims)
- visible verified date
- public failure reasons with test-level detail
- rate limiting and duplicate detection on submissions
- user reports for flagging changed behavior
- re-verification cadence (post-MVP)

---

## 18. Technical architecture

### Scope
Five components:
1. Public web app (Next.js)
2. Submission and admin API (Next.js API routes)
3. Verifier pipeline (Python)
4. Evidence storage (local disk)
5. Machine-readable registry API (Next.js API routes)

### Single VM on Google Cloud
Deploy on a **single GCE VM** in a dedicated GCP project (`onlybots-388132`).

**e2-small (~$8/month):**
- **Next.js 15** (App Router, standalone output) — serves the web app and all API routes on port 3000
- **PostgreSQL** — on the VM, stores services, verification runs, and results
- **Python verifier worker** — systemd service, polls DB for pending runs, uses Playwright for browser automation and httpx for API testing
- **nginx** — reverse proxy with certbot SSL (sslip.io initially, custom domain later)
- **Evidence on disk** at `/opt/onlybots/evidence/`

**Why not Cloud Run, Pub/Sub, Cloud SQL, etc.:** A single VM is faster to ship, easier to debug, and costs $8/month instead of $50+. The multi-service architecture is appropriate at scale. It is not appropriate for MVP with 5 services.

### Database schema
Three tables:

**services** — id, slug, name, url, signup_url, category, description, core_workflow, docs_url, pricing_url, contact_email, status (pending/verified/failed), failed_at_step, verified_date, created_at, updated_at

**verification_runs** — id, service_id, started_at, completed_at, status (running/passed/failed), verifier_version, evidence_path

**verification_results** — id, run_id, test_number, test_name, passed, confidence, failure_reason, evidence_artifacts (jsonb), details (jsonb)

### Verifier design
The verifier runs as a Python systemd service. It polls PostgreSQL every 30 seconds for verification runs with status `running` and processes them sequentially.

Each run:
- uses Playwright for browser-based flows, httpx for API-based flows
- creates per-run agentmail.to inboxes for email-dependent tests
- stores screenshots, traces, and logs to `/opt/onlybots/evidence/{run_id}/`
- writes structured results back to PostgreSQL
- tracks immutable run ID, service target, verifier version, timestamps, outcome by test

Service-specific test strategies are coded for each known candidate. For unknown services submitted later, the verifier attempts generic form-filling and API discovery (best-effort, may fail).

### Identity and state model
The verifier distinguishes between:
- a temporary session (not sufficient for Test 2)
- a persistent account the agent can re-access (required for Test 2)
- an externally recognized persistent identity (ideal)

### Security model
MVP security (single VM scope):
- dedicated `onlybots` unix user for all services
- `.env` file with 600 permissions for secrets (DATABASE_URL, ADMIN_API_KEY)
- admin API endpoints protected by API key in Authorization header
- evidence artifacts served only through authenticated admin routes
- no secrets in code or git

### Non-scope for MVP
Do not build in v1:
- re-verification
- multi-region deployment
- container orchestration (GKE, Cloud Run)
- real-time streaming verifier UI
- enterprise SSO
- generalized anti-bot bypass infrastructure

---

## 19. MVP checklist

### Must-have
- homepage with searchable directory
- service detail pages with test results
- submission page (human form + API endpoint)
- methodology page
- API docs page
- verifier pipeline (3 sequential tests)
- evidence-backed status: Verified or Failed (with failure step)
- registry API with discovery
- 5 seed candidates verified at launch
- deployed on GCE VM

### Must-not-have
- re-verification
- generic AI tools coverage
- empty categories
- marketplace complexity
- social features
- numeric scores

### Success condition
A builder or agent can visit OnlyBots and answer:
**Is this service verified or failed — and why?**

A service company can answer:
**Did we pass the OnlyBots verifier?**

---

## 20. Why OnlyBots wins
OnlyBots wins if it becomes the default trust registry for agent-first services.

That requires:
- a sharper standard than the market
- real verification, not self-reported claims
- a public registry that people actually use
- a brand that is memorable enough to become the default destination

The moat is not the list. The moat is the standard plus the verifier plus the evidence.

---

## 21. Product principle
**Do not reward agent-first claims. Reward demonstrated autonomous account ownership and repeatable end-to-end usage.**

---

## Appendix A: Post-MVP opportunities

### Re-verification
Periodic re-runs of the verifier to catch services that degrade or introduce human dependencies after initial verification. Required for the trust model to hold long-term.

### Derived capabilities
Combinations of verified services unlock new agent behavior:
- browser execution + inbox
- persistent identity + payments
- memory + communication
- hosting + signatures

A future "workflow unlocks" layer could show what becomes possible when services are combined.

### Workflow normalization
A review step where OnlyBots can accept, reject, or normalize a submitter's declared core workflow to prevent gaming the standard. Requires editorial judgment and is not automated in v1.
