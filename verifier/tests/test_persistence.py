"""Test 2 — Persistent Account Ownership.

Verifies credentials from Test 1 persist using direct HTTP calls.
Verdict is determined by Python logic on actual HTTP responses.
"""
from __future__ import annotations

from executor import execute_persist, format_steps, verdict_persist
from harness import get_harness_for_service
from evidence import save_log
from tests.base import BaseTest, TestResult
from tests._common import details_for


class TestPersistence(BaseTest):
    test_number = 2
    test_name = "Persistent account ownership"

    async def run(self, service: dict, state: dict, run_id: int) -> TestResult:
        slug = service["slug"]
        name = service["name"]
        url = service["url"]
        docs_url = service.get("docs_url", "")

        harness_name, model = get_harness_for_service(slug)

        # Execute real HTTP calls to check credential persistence
        print(f"    [executor] Verifying credential persistence for {name}...")
        steps = execute_persist(slug, state)
        http_summary = format_steps(steps)
        save_log(run_id, "t2_persist_http_raw", http_summary)

        # Determine verdict from actual HTTP responses
        verdict = verdict_persist(slug, steps, state)

        passed = verdict["passed"]
        confidence = verdict["confidence"]
        reason = verdict["reason"]
        blocker = verdict.get("blocker")

        if passed:
            state["persistence_verified"] = True

        return TestResult(
            passed=passed,
            confidence=confidence,
            failure_reason=None if passed else reason,
            evidence_artifacts={
                "http_raw": f"{run_id}/t2_persist_http_raw.log",
            },
            details=details_for(
                slug=slug,
                test_name="persistence",
                harness_name=harness_name,
                fallback_model=model,
                steps=steps,
                url_tested=docs_url or url,
                reason=reason,
                blocker=blocker,
            ),
        )
