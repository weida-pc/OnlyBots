"""Test 1 — Autonomous Signup.

Executes real HTTP requests directly (fast, no browsing), then asks the AI
harness to analyze the actual responses and produce a verdict.
"""
from __future__ import annotations

from executor import execute_signup, format_steps
from harness import run_agent, get_harness_for_service
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

        # ── Step 1: Execute real HTTP calls directly ──────────────────────────
        print(f"    [executor] Making direct HTTP calls for {name} signup...")
        steps = execute_signup(slug, state)
        http_summary = format_steps(steps)
        save_log(run_id, "t1_signup_http_raw", http_summary)

        # ── Step 2: Ask AI harness to analyze the actual responses ────────────
        prompt = (
            f"You are analyzing REAL API call results from an autonomous signup attempt.\n"
            f"These HTTP requests were already executed — your job is to analyze the responses.\n\n"
            f"Service: {name}\n"
            f"Signup URL: {signup_url}\n\n"
            f"=== ACTUAL HTTP RESULTS ===\n"
            f"{http_summary}\n"
            f"=== END RESULTS ===\n\n"
            f"Based on these real HTTP responses, determine:\n"
            f"1. Did signup succeed? (Got API key, session token, or account created)\n"
            f"2. Was it blocked? (Requires email OTP, CAPTCHA, browser GUI, manual approval)\n"
            f"3. How confident are you based on these actual responses?\n\n"
            f"Do NOT browse the web. Analyze only the responses above.\n\n"
            f"Output exactly this line:\n"
            f'VERDICT: {{"passed": true/false, "confidence": 0.0-1.0, '
            f'"reason": "what the HTTP responses show about signup success/failure", '
            f'"blocker": null or "specific blocker (e.g. email OTP required, CAPTCHA, no API endpoint)"}}'
        )

        try:
            result = run_agent(
                prompt=prompt,
                harness_name=harness_name,
                model=model,
                run_id=run_id,
                test_name="t1_signup",
                timeout=120,  # 2 min is plenty — no browsing needed
            )

            passed = result.get("passed", False)
            confidence = result.get("confidence", 0.5)
            reason = result.get("reason", "No reason")
            blocker = result.get("blocker")
            elapsed = result.get("response_time_s", 0)

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
                    "agent_output": f"{run_id}/t1_signup_{harness_name}_stdout.log",
                },
                details={
                    "harness": result.get("harness", harness_name),
                    "model": result.get("model", model),
                    "url_tested": signup_url,
                    "response_time_s": elapsed,
                    "agent_reasoning": reason,
                    "blocker_type": blocker,
                    "http_steps": len(steps),
                    "raw_output_excerpt": result.get("raw_output", "")[:500],
                },
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            save_log(run_id, "t1_signup_error", str(e))
            return TestResult(
                passed=False,
                confidence=0.1,
                failure_reason=f"Harness error: {e}",
                evidence_artifacts={"error_log": f"{run_id}/t1_signup_error.log"},
                details={"harness": harness_name, "model": model, "url_tested": signup_url, "error": str(e)},
            )
