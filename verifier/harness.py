"""Agent harness runner — invokes CLI agents (Gemini, Claude, Codex, OpenClaw, Cursor).

Each harness is a CLI tool that receives a prompt and returns text output.
This module handles invocation, output capture, and verdict parsing.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import Any

from config import HARNESSES, SERVICE_HARNESS_MAP, DEFAULT_HARNESS
from evidence import save_log


def get_harness_for_service(slug: str) -> tuple[str, str]:
    """Return (harness_name, model) for a given service slug."""
    return SERVICE_HARNESS_MAP.get(slug, DEFAULT_HARNESS)


def run_agent(
    prompt: str,
    harness_name: str,
    model: str | None,
    run_id: int,
    test_name: str,
    timeout: int = 180,
) -> dict[str, Any]:
    """Invoke a CLI agent harness and parse its output.

    Args:
        prompt: The full task prompt for the agent.
        harness_name: Key into HARNESSES config (e.g., "gemini", "claude").
        model: Model override, or None for harness default.
        run_id: Verification run ID for evidence storage.
        test_name: Test identifier for log naming (e.g., "t1_signup").
        timeout: Max seconds to wait for the agent.

    Returns:
        dict with: passed, confidence, reason, blocker, raw_output
    """
    harness = HARNESSES.get(harness_name)
    if not harness:
        return {
            "passed": False,
            "confidence": 0.0,
            "reason": f"Unknown harness: {harness_name}",
            "blocker": f"Harness '{harness_name}' not configured",
            "raw_output": "",
        }

    cmd_name = harness["cmd"]
    model_flag = harness["model_flag"]
    actual_model = model or harness["default_model"]
    api_key_env = harness["api_key_env"]
    api_key = harness["api_key"]

    # Build command
    cmd = _build_command(cmd_name, model_flag, actual_model, prompt, harness_name)

    # Build environment
    env = {**os.environ}
    if api_key:
        env[api_key_env] = api_key

    print(f"    [{harness_name}] Running {cmd_name} -m {actual_model}...")
    print(f"    [{harness_name}] Timeout: {timeout}s")

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd="/tmp",  # neutral working directory
        )

        elapsed = round(time.time() - start_time, 1)
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # Save evidence
        save_log(run_id, f"{test_name}_{harness_name}_stdout", stdout)
        if stderr:
            save_log(run_id, f"{test_name}_{harness_name}_stderr", stderr)

        print(f"    [{harness_name}] Exit code: {result.returncode}")
        print(f"    [{harness_name}] Output length: {len(stdout)} chars ({elapsed}s)")

        if result.returncode != 0 and not stdout.strip():
            return {
                "passed": False,
                "confidence": 0.1,
                "reason": f"Agent exited with code {result.returncode}: {stderr[:500]}",
                "blocker": None,
                "raw_output": stderr[:2000],
                "harness": harness_name,
                "model": actual_model,
                "response_time_s": elapsed,
            }

        # Parse verdict from output
        verdict = _parse_verdict(stdout)
        verdict["raw_output"] = stdout[-2000:]  # last 2KB for context
        verdict["harness"] = harness_name
        verdict["model"] = actual_model
        verdict["response_time_s"] = elapsed

        return verdict

    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start_time, 1)
        save_log(run_id, f"{test_name}_{harness_name}_timeout",
                 f"Timed out after {timeout}s")
        return {
            "passed": False,
            "confidence": 0.2,
            "reason": f"Agent timed out after {timeout}s",
            "blocker": "timeout",
            "raw_output": "",
            "harness": harness_name,
            "model": actual_model,
            "response_time_s": elapsed,
        }
    except FileNotFoundError:
        return {
            "passed": False,
            "confidence": 0.0,
            "reason": f"Agent CLI '{cmd_name}' not found. Is it installed?",
            "blocker": f"CLI not installed: {cmd_name}",
            "raw_output": "",
            "harness": harness_name,
            "model": actual_model,
            "response_time_s": 0.0,
        }
    except Exception as e:
        elapsed = round(time.time() - start_time, 1)
        save_log(run_id, f"{test_name}_{harness_name}_error", str(e))
        return {
            "passed": False,
            "confidence": 0.1,
            "reason": f"Agent error: {e}",
            "blocker": None,
            "raw_output": "",
            "harness": harness_name,
            "model": actual_model,
            "response_time_s": elapsed,
        }


def _build_command(
    cmd: str, model_flag: str, model: str, prompt: str, harness_name: str
) -> list[str]:
    """Build the CLI command for each harness."""
    if harness_name == "gemini":
        # gemini -m MODEL -p "PROMPT"
        return [cmd, model_flag, model, "-p", prompt]

    elif harness_name == "claude":
        # claude --model MODEL --print "PROMPT"
        # --print = non-interactive, output only
        return [cmd, model_flag, model, "--print", prompt]

    elif harness_name == "codex":
        # codex --model MODEL --print "PROMPT"
        return [cmd, model_flag, model, "--print", prompt]

    elif harness_name == "openclaw":
        # openclaw --provider MODEL -p "PROMPT"
        return [cmd, model_flag, model, "-p", prompt]

    elif harness_name == "cursor":
        # cursor --model MODEL --print "PROMPT"
        return [cmd, model_flag, model, "--print", prompt]

    else:
        # Generic fallback
        return [cmd, model_flag, model, "-p", prompt]


def _parse_verdict(output: str) -> dict[str, Any]:
    """Parse a VERDICT: {...} JSON block from agent output.

    Looks for a line starting with VERDICT: followed by JSON.
    Falls back to scanning the entire output for pass/fail signals.
    """
    # Strategy 1: Find explicit VERDICT: line
    for line in reversed(output.split("\n")):
        line = line.strip()
        if line.startswith("VERDICT:"):
            json_str = line[len("VERDICT:"):].strip()
            try:
                v = json.loads(json_str)
                return {
                    "passed": v.get("passed", False),
                    "confidence": v.get("confidence", 0.5),
                    "reason": v.get("reason", ""),
                    "blocker": v.get("blocker"),
                }
            except json.JSONDecodeError:
                pass

    # Strategy 2: Find JSON block with "passed" key anywhere in output
    json_pattern = re.compile(r'\{[^{}]*"passed"\s*:\s*(true|false)[^{}]*\}', re.IGNORECASE)
    matches = json_pattern.findall(output)
    if matches:
        # Find the full JSON block
        for match in re.finditer(r'\{[^{}]*"passed"\s*:[^{}]*\}', output):
            try:
                v = json.loads(match.group())
                return {
                    "passed": v.get("passed", False),
                    "confidence": v.get("confidence", 0.5),
                    "reason": v.get("reason", "Parsed from output"),
                    "blocker": v.get("blocker"),
                }
            except json.JSONDecodeError:
                continue

    # Strategy 3: Heuristic — look for pass/fail keywords in last 500 chars
    tail = output[-500:].lower()

    if any(w in tail for w in ["captcha", "recaptcha", "hcaptcha", "cloudflare challenge"]):
        return {
            "passed": False,
            "confidence": 0.85,
            "reason": "CAPTCHA or human verification detected in agent output",
            "blocker": "CAPTCHA detected",
        }

    if any(w in tail for w in ["signup is possible", "can sign up", "registration form found",
                                "api key available", "autonomous signup: yes"]):
        return {
            "passed": True,
            "confidence": 0.6,
            "reason": "Positive signals found in agent output (heuristic)",
            "blocker": None,
        }

    if any(w in tail for w in ["cannot sign up", "signup blocked", "no signup",
                                "404", "page not found"]):
        return {
            "passed": False,
            "confidence": 0.6,
            "reason": "Negative signals found in agent output (heuristic)",
            "blocker": None,
        }

    # Strategy 4: Could not determine
    return {
        "passed": False,
        "confidence": 0.2,
        "reason": "Could not parse verdict from agent output",
        "blocker": None,
    }
