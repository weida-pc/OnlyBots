"""Backfill `details.agent_task_model` into existing verification_results.

Run-once migration for the tests/_common.py change (verifier records the
model the contract's agent_task ACTUALLY specifies, not the harness-
default fallback). Old rows have `details.model = <harness default>`
and no agent_task_model. This reads every contract on disk, finds the
per-test agent_task.model, and patches that into the matching rows.

For tests whose contract has no agent_task (pure-HTTP contract path),
set `details.agent_task_model = null` explicitly so the frontend knows
to render the "no LLM used" placeholder instead of a misleading default.

Safe to re-run — if a row already has agent_task_model, it's skipped
unless --overwrite is passed.

Usage (on the VM):
  sudo /opt/onlybots/verifier/venv/bin/python \
    /opt/onlybots/verifier/deploy/backfill-agent-task-model.py
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

# Add verifier/ to path so `from config import ...` and
# `from contract.loader import ...` resolve. Script can be invoked from
# anywhere; we always resolve relative to the script's own location.
HERE = Path(__file__).resolve().parent
for candidate in (HERE.parent / "verifier", HERE.parent, Path("/opt/onlybots/verifier")):
    if (candidate / "config.py").exists():
        sys.path.insert(0, str(candidate))
        break

import psycopg2
import psycopg2.extras
from config import DATABASE_URL
from contract.loader import load_contract, has_contract

TEST_NAME_BY_NUMBER = {1: "signup", 2: "persistence", 3: "workflow"}


def main(overwrite: bool = False) -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT vr.id AS result_id, vr.test_number, vr.details,
                          s.slug
                   FROM verification_results vr
                   JOIN verification_runs r ON r.id = vr.run_id
                   JOIN services s ON s.id = r.service_id
                   ORDER BY vr.id"""
            )
            rows = cur.fetchall()

        # Cache contracts per-slug so we don't re-parse 100 files
        contract_cache: dict[str, object | None] = {}

        updated = 0
        skipped_existing = 0
        no_contract = 0
        for row in rows:
            slug = row["slug"]
            details = row["details"] or {}
            if (not overwrite) and "agent_task_model" in details:
                skipped_existing += 1
                continue

            if slug not in contract_cache:
                contract_cache[slug] = (
                    load_contract(slug) if has_contract(slug) else None
                )
            contract = contract_cache[slug]
            if contract is None:
                no_contract += 1
                # Still update — record that we tried — so the UI
                # renders cleanly instead of the stale default.
                details["agent_task_model"] = None
            else:
                test_name = TEST_NAME_BY_NUMBER.get(row["test_number"])
                test = contract.tests.get(test_name) if test_name else None
                if test and test.agent_task and test.agent_task.model:
                    details["agent_task_model"] = test.agent_task.model
                else:
                    details["agent_task_model"] = None

            # Also normalize `method` from the legacy "direct_http" to
            # "contract" (accurate — runner executes a declared contract)
            if details.get("method") == "direct_http":
                details["method"] = "contract"

            with conn.cursor() as upd:
                upd.execute(
                    "UPDATE verification_results SET details = %s WHERE id = %s",
                    (psycopg2.extras.Json(details), row["result_id"]),
                )
            updated += 1

        conn.commit()
        print(
            f"Updated {updated} rows; skipped {skipped_existing} already-"
            f"backfilled; {no_contract} had no contract on disk."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main(overwrite="--overwrite" in sys.argv)
