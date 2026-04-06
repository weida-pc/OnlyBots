"""Test 2 — Persistent Account Ownership.

Verifies credentials from Test 1 persist using direct HTTP calls.
Verdict is determined by Python logic on actual HTTP responses.
"""
from __future__ import annotations

from executor import execute_persist, format_steps, verdict_persist
from harness import get_harness_for_service
from evidence import save_log
from tests.base import BaseTest, TestResult


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
            details={
                "harness": harness_name,
                "model": model,
                "method": "direct_http",
                "url_tested": docs_url or url,
                "response_time_s": sum(s.get("elapsed_ms", 0) for s in steps) / 1000,
                "agent_reasoning": reason,
                "blocker_type": blocker,
                "http_steps": len(steps),
                "http_statuses": [s.get("status") for s in steps],
            },
        )
