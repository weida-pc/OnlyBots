"""Test 3 — Core Workflow Autonomy.

Executes the service's primary workflow via direct HTTP calls.
Verdict is determined by Python logic on actual HTTP responses.
"""
from __future__ import annotations

from executor import execute_workflow, format_steps, verdict_workflow
from harness import get_harness_for_service
from evidence import save_log
from tests.base import BaseTest, TestResult


class TestWorkflow(BaseTest):
    test_number = 3
    test_name = "Core workflow autonomy"

    async def run(self, service: dict, state: dict, run_id: int) -> TestResult:
        slug = service["slug"]
        name = service["name"]
        url = service["url"]
        docs_url = service.get("docs_url", "")
        core_workflow = service.get("core_workflow", "Unknown")

        harness_name, model = get_harness_for_service(slug)

        # Execute real HTTP workflow calls
        print(f"    [executor] Executing core workflow for {name}...")
        steps = execute_workflow(slug, state)
        http_summary = format_steps(steps)
        save_log(run_id, "t3_workflow_http_raw", http_summary)

        # Determine verdict from actual HTTP responses
        verdict = verdict_workflow(slug, steps, state)

        passed = verdict["passed"]
        confidence = verdict["confidence"]
        reason = verdict["reason"]
        blocker = verdict.get("blocker")

        return TestResult(
            passed=passed,
            confidence=confidence,
            failure_reason=None if passed else reason,
            evidence_artifacts={
                "http_raw": f"{run_id}/t3_workflow_http_raw.log",
            },
            details={
                "harness": harness_name,
                "model": model,
                "method": "direct_http",
                "url_tested": docs_url or url,
                "response_time_s": sum(s.get("elapsed_ms", 0) for s in steps) / 1000,
                "core_workflow": core_workflow,
                "agent_reasoning": reason,
                "blocker_type": blocker,
                "http_steps": len(steps),
                "http_statuses": [s.get("status") for s in steps],
            },
        )
