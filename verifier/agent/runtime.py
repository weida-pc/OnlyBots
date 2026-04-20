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
    # Populated by the public `run_agent_task` retry loop — lets callers see
    # how many attempts were made and what each attempt's status was.
    attempts: list[dict[str, Any]] = field(default_factory=list)


def _build_prompt(task_prompt: str, expected_artifacts: list[str],
                   reminder: bool = False) -> str:
    """Wrap the caller's task prompt with explicit output format instructions.

    On retry (reminder=True), leads with a terse reminder that the prior
    attempt didn't produce the required format — pushes the model to prioritize
    emitting the ARTIFACTS block even if it has to cut its reasoning short.
    """
    keys_display = "\n".join(f"  - {k}" for k in expected_artifacts)
    keys_template = ", ".join(f'"{k}": "..."' for k in expected_artifacts)
    preamble = ""
    if reminder:
        preamble = (
            "IMPORTANT: the previous attempt did not produce the required "
            "final `ARTIFACTS: {...}` line. Complete the task and make SURE "
            "to emit the final line in the exact required format before you "
            "stop.\n\n"
        )
    return (
        f"{preamble}{task_prompt}\n\n"
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
    max_retries: int = 1,
) -> AgentRunResult:
    """Invoke Gemini CLI with the task prompt; parse the ARTIFACTS report.

    Retries up to `max_retries` times on malformed/missing output. Observed
    in the wild: ~1 in 3 runs on complex multi-step tasks (e.g. here-now's
    publish/upload/finalize flow) finish without emitting the final
    ARTIFACTS block within the initial timeout. A single retry with a
    reminder prompt closes this gap.

    Retries do NOT happen for timeout/cli_missing/error — those are
    infrastructure issues and retry won't help.
    """
    attempt = 0
    last: AgentRunResult | None = None
    t_overall = time.time()
    while True:
        # Budget: don't let retries push us past 1.5x the per-attempt timeout.
        # Prevents a late-failing first attempt from leaving seconds for the
        # retry, which would almost certainly fail too.
        remaining_budget = (timeout_s * 1.5) - (time.time() - t_overall)
        attempt_timeout = int(min(timeout_s, max(30, remaining_budget)))

        # Structured log — grep-friendly. Each line is independently parseable
        # so ops can measure real flake rates over time.
        print(
            f"[agent.runtime] attempt={attempt + 1}/{max_retries + 1} "
            f"model={model} timeout={attempt_timeout}s "
            f"reminder={attempt > 0}"
        )

        result = _run_once(prompt, expected_artifacts, model, attempt_timeout,
                            cwd, reminder=(attempt > 0))
        attempt_info = {
            "attempt": attempt + 1,
            "status": result.status,
            "elapsed_s": result.elapsed_s,
        }
        result.attempts = [*(last.attempts if last else []), attempt_info]

        print(
            f"[agent.runtime] attempt={attempt + 1} "
            f"status={result.status} elapsed={result.elapsed_s}s "
            f"missing_keys={result.missing_keys}"
        )

        if result.status == "ok":
            if attempt > 0:
                print(f"[agent.runtime] recovered after {attempt} retry(s)")
            return result

        # Retry only on soft failures (agent produced output but wrong shape).
        # Hard failures (timeout, cli_missing, error) won't benefit from retry.
        if result.status in ("malformed", "missing_keys") and attempt < max_retries:
            # Stop if we've already consumed most of the total budget.
            if (time.time() - t_overall) >= timeout_s * 1.3:
                print(
                    f"[agent.runtime] giving up — retry would exceed "
                    f"time budget ({time.time() - t_overall:.0f}s elapsed)"
                )
                return result
            attempt += 1
            last = result
            continue
        return result


