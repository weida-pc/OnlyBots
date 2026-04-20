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

import base64
import json
import os
import shlex
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
    sandbox_kind: str,
) -> None:
    """Structured log of each agent invocation. Grep target for ops.

    Deliberately does NOT log prompt content or API key values — just the
    shape of the call. Full prompt ends up in evidence/ per-run anyway.

    sandbox_kind: "daytona" | "bwrap" | "none" — which isolation layer
    was used. Lets ops verify which sandbox each test actually ran under.
    """
    print(
        f"[agent.runtime.invoke] model={model} timeout={timeout_s}s "
        f"prompt_chars={prompt_len} env_keys={sorted(env_keys)} "
        f"sandbox={sandbox_kind}"
    )


# Sandbox selection is a preference ladder:
#   1. Daytona (Tier 2, full container isolation) if DAYTONA_API_KEY is set
#   2. bwrap (Tier 1, namespace isolation on the host VM) if /usr/bin/bwrap exists
#   3. Unsandboxed (last resort; logged loudly)
#
# Daytona runs the agent inside a fresh container per invocation, destroyed
# after. bwrap runs the agent on the host VM with filesystem masking.
# Both protect against prompt-injection exfiltration of host .env files,
# but Daytona also isolates network egress and provides per-test ephemeral
# state. Wallet install is gated on Daytona being the active sandbox.

import shutil as _shutil
_HAS_BWRAP = _shutil.which("bwrap") is not None
_HAS_DAYTONA = bool(os.environ.get("DAYTONA_API_KEY"))

# Lazily-initialized Daytona client — the SDK is heavy (pulls in aiohttp,
# opentelemetry, etc.) so don't pay the import cost unless we actually use it.
_daytona_client = None


def _get_daytona_client():
    global _daytona_client
    if _daytona_client is None:
        from daytona import Daytona, DaytonaConfig  # type: ignore
        _daytona_client = Daytona(DaytonaConfig(api_key=os.environ["DAYTONA_API_KEY"]))
    return _daytona_client


