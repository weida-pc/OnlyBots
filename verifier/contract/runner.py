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
    Contract, TestSpec, AgentTask,
    HttpStep, PutFileStep, InjectNonceStep, EnvSecretStep, WaitStep, PollUntilStep,
    ReceiveEmailStep, SendSmsStep, ReceiveSmsStep,
    HttpStatusOk, ArtifactPresent, ContentServesNonce,
)


# ── Templating ────────────────────────────────────────────────────────────────

# Matches either an escape sequence `{{ ... }}` (emitted as literal `{ ... }`)
# OR a template var `{varname}`. The order matters: the escape alternative
# is listed first so re.sub tries to match it before the single-brace form.
_TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}|\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class TemplateError(Exception):
    """Raised when a contract references a state variable that doesn't exist.

    `.missing_key` is set when the cause is specifically "variable not in
    state" (the common failure mode when an earlier test was supposed to
    produce it). The step executor uses it to report a clean
    'prerequisite unmet' skip instead of a noisy HTTP-0 cascade.
    """

    def __init__(self, msg: str, missing_key: str | None = None):
        super().__init__(msg)
        self.missing_key = missing_key


def _render_string(s: str, state: dict) -> str:
    """Replace {varname} with str(state[varname]). Missing vars raise TemplateError.

    Escape syntax: `{{ literal }}` renders as `{ literal }` without variable
    substitution. Use this for contract prompts that include code samples or
    JSON examples containing braces (e.g. `const {{api_key}} = response` for
    a JavaScript destructure, or `{{"key": "value"}}` for a JSON literal).
    Without the escape, such prompts would trigger TemplateError because the
    runner would try to substitute `{api_key}` / `{"key": "value"}` as state
    variables.

    Also rejects templating non-scalar values (dict/list) since str() on those
    produces Python repr that breaks URLs, JSON bodies, and everything else.
    """
    def sub(m: re.Match) -> str:
        # Group 1 is the {{escape}} inner content; group 2 is the {var} name.
        # re.sub gives us the whole match; pick which branch was hit.
        escaped, key = m.group(1), m.group(2)
        if escaped is not None:
            # Literal: emit with single braces around the content.
            return "{" + escaped + "}"
        # Normal variable substitution path
        if key not in state:
            raise TemplateError(
                f"template variable {{{key}}} not in state; "
                f"available keys: {sorted(state.keys())}",
                missing_key=key,
            )
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


_CANONICAL_AUTH_PROBE_PATHS = (
    "/api/me", "/me", "/api/v1/me", "/api/v2/me",
    "/api/account", "/account", "/api/user", "/user",
    "/api/whoami", "/whoami", "/api/auth/me", "/auth/me",
    "/api/agents/me", "/api/agent", "/api/profile",
)


def _try_canonical_auth_probes(base_url: str, headers: dict) -> dict | None:
    """On probe_auth 404 against a URL the LLM invented, try common
    authenticated /me-shaped endpoints against the same origin. Returns
    the first 2xx response dict, or None if none succeed.

    Why this exists: the generator used to invent '/api/v1/me' as the
    probe URL for every service. When the real endpoint differs (most
    services), the 404 killed the signup test even though the agent
    successfully produced a working credential. This fallback gives us
    a last-chance auto-discovery.
    """
    try:
        from urllib.parse import urlparse
        parts = urlparse(base_url)
        origin = f"{parts.scheme}://{parts.netloc}"
    except Exception:
        return None
    for candidate in _CANONICAL_AUTH_PROBE_PATHS:
        candidate_url = origin + candidate
        if candidate_url == base_url:
            continue  # already tried
        r = _legacy.http_get(candidate_url, headers=headers, timeout=10)
        status = r.get("status", 0)
        if 200 <= status < 300:
            r["probed_via"] = f"fallback:{candidate}"
            return r
    return None


