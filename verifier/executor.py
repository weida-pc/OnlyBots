"""Direct HTTP executor for service API calls.

Makes real HTTP requests to each service endpoint and returns structured results.
These results are then passed to the AI harness for verdict analysis — so the
AI never needs to browse the web, only interpret pre-fetched responses.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


# ── Low-level HTTP helpers ───────────────────────────────────────────────────

def http_post(url: str, body: dict, headers: dict | None = None, timeout: int = 30) -> dict:
    data = json.dumps(body).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body_str = resp.read().decode("utf-8", errors="replace")
            return {
                "status": resp.status,
                "body": body_str,
                "elapsed_ms": round((time.time() - t0) * 1000),
                "error": None,
            }
    except urllib.error.HTTPError as e:
        body_str = e.read().decode("utf-8", errors="replace")
        return {
            "status": e.code,
            "body": body_str,
            "elapsed_ms": round((time.time() - t0) * 1000),
            "error": str(e),
        }
    except Exception as e:
        return {
            "status": 0,
            "body": "",
            "elapsed_ms": round((time.time() - t0) * 1000),
            "error": str(e),
        }


def http_get(url: str, headers: dict | None = None, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body_str = resp.read().decode("utf-8", errors="replace")
            return {
                "status": resp.status,
                "body": body_str,
                "elapsed_ms": round((time.time() - t0) * 1000),
                "error": None,
            }
    except urllib.error.HTTPError as e:
        body_str = e.read().decode("utf-8", errors="replace")
        return {
            "status": e.code,
            "body": body_str,
            "elapsed_ms": round((time.time() - t0) * 1000),
            "error": str(e),
        }
    except Exception as e:
        return {
            "status": 0,
            "body": body_str if "body_str" in dir() else "",
            "elapsed_ms": round((time.time() - t0) * 1000),
            "error": str(e),
        }


def http_put(url: str, body: str | bytes, content_type: str = "application/octet-stream",
             timeout: int = 60) -> dict:
    if isinstance(body, str):
        body = body.encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": content_type},
        method="PUT"
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body_str = resp.read().decode("utf-8", errors="replace")
            return {
                "status": resp.status,
                "body": body_str,
                "elapsed_ms": round((time.time() - t0) * 1000),
                "error": None,
            }
    except urllib.error.HTTPError as e:
        body_str = e.read().decode("utf-8", errors="replace")
        return {
            "status": e.code,
            "body": body_str,
            "elapsed_ms": round((time.time() - t0) * 1000),
            "error": str(e),
        }
    except Exception as e:
        return {
            "status": 0,
            "body": "",
            "elapsed_ms": round((time.time() - t0) * 1000),
            "error": str(e),
        }


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
        {"human_email": "onlybots-verify@agentmail.to", "username": f"onlybots-test-{ts}"},
    )
    step.update(resp)

    # Extract credentials if present
    try:
        data = json.loads(resp["body"])
        if "api_key" in data:
            state["agentmail_api_key"] = data["api_key"]
            state["agentmail_org_id"] = data.get("organization_id", "")
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
    """Execute full AgentMail workflow: create inbox → send email → verify receipt."""
    api_key = state.get("agentmail_api_key", "")
    if not api_key:
        return [{"step": "workflow skipped — no API key from signup", "status": 0, "body": "", "elapsed_ms": 0, "error": "Missing API key"}]

    steps = []

    # 1. Create inbox
    step1 = {"step": "POST https://api.agentmail.to/v0/inboxes (create inbox)"}
    r1 = http_post(
        "https://api.agentmail.to/v0/inboxes",
        {"display_name": "OnlyBots Verification Inbox"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    step1.update(r1)
    steps.append(step1)

    inbox_id = None
    inbox_address = None
    try:
        data = json.loads(r1["body"])
        inbox_id = data.get("id") or data.get("inbox_id")
        inbox_address = data.get("address") or data.get("email")
    except Exception:
        pass

    if not inbox_id:
        return steps

    # 2. Send email to self
    step2 = {"step": f"POST /v0/inboxes/{inbox_id}/messages (send email)"}
    r2 = http_post(
        f"https://api.agentmail.to/v0/inboxes/{inbox_id}/messages",
        {
            "to": [{"email": inbox_address or f"{inbox_id}@agentmail.to"}],
            "subject": "OnlyBots Verification Test",
            "body": "This is an automated test by OnlyBots.",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    step2.update(r2)
    steps.append(step2)

    # 3. List messages to verify receipt
    step3 = {"step": f"GET /v0/inboxes/{inbox_id}/messages (verify receipt)"}
    r3 = http_get(
        f"https://api.agentmail.to/v0/inboxes/{inbox_id}/messages",
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
            "name": f"OnlyBots-Verifier-{ts}",
            "description": "Automated verification agent for OnlyBots trust registry",
        },
    )
    step.update(resp)

    try:
        data = json.loads(resp["body"])
        if "api_key" in data:
            state["moltbook_api_key"] = data["api_key"]
        if "agent_id" in data or "id" in data:
            state["moltbook_agent_id"] = data.get("agent_id") or data.get("id")
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
    """Create a post, comment, and upvote on Moltbook."""
    api_key = state.get("moltbook_api_key", "")
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
    """Test Signbee document sending."""
    steps = []

    # Check API signup endpoint
    step1 = {"step": "GET https://signb.ee/api/v1/auth/signup (probe endpoint)"}
    r1 = http_get("https://signb.ee/api/v1/auth/signup")
    step1.update(r1)
    steps.append(step1)

    # Send a document without auth to see the flow
    step2 = {"step": "POST https://signb.ee/api/v1/send (send document)"}
    r2 = http_post(
        "https://signb.ee/api/v1/send",
        {
            "recipient_name": "OnlyBots Verifier",
            "recipient_email": "verify@onlybots.com",
            "markdown": (
                "# OnlyBots Verification Document\n\n"
                "This document verifies that Signbee supports autonomous document signing.\n\n"
                "## Terms\n\n- This is an automated test\n- No real agreement is being made"
            ),
        },
    )
    step2.update(r2)
    steps.append(step2)

    # Extract document_id if present
    try:
        data = json.loads(r2["body"])
        doc_id = data.get("document_id") or data.get("id")
        if doc_id:
            state["signbee_document_id"] = doc_id
        api_key = data.get("api_key")
        if api_key:
            state["signbee_api_key"] = api_key
    except Exception:
        pass

    return steps


def persist_signbee(state: dict) -> list[dict]:
    """Check Signbee document status."""
    steps = []
    api_key = state.get("signbee_api_key", "")
    doc_id = state.get("signbee_document_id", "")

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    if doc_id:
        step = {"step": f"GET /api/v1/documents/{doc_id} (check status)"}
        resp = http_get(f"https://signb.ee/api/v1/documents/{doc_id}", headers=headers or None)
        step.update(resp)
        steps.append(step)
    else:
        step = {"step": "GET /api/v1/documents (list — no doc_id from signup)"}
        resp = http_get("https://signb.ee/api/v1/documents", headers=headers or None)
        step.update(resp)
        steps.append(step)

    return steps


def workflow_signbee(state: dict) -> list[dict]:
    """Full Signbee workflow — same as signup for doc-based service."""
    return signup_signbee(state)


def signup_browseruse(state: dict) -> list[dict]:
    """Probe Browser Use API authentication requirements."""
    steps = []

    # 1. Try creating a session without auth
    step1 = {"step": "POST https://api.browser-use.com/api/v3/sessions (no auth)"}
    r1 = http_post(
        "https://api.browser-use.com/api/v3/sessions",
        {"task": "Navigate to https://example.com and return the page title"},
    )
    step1.update(r1)
    steps.append(step1)

    # 2. List sessions without auth
    step2 = {"step": "GET https://api.browser-use.com/api/v3/sessions (check auth)"}
    r2 = http_get("https://api.browser-use.com/api/v3/sessions")
    step2.update(r2)
    steps.append(step2)

    return steps


def persist_browseruse(state: dict) -> list[dict]:
    """Check Browser Use session persistence."""
    api_key = state.get("browseruse_api_key", "")
    step = {"step": "GET /api/v3/sessions (check auth requirement)"}
    headers = {"X-Browser-Use-API-Key": api_key} if api_key else {}
    resp = http_get("https://api.browser-use.com/api/v3/sessions", headers=headers or None)
    step.update(resp)
    return [step]


def workflow_browseruse(state: dict) -> list[dict]:
    """Browser Use workflow — same as signup probe."""
    return signup_browseruse(state)


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
