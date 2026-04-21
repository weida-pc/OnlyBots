"""OnlyBots Verifier — main polling loop.

Polls the database for verification runs with status='running',
executes three sequential tests using CLI agent harnesses, and records results.

Usage:
    python main.py              # poll mode (runs forever)
    python main.py --once       # run once and exit (for manual/cron)
    python main.py --retry-failed  # re-queue failed services and run once
"""
from __future__ import annotations
import asyncio
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone

from config import POLL_INTERVAL_SECONDS, VERIFIER_VERSION, HARNESSES
from db import (
    fetch_pending_runs, save_test_result, complete_run,
    update_service_status, retry_failed_services,
    queue_drift_check, find_drifted_services,
    ensure_schema,
)
from evidence import get_evidence_dir
from tests.test_signup import TestSignup
from tests.test_persistence import TestPersistence
from tests.test_workflow import TestWorkflow


TESTS = [TestSignup(), TestPersistence(), TestWorkflow()]


async def verify_service(run: dict) -> None:
    """Run all three tests sequentially for a single service."""
    run_id = run["id"]
    service_id = run["service_id"]
    slug = run.get("slug", "")

    print(f"[verifier] Starting verification for {run['name']} (run {run_id})")

    # Gate: if there is no contract for this service, try to auto-generate one
    # before giving up. The generator uses Gemini to draft a contract from the
    # service's landing page + docs, then validates the output against the
    # same loader that runs in production. If the LLM produces an honest
    # contract (signup via agent_task, no env_secret cheat), we promote and
    # run. If generation fails for any reason, mark awaiting_contract with
    # the specific failure so it's debuggable.
    from contract import has_contract
    if slug and not has_contract(slug):
        print(f"[verifier] {run['name']}: NO CONTRACT — attempting auto-generation")
        try:
            from contract.generate import generate as generate_contract
            generate_contract(slug, overwrite_existing=False)
            # generate_contract writes to <slug>.json on success
            if not has_contract(slug):
                raise RuntimeError(
                    "generator completed but contract file still missing"
                )
            print(f"[verifier] {run['name']}: auto-generated contract, continuing to run tests")
        except SystemExit as e:
            # generate raises SystemExit with a reason string for any of:
            #   - service row missing
            #   - LLM failed to produce parseable JSON
            #   - LLM produced JSON that failed schema validation
            #   - LLM produced a dishonest contract (env_secret in signup, etc.)
            reason = str(e) or "contract generation failed"
            print(f"[verifier] {run['name']}: auto-gen FAILED — {reason}")
            complete_run(run_id, "awaiting_contract", None)
            return
        except Exception as e:
            traceback.print_exc()
            print(f"[verifier] {run['name']}: auto-gen EXCEPTION — {e}")
            complete_run(run_id, "awaiting_contract", None)
            return

    evidence_dir = get_evidence_dir(run_id)
    state: dict = {}  # shared state across tests (credentials, tokens, etc.)
    failed_at_step: int | None = None

    # Pre-flight connectivity check. Sparing agent+sandbox budget on dead
    # domains is worth 10 cheap seconds here — we've seen auto-gen produce
    # contracts for domains that time out, which then burn 5+ minutes of
    # Gemini inside Daytona before surfacing a 'timeout' verdict we could
    # have predicted from TCP failure alone.
    try:
        import http.client
        from urllib.parse import urlparse
        parsed = urlparse(run.get("url") or "")
        host = parsed.netloc
        if host:
            t0 = time.time()
            cls = (http.client.HTTPSConnection if parsed.scheme == "https"
                   else http.client.HTTPConnection)
            conn = cls(host, timeout=8)
            try:
                conn.request("HEAD", parsed.path or "/",
                             headers={"User-Agent": "OnlyBotsBot/1.0 preflight"})
                resp = conn.getresponse()
                reach_status = resp.status
            finally:
                conn.close()
            print(f"[verifier] {run['name']}: preflight {run.get('url')} -> "
                  f"HTTP {reach_status} in {time.time()-t0:.1f}s")
    except Exception as e:
        print(f"[verifier] {run['name']}: preflight FAILED "
              f"({type(e).__name__}: {e}) — service unreachable from verifier. "
              f"Recording all 3 tests as unreachable and completing fast.")
        reason = (f"Service URL {run.get('url')} unreachable from verifier "
                  f"({type(e).__name__}). Likely dead domain, DNS failure, "
                  f"or IP block.")
        for test in TESTS:
            save_test_result(
                run_id=run_id, test_number=test.test_number,
                test_name=test.test_name, passed=False, confidence=1.0,
                failure_reason=reason,
            )
        update_service_status(service_id, "failed", 1, None)
        complete_run(run_id, "failed", str(evidence_dir))
        return

    # Policy: run ALL three tests independently. Earlier failure no longer
    # short-circuits, because a failed signup doesn't invalidate the signal
    # that (say) persistence of an operator-provided key works, or that the
    # public API is alive. Tests whose `requires` depend on state a failed
    # upstream test was supposed to produce will fail themselves with a
    # clean "prerequisite unmet" reason — that's what they're designed to
    # do. The service's roll-up `failed_at_step` remains the FIRST failure
    # (signup autonomy dominates), matching the registry's semantics.
    for test in TESTS:
        print(f"  Running Test {test.test_number}: {test.test_name}...")

        caught_exc: Exception | None = None
        try:
            result = await test.run(run, state, run_id)
        except Exception as e:
            traceback.print_exc()
            result = None
            caught_exc = e

        if result is None:
            # Prefer the exception's message over a generic "Unhandled
            # exception" string so the registry actually tells us what
            # broke. Common cases worth a clean label:
            #   - TemplateError: signup didn't produce required state
            #   - requests / timeout: service unreachable
            if caught_exc is not None:
                exc_type = type(caught_exc).__name__
                exc_msg = str(caught_exc)[:200]
                if "template variable" in exc_msg.lower():
                    reason = (f"Prerequisite unmet: an earlier test was "
                              f"supposed to produce state this test needs. "
                              f"({exc_type}: {exc_msg})")
                else:
                    reason = f"{exc_type}: {exc_msg}"
            else:
                reason = "Unhandled exception in test (no exception captured)"
            save_test_result(
                run_id=run_id,
                test_number=test.test_number,
                test_name=test.test_name,
                passed=False,
                confidence=0.0,
                failure_reason=reason,
            )
            if failed_at_step is None:
                failed_at_step = test.test_number
            print(f"  Test {test.test_number}: EXCEPTION — {reason}")
            continue

        save_test_result(
            run_id=run_id,
            test_number=test.test_number,
            test_name=test.test_name,
            passed=result.passed,
            confidence=result.confidence,
            failure_reason=result.failure_reason,
            evidence_artifacts=result.evidence_artifacts,
            details=result.details,
        )

        if result.passed:
            print(f"  Test {test.test_number}: PASS (confidence: {result.confidence:.0%})")
        else:
            print(f"  Test {test.test_number}: FAIL — {result.failure_reason}")
            if failed_at_step is None:
                failed_at_step = test.test_number

    if failed_at_step is None:
        verified_date = datetime.now(timezone.utc).isoformat()
        update_service_status(service_id, "verified", None, verified_date)
        complete_run(run_id, "passed", str(evidence_dir))
        print(f"[verifier] {run['name']}: VERIFIED ✓")
    else:
        # Drift signal: if the service was previously 'verified' and this run
        # failed, log a distinct line so ops can grep for regressions.
        was_verified = run.get("status_before_this_run") == "verified"
        # (status_before_this_run is the service's status at the moment we
        # fetched the run, before update_service_status flips it to 'failed')
        if was_verified:
            print(f"[verifier] {run['name']}: DRIFT DETECTED — "
                  f"previously verified, now failing at step {failed_at_step}")
        update_service_status(service_id, "failed", failed_at_step, None)
        complete_run(run_id, "failed", str(evidence_dir))
        print(f"[verifier] {run['name']}: FAILED at step {failed_at_step} ✗")


