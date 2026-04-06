"""Test 3 — Core Workflow Autonomy.

Can the AI agent execute the service's primary workflow?
Delegates to the configured CLI agent harness.
"""
from __future__ import annotations

from harness import run_agent, get_harness_for_service
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
        description = service.get("description", "")

        harness_name, model = get_harness_for_service(slug)
        test_url = docs_url or url

        prompt = (
            f"You are a verification agent. Your task is to determine whether an AI agent "
            f"can execute the CORE WORKFLOW of '{name}'.\n\n"
            f"Service description: {description}\n"
            f"Core workflow: {core_workflow}\n"
            f"Service URL: {url}\n"
            f"Docs URL: {docs_url}\n\n"
            f"Visit {test_url} and analyze the documentation and API references.\n\n"
            f"Determine:\n"
            f"1. Is the core workflow achievable programmatically?\n"
            f"   - REST/GraphQL API with documented endpoints = PASS\n"
            f"   - SDK/client library available = PASS\n"
            f"   - CLI tool for the workflow = PASS\n"
            f"   - Simple HTTP requests work = PASS\n"
            f"2. Are there blockers to workflow automation?\n"
            f"   - Manual/GUI-only steps required = FAIL\n"
            f"   - Human approval in the loop = FAIL\n"
            f"   - No API or programmatic interface = FAIL\n\n"
            f"When done, output exactly this line:\n"
            f'VERDICT: {{"passed": true/false, "confidence": 0.0-1.0, '
            f'"reason": "your detailed explanation", '
            f'"blocker": null or "specific issue"}}'
        )

        try:
            result = run_agent(
                prompt=prompt,
                harness_name=harness_name,
                model=model,
                run_id=run_id,
                test_name="t3_workflow",
                timeout=600,
            )

            passed = result.get("passed", False)
            confidence = result.get("confidence", 0.5)
            reason = result.get("reason", "No reason")
            elapsed = result.get("response_time_s", 0)

            return TestResult(
                passed=passed,
                confidence=confidence,
                failure_reason=None if passed else reason,
                evidence_artifacts={
                    "agent_output": f"{run_id}/t3_workflow_{harness_name}_stdout.log",
                },
                details={
                    "harness": result.get("harness", harness_name),
                    "model": result.get("model", model),
                    "url_tested": test_url,
                    "response_time_s": elapsed,
                    "core_workflow": core_workflow,
                    "agent_reasoning": reason,
                    "blocker_type": result.get("blocker"),
                    "raw_output_excerpt": result.get("raw_output", "")[:500],
                },
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            save_log(run_id, "t3_workflow_error", str(e))
            return TestResult(
                passed=False,
                confidence=0.1,
                failure_reason=f"Harness error: {e}",
                evidence_artifacts={"error_log": f"{run_id}/t3_workflow_error.log"},
                details={"harness": harness_name, "model": model, "url_tested": test_url, "error": str(e)},
            )
