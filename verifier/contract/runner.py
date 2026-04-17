"""Contract runner — executes steps and evaluates assertions.

Two public functions:
  - run_test_steps(contract, test_name, state, built_ins) -> list[step_record]
  - evaluate_verdict(contract, test_name, steps, state) -> {passed, confidence, reason, blocker}

Steps mutate the shared `state` dict (adding extracted artifacts). Assertions
are pure — they read state and steps and decide pass/fail.

Template syntax: `{varname}` is replaced with the string form of state[varname].
Unresolved variables raise an error at execution time so contracts fail loudly
rather than silently sending empty strings to an API.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import uuid
from typing import Any

# Import the low-level HTTP helpers from the existing executor module so we
# don't duplicate HTTP client logic — the contract runner is a layer *on top*
# of the HTTP primitives, not a replacement for them.
import executor as _legacy


from .schema import (
    Contract, TestSpec,
    HttpStep, PutFileStep, InjectNonceStep, EnvSecretStep, WaitStep, ShellStep,
    HttpStatusOk, HttpBodyContains, ArtifactPresent,
    ContentServesNonce, AuthStillValid,
)


# ── Templating ────────────────────────────────────────────────────────────────

_TEMPLATE_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class TemplateError(Exception):
    """Raised when a contract references a state variable that doesn't exist."""
    pass


def _render_string(s: str, state: dict) -> str:
    """Replace {varname} with state[varname]. Missing vars raise TemplateError."""
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in state:
            raise TemplateError(f"template variable {{{key}}} not in state; "
                                f"available keys: {sorted(state.keys())}")
        val = state[key]
        return "" if val is None else str(val)
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


# ── JSONPath-ish extraction ───────────────────────────────────────────────────

def _walk_path(data: Any, path: str) -> Any:
    """Walk a dotted path through nested dicts/lists. Returns None if any
    segment misses. Numeric segments index into lists.

    e.g. walk_path({'a': [{'b': 1}]}, 'a.0.b') == 1
    """
    cur = data
    for seg in path.split("."):
        if cur is None:
            return None
        if seg.isdigit() and isinstance(cur, list):
            idx = int(seg)
            cur = cur[idx] if 0 <= idx < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            return None
    return cur


def _extract_value(data: Any, expr: str) -> Any:
    """Evaluate an extraction expression with `||` fallbacks.

    e.g. "upload.uploads.0.url || files.0.uploadUrl"
    Returns the first non-None, non-empty value.
    """
    for alt in [a.strip() for a in expr.split("||")]:
        val = _walk_path(data, alt)
        if val not in (None, ""):
            return val
    return None


# ── Step execution ────────────────────────────────────────────────────────────

def _step_record(step_id: str, description: str, raw: dict, extra: dict | None = None) -> dict:
    """Build the canonical step dict stored in the run's steps list.

    Shape matches what the legacy executors produced so the frontend + verdict
    evaluators can consume either source identically.
    """
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


def _run_shell(step: ShellStep, contract: Contract) -> dict:
    # Gated: contracts must explicitly opt-in AND the step must be pre-approved.
    # Not implemented in v1 — any shell step produces an error.
    return {
        "step": f"{step.id}: shell (disabled in v1)",
        "step_id": step.id,
        "status": 0, "body": "", "elapsed_ms": 0,
        "error": "shell step kind is not implemented in v1",
    }


# ── URL allowlist enforcement ─────────────────────────────────────────────────

def _host_matches(host: str, pattern: str) -> bool:
    """Pattern can be a literal host or '*.example.com' to match subdomains."""
    if pattern.startswith("*."):
        suffix = pattern[1:]  # '.example.com'
        return host == pattern[2:] or host.endswith(suffix)
    return host == pattern


def _check_url_allowed(url: str, allowlist: list[str]) -> str | None:
    """Returns None if allowed, else an error string."""
    if not allowlist:
        return None  # empty allowlist = no restriction (development mode)
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return f"could not parse URL: {url}"
    if not any(_host_matches(host, p) for p in allowlist):
        return (f"host '{host}' not in url_allowlist {allowlist} "
                f"(step URL: {url[:120]})")
    return None


# ── Public API: run a test's steps ────────────────────────────────────────────

def run_test_steps(contract: Contract, test_name: str, state: dict) -> list[dict]:
    """Execute all steps for the named test against the shared state."""
    test = contract.tests.get(test_name)
    if not test:
        return [{
            "step": f"contract has no test '{test_name}'",
            "step_id": "_missing", "status": 0, "body": "", "elapsed_ms": 0,
            "error": f"no test named '{test_name}' in contract for {contract.service_slug}",
        }]

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
            elif isinstance(step, ShellStep):
                rec = _run_shell(step, contract)
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


def _eval_assertion(a: Assertion, steps: list[dict], state: dict) -> dict:
    if isinstance(a, HttpStatusOk):
        step = _find_step(steps, a.step)
        if not step:
            return _assertion_result(False, f"step '{a.step}' not found")
        if _ok(step):
            return _assertion_result(True, f"step '{a.step}' returned HTTP {step['status']}")
        return _assertion_result(False,
            f"step '{a.step}' returned HTTP {step.get('status')} "
            f"{('(' + step['error'] + ')') if step.get('error') else ''}")

    if isinstance(a, HttpBodyContains):
        step = _find_step(steps, a.step)
        if not step:
            return _assertion_result(False, f"step '{a.step}' not found")
        needle = a.needle
        if a.needle_artifact:
            needle = state.get(a.needle_artifact, "")
        if not needle:
            return _assertion_result(False,
                f"needle for step '{a.step}' is empty "
                f"(needle={a.needle!r}, needle_artifact={a.needle_artifact!r})")
        body = step.get("body", "") or ""
        found = needle in body
        label = f"'{needle[:40]}'"
        return _assertion_result(found,
            f"step '{a.step}' body {'contains' if found else 'does NOT contain'} {label}")

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

    if isinstance(a, AuthStillValid):
        step = _find_step(steps, a.step)
        if not step:
            return _assertion_result(False, f"step '{a.step}' not found")
        if _ok(step):
            return _assertion_result(True,
                f"auth-gated step '{a.step}' returned HTTP {step['status']} — credential valid")
        return _assertion_result(False,
            f"auth-gated step '{a.step}' returned HTTP {step.get('status')} — credential rejected")

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
    # Blocker = first failing assertion's short label
    first_fail = next(r for _, r in results if not r["passed"])
    blocker = first_fail["message"]
    return {"passed": False, "confidence": 1.0, "reason": reason, "blocker": blocker}
