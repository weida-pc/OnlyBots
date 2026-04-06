"""Test 3 — Core Workflow Autonomy.

Actually executes the service's primary workflow using real API calls.
The agent CLI performs the core operation and reports real results.
"""
from __future__ import annotations

from harness import run_agent, get_harness_for_service
from evidence import save_log
from tests.base import BaseTest, TestResult

WORKFLOW_PROMPTS = {
    "agentmail-to": (
        "You must ACTUALLY execute AgentMail's core workflow. Do this:\n\n"
        "1. Create an inbox (use the API key from signup if you have one):\n"
        "   curl -s -X POST https://api.agentmail.to/v0/inboxes "
        '-H "Authorization: Bearer <API_KEY>" '
        '-H "Content-Type: application/json" '
        "-d '{\"display_name\": \"OnlyBots Verification Inbox\"}'\n\n"
        "2. Send an email from that inbox:\n"
        "   curl -s -X POST https://api.agentmail.to/v0/inboxes/<INBOX_ID>/messages "
        '-H "Authorization: Bearer <API_KEY>" '
        '-H "Content-Type: application/json" '
        "-d '{\"to\": [{\"email\": \"<INBOX_ADDRESS>\"}], \"subject\": \"OnlyBots Verification Test\", \"body\": \"This is an automated test.\"}'\n\n"
        "3. List messages to verify receipt:\n"
        "   curl -s https://api.agentmail.to/v0/inboxes/<INBOX_ID>/messages "
        '-H "Authorization: Bearer <API_KEY>"\n\n'
        "4. Report: Did you create an inbox? Send an email? See it in the inbox?\n\n"
    ),
    "here-now": (
        "You must ACTUALLY execute here.now's core workflow end-to-end. Do this:\n\n"
        "1. Create a site:\n"
        "   curl -s -X POST https://here.now/api/v1/publish "
        '-H "Content-Type: application/json" '
        '-H "X-HereNow-Client: onlybots/verifier" '
        "-d '{\"files\": [{\"path\": \"index.html\", \"size\": 62, \"contentType\": \"text/html; charset=utf-8\"}]}'\n\n"
        "2. Upload the HTML content to the presigned URL from step 1:\n"
        "   curl -s -X PUT \"<upload_url>\" "
        "-H \"Content-Type: text/html; charset=utf-8\" "
        "--data '<html><body><h1>OnlyBots Live Test</h1></body></html>'\n\n"
        "3. Finalize the site:\n"
        "   curl -s -X POST \"<finalize_url>\" "
        "-H \"Content-Type: application/json\" "
        "-d '{\"versionId\": \"<versionId>\"}'\n\n"
        "4. Verify the live URL works:\n"
        "   curl -s <siteUrl>\n\n"
        "5. Report: Did you get a live URL? Does it serve your content?\n\n"
    ),
    "moltbook": (
        "You must ACTUALLY execute Moltbook's core workflow. Do this:\n\n"
        "1. Register an agent (if not already done):\n"
        "   curl -s -X POST https://www.moltbook.com/api/v1/agents/register "
        '-H "Content-Type: application/json" '
        "-d '{\"name\": \"OnlyBots-Verifier-'$(date +%s)'\", \"description\": \"OnlyBots automated verification\"}'\n\n"
        "2. Use the API key to create a post:\n"
        "   curl -s -X POST https://www.moltbook.com/api/v1/posts "
        '-H "Authorization: Bearer <API_KEY>" '
        '-H "Content-Type: application/json" '
        "-d '{\"submolt_name\": \"general\", \"title\": \"OnlyBots Verification Test\", \"content\": \"Automated verification post from OnlyBots trust registry.\"}'\n\n"
        "3. Comment on the post:\n"
        "   curl -s -X POST https://www.moltbook.com/api/v1/posts/<POST_ID>/comments "
        '-H "Authorization: Bearer <API_KEY>" '
        '-H "Content-Type: application/json" '
        "-d '{\"content\": \"Verification comment\"}'\n\n"
        "4. Upvote the post:\n"
        "   curl -s -X POST https://www.moltbook.com/api/v1/posts/<POST_ID>/upvote "
        '-H "Authorization: Bearer <API_KEY>"\n\n'
        "5. Report: Did you create a post? Comment? Upvote? Include response codes.\n\n"
    ),
    "signbee": (
        "You must ACTUALLY execute Signbee's core workflow. Do this:\n\n"
        "1. Send a document for signing:\n"
        "   curl -s -X POST https://signb.ee/api/v1/send "
        '-H "Content-Type: application/json" '
        "-d '{\"recipient_name\": \"OnlyBots Verifier\", \"recipient_email\": \"verify@onlybots.com\", \"markdown\": \"# OnlyBots Verification Document\\n\\nThis document verifies that Signbee supports autonomous document signing by AI agents.\\n\\n## Terms\\n\\n- This is an automated test\\n- No real agreement is being made\"}'\n\n"
        "2. Check the response — did you get a document_id and status?\n\n"
        "3. If you got a document_id, check its status:\n"
        "   curl -s https://signb.ee/api/v1/documents/<DOCUMENT_ID>\n\n"
        "4. Report: Did the document get created? What status was returned?\n"
        "   Note whether the signing flow requires human GUI interaction.\n\n"
    ),
    "browser-use": (
        "You must ACTUALLY execute Browser Use's core workflow. Do this:\n\n"
        "1. Try creating a browser session without a key to see the error:\n"
        "   curl -s -X POST https://api.browser-use.com/api/v3/sessions "
        '-H "Content-Type: application/json" '
        "-d '{\"task\": \"Navigate to https://example.com and return the page title\"}'\n\n"
        "2. Check what authentication is required:\n"
        "   curl -s https://api.browser-use.com/api/v3/sessions\n\n"
        "3. Try the cloud signup page:\n"
        "   curl -s https://cloud.browser-use.com 2>&1 | head -20\n\n"
        "4. Report: Can you create sessions via API? What auth is needed?\n"
        "   Note whether signup requires browser GUI or can be done via API.\n\n"
    ),
}


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

        service_prompt = WORKFLOW_PROMPTS.get(slug, "")
        if not service_prompt:
            service_prompt = (
                f"Actually execute the core workflow for {name}: {core_workflow}\n"
                f"Make real HTTP requests using curl. Report actual responses.\n\n"
            )

        prompt = (
            f"You are a verification agent. ACTUALLY EXECUTE these steps — make real HTTP requests.\n"
            f"Do NOT just describe what you would do. Run the curl commands and report real results.\n\n"
            f"Service: {name}\n"
            f"Core workflow: {core_workflow}\n\n"
            f"{service_prompt}"
            f"After executing, output exactly this line:\n"
            f'VERDICT: {{"passed": true/false, "confidence": 0.0-1.0, '
            f'"reason": "describe what ACTUALLY happened — include real HTTP status codes, response bodies, and whether the workflow completed end-to-end", '
            f'"blocker": null or "specific issue that prevented workflow completion"}}'
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
                    "url_tested": docs_url or url,
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
                passed=False, confidence=0.1,
                failure_reason=f"Harness error: {e}",
                evidence_artifacts={"error_log": f"{run_id}/t3_workflow_error.log"},
                details={"harness": harness_name, "model": model, "error": str(e)},
            )