def _run_http(step: HttpStep, state: dict) -> dict:
    url = _render_string(step.url, state)
    headers = {k: _render_string(v, state) for k, v in step.headers.items()}

    resp: dict

    if step.method == "GET":
        # All GETs go through the resilient path (plain http.client first,
        # escalate to curl_cffi browser fingerprint on 5xx/blocked). This
        # costs nothing on the happy path and auto-handles Cloudflare-gated
        # services. `browser_fallback` with `must_contain_artifact` adds
        # content-check semantics on top of the same resilient escalation.
        needle = ""
        if step.browser_fallback and step.must_contain_artifact:
            needle = str(state.get(step.must_contain_artifact, "") or "")
        # http_get_resilient ignores headers arg today; headers-dependent auth
        # calls are rare on content-fetch GETs. If this bites, extend the
        # resilient helper to pass headers through.
        if headers:
            # When headers are set (e.g. Bearer auth), use plain http_get
            # first. Re-try with browser TLS ONLY on Cloudflare-shaped 403
            # responses; a real auth 403 from an API shouldn't escalate.
            resp = _legacy.http_get(url, headers=headers)

            if _legacy.looks_like_cloudflare_block(resp):
                browser_resp = _legacy.http_get_browser(
                    url, headers=headers, timeout=30
                )
                browser_resp["via"] = browser_resp.get("via") + " (cf-bypass)"
                # Only take the browser result if it actually improved on
                # the plain attempt — otherwise the original 403 is the
                # truthful answer.
                if 200 <= browser_resp.get("status", 0) < 400:
                    resp = browser_resp

            # probe_auth fallback: if an authenticated GET probe 404s and
            # there's a credential header, the LLM probably guessed the
            # wrong path. Try canonical /me-shaped endpoints on the same
            # origin before declaring the signup test failed.
            is_probe = step.id in ("probe_auth", "probe", "recheck_balance",
                                    "get_me", "whoami", "me_check")
            has_auth_header = any(
                k.lower() == "authorization" or k.lower().endswith("-api-key")
                or k.lower().endswith("-key")
                for k in headers.keys()
            )
            if resp.get("status") == 404 and is_probe and has_auth_header:
                fb = _try_canonical_auth_probes(url, headers)
                if fb is not None:
                    resp = fb
        else:
            resp = _legacy.http_get_resilient(url, must_contain=needle)
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


def _run_poll_until(step: PollUntilStep, state: dict) -> dict:
    url = _render_string(step.url, state)
    headers = {k: _render_string(v, state) for k, v in step.headers.items()}

    t_start = time.monotonic()
    last_status = 0
    last_body = ""
    attempts = 0

    for attempt in range(1, step.max_attempts + 1):
        attempts = attempt

        # Make the HTTP request
        if step.method == "GET":
            resp = _legacy.http_get(url, headers=headers or None)
        else:  # POST
            body = _render_any(step.body_json, state) if step.body_json is not None else {}
            resp = _legacy.http_post(url, body, headers=headers or None)

        last_status = resp.get("status", 0)
        last_body = resp.get("body", "")
        elapsed_ms = int((time.monotonic() - t_start) * 1000)

        # 5xx or network error → transient, retry
        if last_status == 0 or last_status >= 500:
            print(f"poll_until {step.id} attempt {attempt}: transient failure (status={last_status}), retrying")
            if attempt < step.max_attempts:
                time.sleep(step.interval_s)
            continue

        # 4xx → terminal failure
        if 400 <= last_status < 500:
            return {
                "step": f"{step.id}: {step.description or f'poll_until {url}'}",
                "step_id": step.id,
                "status": last_status,
                "body": last_body,
                "elapsed_ms": elapsed_ms,
                "error": f"poll_until got HTTP {last_status} — terminal",
                "attempts": attempts,
                "extracted": {},
            }

        # 2xx → check condition
        try:
            parsed = json.loads(last_body or "{}")
        except Exception:
            parsed = {}

        condition_result = _extract_value(parsed, step.condition)
        if condition_result is not None and condition_result not in (False, 0, "", [], {}):
            # Condition met — run extract, populate state, return success
            extracted = {}
            for state_key, expr in step.extract.items():
                val = _extract_value(parsed, expr)
                if val is not None:
                    state[state_key] = val
                    extracted[state_key] = val
            return {
                "step": f"{step.id}: {step.description or f'poll_until {url}'}",
                "step_id": step.id,
                "status": last_status,
                "body": last_body,
                "elapsed_ms": int((time.monotonic() - t_start) * 1000),
                "error": None,
                "attempts": attempts,
                "extracted": extracted,
            }

        # Condition not yet met → wait and retry
        if attempt < step.max_attempts:
            time.sleep(step.interval_s)

    # Exhausted all attempts
    elapsed_ms = int((time.monotonic() - t_start) * 1000)
    return {
        "step": f"{step.id}: {step.description or f'poll_until {url}'}",
        "step_id": step.id,
        "status": last_status,
        "body": last_body,
        "elapsed_ms": elapsed_ms,
        "error": f"poll_until exhausted after {step.max_attempts} attempts",
        "attempts": attempts,
        "extracted": {},
    }


