"""Test 1 — Autonomous Signup.

Can an AI agent create an account on this service without human intervention?
Delegates to the configured CLI agent harness (Gemini, Claude, Codex, etc.).
"""
from __future__ import annotations

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
        description = service.get("description", "")
        core_workflow = service.get("core_workflow", "")
        docs_url = service.get("docs_url", "")

        harness_name, model = get_harness_for_service(slug)

        prompt = (
            f"You are a verification agent. Your task is to determine whether an AI agent "
            f"can AUTONOMOUSLY sign up for the service '{name}'.\n\n"
            f"Service description: {description}\n"
            f"Signup URL: {signup_url}\n"
            f"Docs URL: {docs_url}\n"
            f"Core workflow: {core_workflow}\n\n"
            f"Visit {signup_url} and analyze the signup process. Then check {docs_url} if needed.\n\n"
            f"Determine:\n"
            f"1. Is there a signup/registration that an AI can complete without human help?\n"
            f"   - Email + password form = PASS\n"
            f"   - API key registration via API = PASS\n"
            f"   - Claim-code / no-account-needed = PASS\n"
            f"   - Skills/MCP install that auto-provisions = PASS\n"
            f"2. Are there any BLOCKERS preventing autonomous signup?\n"
            f"   - CAPTCHA, reCAPTCHA, hCaptcha, Cloudflare = FAIL\n"
            f"   - Phone/SMS verification = FAIL\n"
            f"   - OAuth-only with no email option = FAIL\n"
            f"   - Manual approval/waitlist = FAIL\n\n"
            f"Do NOT submit real credentials. Just verify the flow is possible.\n\n"
            f"When done, output exactly this line:\n"
            f'VERDICT: {{"passed": true/false, "confidence": 0.0-1.0, '
            f'"reason": "your detailed explanation of what you found", '
            f'"blocker": null or "specific blocker description"}}'
        )

        try:
            result = run_agent(
                prompt=prompt,
                harness_name=harness_name,
                model=model,
                run_id=run_id,
                test_name="t1_signup",
                timeout=600,
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
                    "agent_output": f"{run_id}/t1_signup_{harness_name}_stdout.log",
                },
                details={
                    "harness": result.get("harness", harness_name),
                    "model": result.get("model", model),
                    "url_tested": signup_url,
                    "response_time_s": elapsed,
                    "agent_reasoning": reason,
                    "blocker_type": blocker,
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
                details={
                    "harness": harness_name,
                    "model": model,
                    "url_tested": signup_url,
                    "error": str(e),
                },
            )