def active_sandbox_kind() -> str:
    """Which sandbox the next agent invocation will use. Public for ops/tests."""
    if _HAS_DAYTONA:
        return "daytona"
    if _HAS_BWRAP:
        return "bwrap"
    return "none"


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

    Dispatches to the strongest available sandbox:
      - Daytona  (Tier 2: per-test container, network-isolated, ephemeral)
      - bwrap    (Tier 1: namespace-masked filesystem on the host VM)
      - raw      (no sandbox — logged loudly, never preferred)

    All three paths enforce env-scoping and emit an audit log line so ops
    can verify which sandbox each test actually used.
    """
    if _HAS_DAYTONA:
        return _run_once_daytona(
            prompt, expected_artifacts, model, timeout_s, cwd, reminder=reminder
        )
    return _run_once_bwrap(
        prompt, expected_artifacts, model, timeout_s, cwd, reminder=reminder
    )


def _parse_agent_stdout(
    stdout: str, expected_artifacts: list[str], model: str, elapsed: float,
    exit_code: int | None, stderr_tail: str = "",
) -> AgentRunResult:
    """Shared: turn raw gemini stdout into an AgentRunResult.

    Both daytona and bwrap paths end with "we have stdout + exit code, now
    parse the ARTIFACTS block" — keep that logic in one place so the two
    paths can't silently diverge on result shape.
    """
    raw_tail = stdout[-2000:]

    if exit_code is not None and exit_code != 0 and not stdout.strip():
        return AgentRunResult(
            status="error", elapsed_s=elapsed, model=model, exit_code=exit_code,
            stderr_tail=stderr_tail, raw_output=raw_tail,
            error=f"agent exited {exit_code} with no stdout",
        )

    found_marker, parsed = _extract_last_artifacts_block(stdout)

    if not found_marker:
        return AgentRunResult(
            status="malformed", elapsed_s=elapsed, model=model, exit_code=exit_code,
            raw_output=raw_tail, stderr_tail=stderr_tail,
            error="no 'ARTIFACTS:' block found in agent output",
        )
    if parsed is None:
        return AgentRunResult(
            status="malformed", elapsed_s=elapsed, model=model, exit_code=exit_code,
            raw_output=raw_tail, stderr_tail=stderr_tail,
            error="'ARTIFACTS:' marker present but JSON failed to parse",
        )
    if not isinstance(parsed, dict):
        return AgentRunResult(
            status="malformed", elapsed_s=elapsed, model=model, exit_code=exit_code,
            raw_output=raw_tail, stderr_tail=stderr_tail,
            error=f"ARTIFACTS must be a JSON object, got {type(parsed).__name__}",
        )

    artifacts = dict(parsed)
    missing = [k for k in expected_artifacts
               if k not in artifacts or artifacts[k] in (None, "", [], {})]
    if missing:
        return AgentRunResult(
            status="missing_keys", elapsed_s=elapsed, model=model, exit_code=exit_code,
            artifacts=artifacts, missing_keys=missing,
            raw_output=raw_tail, stderr_tail=stderr_tail,
            error=f"ARTIFACTS parsed but missing/empty keys: {missing}",
        )

    return AgentRunResult(
        status="ok", elapsed_s=elapsed, model=model, exit_code=exit_code,
        artifacts=artifacts, raw_output=raw_tail, stderr_tail=stderr_tail,
    )


def _run_once_daytona(
    prompt: str,
    expected_artifacts: list[str],
    model: str,
    timeout_s: int,
    cwd: str,
    reminder: bool = False,
) -> AgentRunResult:
    """Run the agent inside a fresh Daytona sandbox.

    Per-invocation lifecycle:
      1. Create sandbox (~0.2s)
      2. Install gemini CLI (~10s; cached across image if we ever build one)
      3. Write prompt to a file inside the sandbox (base64-encoded transport
         so arbitrary prompt content can't break the shell)
      4. Invoke gemini with GEMINI_API_KEY in per-exec env only
      5. Parse stdout with the shared parser
      6. Destroy sandbox (finally; sandbox leak is a real cost bug)

    If ANY step above fails with an infrastructure error (Daytona API error,
    network, timeout), we return an error-status AgentRunResult and DO NOT
    retry at this layer. The caller (run_agent_task) handles retries.

    Security properties:
      - Host filesystem is invisible to the agent (no /opt/onlybots, no .env)
      - Network egress from sandbox goes out to Daytona's infra, not our VM
      - GEMINI_API_KEY is ephemeral to the sandbox (destroyed on cleanup)
      - No pre-provisioned service keys, no Twilio creds, no wallet seed
      - Sandbox destruction is in `finally` — no persistence across tests
    """
    full_prompt = _build_prompt(prompt, expected_artifacts, reminder=reminder)
    env = _minimal_agent_env()
    gemini_key = env.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return AgentRunResult(
            status="error", model=model, elapsed_s=0.0,
            error="GEMINI_API_KEY not set — agent cannot authenticate",
        )

    _audit_log_invocation(
        model, timeout_s, len(full_prompt), list(env.keys()),
        sandbox_kind="daytona",
    )

    t_start = time.time()
    sandbox = None
    try:
        daytona = _get_daytona_client()
        try:
            sandbox = daytona.create()
        except Exception as e:
            return AgentRunResult(
                status="error", model=model,
                elapsed_s=round(time.time() - t_start, 2),
                error=f"daytona create failed: {type(e).__name__}: {e}",
            )

        # 1. Install gemini CLI. ~10s. Node + npm are already in Daytona's
        # default image. We strip to stderr because `2>&1 >/dev/null` keeps
        # stdout silent unless something real goes wrong.
        try:
            install_r = sandbox.process.exec(
                "npm install -g @google/gemini-cli 2>&1 >/dev/null",
                timeout=120,
            )
        except Exception as e:
            return AgentRunResult(
                status="error", model=model,
                elapsed_s=round(time.time() - t_start, 2),
                error=f"daytona install-exec failed: {type(e).__name__}: {e}",
            )
        if install_r.exit_code != 0:
            return AgentRunResult(
                status="error", model=model,
                elapsed_s=round(time.time() - t_start, 2),
                exit_code=install_r.exit_code,
                stderr_tail=str(install_r.result)[-500:],
                error="gemini CLI install failed inside Daytona sandbox",
            )

        # 2. Transport the prompt via base64. Avoids CLI argument length
        # limits (ARG_MAX) and all shell-escaping concerns.
        prompt_b64 = base64.b64encode(full_prompt.encode("utf-8")).decode("ascii")
        write_cmd = f"echo '{prompt_b64}' | base64 -d > /tmp/onlybots_prompt.txt"
        try:
            write_r = sandbox.process.exec(write_cmd, timeout=15)
        except Exception as e:
            return AgentRunResult(
                status="error", model=model,
                elapsed_s=round(time.time() - t_start, 2),
                error=f"daytona prompt-write failed: {type(e).__name__}: {e}",
            )
        if write_r.exit_code != 0:
            return AgentRunResult(
                status="error", model=model,
                elapsed_s=round(time.time() - t_start, 2),
                exit_code=write_r.exit_code,
                error=f"prompt write to sandbox failed: {str(write_r.result)[-200:]}",
            )

        # 3. Run gemini. The env= dict scopes GEMINI_API_KEY to just this exec.
        run_cmd = (
            f"gemini --yolo -m {shlex.quote(model)} "
            f"-p \"$(cat /tmp/onlybots_prompt.txt)\" 2>&1"
        )
        try:
            run_r = sandbox.process.exec(
                run_cmd,
                env={"GEMINI_API_KEY": gemini_key},
                timeout=timeout_s,
            )
        except Exception as e:
            # Timeout from the SDK surfaces as an exception too
            msg = f"{type(e).__name__}: {e}"
            status = "timeout" if "timeout" in msg.lower() else "error"
            return AgentRunResult(
                status=status, model=model,
                elapsed_s=round(time.time() - t_start, 2),
                error=f"daytona run-exec failed: {msg}",
            )

        elapsed = round(time.time() - t_start, 2)
        return _parse_agent_stdout(
            stdout=str(run_r.result or ""),
            expected_artifacts=expected_artifacts,
            model=model,
            elapsed=elapsed,
            exit_code=run_r.exit_code,
            stderr_tail="",
        )
    finally:
        if sandbox is not None:
            try:
                sandbox.delete()
            except Exception as e:
                # Loud log but don't fail the test — a lingering sandbox costs
                # money but doesn't corrupt results. Surface via metrics later.
                print(f"[agent.runtime.WARNING] daytona sandbox delete failed "
                      f"(sandbox may persist): {type(e).__name__}: {e}")


def _run_once_bwrap(
    prompt: str,
    expected_artifacts: list[str],
    model: str,
    timeout_s: int,
    cwd: str,
    reminder: bool = False,
) -> AgentRunResult:
    """Tier 1 sandbox: bwrap namespaces on the host VM.

    Kept as the fallback path when DAYTONA_API_KEY is unset. Env scoping
    applied, filesystem masked, kernel namespaces unshared. See _bwrap_command
    for the exact isolation flags.
    """
    full_prompt = _build_prompt(prompt, expected_artifacts, reminder=reminder)
    env = _minimal_agent_env()

    base_cmd = ["gemini", "-m", model, "--yolo", "-p", full_prompt]
    if _HAS_BWRAP:
        cmd = _bwrap_command(base_cmd)
        kind = "bwrap"
    else:
        cmd = base_cmd
        kind = "none"
        print("[agent.runtime.WARNING] no sandbox available — running agent "
              "WITHOUT isolation. Install bubblewrap or set DAYTONA_API_KEY.")

    _audit_log_invocation(
        model, timeout_s, len(full_prompt), list(env.keys()),
        sandbox_kind=kind,
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
    return _parse_agent_stdout(
        stdout=completed.stdout or "",
        expected_artifacts=expected_artifacts,
        model=model,
        elapsed=elapsed,
        exit_code=completed.returncode,
        stderr_tail=(completed.stderr or "")[-500:],
    )