_RECEIVE_EMAIL_MATCH_KEYS = {"from_contains", "subject_regex", "body_contains"}
_AGENTMAIL_API_BASE = "https://api.agentmail.to/v0"

_TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"
_RECEIVE_SMS_MATCH_KEYS = {"from_contains", "body_contains", "body_regex"}


def _run_receive_email(step: ReceiveEmailStep, state: dict) -> dict:
    """Poll an AgentMail inbox until a matching message arrives or attempts exhausted.

    Strategy:
      1. Record watermark t0 as an ISO timestamp.
      2. Use server-side ?after=<ISO> to filter messages by arrival time.
      3. For each candidate, optionally fetch the full message (GET /messages/{id})
         only when body_contains or body-extracting regex is needed.
      4. First message passing all match filters wins; extract into state, return.
      5. After max_attempts: return failure record.

    The returned body is a short summary (from + subject + any extracts only) —
    the full email body is never written to the step record.
    """
    import datetime

    inbox = _render_string(step.inbox, state)
    rendered_match = {k: _render_string(v, state) for k, v in step.match.items()}

    api_key = os.environ.get("AGENTMAIL_API_KEY", "")
    if not api_key:
        return {
            "step": f"{step.id}: {step.description or f'receive_email {inbox}'}",
            "step_id": step.id,
            "status": 0, "body": "", "elapsed_ms": 0,
            "error": "AGENTMAIL_API_KEY not set in environment",
            "attempts": 0, "extracted": {},
        }

    auth_headers = {"Authorization": f"Bearer {api_key}"}

    # Record watermark — ISO 8601 with Z suffix (UTC), truncated to seconds.
    t0_dt = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    t0_iso = t0_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    t0_monotonic = time.monotonic()

    needs_body = ("body_contains" in rendered_match or
                  any(v.startswith("regex:") for v in step.extract.values()))

    list_url = f"{_AGENTMAIL_API_BASE}/inboxes/{inbox}/messages"

    last_list_status = 0
    attempts = 0

    for attempt in range(1, step.max_attempts + 1):
        attempts = attempt
        elapsed_ms = int((time.monotonic() - t0_monotonic) * 1000)

        # Server-side ?after= filter — only messages after watermark.
        full_list_url = f"{list_url}?after={t0_iso}&ascending=true"
        resp = _legacy.http_get(full_list_url, headers=auth_headers)
        last_list_status = resp.get("status", 0)

        if last_list_status == 0 or last_list_status >= 500:
            # Transient error — retry
            if attempt < step.max_attempts:
                time.sleep(step.interval_s)
            continue

        if 400 <= last_list_status < 500:
            return {
                "step": f"{step.id}: {step.description or f'receive_email {inbox}'}",
                "step_id": step.id,
                "status": last_list_status,
                "body": resp.get("body", "")[:200],
                "elapsed_ms": elapsed_ms,
                "error": f"AgentMail list-messages returned HTTP {last_list_status}",
                "attempts": attempts, "extracted": {},
            }

        try:
            list_data = json.loads(resp.get("body", "") or "[]")
        except Exception:
            list_data = []

        # API may return a list directly or wrap it: {"messages": [...]}
        if isinstance(list_data, dict):
            messages = list_data.get("messages", [])
        elif isinstance(list_data, list):
            messages = list_data
        else:
            messages = []

        for msg in messages:
            if not isinstance(msg, dict):
                continue

            # Client-side timestamp guard (belt-and-suspenders against ?after= gaps).
            msg_ts_str = msg.get("timestamp") or msg.get("created_at") or ""
            if msg_ts_str:
                try:
                    msg_ts = datetime.datetime.fromisoformat(
                        msg_ts_str.replace("Z", "+00:00"))
                    if msg_ts < t0_dt:
                        continue
                except ValueError:
                    pass  # Unparseable timestamp — let it through, server filtered

            msg_from = msg.get("from", "") or ""
            msg_subject = msg.get("subject", "") or ""
            msg_preview = msg.get("preview", "") or ""
            msg_id = msg.get("message_id") or msg.get("id") or ""

            # Apply from_contains / subject_regex without fetching body.
            if "from_contains" in rendered_match:
                if rendered_match["from_contains"] not in msg_from:
                    continue
            if "subject_regex" in rendered_match:
                if not re.search(rendered_match["subject_regex"], msg_subject):
                    continue

            # Fetch full message if body is needed.
            msg_body_text = ""
            full_msg = msg  # default: use list-item fields
            if needs_body and msg_id:
                get_url = f"{_AGENTMAIL_API_BASE}/inboxes/{inbox}/messages/{msg_id}"
                get_resp = _legacy.http_get(get_url, headers=auth_headers)
                if get_resp.get("status", 0) == 200:
                    try:
                        full_msg = json.loads(get_resp.get("body", "") or "{}")
                    except Exception:
                        full_msg = msg
                    msg_body_text = full_msg.get("text", "") or ""

            if "body_contains" in rendered_match:
                if rendered_match["body_contains"] not in msg_body_text:
                    continue

            # All filters passed — this message matches.
            extracted = {}
            for state_key, expr in step.extract.items():
                if expr.startswith("regex:"):
                    pattern = expr[len("regex:"):]
                    m = re.search(pattern, msg_body_text)
                    val = m.group(1) if (m and m.lastindex and m.lastindex >= 1) else None
                else:
                    val = _extract_value(full_msg, expr)
                if val is not None:
                    state[state_key] = val
                    extracted[state_key] = val

            summary = f"from={msg_from!r} subject={msg_subject!r}"
            if extracted:
                summary += f" extracted={list(extracted.keys())}"

            return {
                "step": f"{step.id}: {step.description or f'receive_email {inbox}'}",
                "step_id": step.id,
                "status": 200,
                "body": summary,
                "elapsed_ms": int((time.monotonic() - t0_monotonic) * 1000),
                "error": None,
                "attempts": attempts,
                "extracted": extracted,
            }

        # No matching message yet — sleep and retry.
        if attempt < step.max_attempts:
            time.sleep(step.interval_s)

    elapsed_ms = int((time.monotonic() - t0_monotonic) * 1000)
    return {
        "step": f"{step.id}: {step.description or f'receive_email {inbox}'}",
        "step_id": step.id,
        "status": 0,
        "body": "",
        "elapsed_ms": elapsed_ms,
        "error": f"no matching email received after {step.max_attempts} attempts",
        "attempts": attempts,
        "extracted": {},
    }


