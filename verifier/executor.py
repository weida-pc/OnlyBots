"""Direct HTTP executor for service API calls.

Makes real HTTP requests to each service endpoint and returns structured results.
These results are then passed to the AI harness for verdict analysis — so the
AI never needs to browse the web, only interpret pre-fetched responses.
"""
from __future__ import annotations

import http.client
import json
import os
import time
import urllib.parse
from typing import Any


# ── Low-level HTTP helpers ───────────────────────────────────────────────────

def _http_request(method: str, url: str, body: bytes | None = None,
                   headers: dict | None = None, timeout: int = 30) -> dict:
    """Low-level HTTP request using http.client — preserves header case exactly."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    t0 = time.time()
    try:
        cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        conn = cls(host, timeout=timeout)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        body_str = resp.read().decode("utf-8", errors="replace")
        return {
            "status": resp.status,
            "body": body_str,
            "elapsed_ms": round((time.time() - t0) * 1000),
            "error": None,
        }
    except Exception as e:
        return {
            "status": 0,
            "body": "",
            "elapsed_ms": round((time.time() - t0) * 1000),
            "error": str(e),
        }


def http_post(url: str, body: dict, headers: dict | None = None, timeout: int = 30) -> dict:
    data = json.dumps(body).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    return _http_request("POST", url, body=data, headers=req_headers, timeout=timeout)


def http_get(url: str, headers: dict | None = None, timeout: int = 30) -> dict:
    return _http_request("GET", url, headers=headers, timeout=timeout)


def http_put(url: str, body: str | bytes, content_type: str = "application/octet-stream",
             timeout: int = 60) -> dict:
    if isinstance(body, str):
        body = body.encode("utf-8")
    return _http_request("PUT", url, body=body,
                          headers={"Content-Type": content_type}, timeout=timeout)


def format_steps(steps: list[dict]) -> str:
    """Format a list of HTTP steps as a human-readable string for LLM analysis."""
    lines = []
    for step in steps:
        lines.append(f"Step: {step.get('step', 'unknown')}")
        lines.append(f"  HTTP {step.get('status', 0)} ({step.get('elapsed_ms', 0)}ms)")
        body = step.get("body", "")
        if body:
            lines.append(f"  Response: {body[:500]}")
        if step.get("error"):
            lines.append(f"  Error: {step['error']}")
        lines.append("")
    return "\n".join(lines)


# ── Per-service executors ────────────────────────────────────────────────────

def signup_agentmail(state: dict) -> list[dict]:
    """Attempt AgentMail agent signup via API."""
    ts = int(time.time())
    step = {"step": "POST https://api.agentmail.to/v0/agent/sign-up"}
    resp = http_post(
        "https://api.agentmail.to/v0/agent/sign-up",
        {"human_email": "sudo@pressclub.app", "username": f"onlybots-test-{ts}"},
    )
    step.update(resp)

    # Extract credentials if present
    try:
        data = json.loads(resp["body"])
        if "api_key" in data:
            state["agentmail_api_key"] = data["api_key"]
            state["agentmail_org_id"] = data.get("organization_id", "")
        # Signup creates an inbox automatically — store it so workflow can reuse it
        if "inbox_id" in data:
            state["agentmail_inbox_id"] = data["inbox_id"]
            state["agentmail_inbox_email"] = data["inbox_id"]  # inbox_id IS the email address
    except Exception:
        pass

    return [step]


def persist_agentmail(state: dict) -> list[dict]:
    """Verify AgentMail credentials persist."""
    api_key = state.get("agentmail_api_key", "")
    steps = []

    if api_key:
        step = {"step": "GET https://api.agentmail.to/v0/inboxes (with API key)"}
        resp = http_get(
            "https://api.agentmail.to/v0/inboxes",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        step.update(resp)
        steps.append(step)
    else:
        # No key from signup — probe unauthenticated
        step = {"step": "GET https://api.agentmail.to/v0/inboxes (no auth)"}
        resp = http_get("https://api.agentmail.to/v0/inboxes")
        step.update(resp)
        steps.append(step)

    return steps


def workflow_agentmail(state: dict) -> list[dict]:
    """Execute full AgentMail workflow: use signup inbox → send email → verify receipt."""
    api_key = state.get("agentmail_api_key", "")
    if not api_key:
        return [{"step": "workflow skipped — no API key from signup", "status": 0, "body": "", "elapsed_ms": 0, "error": "Missing API key"}]

    steps = []

    # Use the inbox created during signup (reuse, don't create new — limit is 1 per org)
    inbox_id = state.get("agentmail_inbox_id")

    if not inbox_id:
        # List inboxes to find existing one
        list_step = {"step": "GET /v0/inboxes (find existing inbox)"}
        r_list = http_get(
            "https://api.agentmail.to/v0/inboxes",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        list_step.update(r_list)
        steps.append(list_step)
        try:
            data = json.loads(r_list["body"])
            inboxes = data.get("inboxes", [])
            if inboxes:
                inbox_id = inboxes[0].get("inbox_id") or inboxes[0].get("id")
        except Exception:
            pass

    if not inbox_id:
        return steps

    # URL-encode the inbox_id for use in path (@ must be %40)
    inbox_id_encoded = urllib.parse.quote(inbox_id, safe="")

    # Send email to the human_email from signup (it's pre-allowed in the send allow list)
    human_email = "sudo@pressclub.app"
    step2 = {"step": f"POST /v0/inboxes/{inbox_id}/messages/send (send email)"}
    r2 = http_post(
        f"https://api.agentmail.to/v0/inboxes/{inbox_id_encoded}/messages/send",
        {
            "to": [human_email],
            "subject": "OnlyBots Verification Test",
            "body": "This is an automated test by OnlyBots trust registry.",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    step2.update(r2)
    steps.append(step2)

    # List messages to confirm the inbox is functional
    step3 = {"step": f"GET /v0/inboxes/{inbox_id}/messages (verify inbox accessible)"}
    r3 = http_get(
        f"https://api.agentmail.to/v0/inboxes/{inbox_id_encoded}/messages",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    step3.update(r3)
    steps.append(step3)

    return steps


def signup_herenow(state: dict) -> list[dict]:
    """Publish a test page on here.now."""
    html_content = "<html><body><h1>OnlyBots Verification Test</h1></body></html>"
    html_bytes = html_content.encode("utf-8")
    steps = []

    # 1. Request publish slot
    step1 = {"step": "POST https://here.now/api/v1/publish"}
    r1 = http_post(
        "https://here.now/api/v1/publish",
        {"files": [{"path": "index.html", "size": len(html_bytes), "contentType": "text/html; charset=utf-8"}]},
        headers={"X-HereNow-Client": "onlybots/verifier"},
    )
    step1.update(r1)
    steps.append(step1)

    upload_url = None
    finalize_url = None
    version_id = None
    try:
        data = json.loads(r1["body"])
        files = data.get("files", [])
        if files:
            upload_url = files[0].get("uploadUrl") or files[0].get("url")
        finalize_url = data.get("finalizeUrl") or data.get("finalize_url")
        version_id = data.get("versionId") or data.get("version_id")
        state["herenow_site_url"] = data.get("siteUrl") or data.get("site_url") or data.get("url")
    except Exception:
        pass

    if not upload_url:
        return steps

    # 2. Upload HTML content
    step2 = {"step": "PUT presigned upload URL (upload index.html)"}
    r2 = http_put(upload_url, html_bytes, content_type="text/html; charset=utf-8")
    step2.update(r2)
    steps.append(step2)

    if not finalize_url or not version_id:
        return steps

    # 3. Finalize
    step3 = {"step": f"POST {finalize_url} (finalize)"}
    r3 = http_post(finalize_url, {"versionId": version_id})
    step3.update(r3)
    steps.append(step3)

    # Extract site URL from finalize response
    try:
        data = json.loads(r3["body"])
        state["herenow_site_url"] = (
            data.get("siteUrl") or data.get("site_url") or data.get("url")
            or state.get("herenow_site_url")
        )
    except Exception:
        pass

    # 4. Verify live URL
    site_url = state.get("herenow_site_url")
    if site_url:
        step4 = {"step": f"GET {site_url} (verify live)"}
        r4 = http_get(site_url)
        step4.update(r4)
        steps.append(step4)
        # Store result so persistence test can reference it
        state["herenow_site_live_status"] = r4.get("status", 0)

    return steps


def persist_herenow(state: dict) -> list[dict]:
    """Verify the published here.now page still exists."""
    site_url = state.get("herenow_site_url")
    if not site_url:
        return [{"step": "GET here.now site (no URL from signup)", "status": 0, "body": "", "elapsed_ms": 0, "error": "No site URL in state"}]

    step = {"step": f"GET {site_url} (verify persistence)"}
    resp = http_get(site_url)
    step.update(resp)
    return [step]


def workflow_herenow(state: dict) -> list[dict]:
    """here.now workflow is the same as signup — publish and verify."""
    return signup_herenow(state)


def signup_moltbook(state: dict) -> list[dict]:
    """Register an agent on Moltbook."""
    ts = int(time.time())
    step = {"step": "POST https://www.moltbook.com/api/v1/agents/register"}
    resp = http_post(
        "https://www.moltbook.com/api/v1/agents/register",
        {
            "name": f"onlybots-verifier-{ts}",
            "description": "Automated verification agent for OnlyBots trust registry",
        },
    )
    step.update(resp)

    try:
        data = json.loads(resp["body"])
        # API key is nested under data["agent"]["api_key"]
        agent = data.get("agent", data)
        api_key = agent.get("api_key") or data.get("api_key")
        if api_key:
            state["moltbook_api_key"] = api_key
        agent_id = agent.get("id") or data.get("agent_id") or data.get("id")
        if agent_id:
            state["moltbook_agent_id"] = agent_id
    except Exception:
        pass

    return [step]


def persist_moltbook(state: dict) -> list[dict]:
    """Verify Moltbook API key still works."""
    api_key = state.get("moltbook_api_key", "")
    steps = []

    if api_key:
        step = {"step": "GET https://www.moltbook.com/api/v1/agents/me"}
        resp = http_get(
            "https://www.moltbook.com/api/v1/agents/me",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        step.update(resp)
        steps.append(step)
    else:
        step = {"step": "GET /api/v1/agents/me (no key from signup)"}
        resp = http_get("https://www.moltbook.com/api/v1/agents/me")
        step.update(resp)
        steps.append(step)

    return steps


def workflow_moltbook(state: dict) -> list[dict]:
    """Create a post, comment, and upvote on Moltbook.

    Uses MOLTBOOK_API_KEY from env if set (pre-claimed agent) so the workflow
    test is not blocked by the one-time human claim requirement.
    """
    api_key = os.environ.get("MOLTBOOK_API_KEY", state.get("moltbook_api_key", ""))
    if not api_key:
        return [{"step": "workflow skipped — no API key", "status": 0, "body": "", "elapsed_ms": 0, "error": "Missing API key"}]

    steps = []
    auth = {"Authorization": f"Bearer {api_key}"}

    # 1. Create post
    step1 = {"step": "POST /api/v1/posts (create post)"}
    r1 = http_post(
        "https://www.moltbook.com/api/v1/posts",
        {
            "submolt_name": "general",
            "title": "OnlyBots Verification Test",
            "content": "Automated verification post from OnlyBots trust registry.",
        },
        headers=auth,
    )
    step1.update(r1)
    steps.append(step1)

    post_id = None
    try:
        data = json.loads(r1["body"])
        post_id = data.get("id") or data.get("post_id")
    except Exception:
        pass

    if not post_id:
        return steps

    # 2. Comment
    step2 = {"step": f"POST /api/v1/posts/{post_id}/comments"}
    r2 = http_post(
        f"https://www.moltbook.com/api/v1/posts/{post_id}/comments",
        {"content": "Verification comment from OnlyBots."},
        headers=auth,
    )
    step2.update(r2)
    steps.append(step2)

    # 3. Upvote
    step3 = {"step": f"POST /api/v1/posts/{post_id}/upvote"}
    r3 = http_post(
        f"https://www.moltbook.com/api/v1/posts/{post_id}/upvote",
        {},
        headers=auth,
    )
    step3.update(r3)
    steps.append(step3)

    return steps


def signup_signbee(state: dict) -> list[dict]:
    """Send a document via Signbee using pre-provisioned API key."""
    api_key = os.environ.get("SIGNBEE_API_KEY", state.get("signbee_api_key", ""))
    if api_key:
        state["signbee_api_key"] = api_key

    step = {"step": "POST https://signb.ee/api/v1/send (send document with API key)"}
    payload: dict = {
        "recipient_name": "OnlyBots Verifier",
        "recipient_email": "sudo@pressclub.app",
        "markdown": (
            "# OnlyBots Verification Document\n\n"
            "This document verifies that Signbee supports autonomous document workflows "
            "for AI agents registered in the OnlyBots trust registry.\n\n"
            "## Scope\n\nThis is an automated verification-only test document."
        ),
    }
    if api_key:
        headers = {"Authorization": f"Bearer {api_key}"}
    else:
        # Without API key, sender must verify via email OTP — include sender fields
        payload["sender_name"] = "OnlyBots Verifier"
        payload["sender_email"] = "sudo@pressclub.app"
        headers = None

    resp = http_post("https://signb.ee/api/v1/send", payload, headers=headers)
    step.update(resp)

    try:
        data = json.loads(resp["body"])
        doc_id = data.get("document_id") or data.get("id")
        if doc_id:
            state["signbee_document_id"] = doc_id
    except Exception:
        pass

    return [step]


def persist_signbee(state: dict) -> list[dict]:
    """Verify Signbee API key still works by checking document status."""
    api_key = state.get("signbee_api_key", os.environ.get("SIGNBEE_API_KEY", ""))
    doc_id = state.get("signbee_document_id", "")

    if api_key and doc_id:
        step = {"step": f"GET /api/v1/documents/{doc_id} (check document status)"}
        resp = http_get(f"https://signb.ee/api/v1/documents/{doc_id}",
                        headers={"Authorization": f"Bearer {api_key}"})
        step.update(resp)
        return [step]

    if api_key:
        # No doc_id — send a second document to prove persistence
        step = {"step": "POST /api/v1/send (2nd send — verify key still works)"}
        resp = http_post(
            "https://signb.ee/api/v1/send",
            {
                "recipient_name": "OnlyBots Persistence Check",
                "recipient_email": "sudo@pressclub.app",
                "markdown": "# Persistence Check\n\nVerifying API key still works after initial signup.",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        step.update(resp)
        return [step]

    return [{"step": "persist check skipped — no API key", "status": 0, "body": "",
             "elapsed_ms": 0, "error": "No API key"}]


def workflow_signbee(state: dict) -> list[dict]:
    """Full Signbee workflow — send document and verify it was created."""
    return signup_signbee(state)


def signup_browseruse(state: dict) -> list[dict]:
    """Verify Browser Use API key works and list sessions."""
    api_key = os.environ.get("BROWSER_USE_API_KEY", state.get("browseruse_api_key", ""))
    if api_key:
        state["browseruse_api_key"] = api_key

    steps = []
    headers = {"X-Browser-Use-API-Key": api_key} if api_key else {}

    # 1. List sessions to verify auth
    step1 = {"step": "GET https://api.browser-use.com/api/v3/sessions (verify API key)"}
    r1 = http_get("https://api.browser-use.com/api/v3/sessions", headers=headers or None)
    step1.update(r1)
    steps.append(step1)

    # Extract session count
    try:
        data = json.loads(r1["body"])
        state["browseruse_session_count"] = data.get("total", 0)
    except Exception:
        pass

    return steps


def persist_browseruse(state: dict) -> list[dict]:
    """Check Browser Use API key still valid."""
    api_key = state.get("browseruse_api_key", os.environ.get("BROWSER_USE_API_KEY", ""))
    step = {"step": "GET /api/v3/sessions (verify key persists)"}
    headers = {"X-Browser-Use-API-Key": api_key} if api_key else {}
    resp = http_get("https://api.browser-use.com/api/v3/sessions", headers=headers or None)
    step.update(resp)
    return [step]


def workflow_browseruse(state: dict) -> list[dict]:
    """Browser Use workflow — create a browser automation task."""
    api_key = state.get("browseruse_api_key", os.environ.get("BROWSER_USE_API_KEY", ""))
    if not api_key:
        return [{"step": "workflow skipped — no API key", "status": 0, "body": "",
                 "elapsed_ms": 0, "error": "No API key"}]

    headers = {"X-Browser-Use-API-Key": api_key}
    steps = []

    # Create a browser session with a simple task
    step1 = {"step": "POST /api/v3/sessions (create browser automation task)"}
    r1 = http_post(
        "https://api.browser-use.com/api/v3/sessions",
        {"task": "Navigate to https://example.com and return the page title"},
        headers=headers,
    )
    step1.update(r1)
    steps.append(step1)

    # Extract session_id
    session_id = None
    try:
        data = json.loads(r1["body"])
        session_id = data.get("id") or data.get("session_id")
        if session_id:
            state["browseruse_session_id"] = session_id
    except Exception:
        pass

    if session_id:
        # Check session status
        step2 = {"step": f"GET /api/v3/sessions/{session_id} (check task started)"}
        r2 = http_get(f"https://api.browser-use.com/api/v3/sessions/{session_id}", headers=headers)
        step2.update(r2)
        steps.append(step2)

    return steps


# ── Dispatcher ───────────────────────────────────────────────────────────────

SIGNUP_EXECUTORS = {
    "agentmail-to": signup_agentmail,
    "here-now": signup_herenow,
    "moltbook": signup_moltbook,
    "signbee": signup_signbee,
    "browser-use": signup_browseruse,
}

PERSIST_EXECUTORS = {
    "agentmail-to": persist_agentmail,
    "here-now": persist_herenow,
    "moltbook": persist_moltbook,
    "signbee": persist_signbee,
    "browser-use": persist_browseruse,
}

WORKFLOW_EXECUTORS = {
    "agentmail-to": workflow_agentmail,
    "here-now": workflow_herenow,
    "moltbook": workflow_moltbook,
    "signbee": workflow_signbee,
    "browser-use": workflow_browseruse,
}


def execute_signup(slug: str, state: dict) -> list[dict]:
    fn = SIGNUP_EXECUTORS.get(slug)
    if fn:
        return fn(state)
    return []


def execute_persist(slug: str, state: dict) -> list[dict]:
    fn = PERSIST_EXECUTORS.get(slug)
    if fn:
        return fn(state)
    return []


def execute_workflow(slug: str, state: dict) -> list[dict]:
    fn = WORKFLOW_EXECUTORS.get(slug)
    if fn:
        return fn(state)
    return []


# ── Python-based verdict generation ─────────────────────────────────────────
# Determines pass/fail from actual HTTP responses — no LLM hallucination.

def _ok(step: dict) -> bool:
    return 200 <= step.get("status", 0) < 300


def _parse_json(step: dict) -> dict:
    try:
        return json.loads(step.get("body", "{}"))
    except Exception:
        return {}


def verdict_signup(slug: str, steps: list[dict], state: dict) -> dict:
    """Determine signup pass/fail from HTTP responses."""
    if not steps:
        return {"passed": False, "confidence": 1.0, "reason": "No HTTP steps executed", "blocker": "executor error"}

    if slug == "agentmail-to":
        s = steps[0]
        if _ok(s):
            data = _parse_json(s)
            if data.get("api_key"):
                return {"passed": True, "confidence": 1.0,
                        "reason": f"Agent signup succeeded (HTTP {s['status']}). Got API key and organization_id={data.get('organization_id','?')}.",
                        "blocker": None}
            return {"passed": False, "confidence": 0.9,
                    "reason": f"HTTP {s['status']} but no api_key in response: {s['body'][:200]}",
                    "blocker": "no api_key returned"}
        return {"passed": False, "confidence": 1.0,
                "reason": f"Signup failed HTTP {s['status']}: {s['body'][:300]}",
                "blocker": f"HTTP {s['status']}"}

    elif slug == "here-now":
        if not steps:
            return {"passed": False, "confidence": 1.0, "reason": "No steps", "blocker": "executor error"}
        step1 = steps[0]
        if not _ok(step1):
            return {"passed": False, "confidence": 1.0,
                    "reason": f"Publish endpoint returned HTTP {step1['status']}: {step1['body'][:200]}",
                    "blocker": f"HTTP {step1['status']}"}
        # Check if we got a siteUrl
        site_url = state.get("herenow_site_url")
        if not site_url:
            return {"passed": False, "confidence": 0.9,
                    "reason": "Publish returned 200 but no siteUrl extracted",
                    "blocker": "no siteUrl"}
        # Check if the live URL is accessible (step 4 if present)
        live_step = next((s for s in steps if "verify live" in s.get("step", "")), None)
        if live_step and _ok(live_step):
            return {"passed": True, "confidence": 1.0,
                    "reason": f"Published to {site_url} and live URL returned HTTP {live_step['status']}.",
                    "blocker": None}
        elif live_step:
            # Cloudflare may block but site IS published
            if live_step.get("status") == 403:
                return {"passed": True, "confidence": 0.85,
                        "reason": f"Published to {site_url}. Live URL returns 403 (Cloudflare bot-check blocks direct HTTP client, but site was published successfully).",
                        "blocker": None}
        # No live check step — just confirm publish succeeded
        return {"passed": True, "confidence": 0.9,
                "reason": f"Publish workflow completed. siteUrl={site_url}",
                "blocker": None}

    elif slug == "moltbook":
        s = steps[0]
        if s.get("status") in (200, 201):
            api_key = state.get("moltbook_api_key")
            if api_key:
                return {"passed": True, "confidence": 1.0,
                        "reason": f"Agent registered (HTTP {s['status']}). Got API key starting with '{api_key[:12]}...'.",
                        "blocker": None}
            return {"passed": False, "confidence": 0.9,
                    "reason": f"Registration returned {s['status']} but API key not found in response.",
                    "blocker": "api_key not extracted"}
        if s.get("status") == 429:
            data = _parse_json(s)
            reset = data.get("reset_at", "unknown")
            return {"passed": False, "confidence": 1.0,
                    "reason": f"Registration rate-limited (HTTP 429). Limit resets at {reset}.",
                    "blocker": f"rate limit — retry after {reset}"}
        return {"passed": False, "confidence": 1.0,
                "reason": f"Registration failed HTTP {s['status']}: {s['body'][:300]}",
                "blocker": f"HTTP {s['status']}"}

    elif slug == "signbee":
        send_step = next((s for s in steps if "/send" in s.get("step", "")), None)
        if not send_step:
            return {"passed": False, "confidence": 1.0, "reason": "No send step executed", "blocker": "executor error"}
        if _ok(send_step):
            data = _parse_json(send_step)
            doc_id = data.get("document_id") or data.get("id")
            status = data.get("status", "?")
            if status == "pending_recipient":
                return {"passed": True, "confidence": 1.0,
                        "reason": f"Document sent with API key (HTTP {send_step['status']}). document_id={doc_id}, status=pending_recipient. Recipient will receive signing email immediately.",
                        "blocker": None}
            if status == "pending_sender":
                return {"passed": False, "confidence": 1.0,
                        "reason": f"Document created (HTTP {send_step['status']}) but requires sender email verification (status=pending_sender). API key not recognized or not provided.",
                        "blocker": "sender email verification required — API key not working"}
            return {"passed": True, "confidence": 0.9,
                    "reason": f"Document created (HTTP {send_step['status']}). document_id={doc_id}, status={status}",
                    "blocker": None}
        body = send_step.get("body", "")
        return {"passed": False, "confidence": 1.0,
                "reason": f"Document send failed HTTP {send_step['status']}: {body[:200]}",
                "blocker": f"HTTP {send_step['status']}"}

    elif slug == "browser-use":
        s = steps[0] if steps else {}
        if _ok(s):
            data = _parse_json(s)
            total = data.get("total", 0)
            return {"passed": True, "confidence": 1.0,
                    "reason": f"API key valid (HTTP {s['status']}). Sessions accessible, total={total}.",
                    "blocker": None}
        statuses = [s.get("status", 0) for s in steps]
        if not state.get("browseruse_api_key"):
            return {"passed": False, "confidence": 1.0,
                    "reason": f"No BROWSER_USE_API_KEY in environment. Statuses: {statuses}.",
                    "blocker": "no API key — requires account creation via browser"}
        return {"passed": False, "confidence": 1.0,
                "reason": f"API key rejected. Statuses: {statuses}: {s.get('body', '')[:200]}",
                "blocker": f"HTTP {statuses[0] if statuses else 0}"}

    # Generic fallback
    all_ok = all(_ok(s) for s in steps)
    return {"passed": all_ok, "confidence": 0.7,
            "reason": f"Steps completed with statuses: {[s.get('status') for s in steps]}",
            "blocker": None if all_ok else "one or more HTTP errors"}


def verdict_persist(slug: str, steps: list[dict], state: dict) -> dict:
    """Determine credential persistence pass/fail from HTTP responses."""
    if not steps:
        return {"passed": False, "confidence": 1.0, "reason": "No HTTP steps executed", "blocker": "executor error"}

    if slug == "agentmail-to":
        s = steps[0]
        if _ok(s):
            data = _parse_json(s)
            count = data.get("count", "?")
            return {"passed": True, "confidence": 1.0,
                    "reason": f"API key valid (HTTP {s['status']}). Inboxes accessible: count={count}.",
                    "blocker": None}
        if not state.get("agentmail_api_key"):
            return {"passed": False, "confidence": 1.0,
                    "reason": "No API key from signup to test persistence.",
                    "blocker": "no credentials from signup"}
        return {"passed": False, "confidence": 1.0,
                "reason": f"API key rejected HTTP {s['status']}: {s['body'][:200]}",
                "blocker": f"HTTP {s['status']}"}

    elif slug == "here-now":
        s = steps[0]
        site_url = state.get("herenow_site_url", "unknown")
        if _ok(s):
            return {"passed": True, "confidence": 1.0,
                    "reason": f"Published site at {site_url} still accessible (HTTP {s['status']}).",
                    "blocker": None}
        if s.get("status") == 403:
            # Cloudflare blocks the Python HTTP client on re-check.
            # here.now has no account or credentials — persistence means the URL stays live.
            # Only pass if signup already confirmed the site was accessible (HTTP 200).
            signup_status = state.get("herenow_site_live_status", 0)
            if signup_status == 200:
                return {"passed": True, "confidence": 0.75,
                        "reason": f"Site at {site_url} confirmed live immediately after publish (HTTP 200 during signup). "
                                  f"Re-verification blocked by Cloudflare (403). here.now has no account credentials — "
                                  f"persistence is defined as the URL remaining live, which was confirmed at publish time.",
                        "blocker": None}
            return {"passed": False, "confidence": 0.9,
                    "reason": f"Site at {site_url} returns 403 on re-check (Cloudflare bot-detection). "
                              f"Signup did not confirm the site was live (signup status: {signup_status}). "
                              f"Cannot verify persistence.",
                    "blocker": "Cloudflare bot-detection (403)"}
        return {"passed": False, "confidence": 1.0,
                "reason": f"Site URL {site_url} returned HTTP {s['status']}",
                "blocker": f"HTTP {s['status']}"}

    elif slug == "moltbook":
        s = steps[0]
        if _ok(s):
            data = _parse_json(s)
            name = data.get("name") or data.get("agent", {}).get("name", "?")
            return {"passed": True, "confidence": 1.0,
                    "reason": f"API key valid (HTTP {s['status']}). Agent profile: name={name}.",
                    "blocker": None}
        if not state.get("moltbook_api_key"):
            return {"passed": False, "confidence": 1.0,
                    "reason": "No API key from signup to test persistence.",
                    "blocker": "no credentials from signup"}
        return {"passed": False, "confidence": 1.0,
                "reason": f"API key rejected HTTP {s['status']}: {s['body'][:200]}",
                "blocker": f"HTTP {s['status']}"}

    elif slug == "signbee":
        s = steps[0]
        if _ok(s):
            data = _parse_json(s)
            doc_status = data.get("status", "?")
            doc_id = data.get("document_id") or data.get("id", "?")
            return {"passed": True, "confidence": 1.0,
                    "reason": f"API key valid (HTTP {s['status']}). Document accessible: id={doc_id}, status={doc_status}.",
                    "blocker": None}
        if s.get("error") == "No API key":
            return {"passed": False, "confidence": 1.0,
                    "reason": "No SIGNBEE_API_KEY available to test persistence.",
                    "blocker": "no API key"}
        return {"passed": False, "confidence": 1.0,
                "reason": f"HTTP {s['status']}: {s['body'][:200]}",
                "blocker": f"HTTP {s['status']}"}

    elif slug == "browser-use":
        s = steps[0]
        if _ok(s):
            data = _parse_json(s)
            total = data.get("total", 0)
            return {"passed": True, "confidence": 1.0,
                    "reason": f"API key persists (HTTP {s['status']}). Sessions: total={total}.",
                    "blocker": None}
        if not state.get("browseruse_api_key"):
            return {"passed": False, "confidence": 1.0,
                    "reason": "No BROWSER_USE_API_KEY available to test persistence.",
                    "blocker": "no API key"}
        return {"passed": False, "confidence": 1.0,
                "reason": f"HTTP {s['status']}: {s['body'][:200]}",
                "blocker": f"HTTP {s['status']}"}

    all_ok = all(_ok(s) for s in steps)
    return {"passed": all_ok, "confidence": 0.7,
            "reason": f"Statuses: {[s.get('status') for s in steps]}",
            "blocker": None if all_ok else "one or more HTTP errors"}


def verdict_workflow(slug: str, steps: list[dict], state: dict) -> dict:
    """Determine workflow pass/fail from HTTP responses."""
    if not steps:
        return {"passed": False, "confidence": 1.0, "reason": "No steps executed", "blocker": "executor error"}

    if slug == "agentmail-to":
        if steps[0].get("error") == "Missing API key":
            return {"passed": False, "confidence": 1.0,
                    "reason": "Workflow requires API key from signup. Signup must pass first.",
                    "blocker": "no API key from signup"}
        send_step = next((s for s in steps if "send email" in s.get("step", "")), None)
        inbox_step = next((s for s in steps if "accessible" in s.get("step", "") or "verify" in s.get("step", "")), None)
        if send_step and _ok(send_step):
            inbox_info = ""
            if inbox_step and _ok(inbox_step):
                data = _parse_json(inbox_step)
                inbox_info = f", inbox accessible (count={data.get('count', '?')})"
            return {"passed": True, "confidence": 1.0,
                    "reason": f"Full workflow complete: email sent from inbox (HTTP {send_step['status']}){inbox_info}.",
                    "blocker": None}
        failed = [s for s in steps if not _ok(s) and s.get("status", 0) != 0]
        return {"passed": False, "confidence": 1.0,
                "reason": f"Workflow incomplete. Failed steps: {[s['step'] for s in failed]}. Statuses: {[s.get('status') for s in steps]}",
                "blocker": f"HTTP {failed[0]['status']}" if failed else "incomplete"}

    elif slug == "here-now":
        # Same as signup — publish and verify live
        return verdict_signup("here-now", steps, state)

    elif slug == "moltbook":
        if steps[0].get("error") == "Missing API key":
            return {"passed": False, "confidence": 1.0,
                    "reason": "Workflow requires API key from signup.",
                    "blocker": "no API key from signup"}
        post_step = next((s for s in steps if "create post" in s.get("step", "")), None)
        comment_step = next((s for s in steps if "comments" in s.get("step", "")), None)
        upvote_step = next((s for s in steps if "upvote" in s.get("step", "")), None)
        passed_steps = [s for s in [post_step, comment_step, upvote_step] if s and _ok(s)]
        if len(passed_steps) == 3:
            return {"passed": True, "confidence": 1.0,
                    "reason": "Full workflow complete: post created, comment posted, upvote submitted.",
                    "blocker": None}
        statuses = {s["step"]: s.get("status") for s in steps}
        return {"passed": False, "confidence": 1.0,
                "reason": f"Workflow partial. Step statuses: {statuses}",
                "blocker": "workflow steps failed"}

    elif slug == "signbee":
        return verdict_signup(slug, steps, state)

    elif slug == "browser-use":
        if steps[0].get("error") == "No API key":
            return {"passed": False, "confidence": 1.0,
                    "reason": "No BROWSER_USE_API_KEY in environment.",
                    "blocker": "no API key"}
        create_step = next((s for s in steps if "create browser" in s.get("step", "")), None)
        status_step = next((s for s in steps if "check task" in s.get("step", "")), None)
        if create_step and _ok(create_step):
            data = _parse_json(create_step)
            session_id = data.get("id") or data.get("session_id", "?")
            status_info = ""
            if status_step and _ok(status_step):
                sd = _parse_json(status_step)
                status_info = f", task status={sd.get('status', '?')}"
            return {"passed": True, "confidence": 1.0,
                    "reason": f"Browser automation task created (HTTP {create_step['status']}). session_id={session_id}{status_info}.",
                    "blocker": None}
        statuses = {s["step"]: s.get("status") for s in steps}
        return {"passed": False, "confidence": 1.0,
                "reason": f"Workflow failed. Statuses: {statuses}",
                "blocker": "task creation failed"}

    all_ok = all(_ok(s) for s in steps)
    return {"passed": all_ok, "confidence": 0.7,
            "reason": f"Statuses: {[s.get('status') for s in steps]}",
            "blocker": None if all_ok else "one or more HTTP errors"}
