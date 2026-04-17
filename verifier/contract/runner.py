"""Contract runner — executes steps and evaluates assertions.

Two public functions:
  - run_test_steps(contract, test_name, state) -> list[step_record]
  - evaluate_verdict(contract, test_name, steps, state) -> {passed, confidence, reason, blocker}

Steps mutate the shared `state` dict (adding extracted artifacts). Assertions
are pure — they read state and steps and decide pass/fail.

Template syntax: `{varname}` is replaced with the string form of state[varname].
Unresolved variables raise an error at execution time so contracts fail loudly
rather than silently sending empty strings to an API.

Extraction syntax: JMESPath (https://jmespath.org/). Chain fallbacks with `||`.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import uuid
from typing import Any

import jmespath

# Import the low-level HTTP helpers from the existing executor module so we
# don't duplicate HTTP client logic — the contract runner is a layer *on top*
# of the HTTP primitives, not a replacement for them.
import executor as _legacy


from .schema import (
    Contract, TestSpec,
    HttpStep, PutFileStep, InjectNonceStep, EnvSecretStep, WaitStep,
    HttpStatusOk, ArtifactPresent, ContentServesNonce,
)


# ── Templating ────────────────────────────────────────────────────────────────

_TEMPLATE_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class TemplateError(Exception):
    """Raised when a contract references a state variable that doesn't exist."""
    pass


def _render_string(s: str, state: dict) -> str:
    """Replace {varname} with str(state[varname]). Missing vars raise TemplateError.

    Also rejects templating non-scalar values (dict/list) since str() on those
    produces Python repr that breaks URLs, JSON bodies, and everything else.
    The critique flagged silent type coercion here — this is the fix.
    """
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in state:
            raise TemplateError(f"template variable {{{key}}} not in state; "
                                f"available keys: {sorted(state.keys())}")
        val = state[key]
        if val is None:
            raise TemplateError(f"template variable {{{key}}} is None; "
                                f"check extraction in earlier step")
        if isinstance(val, (dict, list)):
            raise TemplateError(
                f"template variable {{{key}}} is {type(val).__name__}, "
                f"expected scalar. Fix the extract expression to pull out the "
                f"specific scalar field instead of the whole object.")
        return str(val)
    return _TEMPLATE_RE.sub(sub, s)


def _render_any(obj: Any, state: dict) -> Any:
    """Walk dicts/lists/strings recursively, templating every string."""
    if isinstance(obj, str):
        return _render_string(obj, state)
    if isinstance(obj, dict):
        return {k: _render_any(v, state) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_render_any(v, state) for v in obj]
    return obj


# ── JMESPath extraction with || fallback ──────────────────────────────────────

def _extract_value(data: Any, expr: str) -> Any:
    """Evaluate a JMESPath expression with `||` fallback chains.

    JMESPath's built-in `||` treats 0, False, empty list/dict, empty string
    as "falsy" and falls through. That matches our notion of "empty/unset"
    for the domain (URLs, IDs, API keys), so we just hand the whole
    expression to jmespath directly.

    Returns None if the expression doesn't resolve.
    """
    try:
        result = jmespath.search(expr, data)
    except jmespath.exceptions.JMESPathError:
        return None
    # JMESPath returns empty string/list/dict as-is; normalize "empty" to None
    if result in (None, "", [], {}):
        return None
    return result


# ── Step execution ────────────────────────────────────────────────────────────

def _step_record(step_id: str, description: str, raw: dict,
                  extra: dict | None = None) -> dict:
    """Build the canonical step dict stored in the run's steps list."""
    rec = {
        "step": f"{step_id}: {description}" if description else step_id,
        "step_id": step_id,
        "status": raw.get("status", 0),
        "body": raw.get("body", ""),
        "elapsed_ms": raw.get("elapsed_ms", 0),
        "error": raw.get("error"),
    }
    for k in ("via", "attempts", "nonce_found"):
        if k in raw:
            rec[k] = raw[k]
    if extra:
        rec.update(extra)
    return rec