def _run_send_sms(step: SendSmsStep, state: dict, contract: Contract) -> dict:
    """Send an outbound SMS via the Twilio Messages API using API key auth.

    Uses Basic Auth with TWILIO_API_KEY_SID:TWILIO_API_KEY_SECRET per
    https://www.twilio.com/docs/iam/api-keys. The response SID is stored in
    state as {step.id}_message_sid for downstream correlation.

    api.twilio.com must be in the contract's url_allowlist (enforced by the
    caller's sandbox check before this function is reached).
    """
    # Read credentials from env — all must be in contract.allowed_env
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    api_key_sid = os.environ.get("TWILIO_API_KEY_SID", "")
    api_key_secret = os.environ.get("TWILIO_API_KEY_SECRET", "")
    from_number = os.environ.get("TWILIO_PHONE_NUMBER", "")

    missing_env = [k for k, v in {
        "TWILIO_ACCOUNT_SID": account_sid,
        "TWILIO_API_KEY_SID": api_key_sid,
        "TWILIO_API_KEY_SECRET": api_key_secret,
        "TWILIO_PHONE_NUMBER": from_number,
    }.items() if not v]
    if missing_env:
        return {
            "step": f"{step.id}: {step.description or 'send_sms'}",
            "step_id": step.id,
            "status": 0, "body": "", "elapsed_ms": 0,
            "error": f"missing env vars: {missing_env}",
        }

    # Template-render destination and message body
    to_number = _render_string(step.to, state)
    sms_body = _render_string(step.body, state)

    # Build form-encoded body per Twilio Messages API spec
    form_data = urllib.parse.urlencode({
        "From": from_number,
        "To": to_number,
        "Body": sms_body,
    })
    url = f"{_TWILIO_API_BASE}/Accounts/{account_sid}/Messages.json"

    # Basic Auth: API Key SID as username, API Key Secret as password
    import base64
    credentials = base64.b64encode(
        f"{api_key_sid}:{api_key_secret}".encode("utf-8")
    ).decode("ascii")

    resp = _legacy._http_request(
        "POST", url,
        body=form_data.encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}",
        },
    )

    # Twilio returns 201 Created on success
    status = resp.get("status", 0)
    if status != 201:
        return {
            "step": f"{step.id}: {step.description or f'send_sms to {to_number}'}",
            "step_id": step.id,
            "status": status,
            "body": resp.get("body", "")[:500],
            "elapsed_ms": resp.get("elapsed_ms", 0),
            "error": f"Twilio returned HTTP {status} (expected 201)",
        }

    # Extract the message SID for downstream correlation
    try:
        msg_data = json.loads(resp.get("body", "") or "{}")
        msg_sid = msg_data.get("sid", "")
        if msg_sid:
            state[f"{step.id}_message_sid"] = msg_sid
    except Exception:
        msg_sid = ""

    return {
        "step": f"{step.id}: {step.description or f'send_sms to {to_number}'}",
        "step_id": step.id,
        "status": status,
        "body": f"sid={msg_sid} to={to_number} status={msg_data.get('status', '?')}",
        "elapsed_ms": resp.get("elapsed_ms", 0),
        "error": None,
    }


