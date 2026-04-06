"""Test 3 — Core Workflow Autonomy.

Executes the service's primary workflow via direct HTTP calls (fast, no browsing),
then asks the AI harness to analyze the actual responses and produce a verdict.
"""
from __future__ import annotations

from executor import execute_workflow, format_steps
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

        harness_name, model = get_harness_for_service(slug)

        # ── Step 1: Execute real HTTP workflow calls directly ─────────────────
        print(f"    [executor] Executing core workflow for {name}...")
        steps = execute_workflow(slug, state)
        http_summary = format_steps(steps)
        save_log(run_id, "t3_workflow_http_raw", http_summary)

        # ── Step 2: Ask AI harness to analyze the actual responses ────────────
        prompt = (
            f"You are analyzing REAL API call results from an autonomous workflow execution.\n"
            f"These HTTP requests were already executed — your job is to analyze the responses.\n\n"
            f"Service: {name}\n"
            f"Core workflow: {core_workflow}\n\n"
            f"=== ACTUAL HTTP RESULTS ===\n"
            f"{http_summary}\n"
            f"=== END RESULTS ===\n\n"
            f"Based on these real HTTP responses, determine:\n"
            f"1. Did the core workflow complete end-to-end?\n"
            f"2. Did each step return a success status code (2xx)?\n"
            f"3. Was there any blocker preventing full workflow completion?\n"
            f"   (e.g. missing API key from earlier step, 401, 404, rate limit)\n\n"
            f"Do NOT browse the web. Analyze only the responses above.\n\n"
            f"Output exactly this line:\n"
            f'VERDICT: {{"passed": true/false, "confidence": 0.0-1.0, '
            f'"reason": "describe what the HTTP responses show — include status codes and whether workflow completed end-to-end", '
            f'"blocker": null or "specific issue that prevented workflow completion"}}'
        )

        try:
            result = run_agent(
                prompt=prompt,
                harness_name=harness_name,
                model=model,
                run_id=run_id,
                test_name="t3_workflow",
                timeout=120,
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
                    "http_raw": f"{run_id}/t3_workflow_http_raw.log",
                    "agent_output": f"{run_id}/t3_workflow_{harness_name}_stdout.log",
                },
                details={
                    "harness": result.get("harness", harness_name),
                    "model": result.get("model", model),
                    "url_tested": docs_url or url,
                    "response_time_s": elapsed,
                    "core_workflow": core_workflow,
                    "agent_reasoning": reason,
                    "blocker_type": result.get("blocker"),
                    "http_steps": len(steps),
                    "raw_output_excerpt": result.get("raw_output", "")[:500],
                },
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            save_log(run_id, "t3_workflow_error", str(e))
            return TestResult(
                passed=False, confidence=0.1,
                failure_reason=f"Harness error: {e}",
                evidence_artifacts={"error_log": f"{run_id}/t3_workflow_error.log"},
                details={"harness": harness_name, "model": model, "error": str(e)},
            )