def _run_http(step: HttpStep, state: dict) -> dict:
    url = _render_string(step.url, state)
    headers = {k: _render_string(v, state) for k, v in step.headers.items()}

    resp: dict

    if step.method == "GET":
        if step.browser_fallback:
            needle = ""
            if step.must_contain_artifact:
                needle = str(state.get(step.must_contain_artifact, "") or "")
            resp = _legacy.http_get_resilient(url, must_contain=needle)
        else:
            resp = _legacy.http_get(url, headers=headers or None)
    elif step.method == "POST":
        if step.body_raw is not None:
            body_str = _render_string(step.body_raw, state)
            resp = _legacy._http_request(
                "POST", url, body=body_str.encode("utf-8"),
                headers={"Content-Type": "application/json", **headers},
            )
        elif step.body_json is not None:
            body = _render_any(step.body_json, state)
            resp = _legacy.http_post(url, body, headers=headers or None)
        else:
            resp = _legacy.http_post(url, {}, headers=headers or None)
    elif step.method == "DELETE":
        resp = _legacy._http_request("DELETE", url, headers=headers or None)
    elif step.method == "PATCH":
        body_bytes = b""
        if step.body_json is not None:
            body_bytes = json.dumps(_render_any(step.body_json, state)).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        resp = _legacy._http_request("PATCH", url, body=body_bytes, headers=headers or None)
    else:
        # PUT as a normal http step (distinct from put_file which handles presigned)
        body_bytes = b""
        if step.body_raw is not None:
            body_bytes = _render_string(step.body_raw, state).encode("utf-8")
        elif step.body_json is not None:
            body_bytes = json.dumps(_render_any(step.body_json, state)).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        resp = _legacy._http_request("PUT", url, body=body_bytes, headers=headers or None)

    # Run extractions
    extracted = {}
    if step.extract:
        try:
            parsed = json.loads(resp.get("body", "") or "{}")
        except Exception:
            parsed = {}
        for state_key, expr in step.extract.items():
            val = _extract_value(parsed, expr)
            if val is not None:
                state[state_key] = val
                extracted[state_key] = val

    rec = _step_record(step.id, step.description or f"{step.method} {url}", resp,
                       extra={"extracted": extracted} if extracted else None)
    return rec


def _run_put_file(step: PutFileStep, state: dict) -> dict:
    url = _render_string(step.url, state)
    body = _render_string(step.body_template, state).encode("utf-8")
    content_type = _render_string(step.content_type, state)
    resp = _legacy.http_put(url, body, content_type=content_type)
    return _step_record(step.id, step.description or f"PUT {url[:80]}...", resp,
                        extra={"bytes_uploaded": len(body)})


def _run_inject_nonce(step: InjectNonceStep, state: dict) -> dict:
    nonce = f"{step.prefix}-{uuid.uuid4().hex[:16]}"
    state[step.state_key] = nonce
    return {
        "step": f"{step.id}: inject_nonce → state['{step.state_key}']",
        "step_id": step.id,
        "status": 200,  # non-HTTP step; 200 means "ran successfully"
        "body": f"nonce={nonce}",
        "elapsed_ms": 0,
        "error": None,
        "nonce": nonce,
    }


def _run_env_secret(step: EnvSecretStep, state: dict, contract: Contract) -> dict:
    if step.env_var not in contract.allowed_env:
        return {
            "step": f"{step.id}: env_secret {step.env_var}",
            "step_id": step.id,
            "status": 0, "body": "", "elapsed_ms": 0,
            "error": f"{step.env_var} not in contract.allowed_env",
        }
    val = os.environ.get(step.env_var, "")
    if val:
        state[step.state_key] = val
    status = 200 if val else (0 if step.required else 204)
    err = None
    if not val and step.required:
        err = f"required env var {step.env_var} not set"
    return {
        "step": f"{step.id}: env_secret {step.env_var} → state['{step.state_key}']",
        "step_id": step.id,
        "status": status,
        "body": "(redacted)" if val else "",
        "elapsed_ms": 0,
        "error": err,
    }


def _run_wait(step: WaitStep) -> dict:
    time.sleep(step.seconds)
    return {
        "step": f"{step.id}: wait {step.seconds}s",
        "step_id": step.id,
        "status": 200, "body": "", "elapsed_ms": int(step.seconds * 1000),
        "error": None,
    }


# ── URL allowlist enforcement (speed bump, NOT a sandbox) ─────────────────────

def _host_matches(host: str, pattern: str) -> bool:
    """Pattern can be a literal host or '*.example.com' to match subdomains."""
    if pattern.startswith("*."):
        suffix = pattern[1:]  # '.example.com'
        return host == pattern[2:] or host.endswith(suffix)
    return host == pattern


