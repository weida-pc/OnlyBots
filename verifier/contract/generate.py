"""Phase 5 — LLM-assisted contract generator (CLI, no admin UI).

Produces a contract JSON draft for a submitted service whose metadata is in
the services table. Does NOT auto-approve: the output is written to
`verifier/contracts/<slug>.json.draft` for a human to review and rename.

Intentionally minimal:
  - No admin UI (review happens in a text editor)
  - One retry on parse failure
  - Strict validation: draft must parse through the same loader that enforces
    contract schema in production

Usage (from /opt/onlybots/verifier):
  sudo -u onlybots venv/bin/python -m contract.generate <slug>

If the slug doesn't exist in DB, or already has a contract, exits non-zero.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


# Run this via `python -m contract.generate` so imports resolve. If the
# user runs it as a script, make sure the verifier package dir is on path.
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "contract"

from .loader import CONTRACTS_DIR, parse_contract, ContractError, has_contract


# Reference contracts the LLM can learn from. Intentionally picked for
# coverage: agent_task usage, env_secret, inject_nonce, content_serves_nonce.
EXAMPLES = ["agentmail-to", "here-now", "moltbook"]


def _load_service(slug: str) -> dict[str, Any]:
    """Fetch service metadata from DB. Not importing from lib/db.ts because
    we're in Python; hit psycopg2 directly.
    """
    import psycopg2
    import psycopg2.extras
    from config import DATABASE_URL

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT slug, name, url, signup_url, category, description, "
                "core_workflow, docs_url, pricing_url "
                "FROM services WHERE slug = %s",
                (slug,),
            )
            row = cur.fetchone()
            if not row:
                raise SystemExit(f"service '{slug}' not found in database")
            return dict(row)


def _fetch_docs(url: str | None, budget_chars: int = 6000) -> str:
    """Best-effort fetch of docs URL. Returns a truncated excerpt or ''."""
    if not url:
        return ""
    try:
        # Use the verifier's existing browser-TLS helper so sites behind
        # Cloudflare don't 403 us on this fetch.
        import executor as _legacy  # type: ignore
        resp = _legacy.http_get_resilient(url)
        body = resp.get("body", "")[:budget_chars]
        return body
    except Exception as e:
        return f"(docs fetch failed: {e})"


def _load_example(slug: str) -> str:
    path = CONTRACTS_DIR / f"{slug}.json"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


SCHEMA_SPEC = """
Schema (strict — validator rejects unknown fields and kinds):

Contract = {
  "schema_version": 1,                     // must be 1
  "service_slug": "<slug>",
  "allowed_env": ["MY_SERVICE_API_KEY"],   // env vars env_secret may read (can be [])
  "sandbox": {
    "url_allowlist": ["api.example.com", "*.example.com"]  // non-empty required
  },
  "tests": {
    "signup": TestSpec,
    "persistence": TestSpec,
    "workflow": TestSpec
  },
  "notes": "…"
}

TestSpec = {
  "produces": ["state_key_1"],             // keys this test writes to state
  "requires": [],                          // keys it reads (must be in signup.produces)
  "agent_task": AgentTask,                 // optional
  "steps": [Step, …],
  "assertions": [Assertion, …]
}

AgentTask (optional — describes what an LLM agent should do):
  {
    "prompt": "<task description; {state_vars} templated>",
    "expected_artifacts": ["state_key_returned_by_agent"],
    "model": "gemini-2.5-flash",           // optional
    "timeout_s": 180                       // optional
  }
  expected_artifacts MUST be a subset of produces.

Step kinds (exactly one per step):
  http          {id, method: GET|POST|PUT|DELETE|PATCH, url, headers?,
                 body_json? | body_raw?, extract?, browser_fallback?,
                 must_contain_artifact?, description?}
  put_file      {id, url, body_template, content_type?, description?}
  inject_nonce  {id, state_key, prefix?, description?}
  env_secret    {id, env_var, state_key, required?, description?}
  wait          {id, seconds, description?}

Assertion kinds:
  http_status_ok         {step, description?}
  artifact_present       {artifact, description?}
  content_serves_nonce   {step, description?}  // use for publish-and-verify services

Templating:
  In strings, `{state_key}` is substituted with the value of state[state_key]
  at execution time. Extract expressions use JMESPath: `foo.bar[0].baz` or
  `a || b` for fallback. Numeric array indices use brackets, not dots.
