"""Test 1 — Autonomous Signup.

Makes real HTTP requests directly (fast, no LLM browsing), then uses
Python-based verdict logic on the actual responses. The AI harness name
is recorded for provenance but pass/fail is determined deterministically.
"""
from __future__ import annotations

from executor import execute_signup, format_steps, verdict_signup
from harness import get_harness_for_service
from evidence import save_log
from tests.base import BaseTest, TestResult


class TestSignup(BaseTest):
    test_number = 1
    test_name = "Autonomous signup"

    async def run(self, service: dict, state: dict, run_id: int) -> TestResult:
        slug = service["slug"]
        name = service["name"]
        signup_url = service["signup_url"]

        harness_name, model = get_harness_for_service(slug)

        # Execute real HTTP calls directly
        print(f"    [executor] Making direct HTTP calls for {name} signup...")
        steps = execute_signup(slug, state)
        http_summary = format_steps(steps)
        save_log(run_id, "t1_signup_http_raw", http_summary)

        # Determine verdict from actual HTTP responses (deterministic, no hallucination)
        verdict = verdict_signup(slug, steps, state)

        passed = verdict["passed"]
        confidence = verdict["confidence"]
        reason = verdict["reason"]
        blocker = verdict.get("blocker")

        if passed:
            state["signup_verified"] = True
            state["signup_method"] = reason
            state["signup_url"] = signup_url

        return TestResult(
            passed=passed,
            confidence=confidence,
            failure_reason=None if passed else (f"Blocked: {blocker}" if blocker else reason),
            evidence_artifacts={
                "http_raw": f"{run_id}/t1_signup_http_raw.log",
            },
            details={
                "harness": harness_name,
                "model": model,
                "method": "direct_http",
                "url_tested": signup_url,
                "response_time_s": sum(s.get("elapsed_ms", 0) for s in steps) / 1000,
                "agent_reasoning": reason,
                "blocker_type": blocker,
                "http_steps": len(steps),
                "http_statuses": [s.get("status") for s in steps],
            },
        )
