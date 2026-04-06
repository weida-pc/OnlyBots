"""Test 2 — Persistent Account Ownership.

Can the AI agent retain access to the account/resource it created?
Delegates to the configured CLI agent harness.
"""
from __future__ import annotations

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
        description = service.get("description", "")
        signup_method = state.get("signup_method", "unknown")

        harness_name, model = get_harness_for_service(slug)
        test_url = docs_url or url

        prompt = (
            f"You are a verification agent. Your task is to determine whether '{name}' "
            f"provides PERSISTENT account ownership for AI agents.\n\n"
            f"Service description: {description}\n"
            f"Service URL: {url}\n"
            f"Docs URL: {docs_url}\n"
            f"Signup method from previous test: {signup_method}\n\n"
            f"Visit {test_url} and analyze the documentation.\n\n"
            f"Determine:\n"
            f"1. Does the service provide persistent credentials?\n"
            f"   - API keys that don't expire = PASS\n"
            f"   - Username/password login = PASS\n"
            f"   - Persistent tokens or sessions = PASS\n"
            f"   - Claim-codes that persist 24h+ = PASS\n"
            f"2. Are there signs of credential volatility?\n"
            f"   - Session-only access (expires on close) = FAIL\n"
            f"   - One-time tokens with no renewal = FAIL\n"
            f"   - No way to re-authenticate programmatically = FAIL\n\n"
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
                test_name="t2_persist",
                timeout=600,
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
                    "agent_output": f"{run_id}/t2_persist_{harness_name}_stdout.log",
                },
                details={
                    "harness": result.get("harness", harness_name),
                    "model": result.get("model", model),
                    "url_tested": test_url,
                    "response_time_s": elapsed,
                    "agent_reasoning": reason,
                    "blocker_type": result.get("blocker"),
                    "raw_output_excerpt": result.get("raw_output", "")[:500],
                },
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            save_log(run_id, "t2_persist_error", str(e))
            return TestResult(
                passed=False,
                confidence=0.1,
                failure_reason=f"Harness error: {e}",
                evidence_artifacts={"error_log": f"{run_id}/t2_persist_error.log"},
                details={"harness": harness_name, "model": model, "url_tested": test_url, "error": str(e)},
            )
