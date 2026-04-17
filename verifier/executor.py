"""HTTP primitives + contract dispatch.

All per-service logic now lives in `verifier/contracts/{slug}.json` and is
executed by the `contract` package. This module contains only:

  1. The low-level HTTP helpers (plain socket + curl_cffi browser TLS).
  2. A tiny dispatch layer that calls into `contract` for each test phase.

Adding a new service is a matter of writing a JSON file — no Python changes.
If a service has no contract, the dispatch returns an explicit error step so
verification fails loudly rather than silently.
"""
from __future__ import annotations

import http.client
import json
import time
import urllib.parse
from typing import Any

# Browser-fingerprint HTTP client (bypasses Cloudflare bot-detection).
# Falls back gracefully if the package isn't installed.
try:
    from curl_cffi import requests as curl_requests  # type: ignore
    HAS_CURL_CFFI = True
except Exception:
    HAS_CURL_CFFI = False


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


def http_get_browser(url: str, timeout: int = 30) -> dict:
    """GET with a real browser TLS/JA3 fingerprint.

    Uses curl_cffi (libcurl with Chrome impersonation) so Cloudflare and similar
    bot-detection systems see a realistic client. Falls back to plain http_get
    if curl_cffi is not installed, so the verifier still runs in development.
    """
    if not HAS_CURL_CFFI:
        r = http_get(url, timeout=timeout)
        r["via"] = "http.client (curl_cffi unavailable)"
        return r

    t0 = time.time()
    try:
        resp = curl_requests.get(url, impersonate="chrome124", timeout=timeout)
        return {
            "status": resp.status_code,
            "body": resp.text,
            "elapsed_ms": round((time.time() - t0) * 1000),
            "error": None,
            "via": "curl_cffi/chrome124",
        }
    except Exception as e:
        return {
            "status": 0,
            "body": "",
            "elapsed_ms": round((time.time() - t0) * 1000),
            "error": str(e),
            "via": "curl_cffi/chrome124",
        }


def http_get_resilient(url: str, must_contain: str = "", timeout: int = 30) -> dict:
    """GET that escalates from plain HTTP to browser TLS when needed.

    Strategy:
      1. Try plain http_get (fast, cheap).
      2. If status is non-2xx OR (must_contain is set and not found in body),
         escalate to http_get_browser (browser TLS fingerprint).
      3. Return the best attempt, annotated with `via`, `attempts`, and
         `nonce_found` (if must_contain was provided).

    A 200 with a Cloudflare JS-challenge page is still a failure when
    must_contain is set — the marker acts as proof the real content was served.
    """
    attempts = []

    r1 = http_get(url, timeout=timeout)
    r1["via"] = r1.get("via", "http.client")
    r1_ok = 200 <= r1.get("status", 0) < 300
    r1_has_marker = (not must_contain) or (must_contain in r1.get("body", ""))
    attempts.append({"via": r1["via"], "status": r1.get("status"),
                     "marker_found": r1_has_marker})

    if r1_ok and r1_has_marker:
        r1["attempts"] = attempts
        r1["nonce_found"] = r1_has_marker if must_contain else None
        return r1

    # Escalate
    r2 = http_get_browser(url, timeout=timeout)
    r2_ok = 200 <= r2.get("status", 0) < 300
    r2_has_marker = (not must_contain) or (must_contain in r2.get("body", ""))
    attempts.append({"via": r2.get("via", "curl_cffi"), "status": r2.get("status"),
                     "marker_found": r2_has_marker})

    # Prefer the browser attempt if it found the marker, else return it anyway
    # since it carries richer failure information than a blocked http.client.
    r2["attempts"] = attempts
    r2["nonce_found"] = r2_has_marker if must_contain else None
    return r2


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


# ── Contract dispatch ────────────────────────────────────────────────────────
# All per-service logic lives in verifier/contracts/{slug}.json. The contract
# package executes the JSON and returns the same step/verdict shapes the
# legacy per-service Python functions used to produce, so tests and DB stay
# unchanged.

def _missing_contract_step(slug: str, test_name: str) -> list[dict]:
    return [{
        "step": f"no contract for '{slug}' test '{test_name}'",
        "step_id": "_no_contract",
        "status": 0, "body": "", "elapsed_ms": 0,
        "error": (f"no contract file found at verifier/contracts/{slug}.json — "
                   f"contracts are required after Phase 1 migration"),
    }]


def _missing_contract_verdict(slug: str, test_name: str) -> dict:
    return {
        "passed": False, "confidence": 1.0,
        "reason": (f"no contract for service '{slug}'. Contracts are required "
                   f"for all services after Phase 1 — add "
                   f"verifier/contracts/{slug}.json."),
        "blocker": "missing contract",
    }


def _run_contract_test(slug: str, test_name: str, state: dict) -> list[dict]:
    from contract import has_contract, load_contract, run_test_steps
    if not has_contract(slug):
        return _missing_contract_step(slug, test_name)
    contract = load_contract(slug)
    if contract is None:
        return _missing_contract_step(slug, test_name)
    return run_test_steps(contract, test_name, state)


def _eval_contract_verdict(slug: str, test_name: str, steps: list[dict],
                            state: dict) -> dict:
    from contract import has_contract, load_contract, evaluate_verdict
    if not has_contract(slug):
        return _missing_contract_verdict(slug, test_name)
    contract = load_contract(slug)
    if contract is None:
        return _missing_contract_verdict(slug, test_name)
    return evaluate_verdict(contract, test_name, steps, state)


# Public API consumed by verifier/tests/test_*.py. Signatures match the legacy
# implementation exactly so test files (and the harness/DB shape) don't change.

def execute_signup(slug: str, state: dict) -> list[dict]:
    return _run_contract_test(slug, "signup", state)


def execute_persist(slug: str, state: dict) -> list[dict]:
    return _run_contract_test(slug, "persistence", state)


def execute_workflow(slug: str, state: dict) -> list[dict]:
    return _run_contract_test(slug, "workflow", state)


def verdict_signup(slug: str, steps: list[dict], state: dict) -> dict:
    return _eval_contract_verdict(slug, "signup", steps, state)


def verdict_persist(slug: str, steps: list[dict], state: dict) -> dict:
    return _eval_contract_verdict(slug, "persistence", steps, state)


def verdict_workflow(slug: str, steps: list[dict], state: dict) -> dict:
    return _eval_contract_verdict(slug, "workflow", steps, state)