def _run_receive_sms(step: ReceiveSmsStep, state: dict) -> dict:
    """Poll twilio_inbound_sms table until a matching SMS arrives or max_attempts exhausted.

    Only messages received at or after step-entry time (t_start) are considered,
    preventing matches from old/stale messages.

    The returned body is a brief summary — never the full SMS body — to keep
    step records small and avoid logging sensitive content.
    """
    import datetime

    # Determine which phone number to watch
    to_number = (_render_string(step.to_number, state)
                 if step.to_number else os.environ.get("TWILIO_PHONE_NUMBER", ""))
    if not to_number:
        return {
            "step": f"{step.id}: {step.description or 'receive_sms'}",
            "step_id": step.id,
            "status": 0, "body": "", "elapsed_ms": 0,
            "error": "to_number not set and TWILIO_PHONE_NUMBER env var not set",
            "attempts": 0, "extracted": {},
        }

    rendered_match = {k: _render_string(v, state) for k, v in step.match.items()}

    # Watermark: only consider messages after step entry
    import db as _db
    t_start = datetime.datetime.now(datetime.timezone.utc)
    t0_monotonic = time.monotonic()

    attempts = 0
    last_db_error = None

    for attempt in range(1, step.max_attempts + 1):
        attempts = attempt
        elapsed_ms = int((time.monotonic() - t0_monotonic) * 1000)

        try:
            conn = _db.get_conn()
            try:
                import psycopg2.extras
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT message_sid, from_number, body, received_at
                        FROM twilio_inbound_sms
                        WHERE to_number = %s AND received_at >= %s
                        ORDER BY received_at ASC
                        """,
                        (to_number, t_start),
                    )
                    rows = cur.fetchall()
            finally:
                conn.close()
        except Exception as e:
            last_db_error = str(e)
            if attempt < step.max_attempts:
                time.sleep(step.interval_s)
            continue

        for row in rows:
            from_num = row["from_number"] or ""
            sms_body = row["body"] or ""
            received_at = row["received_at"]

            # Apply AND-semantics match filters
            if "from_contains" in rendered_match:
                if rendered_match["from_contains"] not in from_num:
                    continue
            if "body_contains" in rendered_match:
                if rendered_match["body_contains"] not in sms_body:
                    continue
            if "body_regex" in rendered_match:
                if not re.search(rendered_match["body_regex"], sms_body):
                    continue

            # All filters passed — extract and return
            extracted: dict = {}
            for state_key, expr in step.extract.items():
                if expr.startswith("regex:"):
                    pattern = expr[len("regex:"):]
                    m = re.search(pattern, sms_body)
                    val = m.group(1) if (m and m.lastindex and m.lastindex >= 1) else None
                elif expr == "body":
                    val = sms_body
                elif expr == "from_number":
                    val = from_num
                elif expr == "received_at":
                    val = received_at.isoformat() if hasattr(received_at, "isoformat") else str(received_at)
                else:
                    val = None
                if val is not None:
                    state[state_key] = val
                    extracted[state_key] = val

            # Summary only — no full body in step record
            preview = sms_body[:40] + ("…" if len(sms_body) > 40 else "")
            summary = f"from={from_num!r} body={preview!r}"
            if extracted:
                summary += f" extracted={list(extracted.keys())}"

            return {
                "step": f"{step.id}: {step.description or f'receive_sms on {to_number}'}",
                "step_id": step.id,
                "status": 200,
                "body": summary,
                "elapsed_ms": int((time.monotonic() - t0_monotonic) * 1000),
                "error": None,
                "attempts": attempts,
                "extracted": extracted,
            }

        # No match yet — sleep and retry
        if attempt < step.max_attempts:
            time.sleep(step.interval_s)

    elapsed_ms = int((time.monotonic() - t0_monotonic) * 1000)
    err_msg = f"no matching SMS received after {step.max_attempts} attempts"
    if last_db_error:
        err_msg += f" (last DB error: {last_db_error})"
    return {
        "step": f"{step.id}: {step.description or f'receive_sms on {to_number}'}",
        "step_id": step.id,
        "status": 0, "body": "",
        "elapsed_ms": elapsed_ms,
        "error": err_msg,
        "attempts": attempts, "extracted": {},
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


def _run_agent_task(task: AgentTask, state: dict) -> dict:
    """Run the Phase 2 agent task, merge its artifacts into state, and return
    a step-shaped record (so it shows up in the run's step list alongside HTTP
    steps, with a consistent schema for the DB and frontend).

    The task prompt is template-rendered against state BEFORE being passed to
    the agent. This lets `inject_nonce` / `env_secret` setup steps hand values
    to the agent (e.g. "embed this nonce: {herenow_nonce}"). A missing
    template variable here is a contract-authoring bug — the agent would
    otherwise get a prompt like "embed this nonce: {herenow_nonce}" literally.
    """
    # Local import so the contract package doesn't hard-depend on agent
    # when no contract uses agent_task. Keeps Phase 1-only deployments slim.
    from agent import run_agent_task

    rendered_prompt = _render_string(task.prompt, state)

    result = run_agent_task(
        prompt=rendered_prompt,
        expected_artifacts=task.expected_artifacts,
        model=task.model,
        timeout_s=task.timeout_s,
    )

    # Merge artifacts regardless of status. Even a "missing_keys" report may
    # contain partial claims the probes can still fail on — we want the
    # evidence, not just the verdict.
    for k, v in result.artifacts.items():
        if v not in (None, "", [], {}):
            state[k] = v

    ok = result.status == "ok"
    return {
        "step": f"_agent_task: {result.status}",
        "step_id": "_agent_task",
        "status": 200 if ok else 0,
        "body": json.dumps({
            "artifacts": result.artifacts,
            "missing_keys": result.missing_keys,
            "status": result.status,
            "model": result.model,
            "exit_code": result.exit_code,
        }, default=str),
        "elapsed_ms": int(result.elapsed_s * 1000),
        "error": result.error,
        "extracted": result.artifacts,
        "agent": {
            "status": result.status,
            "model": result.model,
            "elapsed_s": result.elapsed_s,
            "raw_output_tail": result.raw_output,
            "stderr_tail": result.stderr_tail,
        },
    }


def run_test_steps(contract: Contract, test_name: str, state: dict) -> list[dict]:
    """Execute all steps for the named test against the shared state.

    Order of execution:
      1. requires check (raises ContractRunError if state is missing them)
      2. agent_task if set — runs the LLM agent, merges artifacts into state
      3. steps — verifier's HTTP probes
      4. produces check (annotates missing produces as a synthetic step)
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

    # Execution order (regardless of declaration order in the contract):
    #   1. Setup steps (inject_nonce / env_secret / wait) populate state with
    #      values the agent or probes will reference.
    #   2. Agent task (if present) runs with setup state already in place, so
    #      its prompt can template-reference {nonce}, {api_key}, etc.
    #   3. Probe steps (http / put_file) are verifier's independent checks
    #      against what the agent claims — or the full direct-HTTP flow when
    #      agent_task is absent.
    setup_kinds = (InjectNonceStep, EnvSecretStep, WaitStep)
    setup_steps = [s for s in test.steps if isinstance(s, setup_kinds)]
    # send_sms and receive_sms are probe steps (run after setup + agent_task)
    probe_steps = [s for s in test.steps if not isinstance(s, setup_kinds)]

    def _execute_one(step: Any) -> None:
        # Sandbox URL check happens after template rendering for http/put_file/poll_until.
        # For receive_email the URL is fixed (_AGENTMAIL_API_BASE); check that host.
        try:
            if isinstance(step, (HttpStep, PutFileStep, PollUntilStep)):
                rendered_url = _render_string(step.url, state)
                err = _check_url_allowed(rendered_url, allowlist)
                if err:
                    steps_out.append({
                        "step": f"{step.id}: blocked by sandbox",
                        "step_id": step.id,
                        "status": 0, "body": "", "elapsed_ms": 0, "error": err,
                    })
                    return
            elif isinstance(step, ReceiveEmailStep):
                err = _check_url_allowed(_AGENTMAIL_API_BASE, allowlist)
                if err:
                    steps_out.append({
                        "step": f"{step.id}: blocked by sandbox",
                        "step_id": step.id,
                        "status": 0, "body": "", "elapsed_ms": 0, "error": err,
                    })
                    return
            elif isinstance(step, SendSmsStep):
                # Check that api.twilio.com is in the allowlist before sending
                err = _check_url_allowed(_TWILIO_API_BASE, allowlist)
                if err:
                    steps_out.append({
                        "step": f"{step.id}: blocked by sandbox",
                        "step_id": step.id,
                        "status": 0, "body": "", "elapsed_ms": 0, "error": err,
                    })
                    return
            # receive_sms uses only DB (no outbound URL to check)
        except TemplateError as e:
            # Missing state vars almost always mean "an earlier step that
            # was supposed to produce this didn't". Report it as a skip
            # with a clean prerequisite message instead of a confusing
            # "HTTP 0 + template variable not in state" line.
            missing = getattr(e, "missing_key", None)
            if missing:
                label = (f"{step.id}: skipped — prerequisite '{missing}' "
                         f"not produced by an earlier step")
            else:
                label = f"{step.id}: template error"
            steps_out.append({
                "step": label,
                "step_id": step.id,
                "status": 0, "body": "", "elapsed_ms": 0,
                "error": str(e),
                "skipped": True,
                "skip_reason": (
                    f"prerequisite '{missing}' missing from state"
                    if missing else "template error"
                ),
            })
            return

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
            elif isinstance(step, PollUntilStep):
                rec = _run_poll_until(step, state)
            elif isinstance(step, ReceiveEmailStep):
                rec = _run_receive_email(step, state)
            elif isinstance(step, SendSmsStep):
                rec = _run_send_sms(step, state, contract)
            elif isinstance(step, ReceiveSmsStep):
                rec = _run_receive_sms(step, state)
            else:
                rec = {"step": f"{getattr(step, 'id', '?')}: unknown step kind",
                       "step_id": getattr(step, "id", "?"),
                       "status": 0, "body": "", "elapsed_ms": 0,
                       "error": f"unknown step kind: {type(step).__name__}"}
        except TemplateError as e:
            missing = getattr(e, "missing_key", None)
            if missing:
                rec = {
                    "step": (f"{step.id}: skipped — prerequisite '{missing}' "
                              f"not produced by an earlier step"),
                    "step_id": step.id,
                    "status": 0, "body": "", "elapsed_ms": 0,
                    "error": str(e),
                    "skipped": True,
                    "skip_reason": f"prerequisite '{missing}' missing from state",
                }
            else:
                rec = {"step": f"{step.id}: template error", "step_id": step.id,
                       "status": 0, "body": "", "elapsed_ms": 0, "error": str(e)}
        except Exception as e:
            rec = {"step": f"{step.id}: exception", "step_id": step.id,
                   "status": 0, "body": "", "elapsed_ms": 0,
                   "error": f"{type(e).__name__}: {e}"}

        steps_out.append(rec)

    # 1. Setup
    for step in setup_steps:
        _execute_one(step)

    # 2. Agent task (after setup so prompt can reference setup state)
    if test.agent_task is not None:
        steps_out.append(_run_agent_task(test.agent_task, state))

    # 3. Probes
    for step in probe_steps:
        _execute_one(step)

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
        # Skipped-due-to-prerequisite: surface the real cause, not the
        # HTTP-0 noise. These are cascades from an upstream test that
        # didn't produce the state this step needed — the upstream
        # failure is what the registry should communicate.
        if step.get("skipped"):
            reason = step.get("skip_reason", "prerequisite unmet")
            return _assertion_result(False,
                f"step '{a.step}' skipped — {reason}")
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