"""


PROMPT_TEMPLATE = """You are generating a hand-written verification contract for the OnlyBots trust registry. The contract will be executed by a verifier that tests whether an AI agent can autonomously sign up for, persist, and operate a web service.

{schema_spec}

Reference contracts (these all pass verification in production):

--- agentmail-to.json (programmatic API signup, agent-driven) ---
{example_agentmail}

--- here-now.json (ANONYMOUS service with NO accounts — uses inject_nonce +
    content_serves_nonce for round-trip proof. This is the pattern for any
    service whose primary flow is "agent publishes/posts content; verifier
    reads it back". No auth header ever. No env_secret ever. Autonomy
    proven by the fact that the verifier sees its own injected nonce come
    back through the service.) ---
{example_herenow}

--- moltbook.json (env_secret for pre-claimed API key — PERSISTENCE only, NOT signup) ---
{example_moltbook}

Now generate a contract for this service:

Service slug:       {slug}
Service name:       {name}
Service URL:        {url}
Signup URL:         {signup_url}
Category:           {category}
Description:        {description}
Core workflow:      {core_workflow}

Docs excerpt ({docs_len} chars from {docs_url}):
{docs_excerpt}

CRITICAL SEMANTICS (violate these and the contract will be rejected by code review):

  The registry's headline question is: "Can an AI agent sign up autonomously,
  starting from zero identity?" The `signup` test MUST measure exactly that.
  `persistence` and `workflow` measure different, lesser questions.

  RULE A — `signup` test SHAPE IS FIXED:
    - signup.agent_task MUST be present, prompting an LLM agent to attempt
      autonomous registration.
    - signup.steps MAY contain at most probe http steps that verify the
      agent-returned credential. Nothing else.
    - signup MUST NOT contain env_secret. Loading an operator-provided key
      in signup is a LIE — it claims autonomy the agent never achieved.
    - If the service's signup path is genuinely browser/dashboard/OAuth-only,
      still use agent_task. The agent will correctly fail to produce the
      credential, the assertion will fail, and the registry records "not
      agent-first" honestly. Do NOT fall back to env_secret to make it pass.

  RULE B — env_secret belongs in `persistence` / `workflow` ONLY:
    - Use it when an operator has pre-provisioned a key for the service in
      /opt/onlybots/verifier/.env and you want to exercise the API.
    - Declare the env var in allowed_env.
    - These tests report "given creds, ops work" — a separate signal from
      signup autonomy.
    - Each ops test should load its OWN credential via env_secret (not
      depend on signup.produces). This lets ops tests run even when
      signup fails — which is the common case for Tier-3 services.

  RULE D — persistence and workflow should NOT `requires` from signup.
    - If signup is an agent_task that will fail for Tier-3 services,
      persistence/workflow that `requires` signup.produces will crash
      with a TemplateError. Instead, each ops test declares its own
      env_secret step and loads the operator-provided key fresh.
    - If no operator key exists, use env_secret with `required: false`
      — the step no-ops, the subsequent probe gets an empty Bearer
      header, and the test fails with a 401/403 rather than crashing.

  RULE C — service-wide roll-up:
    - Each test rolls up independently. The service's headline status is
      driven by signup's pass/fail, not by the composite.

  RULE E — persistence / workflow must exercise an AUTHENTICATED endpoint.
    - Every non-inject_nonce http step in persistence/workflow must either
      (a) carry an Authorization / apikey / bearer header, OR
      (b) be a post-signup probe that uses state the signup agent produced.
    - Do NOT use unauthenticated GET of the homepage as a "persistence"
      test. That's trivia — parked domains pass it. A real persistence
      test exercises the credential.
    - If there's no realistic authenticated endpoint to hit (because the
      service genuinely has no API), make the test require signup.produces
      so it fails cleanly rather than passing trivially.