def _minimal_agent_env() -> dict[str, str]:
    """Build the minimum env the gemini subprocess actually needs.

    Pre-Tier-1 behavior: we passed the verifier's full os.environ to the
    gemini subprocess. That meant a malicious service whose prompt-injected
    the agent into running `printenv` could exfiltrate every pre-provisioned
    API key (SIGNBEE_API_KEY, MOLTBOOK_API_KEY, BROWSER_USE_API_KEY, TWILIO_*,
    and eventually VERIFIER_WALLET_KEY). The env_secret contract mechanism
    scopes which state keys are exposed to the contract, but the subprocess
    inherited the host env directly, bypassing that gate entirely.

    Post-Tier-1: we pass only what gemini CLI genuinely needs — its own API
    key, enough PATH to find curl/node, a HOME so it can read ~/.gemini
    config, and locale settings. Everything else is dropped.

    Pre-provisioned service keys are NOT passed here. Contracts that need
    them read them via env_secret step (runs in the Python process, stores
    in state) and pass them to the agent only as template-substituted values
    in the prompt text. The agent still sees the value, but cannot enumerate
    *other* services' keys via `printenv`.
    """
    allowed = {
        # Needed for gemini CLI auth — the only secret the agent should see
        # at the env level.
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        # Needed so gemini can find curl, node, sh, etc.
        "PATH": os.environ.get(
            "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        ),
        # Needed so gemini can find its config directory (~/.gemini)
        "HOME": os.environ.get("HOME", "/tmp"),
        # Locale — gemini may misbehave without these under some Node builds
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        # Gemini CLI checks these to detect a tty
        "TERM": os.environ.get("TERM", "dumb"),
    }
    # Drop any empty values so we don't pass `GEMINI_API_KEY=""` when unset.
    return {k: v for k, v in allowed.items() if v}


def _audit_log_invocation(
    model: str, timeout_s: int, prompt_len: int, env_keys: list[str],
    sandboxed: bool,
) -> None:
    """Structured log of each agent invocation. Grep target for ops.

    Deliberately does NOT log prompt content or API key values — just the
    shape of the call. Full prompt ends up in evidence/ per-run anyway.
    """
    print(
        f"[agent.runtime.invoke] model={model} timeout={timeout_s}s "
        f"prompt_chars={prompt_len} env_keys={sorted(env_keys)} "
        f"fs_sandbox={'bwrap' if sandboxed else 'none'}"
    )


# bwrap presence is probed once at import time. On systems without bwrap we
# fall back to un-sandboxed exec — better than failing closed when the
# sandbox tool is missing, but we log it loudly so ops can notice.
import shutil as _shutil
_HAS_BWRAP = _shutil.which("bwrap") is not None


def _bwrap_command(cmd: list[str]) -> list[str]:
    """Wrap `cmd` with bwrap arguments that hide sensitive filesystem paths.

    The agent subprocess inherits a read-only view of the root filesystem,
    but `/opt/onlybots` (which contains the verifier's .env files and other
    services' contracts) and `/home/onlybots` (which may contain config)
    are replaced with empty tmpfs mounts. The agent can no longer read
    credentials or prior evidence.

    This is Tier 1 isolation. It does NOT protect against:
      - Network exfiltration via URLs the agent is told to reach
      - Prompt-injection attacks that manipulate the agent's reasoning
      - Resource exhaustion (no CPU/memory caps yet — Tier 2)

    --- bwrap flags explained ---
      --ro-bind / /           : Root filesystem available read-only
      --dev-bind /dev /dev    : Real /dev (gemini needs /dev/urandom, /dev/null)
      --proc /proc            : New /proc
      --tmpfs /tmp            : Fresh /tmp
      --tmpfs /opt/onlybots   : Hides verifier secrets + past evidence
      --tmpfs /home/onlybots  : Hides user config that might contain secrets
      --die-with-parent       : Clean up if the parent dies
      --unshare-pid           : PID namespace so agent can't see host processes
      --unshare-ipc           : IPC namespace
      --unshare-uts           : UTS namespace
      --new-session           : New controlling TTY, prevents TTY hijack
    """
    return [
        "bwrap",
        "--ro-bind", "/", "/",
        "--dev-bind", "/dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--tmpfs", "/opt/onlybots",
        "--tmpfs", "/home/onlybots",
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--new-session",
        *cmd,
    ]


def _run_once(
    prompt: str,
    expected_artifacts: list[str],
    model: str,
    timeout_s: int,
    cwd: str,
    reminder: bool = False,
) -> AgentRunResult:
    """Single invocation of the Gemini CLI. Public runner is `run_agent_task`.

    Tier 1 hardening applied:
      - Env is built from allowlist only (_minimal_agent_env), NOT inherited.
      - Every invocation is logged structurally for audit.
      - Filesystem isolation is Tier 2 (Docker-per-test); until then the
        agent subprocess can still read any file the onlybots user can.
        Known gap, documented explicitly.
    """
    full_prompt = _build_prompt(prompt, expected_artifacts, reminder=reminder)

    # Minimal env — Tier 1.1 fix. No pre-provisioned service keys
    # inherited, no DB URL, no Twilio credentials visible to the subprocess.
    env = _minimal_agent_env()

    # bwrap filesystem isolation — Tier 1.2. Hides /opt/onlybots and
    # /home/onlybots from the agent subprocess so it can't read .env files
    # or evidence from prior runs. Falls back to unwrapped exec if bwrap
    # isn't installed (logged loudly at invoke time).
    base_cmd = ["gemini", "-m", model, "--yolo", "-p", full_prompt]
    if _HAS_BWRAP:
        cmd = _bwrap_command(base_cmd)
    else:
        cmd = base_cmd
        print("[agent.runtime.WARNING] bwrap not available — running agent "
              "WITHOUT filesystem sandbox. Install bubblewrap on the host.")

    _audit_log_invocation(
        model, timeout_s, len(full_prompt), list(env.keys()),
        sandboxed=_HAS_BWRAP,
    )

    t0 = time.time()
    try:
        completed = subprocess.run(
            cmd,
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