def _check_url_allowed(url: str, allowlist: list[str]) -> str | None:
    """Returns None if allowed, else an error string.

    FAIL-CLOSED: an empty allowlist rejects every URL. Previous behavior
    (empty = no restriction) was security-theater-code that lied to readers.
    If a contract genuinely needs to hit any URL, it must say so explicitly
    with `"url_allowlist": ["*"]` — a pattern that currently matches nothing
    (we don't implement a wildcard-everything), making the intent impossible
    to express silently.
    """
    if not allowlist:
        return ("url_allowlist is empty — fail-closed. Add the required hosts "
                "to contract.sandbox.url_allowlist.")
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return f"could not parse URL: {url}"
    if not any(_host_matches(host, p) for p in allowlist):
        return (f"host '{host}' not in url_allowlist {allowlist} "
                f"(step URL: {url[:120]})")
    return None


# ── Public API: run a test's steps ────────────────────────────────────────────

class ContractRunError(Exception):
    """Raised when a contract's declared requires/produces are violated.

    These are contract-authoring bugs, not service failures — they should
    surface immediately rather than producing confusing verification output.
    """
    pass


def _check_requires(test: TestSpec, test_name: str, state: dict) -> None:
    missing = [k for k in test.requires if k not in state or not state[k]]
    if missing:
        raise ContractRunError(
            f"test '{test_name}' requires {missing} but they're not in state "
            f"(available: {sorted(state.keys())}). An earlier test must "
            f"produce these, or this test shouldn't run in isolation.")


def _check_produces(test: TestSpec, test_name: str, state: dict) -> list[str]:
    """Returns list of keys that the contract promised to produce but didn't.
    Does not raise — the steps may have legitimately failed, and the assertion
    layer will report that. But we annotate the run so reviewers see when
    the produces declaration is stale.
    """
    return [k for k in test.produces if k not in state or not state[k]]


def run_test_steps(contract: Contract, test_name: str, state: dict) -> list[dict]:
    """Execute all steps for the named test against the shared state.

    Validates `requires` before running, and annotates unproduced `produces`
    as a synthetic final step. Raises ContractRunError if requires are not met
    (caller should surface as a contract-authoring bug, not a service failure).
    """
    test = contract.tests.get(test_name)
    if not test:
        return [{
            "step": f"contract has no test '{test_name}'",
            "step_id": "_missing", "status": 0, "body": "", "elapsed_ms": 0,
            "error": f"no test named '{test_name}' in contract for {contract.service_slug}",
        }]

    _check_requires(test, test_name, state)

    steps_out: list[dict] = []
    allowlist = contract.sandbox.url_allowlist

    for step in test.steps:
        # Sandbox URL check — happens after template rendering for http / put_file.
        try:
            if isinstance(step, (HttpStep, PutFileStep)):
                rendered_url = _render_string(step.url, state)
                err = _check_url_allowed(rendered_url, allowlist)
                if err:
                    steps_out.append({
                        "step": f"{step.id}: blocked by sandbox",
                        "step_id": step.id,
                        "status": 0, "body": "", "elapsed_ms": 0, "error": err,
                    })
                    continue
        except TemplateError as e:
            steps_out.append({
                "step": f"{step.id}: template error",
                "step_id": step.id,
                "status": 0, "body": "", "elapsed_ms": 0, "error": str(e),
            })
            continue

        try:
            if isinstance(step, HttpStep):
                rec = _run_http(step, state)
            elif isinstance(step, PutFileStep):
                rec = _run_put_file(step, state)
            elif isinstance(step, InjectNonceStep):
                rec = _run_inject_nonce(step, state)
            elif isinstance(step, EnvSecretStep):
                rec = _run_env_secret(step, state, contract)
            elif isinstance(step, WaitStep):
                rec = _run_wait(step)
            else:
                rec = {"step": f"{getattr(step, 'id', '?')}: unknown step kind",
                       "step_id": getattr(step, "id", "?"),
                       "status": 0, "body": "", "elapsed_ms": 0,
                       "error": f"unknown step kind: {type(step).__name__}"}
        except TemplateError as e:
            rec = {"step": f"{step.id}: template error", "step_id": step.id,
                   "status": 0, "body": "", "elapsed_ms": 0, "error": str(e)}
        except Exception as e:
            rec = {"step": f"{step.id}: exception", "step_id": step.id,
                   "status": 0, "body": "", "elapsed_ms": 0, "error": f"{type(e).__name__}: {e}"}

        steps_out.append(rec)

    # Annotate missing produces as a diagnostic step (not an assertion failure
    # — assertions check what actually matters; this flags stale declarations).
    missing = _check_produces(test, test_name, state)
    if missing:
        steps_out.append({
            "step": f"_produces_check: {len(missing)} unproduced artifact(s)",
            "step_id": "_produces_check",
            "status": 0, "body": "", "elapsed_ms": 0,
            "error": f"contract promised to produce {missing} but state is missing them",
        })

    return steps_out


