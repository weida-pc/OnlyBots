"""URL resolution via BrightData SERP.

Given a service name, return candidate canonical URLs. Caller then fetches
each candidate and verifies the rendered page actually describes the named
service (title match, description match, etc) before adding to the registry.

This fixes the "I guessed <name>.com" failure mode. The rule is NOT
"don't look up URLs" (that's too stringent) — it's "look up, then
verify the top candidate with a real browser fetch before submitting".

Environment:
  BRIGHTDATA_API_KEY       — Bearer token for api.brightdata.com/request
  BRIGHTDATA_SERP_ZONE     — defaults to "serp_api1"

Implementation ported from pressclub/serp_utils.py (the primary vendor
path). We skip the async + Serper fallback + proxy variants — this
module only runs from the operator's terminal as a pre-submission
sanity check, not on the hot path.
"""
from __future__ import annotations

import json
import os
import random
import time
from urllib.parse import quote
from typing import Optional

import requests  # type: ignore


BRIGHTDATA_API_KEY = os.getenv("BRIGHTDATA_API_KEY", "")
BRIGHTDATA_SERP_ZONE = os.getenv("BRIGHTDATA_SERP_ZONE", "serp_api1")
BRIGHTDATA_API_URL = "https://api.brightdata.com/request"

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0


def _build_serp_url(query: str, num: int = 10) -> str:
    # brd_json=1 flips Brightdata to structured JSON output.
    return (f"https://www.google.com/search?q={quote(query)}"
            f"&num={num}&brd_json=1")


def _sleep_backoff(attempt: int, retry_after: str = "",
                   rate_limited: bool = False) -> None:
    if retry_after and retry_after.isdigit():
        time.sleep(min(int(retry_after), 60))
        return
    if rate_limited:
        time.sleep(min(BACKOFF_BASE_SECONDS * (attempt + 1), 30)
                   + random.uniform(0, 1))
        return
    time.sleep(min(0.25 * (2 ** attempt), 4.0))


def serp_search(query: str, num: int = 10,
                timeout: int = 30) -> list[dict]:
    """Return a list of normalized organic results: [{rank, title, link,
    snippet}, ...]. Empty list on failure.
    """
    if not BRIGHTDATA_API_KEY:
        raise RuntimeError(
            "BRIGHTDATA_API_KEY not set. Copy from pressclub/.env or VM "
            "/opt/onlybots/verifier/.env, e.g. "
            "`export BRIGHTDATA_API_KEY=$(ssh VM 'sudo grep ^BRIGHTDATA "
            "/opt/onlybots/verifier/.env | cut -d= -f2')`."
        )
    url = _build_serp_url(query, num=num)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BRIGHTDATA_API_KEY}",
    }
    body = {"zone": BRIGHTDATA_SERP_ZONE, "url": url, "format": "raw"}

    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(BRIGHTDATA_API_URL, headers=headers,
                              json=body, timeout=timeout)
            bd_sc = r.headers.get("x-brd-status-code", "")
            if r.status_code == 429 or bd_sc == "429":
                _sleep_backoff(
                    attempt, r.headers.get("Retry-After", ""),
                    rate_limited=True,
                )
                continue
            if r.status_code != 200:
                return []
            if not r.text:
                _sleep_backoff(attempt)
                continue
            data = r.json()
            out = []
            for i, item in enumerate(data.get("organic") or [], start=1):
                out.append({
                    "rank": item.get("rank", i),
                    "title": item.get("title", "") or "",
                    "link": item.get("link", "") or "",
                    "snippet": item.get("description", "") or "",
                })
            return out
        except Exception:
            if attempt == MAX_RETRIES - 1:
                return []
            _sleep_backoff(attempt)
    return []


def resolve_service_url(name: str, hints: Optional[list[str]] = None,
                         num_candidates: int = 5) -> list[dict]:
    """Return up to `num_candidates` SERP hits for a service name.

    `hints` are extra words appended to the query to narrow results
    (e.g. ["agent", "openclaw", "official site"]). Caller then fetches
    each result's link and compares the landing-page title against the
    service name to pick the true canonical URL.
    """
    terms = [name] + (hints or ["official site"])
    query = " ".join(terms)
    results = serp_search(query, num=num_candidates * 2)
    # De-dupe by hostname (first hit wins), cap at num_candidates
    seen = set()
    out = []
    for r in results:
        link = r.get("link", "")
        if not link:
            continue
        try:
            from urllib.parse import urlparse
            host = urlparse(link).netloc.lower()
        except Exception:
            continue
        if host in seen:
            continue
        seen.add(host)
        out.append(r)
        if len(out) >= num_candidates:
            break
    return out


if __name__ == "__main__":
    # Manual probe: `python -m verifier.url_resolve <service name> [hint1 hint2 ...]`
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m verifier.url_resolve <name> [hint ...]")
        sys.exit(2)
    name = sys.argv[1]
    hints = sys.argv[2:] or None
    for r in resolve_service_url(name, hints):
        print(f"{r['rank']:>2} {r['link']}")
        print(f"   {r['title']}")
        if r.get("snippet"):
            print(f"   {r['snippet'][:120]}")
