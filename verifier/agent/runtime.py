"""Agent runtime — invokes the Gemini CLI with a JSON artifact-report contract.

The agent is told to perform a task and emit a line of the form:

    ARTIFACTS: {"key1": "value", "key2": "value"}

at the end of its output. The runner parses the last such block, validates the
expected keys are present and non-empty, and returns a structured result.

Scope (Phase 2 prototype):
  - Single harness: Gemini CLI (`gemini -m MODEL -p PROMPT`)
  - No retries in this version — if the agent produces malformed output, the
    runner reports that honestly. Retries would be a Phase 2.1 improvement.
  - No streaming/intermediate-state capture — we take the final stdout.

The returned artifacts are trusted ONLY as claims; the contract's verifier
steps probe them independently. A hallucinated `api_key` that looks plausible
will still fail the verifier's GET /v0/inboxes probe.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentRunResult:
    """Result of a single agent invocation."""
    # Status categories:
    #   ok             -- artifacts parsed and all expected keys present & non-empty
    #   malformed      -- no ARTIFACTS block, or JSON parse failed
    #   missing_keys   -- ARTIFACTS parsed but some expected keys empty/missing
    #   timeout        -- subprocess exceeded timeout_s
    #   cli_missing    -- gemini binary not found
    #   error          -- other subprocess or I/O error
    status: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    missing_keys: list[str] = field(default_factory=list)
    raw_output: str = ""           # last ~2KB of stdout
    stderr_tail: str = ""          # last ~500 bytes of stderr
    elapsed_s: float = 0.0
    error: str | None = None
    model: str = ""
    exit_code: int | None = None


def _build_prompt(task_prompt: str, expected_artifacts: list[str]) -> str:
    """Wrap the caller's task prompt with explicit output format instructions."""
    keys_display = "\n".join(f"  - {k}" for k in expected_artifacts)
    keys_template = ", ".join(f'"{k}": "..."' for k in expected_artifacts)
    return (
        f"{task_prompt}\n\n"
        f"When you have completed the task (successfully or not), output one "
        f"final line in EXACTLY this format (single line, ARTIFACTS: prefix, "
        f"valid JSON):\n\n"
        f"ARTIFACTS: {{{keys_template}}}\n\n"
        f"Required keys (all must be present and non-empty):\n{keys_display}\n\n"
        f"If a value cannot be obtained, set it to empty string \"\" rather "
        f"than omitting the key. If the entire task failed, include an "
        f"\"error\" key describing what blocked you."
    )


def _extract_last_artifacts_block(output: str) -> tuple[bool, Any | None]:
    """Find the LAST `ARTIFACTS: {...}` block in output and parse its JSON.

    Uses json.JSONDecoder.raw_decode so the JSON object can span multiple
    lines and there can be trailing text after the closing brace.

    Returns (found_marker, parsed_or_None). If found_marker is True but the
    parse failed, parsed_or_None is None.
    """
    decoder = json.JSONDecoder()
    last_parsed: Any | None = None
    any_marker = False
    pos = 0
    marker = "ARTIFACTS:"
    while True:
        idx = output.find(marker, pos)
        if idx == -1:
            break
        any_marker = True
        start = idx + len(marker)
        # Skip whitespace between marker and JSON
        while start < len(output) and output[start] in " \t\r\n":
            start += 1
        if start < len(output):
            try:
                obj, _ = decoder.raw_decode(output[start:])
                last_parsed = obj
            except json.JSONDecodeError:
                pass
        pos = idx + len(marker)
    return (any_marker, last_parsed)


def run_agent_task(
    prompt: str,
    expected_artifacts: list[str],
    model: str = "gemini-2.5-flash",
    timeout_s: int = 180,
    cwd: str = "/tmp",
) -> AgentRunResult:
    """Invoke Gemini CLI with the task prompt; parse the ARTIFACTS report.

    No retries in v1. If you need retry-on-malformed, call this twice from
    the caller with different prompt variants.
    """
    full_prompt = _build_prompt(prompt, expected_artifacts)

    env = dict(os.environ)
    # Gemini CLI reads GEMINI_API_KEY from env; ensure it's there if set.
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        env["GEMINI_API_KEY"] = api_key

    # In headless mode (-p), Gemini CLI blocks tool use unless approval is
    # pre-granted. --yolo auto-approves all tool calls. Required so the agent
    # can actually run curl/web_fetch/etc. to complete the task.
    # Security note: this is an agent verifier running in a dedicated VM with
    # a scoped API key and URL allowlist enforcement downstream — the YOLO
    # blast radius is this VM's network + filesystem. Real isolation is
    # Phase 3 work (sandbox namespace / firewall rules).
    t0 = time.time()
    try:
        completed = subprocess.run(
            ["gemini", "-m", model, "--yolo", "-p", full_prompt],
            capture_output=True, text=True,
            timeout=timeout_s, env=env, cwd=cwd,
        )
    except FileNotFoundError:
        return AgentRunResult(
            status="cli_missing", elapsed_s=round(time.time() - t0, 2),
            error="gemini CLI not found on PATH", model=model,
        )
    except subprocess.TimeoutExpired:
        return AgentRunResult(
            status="timeout", elapsed_s=round(time.time() - t0, 2),
            error=f"agent timed out after {timeout_s}s", model=model,
        )
    except Exception as e:
        return AgentRunResult(
            status="error", elapsed_s=round(time.time() - t0, 2),
            error=f"{type(e).__name__}: {e}", model=model,
        )

    elapsed = round(time.time() - t0, 2)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""

    if completed.returncode != 0 and not stdout.strip():
        return AgentRunResult(
            status="error", elapsed_s=elapsed, model=model,
            exit_code=completed.returncode,
            stderr_tail=stderr[-500:],
            error=f"agent exited {completed.returncode} with no stdout",
        )

    found_marker, parsed = _extract_last_artifacts_block(stdout)
    raw_tail = stdout[-2000:]

    if not found_marker:
        return AgentRunResult(
            status="malformed", elapsed_s=elapsed, model=model,
            exit_code=completed.returncode,
            raw_output=raw_tail, stderr_tail=stderr[-500:],
            error="no 'ARTIFACTS:' block found in agent output",
        )
    if parsed is None:
        return AgentRunResult(
            status="malformed", elapsed_s=elapsed, model=model,
            exit_code=completed.returncode,
            raw_output=raw_tail, stderr_tail=stderr[-500:],
            error="'ARTIFACTS:' marker present but JSON failed to parse",
        )
    if not isinstance(parsed, dict):
        return AgentRunResult(
            status="malformed", elapsed_s=elapsed, model=model,
            exit_code=completed.returncode,
            raw_output=raw_tail, stderr_tail=stderr[-500:],
            error=f"ARTIFACTS must be a JSON object, got {type(parsed).__name__}",
        )

    artifacts = {k: v for k, v in parsed.items()}
    missing = [k for k in expected_artifacts
               if k not in artifacts or artifacts[k] in (None, "", [], {})]
    if missing:
        return AgentRunResult(
            status="missing_keys", elapsed_s=elapsed, model=model,
            exit_code=completed.returncode,
            artifacts=artifacts, missing_keys=missing,
            raw_output=raw_tail, stderr_tail=stderr[-500:],
            error=f"ARTIFACTS parsed but missing/empty keys: {missing}",
        )

    return AgentRunResult(
        status="ok", elapsed_s=elapsed, model=model,
        exit_code=completed.returncode,
        artifacts=artifacts, raw_output=raw_tail, stderr_tail=stderr[-500:],
    )
