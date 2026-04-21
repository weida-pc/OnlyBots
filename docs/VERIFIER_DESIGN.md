# Verifier design notes

Principles the verifier has to hold, and the mistakes it took to learn them.

## What the registry measures

A service's headline status answers exactly one question:

> **Can an AI agent sign up for this service without any human in the loop?**

Not "can an agent do useful work *with* a credential a human gave it." The second thing is interesting and worth testing, but it is not agent-first signup and must not be reported as such.

## Three tests, independent meanings

| Test | What it actually measures | What it does NOT measure |
|---|---|---|
| **signup** | The agent autonomously obtained a credential from the service starting from zero identity. | Whether credentials exist. Whether curl/HTTP works. |
| **persistence** | A valid credential still authenticates on a return visit. | Signup autonomy. |
| **workflow** | The core service workflow can be driven via the API, given a valid credential. | Signup autonomy. |

The service's overall `status` rolls up from **signup only**. `persistence` and `workflow` carry useful operational signal that is reported in the detail view, but a service cannot be `verified` unless signup passed.

## Anti-pattern: `env_secret` in a signup test

```json
// WRONG — this test always "passes" as long as the operator set an env var
"signup": {
  "steps": [
    { "kind": "env_secret", "env_var": "FOO_API_KEY", "state_key": "foo_key" },
    { "kind": "http", "url": "/me", "headers": { "Authorization": "Bearer {foo_key}" } }
  ]
}
```

This is testing that the operator has a key, not that an agent obtained one. A contract written this way produces registry entries that look like wins but are lies. The `env_secret` primitive must never appear in a `signup` test.

The right shape for a service whose signup genuinely is not agent-accessible:

```json
"signup": {
  "agent_task": {
    "prompt": "Attempt to sign up autonomously for <service>. Do not use any pre-provisioned env credentials. If autonomous signup is impossible, report that — do NOT fabricate a credential.",
    "expected_artifacts": ["foo_api_key"]
  },
  "steps": [],
  "assertions": [
    { "kind": "artifact_present", "artifact": "foo_api_key" }
  ]
}
```

The agent_task runs in the sandbox, genuinely tries, and genuinely fails. The service rolls up as `failed` with a clean blocker. `persistence` and `workflow` may then use `env_secret` to exercise operational endpoints with an operator-provided key — those tests tell us "given creds, ops work," which is a distinct and useful signal.

## Two different agents, do not confuse them

- **Gemini-CLI inside a fresh Daytona container** is what the `agent_task` step actually runs. This is the registry's autonomous-signup test. If it can't complete signup, the service is not agent-first.
- **Claude (this assistant) driving a browser via Chrome MCP** is a different animal entirely. It can click Submit buttons, read OTPs from AgentMail, complete dashboard flows — but every one of those requires a human in the loop (the user approves a Submit click, signs a magic link, enters a Stripe card). That is not a verifier test; that is the operator manually obtaining credentials.

Credentials the operator captures via the Chrome path go into `/opt/onlybots/verifier/.env` and are *only* visible to `persistence` / `workflow` tests. They never satisfy `signup`. A verified service must pass `signup` under the Gemini-CLI sandbox on its own.

## Tier classification (informal)

| Tier | Definition |
|---|---|
| 1 | HTTP-only signup, no CAPTCHA / email gate / payment. Gemini can complete autonomously. |
| 2 | Signup needs a receivable channel (email OTP, SMS OTP, inbound webhook). Gemini can complete if the verifier has the right primitive. |
| 3 | Signup requires a browser dashboard click, OAuth consent screen, on-chain signature, or human payment. Gemini cannot complete. Service is **not agent-first**. |

The verifier only claims `verified` for Tier 1 or Tier 2 services. Tier 3 is a permanent `failed` unless the vendor ships a programmatic path.

## Rejected shortcuts

- ❌ Fabricating credentials in agent output to satisfy `expected_artifacts`.
- ❌ Pulling credentials from env in the signup step.
- ❌ Calling Chrome-MCP signup "agent-first" because a Claude instance drove it.
- ❌ Reporting `verified` when signup skipped.

## Historical notes

- **Runs 131 / 132 (skyfire, nevermined, 2026-04-20)** were originally recorded as `passed 3/3` because their signup contracts used the `env_secret` shortcut. Both services are Tier 3 (Stytch dashboard and Privy dashboard respectively) and cannot be signed up for autonomously. The T1 row on those runs was retroactively flipped to `passed=false` with an explanatory `failure_reason`; T2 and T3 stay `true` because the operator-provided key does work for operations. Contract files were rewritten so future runs fail honestly at T1.
- **Runs 133 / 134** were a wasteful rerun of the rewritten contracts to re-confirm what we already knew. They were deleted after the correction — they carry less information than 131/132 (T1-only) and the T1 verdict was already knowable from first principles.
