"""Phase 2 prototype: agent drives, verifier observes.

The `runtime` module wraps a Gemini CLI invocation with a strict
JSON-artifact-report contract: the agent is told to do a task and end its
output with a line `ARTIFACTS: {json}`. The runner parses that block,
validates expected keys are present, and returns a structured result.

Contracts that want to use this must add `agent_task` to a TestSpec.
Contracts without `agent_task` continue to run verifier-driven HTTP steps
exactly as before — the prototype is additive, not a replacement.
"""
from .runtime import run_agent_task, AgentRunResult

__all__ = ["run_agent_task", "AgentRunResult"]
