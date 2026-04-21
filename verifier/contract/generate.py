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

--- here-now.json (multi-step publish flow with nonce verification) ---
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
  5. Return ONLY a JSON object inside a ```json code block. No prose before
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


def generate(slug: str, *, overwrite_existing: bool = False,
              model: str = "gemini-2.5-pro") -> Path:
    if has_contract(slug) and not overwrite_existing:
        raise SystemExit(
            f"contract for '{slug}' already exists at "
            f"{CONTRACTS_DIR / (slug + '.json')}. Pass --overwrite to replace.")

    service = _load_service(slug)
    docs_excerpt = _fetch_docs(service.get("docs_url"))
    prompt = _build_prompt(service, docs_excerpt)

    print(f"[generate] Calling {model} for {slug} (prompt={len(prompt)} chars)...")
    output = _call_gemini(prompt, model=model)

    # Attempt 1: parse + validate
    raw = _extract_json(output)
    if raw is None:
        raise SystemExit(
            "LLM output did not contain a parseable ```json``` block.\n"
            f"Last 1KB of output:\n{output[-1024:]}"
        )

    try:
        contract = parse_contract(raw, source=f"<generate {slug}>")
    except ContractError as e:
        # Retry once with error feedback
        print(f"[generate] First draft failed validation: {e}")
        print(f"[generate] Retrying with error in feedback prompt...")
        retry_prompt = (
            f"{prompt}\n\n"
            f"YOUR PREVIOUS RESPONSE FAILED VALIDATION WITH THIS ERROR:\n"
            f"  {e}\n\n"
            f"Produce a CORRECTED JSON contract that fixes the specific problem above."
        )
        output = _call_gemini(retry_prompt, model=model)
        raw = _extract_json(output)
        if raw is None:
            raise SystemExit(
                "Retry also produced no parseable JSON. Raw last 1KB:\n"
                f"{output[-1024:]}"
            )
        contract = parse_contract(raw, source=f"<generate {slug} retry>")

    # Enforce the honest-signup rules programmatically (Rule A + B from the
    # prompt). The LLM will sometimes slip these; catch it here rather than
    # letting a dishonest contract land in the registry.
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
                f"generated contract's signup test contains an env_secret step "
                f"(id={step.id}). That's the 'dishonest signup' anti-pattern "
                f"(Rule A). env_secret belongs in persistence/workflow only."
            )

    # Rule E — reject "homepage still responds" trivia as persistence /
    # workflow. When the service has no real API, the LLM likes to paper
    # over the gap by writing a persistence step that just GETs the
    # homepage and asserts 200. That turns into an F-P-P false positive:
    # the service has NO agent surface but the registry row looks partly
    # green. A persistence/workflow step must exercise an AUTHENTICATED
    # endpoint — either via env_secret + auth header, or by using state
    # produced by signup. Unauthenticated GETs of the service's landing
    # page don't count.
    def _is_authenticated_step(step) -> bool:
        headers = getattr(step, "headers", {}) or {}
        for v in headers.values():
            low = str(v).lower()
            if "bearer" in low or "apikey" in low or "api-key" in low or "token" in low:
                return True
        return False
    for test_name in ("persistence", "workflow"):
        test = contract.tests.get(test_name)
        if test is None:
            continue
        has_env_secret = any(
            getattr(s, "kind", None) == "env_secret" for s in test.steps
        )
        http_steps = [s for s in test.steps if getattr(s, "kind", None) == "http"]
        if not http_steps:
            continue
        any_authed = any(_is_authenticated_step(s) for s in http_steps)
        # If the test has no env_secret AND no auth-header on any http
        # step AND doesn't require signup-produced state, it's trivia.
        if not has_env_secret and not any_authed and not test.requires:
            raise SystemExit(
                f"generated contract's {test_name} test is 'homepage trivia' "
                f"(Rule E). Every http step is unauthenticated with no "
                f"env_secret and no `requires` from signup. That produces "
                f"FPP false positives on parked / no-API services. Use "
                f"env_secret + Authorization header, or declare a credential "
                f"from signup in `requires`."
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
