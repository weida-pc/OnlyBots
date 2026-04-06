"""Test 2 — Persistent Account Ownership.

Executes real HTTP requests directly to verify credentials from Test 1 persist,
then asks the AI harness to analyze the actual responses and produce a verdict.
"""
from __future__ import annotations

from executor import execute_persist, format_steps
from harness import run_agent, get_harness_for_service
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
        signup_method = state.get("signup_method", "unknown")

        harness_name, model = get_harness_for_service(slug)

        # ── Step 1: Execute real HTTP calls directly ──────────────────────────
        print(f"    [executor] Verifying credential persistence for {name}...")
        steps = execute_persist(slug, state)
        http_summary = format_steps(steps)
        save_log(run_id, "t2_persist_http_raw", http_summary)

        # ── Step 2: Ask AI harness to analyze the actual responses ────────────
        prompt = (
            f"You are analyzing REAL API call results to verify credential persistence.\n"
            f"These HTTP requests were already executed — your job is to analyze the responses.\n\n"
            f"Service: {name}\n"
            f"Signup method from Test 1: {signup_method}\n\n"
            f"=== ACTUAL HTTP RESULTS ===\n"
            f"{http_summary}\n"
            f"=== END RESULTS ===\n\n"
            f"Based on these real HTTP responses, determine:\n"
            f"1. Did credentials from signup persist? (API key still works, returns valid data)\n"
            f"2. Does the account still exist after the session?\n"
            f"3. Was there a persistence failure? (401 unauthorized, 404 not found, session expired)\n\n"
            f"Do NOT browse the web. Analyze only the responses above.\n\n"
            f"Output exactly this line:\n"
            f'VERDICT: {{"passed": true/false, "confidence": 0.0-1.0, '
            f'"reason": "what the HTTP responses show about credential persistence", '
            f'"blocker": null or "specific issue (e.g. no API key from signup, 401 unauthorized)"}}'
        )

        try:
            result = run_agent(
                prompt=prompt,
                harness_name=harness_name,
                model=model,
                run_id=run_id,
                test_name="t2_persist",
                timeout=120,
            )

            passed = result.get("passed", False)
            confidence = result.get("confidence", 0.5)
            reason = result.get("reason", "No reason")
            elapsed = result.get("response_time_s", 0)

            if passed:
                state["persistence_verified"] = True

            return TestResult(
                passed=passed,
                confidence=confidence,
                failure_reason=None if passed else reason,
                evidence_artifacts={
                    "http_raw": f"{run_id}/t2_persist_http_raw.log",
                    "agent_output": f"{run_id}/t2_persist_{harness_name}_stdout.log",
                },
                details={
                    "harness": result.get("harness", harness_name),
                    "model": result.get("model", model),
                    "url_tested": docs_url or url,
                    "response_time_s": elapsed,
                    "agent_reasoning": reason,
                    "blocker_type": result.get("blocker"),
                    "http_steps": len(steps),
                    "raw_output_excerpt": result.get("raw_output", "")[:500],
                },
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            save_log(run_id, "t2_persist_error", str(e))
            return TestResult(
                passed=False, confidence=0.1,
                failure_reason=f"Harness error: {e}",
                evidence_artifacts={"error_log": f"{run_id}/t2_persist_error.log"},
                details={"harness": harness_name, "model": model, "error": str(e)},
            )
