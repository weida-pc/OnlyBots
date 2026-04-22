"""Shared helpers for test_signup / test_persistence / test_workflow.

Extracted so all three record honest per-test details — specifically the
`model` that the contract's agent_task actually uses, not a harness-default
that the verifier reported but never invoked. Before this module existed,
every test.details recorded `model=<harness.default_model>` (e.g.
"gemini-3-flash-preview") while the real contract was running
`gemini-2.5-flash` via the agent_task.model field. The registry page's
"Underlying LLM" label and "Reproduce This Verification" section both
displayed that fake default. Fixed at the source.
"""
from __future__ import annotations
from typing import Any


def agent_task_model_for(slug: str, test_name: str) -> str | None:
    """Return the model the contract's agent_task specifies for `test_name`,
    or None if the test has no agent_task (pure-HTTP contract path).

    Safe to call from any of the three test harnesses. Import is deferred
    so a contract-loader import failure doesn't break the test runner.
    """
    try:
        from contract import has_contract, load_contract
    except Exception:
        return None
    if not has_contract(slug):
        return None
    contract = load_contract(slug)
    if contract is None:
        return None
    test = contract.tests.get(test_name)
    if test is None or test.agent_task is None:
        return None
    return test.agent_task.model or None


def details_for(
    *,
    slug: str,
    test_name: str,
    harness_name: str,
    fallback_model: str,
    steps: list[dict[str, Any]],
    url_tested: str,
    reason: str,
    blocker: str | None,
) -> dict[str, Any]:
    """Build the per-test `details` dict that lands in verification_results.

    Uses the contract's agent_task.model when present; falls back to the
    harness default (still recorded so old contracts without agent_task
    keep a value). Downstream UI should prefer `agent_task_model` when
    present and hide the LLM label entirely when both are null.
    """
    actual_model = agent_task_model_for(slug, test_name)
    return {
        "harness": harness_name,
        "model": actual_model or fallback_model,
        "agent_task_model": actual_model,  # null when the test runs no agent
        "method": "contract",
        "url_tested": url_tested,
        "response_time_s": sum(s.get("elapsed_ms", 0) for s in steps) / 1000,
        "agent_reasoning": reason,
        "blocker_type": blocker,
        "http_steps": len(steps),
        "http_statuses": [s.get("status") for s in steps],
    }