async def poll_once() -> int:
    runs = fetch_pending_runs()
    if not runs:
        return 0
    print(f"[verifier] Found {len(runs)} pending run(s)")
    for run in runs:
        await verify_service(run)
    return len(runs)


async def poll_loop() -> None:
    print(f"[verifier] OnlyBots Verifier v{VERIFIER_VERSION}")
    # Idempotent schema guards — specifically the unique constraint on
    # (run_id, test_number) that save_test_result's upsert depends on.
    try:
        ensure_schema()
    except Exception as e:
        print(f"[verifier] schema check failed (will try to continue): {e}")
    print(f"[verifier] Polling every {POLL_INTERVAL_SECONDS}s...")
    while True:
        try:
            count = await poll_once()
            if count > 0:
                print(f"[verifier] Processed {count} run(s)")
        except KeyboardInterrupt:
            print("\n[verifier] Shutting down...")
            break
        except Exception:
            traceback.print_exc()
            print("[verifier] Error in poll cycle, retrying...")
        time.sleep(POLL_INTERVAL_SECONDS)


def check_harnesses():
    """Check which CLI agent harnesses are installed."""
    print("[verifier] Checking installed harnesses:")
    for name, cfg in HARNESSES.items():
        cmd = cfg["cmd"]
        found = shutil.which(cmd)
        key_set = "✓" if cfg["api_key"] else "✗"
        if found:
            print(f"  {name:12s} {cmd:12s} installed ✓  key {key_set}")
        else:
            print(f"  {name:12s} {cmd:12s} NOT FOUND ✗  key {key_set}")


def main():
    check_harnesses()
    print()

    retry = "--retry-failed" in sys.argv
    drift = "--drift-check" in sys.argv
    list_drift = "--list-drift" in sys.argv
    once = "--once" in sys.argv or retry or drift

    if list_drift:
        drifted = find_drifted_services()
        if not drifted:
            print("[verifier] No drifted services (all latest runs match prior passing state).")
        else:
            print(f"[verifier] {len(drifted)} drifted service(s) — previously passed, now failing:")
            for d in drifted:
                print(f"  - {d['slug']:20s} last failed at {d['latest_failed_at']}")
        return

    if retry:
        print("[verifier] Re-queuing failed services...")
        count = retry_failed_services()
        print(f"[verifier] Re-queued {count} service(s)")

    if drift:
        # Phase 4: re-run verified services whose last check is stale.
        # Intended to be run on a schedule (cron / systemd timer).
        staleness = 24
        for arg in sys.argv:
            if arg.startswith("--staleness-hours="):
                staleness = int(arg.split("=", 1)[1])
        print(f"[verifier] Drift check: queuing re-runs for services stale >{staleness}h...")
        count = queue_drift_check(staleness_hours=staleness,
                                   verifier_version=VERIFIER_VERSION)
        print(f"[verifier] Queued {count} drift-check run(s)")

    if once:
        print("[verifier] Running single poll...")
        count = asyncio.run(poll_once())
        print(f"[verifier] Done. Processed {count} run(s).")
    else:
        asyncio.run(poll_loop())


if __name__ == "__main__":
    main()