OTHER GUIDELINES:
  1. Use inject_nonce + content_serves_nonce for content-publishing services
     (the verifier generates a random nonce, the agent embeds it, the probe
     confirms it served back).
  2. Fill sandbox.url_allowlist with EVERY host you'll contact (including
     CDN / upload hosts — check the docs excerpt).
  3. Every test that requires state from signup must declare `requires`.
     Every test that writes state must declare `produces`.
  4. If the service is OpenClaw / ClawHub-based (crypto wallet, skill-install
     flow), still use agent_task in signup. The agent can do `npm install
     ethers` and generate a keypair + sign a challenge inside the sandbox.
     Document the wallet-signing steps plainly in the prompt. Do NOT assume
     a Clawdis runtime; write the crypto ops inline.
  5. PROBE_AUTH: do NOT invent a URL like "/api/v1/me" — most services
     don't have it. Instead, instruct the agent_task to ALSO report a
     "<slug>_probe_url" artifact: the exact authenticated URL the agent
     used to verify its own credential (e.g. the URL that returned 200
     right after signup — typically a profile or balance endpoint). The
     probe_auth http step then uses {{<slug>_probe_url}} as its url
     template (double-braces because this is Python .format() text),
     not a guessed path. Declare "<slug>_probe_url" in produces +
     expected_artifacts, and reference it in the probe_auth step's url.
     This change fixed a batch of false-negatives where the agent got a
     real key but the verifier's invented /me 404'd.
  6. Return ONLY a JSON object inside a ```json code block. No prose before
     or after. The JSON must parse as a valid Contract.
"""


def _build_prompt(service: dict, docs_excerpt: str) -> str:
    return PROMPT_TEMPLATE.format(
        schema_spec=SCHEMA_SPEC,
        example_agentmail=_load_example("agentmail-to"),
        example_herenow=_load_example("here-now"),
        example_moltbook=_load_example("moltbook"),
        slug=service["slug"],
        name=service["name"],
        url=service["url"],
        signup_url=service["signup_url"],
        category=service["category"],
        description=service["description"],
        core_workflow=service["core_workflow"],
        docs_url=service.get("docs_url") or "(none provided)",
        docs_len=len(docs_excerpt),
        docs_excerpt=docs_excerpt or "(no docs fetched)",
    )


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


def _extract_json(llm_output: str) -> dict | None:
    """Find the largest ```json``` fenced block and parse it."""
    matches = JSON_BLOCK_RE.findall(llm_output)
    for block in reversed(matches):  # prefer the last block (often the final answer)
        try:
            obj = json.loads(block)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    # Fallback: try the whole output
    try:
        obj = json.loads(llm_output)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _call_gemini(prompt: str, model: str = "gemini-2.5-pro",
                   timeout_s: int = 180) -> str:
    """Invoke gemini CLI and return stdout. Uses gemini-2.5-pro by default for
    generation (better at structured JSON output than flash)."""
    env = dict(os.environ)
    t0 = time.time()
    completed = subprocess.run(
        # No --yolo here: contract generation doesn't need tool use
        ["gemini", "-m", model, "-p", prompt],
        capture_output=True, text=True, timeout=timeout_s, env=env, cwd="/tmp",
    )
    elapsed = time.time() - t0
    if completed.returncode != 0 and not completed.stdout.strip():
        raise SystemExit(
            f"gemini exited {completed.returncode} after {elapsed:.1f}s. "
            f"stderr: {completed.stderr[-500:]}"
        )
    return completed.stdout


def _enforce_honesty_rules(contract, *, signup_only: bool = False) -> None:
    """Reject generator output that violates OnlyBots' honesty rules.

    Raises SystemExit with a message that's fed back into the next
    generator retry, so the LLM gets a specific correction signal
    rather than a generic "try again". Rules enforced:

      A. signup has agent_task (no env_secret cheat)
      Rule-5. signup.steps that reference {<slug>_probe_url} have that
             key in produces + agent_task.expected_artifacts
      E. persistence / workflow prove agent-specific action: either
         env_secret + auth-header, `requires` from signup + authed
         endpoint, inject_nonce + content_serves_nonce round-trip, or
         chained state extracted within the same test. Homepage trivia
         rejected.

    `signup_only=True` skips Rule E; used when we just want to check
    the signup shape before running expensive downstream tests.
    """
    import re as _re

    signup = contract.tests.get("signup")
    if signup is None:
        raise SystemExit("generated contract has no 'signup' test")
    if signup.agent_task is None:
        raise SystemExit(
            "generated contract's signup test has no agent_task (Rule A). "
            "Signup MUST attempt autonomous registration via agent_task, "
            "not pre-provisioned env vars."
        )
    for step in signup.steps:
        if getattr(step, "kind", None) == "env_secret":
            raise SystemExit(
                f"generated contract's signup test contains an env_secret "
                f"step (id={step.id}). That's the 'dishonest signup' anti-"
                f"pattern (Rule A). env_secret belongs in persistence/"
                f"workflow only."
            )

    # Rule 5: signup step URLs that reference {<slug>_probe_url} must
    # have that var in produces AND in agent_task.expected_artifacts so
    # the agent knows to return it.
    probe_url_refs = set()
    for step in signup.steps:
        url_template = getattr(step, "url", "") or ""
        for m in _re.finditer(
            r"\{([a-zA-Z_][a-zA-Z_0-9]*_probe_url)\}", url_template
        ):
            probe_url_refs.add(m.group(1))
    for ref in probe_url_refs:
        if ref not in signup.produces:
            raise SystemExit(
                f"generated contract references {{{ref}}} in a signup "
                f"step URL but didn't declare it in signup.produces. The "
                f"agent won't know to return it. Add '{ref}' to produces "
                f"and to agent_task.expected_artifacts."
            )
        if (signup.agent_task
                and ref not in signup.agent_task.expected_artifacts):
            raise SystemExit(
                f"generated contract has '{ref}' in produces but not in "
                f"agent_task.expected_artifacts. The agent needs the key "
                f"listed there so it knows to include it in the ARTIFACTS "
                f"JSON block."
            )
    if signup.agent_task:
        for art in signup.agent_task.expected_artifacts:
            if (art.endswith("_probe_url")
                    and art not in probe_url_refs):
                print(f"[generate] WARNING: agent_task.expected_artifacts "
                      f"contains '{art}' but no signup step URL template "
                      f"references {{{art}}}. Probe step will not use it.")

    if signup_only:
        return

    # Rule E: persistence / workflow must prove agent-specific action.
    # Four accepted proofs (any ONE is sufficient):
    #   1. env_secret step + at least one auth-header http step
    #   2. `requires` from signup (implicitly used in authed step)
    #   3. inject_nonce + content_serves_nonce round-trip
    #   4. chained-state: later step interpolates earlier step's extract

    def _is_authenticated_step(step) -> bool:
        headers = getattr(step, "headers", {}) or {}
        for v in headers.values():
            low = str(v).lower()
            if ("bearer" in low or "apikey" in low
                    or "api-key" in low or "token" in low):
                return True
        return False

    def _step_interpolates_any(step, keys: set) -> bool:
        if not keys:
            return False
        blob = (str(getattr(step, "url", "") or "")
                + str(getattr(step, "headers", {}) or "")
                + str(getattr(step, "body_json", None) or "")
                + str(getattr(step, "body_raw", None) or "")
                + str(getattr(step, "content_type", "") or "")
                + str(getattr(step, "body_template", "") or ""))
        for m in _re.finditer(r"\{([a-zA-Z_][a-zA-Z_0-9]*)\}", blob):
            if m.group(1) in keys:
                return True
        return False

    for test_name in ("persistence", "workflow"):
        test = contract.tests.get(test_name)
        if test is None:
            continue
        http_steps = [s for s in test.steps
                      if getattr(s, "kind", None) == "http"]
        if not http_steps:
            continue

        has_env_secret = any(
            getattr(s, "kind", None) == "env_secret"
            for s in test.steps
        )
        any_authed = any(
            _is_authenticated_step(s) for s in http_steps
        )
        has_nonce_inject = any(
            getattr(s, "kind", None) == "inject_nonce"
            for s in test.steps
        )
        has_nonce_assertion = any(
            getattr(a, "kind", None) == "content_serves_nonce"
            for a in test.assertions
        )
        nonce_roundtrip = has_nonce_inject and has_nonce_assertion

        produced_here = set()
        for s in test.steps:
            extracts = getattr(s, "extract", {}) or {}
            for k in extracts:
                produced_here.add(k)
        chained_state = any(
            _step_interpolates_any(s, produced_here) for s in http_steps
        )

        if (not has_env_secret and not any_authed and not test.requires
                and not nonce_roundtrip and not chained_state):
            raise SystemExit(
                f"generated contract's {test_name} test is 'homepage "
                f"trivia' (Rule E). No authenticated step, no env_secret, "
                f"no `requires` from signup, no inject_nonce + "
                f"content_serves_nonce round-trip, and no chained state "
                f"from within-test extracts. A parked domain would pass "
                f"this same test, so it's not real agent-action proof. "
                f"Rewrite the {test_name} test to do one of: "
                f"(a) env_secret + auth header; "
                f"(b) require signup state + authed endpoint; "
                f"(c) inject_nonce, embed it via the agent, then "
                f"content_serves_nonce assertion on a GET that reads "
                f"it back (here-now.json pattern); "
                f"(d) chain http steps where a later step interpolates "
                f"state extracted by an earlier step."
            )


def generate(slug: str, *, overwrite_existing: bool = False,
              model: str = "gemini-2.5-pro") -> Path:
    if has_contract(slug) and not overwrite_existing:
        raise SystemExit(
            f"contract for '{slug}' already exists at "
            f"{CONTRACTS_DIR / (slug + '.json')}. Pass --overwrite to replace.")

    service = _load_service(slug)
    docs_excerpt = _fetch_docs(service.get("docs_url"))
    prompt = _build_prompt(service, docs_excerpt)

    # Attempt loop: call LLM, parse, validate structurally, validate
    # honesty rules. On any failure, compose a feedback prompt with the
    # specific error and retry. MAX_ATTEMPTS total tries before giving up.
    MAX_ATTEMPTS = 3
    current_prompt = prompt
    last_error: str | None = None

    for attempt in range(MAX_ATTEMPTS):
        label = "initial" if attempt == 0 else f"retry {attempt}"
        print(f"[generate] Calling {model} for {slug} "
              f"({label}, prompt={len(current_prompt)} chars)...")
        output = _call_gemini(current_prompt, model=model)

        raw = _extract_json(output)
        if raw is None:
            last_error = "LLM output did not contain a parseable ```json``` block"
            current_prompt = (
                f"{prompt}\n\n"
                f"YOUR PREVIOUS RESPONSE FAILED:\n  {last_error}\n\n"
                f"Return ONLY a single JSON object inside a ```json code block. "
                f"No prose before or after."
            )
            continue

        try:
            contract = parse_contract(raw, source=f"<generate {slug} {label}>")
        except ContractError as e:
            last_error = f"schema validation: {e}"
            print(f"[generate] {label} failed schema: {e}")
            current_prompt = (
                f"{prompt}\n\n"
                f"YOUR PREVIOUS RESPONSE FAILED SCHEMA VALIDATION:\n  {e}\n\n"
                f"Produce a CORRECTED JSON contract that fixes the specific "
                f"problem above."
            )
            continue

        try:
            _enforce_honesty_rules(contract, signup_only=False)
        except SystemExit as e:
            # Our own Rules (A/D/E etc.) rejected the draft. Feed the
            # specific rule violation back so the LLM can correct.
            last_error = f"honesty rule: {e}"
            print(f"[generate] {label} failed honesty rule: {e}")
            current_prompt = (
                f"{prompt}\n\n"
                f"YOUR PREVIOUS RESPONSE VIOLATED AN HONESTY RULE:\n  {e}\n\n"
                f"Produce a CORRECTED JSON contract. Pay special attention "
                f"to the reference contracts — here-now.json in particular "
                f"shows how to handle services that don't have authenticated "
                f"endpoints (use inject_nonce + content_serves_nonce for "
                f"round-trip proof instead of unauthenticated homepage GETs)."
            )
            continue

        # All three gates passed.
        break
    else:
        # Loop exhausted without break — final failure.
        raise SystemExit(
            f"gemini failed to produce a valid contract after "
            f"{MAX_ATTEMPTS} attempts. Last error: {last_error}\n"
            f"Last 1KB of output:\n{output[-1024:]}"
        )

    # Contract passed structural + honesty checks. Auto-promote on the daemon
    # path (this function is also invoked by an operator from CLI, but that
    # caller can still use --draft-only if they want to keep the old flow.)
    final_path = CONTRACTS_DIR / f"{slug}.json"
    final_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    print(f"[generate] Wrote validated contract to {final_path}")
    print(f"[generate] Contract summary:")
    for tname, spec in contract.tests.items():
        has_agent = "AGENT" if spec.agent_task else "direct"
        print(f"  {tname}: {has_agent} | {len(spec.steps)} steps, "
              f"{len(spec.assertions)} assertions | produces={spec.produces}")
    return final_path


def main():
    ap = argparse.ArgumentParser(description="Generate a contract draft via LLM")
    ap.add_argument("slug", help="Service slug (must exist in DB)")
    ap.add_argument("--overwrite", action="store_true",
                     help="Overwrite an existing contract (default: fail if present)")
    ap.add_argument("--model", default="gemini-2.5-pro",
                     help="Gemini model to use (default: gemini-2.5-pro)")
    args = ap.parse_args()
    generate(args.slug, overwrite_existing=args.overwrite, model=args.model)


if __name__ == "__main__":
    main()
