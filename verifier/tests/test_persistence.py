"""Test 2 — Persistent Account Ownership.

Verifies that credentials obtained in Test 1 still work.
The agent CLI re-authenticates or re-uses tokens to prove persistence.
"""
from __future__ import annotations

from harness import run_agent, get_harness_for_service
from evidence import save_log
from tests.base import BaseTest, TestResult

PERSISTENCE_PROMPTS = {
    "agentmail-to": (
        "You must ACTUALLY verify that AgentMail credentials persist. Do this:\n\n"
        "1. If you obtained an API key in the previous step, use it:\n"
        "   curl -s https://api.agentmail.to/v0/inboxes "
        '-H "Authorization: Bearer <API_KEY>"\n\n'
        "2. If signup returned an organization_id, try listing API keys:\n"
        "   curl -s https://api.agentmail.to/v0/api-keys "
        '-H "Authorization: Bearer <API_KEY>"\n\n'
        "3. If you don't have credentials from Test 1, try the API without auth:\n"
        "   curl -s https://api.agentmail.to/v0/inboxes\n\n"
        "4. Report what happened — did the API key work? Did you get a valid response?\n\n"
    ),
    "here-now": (
        "You must ACTUALLY verify that the here.now site you published still exists. Do this:\n\n"
        "1. If you got a siteUrl from Test 1, fetch it:\n"
        "   curl -s <siteUrl>\n\n"
        "2. If you don't have the URL, try the here.now API to list sites:\n"
        "   curl -s https://here.now/api/v1/sites\n\n"
        "3. Verify the content matches what was published.\n\n"
        "Note: here.now anonymous sites persist for 24 hours. Check if the content is still there.\n\n"
    ),
    "moltbook": (
        "You must ACTUALLY verify Moltbook credentials persist. Do this:\n\n"
        "1. If you got an API key from registration, use it to fetch your profile:\n"
        "   curl -s https://www.moltbook.com/api/v1/agents/me "
        '-H "Authorization: Bearer <API_KEY>"\n\n'
        "2. Try listing posts to verify the key works:\n"
        "   curl -s https://www.moltbook.com/api/v1/posts "
        '-H "Authorization: Bearer <API_KEY>"\n\n'
        "3. Report whether the API key is still valid and returns data.\n\n"
    ),
    "signbee": (
        "You must ACTUALLY verify Signbee credential persistence. Do this:\n\n"
        "1. If you got an API key, use it to list documents:\n"
        "   curl -s https://signb.ee/api/v1/documents "
        '-H "Authorization: Bearer <API_KEY>"\n\n'
        "2. If you sent a document in Test 1, check its status:\n"
        "   curl -s https://signb.ee/api/v1/documents/<DOCUMENT_ID> "
        '-H "Authorization: Bearer <API_KEY>"\n\n'
        "3. If no credentials, try the API unauthenticated and report what error you get.\n\n"
    ),
    "browser-use": (
        "You must ACTUALLY verify Browser Use credential persistence. Do this:\n\n"
        "1. If you have an API key (starts with bu_), verify it still works:\n"
        "   curl -s https://api.browser-use.com/api/v3/sessions "
        '-H "X-Browser-Use-API-Key: <API_KEY>"\n\n'
        "2. If no key, try the API unauthenticated:\n"
        "   curl -s https://api.browser-use.com/api/v3/sessions\n\n"
        "3. Report whether the key/session is still valid.\n\n"
    ),
}


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

        service_prompt = PERSISTENCE_PROMPTS.get(slug, "")
        if not service_prompt:
            service_prompt = (
                f"Verify that credentials for {name} persist. Re-use any API keys or tokens "
                f"from the signup step. Make real curl requests and report responses.\n\n"
            )

        prompt = (
            f"You are a verification agent. ACTUALLY EXECUTE these steps — make real HTTP requests.\n\n"
            f"Service: {name}\n"
            f"Signup method from Test 1: {signup_method}\n\n"
            f"{service_prompt}"
            f"After executing, output exactly this line:\n"
            f'VERDICT: {{"passed": true/false, "confidence": 0.0-1.0, '
            f'"reason": "describe what actually happened — include HTTP status codes and whether credentials still worked", '
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
                    "url_tested": docs_url or url,
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
                passed=False, confidence=0.1,
                failure_reason=f"Harness error: {e}",
                evidence_artifacts={"error_log": f"{run_id}/t2_persist_error.log"},
                details={"harness": harness_name, "model": model, "error": str(e)},
            )