# ── Assertion evaluation ──────────────────────────────────────────────────────

def _find_step(steps: list[dict], step_id: str) -> dict | None:
    return next((s for s in steps if s.get("step_id") == step_id), None)


def _ok(step: dict | None) -> bool:
    if not step:
        return False
    s = step.get("status", 0)
    return 200 <= s < 300


def _assertion_result(passed: bool, message: str) -> dict:
    return {"passed": passed, "message": message}


def _eval_assertion(a: Any, steps: list[dict], state: dict) -> dict:
    if isinstance(a, HttpStatusOk):
        step = _find_step(steps, a.step)
        if not step:
            return _assertion_result(False, f"step '{a.step}' not found")
        if _ok(step):
            return _assertion_result(True, f"step '{a.step}' returned HTTP {step['status']}")
        return _assertion_result(False,
            f"step '{a.step}' returned HTTP {step.get('status')} "
            f"{('(' + step['error'] + ')') if step.get('error') else ''}")

    if isinstance(a, ArtifactPresent):
        val = state.get(a.artifact)
        if val:
            s = str(val)
            return _assertion_result(True,
                f"artifact '{a.artifact}' present ({len(s)} chars, starts '{s[:20]}...')")
        return _assertion_result(False, f"artifact '{a.artifact}' missing or empty")

    if isinstance(a, ContentServesNonce):
        step = _find_step(steps, a.step)
        if not step:
            return _assertion_result(False, f"step '{a.step}' not found")
        nonce_found = bool(step.get("nonce_found"))
        via = step.get("via", "?")
        if nonce_found:
            return _assertion_result(True,
                f"step '{a.step}' served our nonce (HTTP {step.get('status')} via {via})")
        status = step.get("status")
        if status == 403:
            return _assertion_result(False,
                f"step '{a.step}' blocked (HTTP 403 via {via}); nonce not verifiable")
        if status and _ok(step):
            return _assertion_result(False,
                f"step '{a.step}' returned HTTP {status} via {via} "
                f"but our nonce is not in the body — content not served")
        return _assertion_result(False,
            f"step '{a.step}' returned HTTP {status} via {via}; nonce not found")

    return _assertion_result(False, f"unknown assertion kind: {type(a).__name__}")


def evaluate_verdict(contract: Contract, test_name: str, steps: list[dict],
                      state: dict) -> dict:
    """Return the {passed, confidence, reason, blocker} dict the test framework expects.

    All assertions must pass for the test to pass. The reason string concatenates
    every assertion's message so a human reading the DB row sees exactly what
    was checked and what failed.
    """
    test = contract.tests.get(test_name)
    if not test:
        return {"passed": False, "confidence": 1.0,
                "reason": f"no test '{test_name}' in contract",
                "blocker": "contract error"}

    if not test.assertions:
        return {"passed": False, "confidence": 1.0,
                "reason": "contract test has no assertions",
                "blocker": "contract error"}

    results = [(a, _eval_assertion(a, steps, state)) for a in test.assertions]
    all_passed = all(r["passed"] for _, r in results)

    passing = [r["message"] for _, r in results if r["passed"]]
    failing = [r["message"] for _, r in results if not r["passed"]]

    if all_passed:
        reason = " | ".join(f"✓ {m}" for m in passing)
        return {"passed": True, "confidence": 1.0, "reason": reason, "blocker": None}

    reason = (" | ".join(f"✗ {m}" for m in failing)
               + ((" | (passing: " + " | ".join(passing) + ")") if passing else ""))
    first_fail = next(r for _, r in results if not r["passed"])
    blocker = first_fail["message"]
    return {"passed": False, "confidence": 1.0, "reason": reason, "blocker": blocker}
