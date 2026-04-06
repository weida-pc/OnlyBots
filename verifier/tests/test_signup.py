"""Test 1 — Autonomous Signup.

Actually attempts to create an account on the service via API calls.
The agent CLI executes real HTTP requests and reports what happened.
"""
from __future__ import annotations

from harness import run_agent, get_harness_for_service
from evidence import save_log
from tests.base import BaseTest, TestResult

# Per-service prompts that tell the agent to ACTUALLY sign up
SIGNUP_PROMPTS = {
    "agentmail-to": (
        "You must ACTUALLY sign up for AgentMail by making real API calls. Do this:\n\n"
        "1. Run: curl -s -X POST https://api.agentmail.to/v0/agent/sign-up "
        '-H "Content-Type: application/json" '
        "-d '{\"human_email\": \"onlybots-verify@agentmail.to\", \"username\": \"onlybots-test-'$(date +%s)'\"}'\n\n"
        "2. Check the response. If it returns an API key or organization_id, signup succeeded.\n"
        "   If it requires email OTP verification, note that as a blocker.\n"
        "   If it returns an error, note the error.\n\n"
        "3. Report exactly what HTTP status code and response body you got.\n\n"
    ),
    "here-now": (
        "You must ACTUALLY publish a test page on here.now. Do this:\n\n"
        "1. Run: curl -s -X POST https://here.now/api/v1/publish "
        '-H "Content-Type: application/json" '
        '-H "X-HereNow-Client: onlybots/verifier" '
        "-d '{\"files\": [{\"path\": \"index.html\", \"size\": 44, \"contentType\": \"text/html; charset=utf-8\"}]}'\n\n"
        "2. Check the response for presigned upload URLs and a slug.\n\n"
        "3. If you got upload URLs, upload test content:\n"
        "   curl -X PUT \"<presigned_url>\" -H \"Content-Type: text/html\" "
        "--data '<h1>OnlyBots Test</h1>'\n\n"
        "4. Finalize: curl -s -X POST \"<finalize_url>\" "
        "-H \"Content-Type: application/json\" -d '{\"versionId\": \"<versionId>\"}'\n\n"
        "5. Visit the returned siteUrl to verify it loads.\n\n"
        "Report every HTTP status code and response body you get.\n\n"
    ),
    "moltbook": (
        "You must ACTUALLY register an agent on Moltbook. Do this:\n\n"
        "1. Run: curl -s -X POST https://www.moltbook.com/api/v1/agents/register "
        '-H "Content-Type: application/json" '
        "-d '{\"name\": \"OnlyBots-Verifier-'$(date +%s)'\", \"description\": \"Automated verification agent for OnlyBots trust registry\"}'\n\n"
        "2. Check the response. If it returns an API key or agent ID, registration succeeded.\n"
        "   If it requires Twitter/X verification or manual approval, note that as a blocker.\n"
        "   If it returns an error, note the exact error.\n\n"
        "3. Report exactly what HTTP status code and response body you got.\n\n"
    ),
    "signbee": (
        "You must ACTUALLY test Signbee's signup flow. Do this:\n\n"
        "1. First check if there's an API signup: curl -s https://signb.ee/api/v1/auth/signup 2>&1\n\n"
        "2. Try to access the dashboard API key page: curl -s https://signb.ee/dashboard 2>&1 | head -50\n\n"
        "3. Try sending a test document without auth to see what happens:\n"
        "   curl -s -X POST https://signb.ee/api/v1/send "
        '-H "Content-Type: application/json" '
        "-d '{\"recipient_name\": \"OnlyBots Test\", \"recipient_email\": \"test@example.com\", \"markdown\": \"# Test Document\\n\\nThis is an automated verification test from OnlyBots.\"}'\n\n"
        "4. Report every HTTP status code and response body you get.\n"
        "   Note whether signup requires a browser/GUI or can be done via API.\n\n"
    ),
    "browser-use": (
        "You must ACTUALLY test Browser Use's signup and API. Do this:\n\n"
        "1. Check if there's a programmatic signup: curl -s https://api.browser-use.com/api/v3/auth/signup 2>&1\n\n"
        "2. Try accessing the API without a key to see what error you get:\n"
        "   curl -s -X POST https://api.browser-use.com/api/v3/sessions "
        '-H "Content-Type: application/json" '
        "-d '{\"task\": \"test\"}'\n\n"
        "3. Check what cloud.browser-use.com returns: curl -s https://cloud.browser-use.com/settings 2>&1 | head -50\n\n"
        "4. Report every HTTP status code and response body you get.\n"
        "   Note whether signup requires a browser/GUI or can be done via API.\n\n"
    ),
}


class TestSignup(BaseTest):
    test_number = 1
    test_name = "Autonomous signup"

    async def run(self, service: dict, state: dict, run_id: int) -> TestResult:
        slug = service["slug"]
        name = service["name"]
        signup_url = service["signup_url"]

        harness_name, model = get_harness_for_service(slug)

        service_prompt = SIGNUP_PROMPTS.get(slug, "")
        if not service_prompt:
            service_prompt = (
                f"Try to sign up for {name} at {signup_url} by making real HTTP requests.\n"
                f"Use curl to hit the signup URL and any API endpoints you can find.\n"
                f"Report every HTTP status code and response body.\n\n"
            )

        prompt = (
            f"You are a verification agent. ACTUALLY EXECUTE these steps — do not just describe them.\n"
            f"Make real HTTP requests using curl and report the real responses.\n\n"
            f"Service: {name}\n"
            f"Signup URL: {signup_url}\n\n"
            f"{service_prompt}"
            f"After executing, output exactly this line:\n"
            f'VERDICT: {{"passed": true/false, "confidence": 0.0-1.0, '
            f'"reason": "describe what actually happened when you tried to sign up — include HTTP status codes and key response fields", '
            f'"blocker": null or "specific blocker you hit"}}'
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
                details={"harness": harness_name, "model": model, "url_tested": signup_url, "error": str(e)},
            )
