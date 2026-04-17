"""Database helpers for the verifier."""
import psycopg2
import psycopg2.extras
from config import DATABASE_URL


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def fetch_pending_runs():
    """Return verification runs with status='running' joined with service info.

    Includes `status_before_this_run` (alias for services.status) so the
    runner can detect drift — a service that was 'verified' before this run
    and fails now is a regression, not a first-time failure.
    """
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT vr.*, s.slug, s.name, s.url, s.signup_url,
                       s.category, s.description, s.core_workflow,
                       s.docs_url, s.pricing_url,
                       s.status AS status_before_this_run
                FROM verification_runs vr
                JOIN services s ON s.id = vr.service_id
                WHERE vr.status = 'running'
                ORDER BY vr.started_at ASC
            """)
            return cur.fetchall()
    finally:
        conn.close()


def save_test_result(run_id: int, test_number: int, test_name: str,
                     passed: bool, confidence: float,
                     failure_reason: str | None = None,
                     evidence_artifacts: dict | None = None,
                     details: dict | None = None):
    """Insert a single test result row."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO verification_results
                    (run_id, test_number, test_name, passed, confidence,
                     failure_reason, evidence_artifacts, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                run_id, test_number, test_name, passed, confidence,
                failure_reason,
                psycopg2.extras.Json(evidence_artifacts or {}),
                psycopg2.extras.Json(details or {}),
            ))
        conn.commit()
    finally:
        conn.close()


def complete_run(run_id: int, status: str, evidence_path: str | None = None):
    """Mark a verification run as passed or failed."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE verification_runs
                SET status = %s, completed_at = NOW(), evidence_path = %s
                WHERE id = %s
            """, (status, evidence_path, run_id))
        conn.commit()
    finally:
        conn.close()


def update_service_status(service_id: int, status: str,
                          failed_at_step: int | None = None,
                          verified_date: str | None = None):
    """Update the service's overall verification status."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE services
                SET status = %s, failed_at_step = %s, verified_date = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (status, failed_at_step, verified_date, service_id))
        conn.commit()
    finally:
        conn.close()


def queue_drift_check(staleness_hours: int = 24,
                       verifier_version: str = "0.4.0-drift") -> int:
    """Queue re-runs for verified services whose last verification is older
    than `staleness_hours`. Returns the number of runs queued.

    This is the Phase 4 drift detection mechanism. It doesn't mark anything as
    drifted — it simply re-runs the verification. If a service that was
    passing starts failing, the existing verify_service logic flips its
    status to 'failed' and the normal alerting (if any) triggers. Drift
    detection is the act of *running the check periodically*, not a new
    pass/fail state.
    """
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT s.id, s.slug
                FROM services s
                WHERE s.status = 'verified'
                  AND (s.updated_at IS NULL
                       OR s.updated_at < NOW() - INTERVAL '%s hours')
                  -- Don't queue if there's already a pending/running run
                  AND NOT EXISTS (
                      SELECT 1 FROM verification_runs r
                      WHERE r.service_id = s.id
                        AND r.status IN ('running', 'queued')
                  )
            """, (staleness_hours,))
            stale = cur.fetchall()

            count = 0
            for row in stale:
                cur.execute("""
                    INSERT INTO verification_runs
                        (service_id, status, started_at, verifier_version)
                    VALUES (%s, 'running', NOW(), %s)
                """, (row["id"], verifier_version))
                count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def find_drifted_services() -> list[dict]:
    """Return services that appear to have drifted: their latest run is
    failing, but an earlier run was passing. Useful for a dashboard or a
    one-shot cron-driven alert.
    """
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                WITH latest AS (
                    SELECT DISTINCT ON (service_id) service_id, status, completed_at
                    FROM verification_runs
                    WHERE status IN ('passed', 'failed')
                    ORDER BY service_id, started_at DESC
                ),
                ever_passed AS (
                    SELECT DISTINCT service_id
                    FROM verification_runs
                    WHERE status = 'passed'
                )
                SELECT s.id, s.slug, s.name, l.completed_at AS latest_failed_at
                FROM services s
                JOIN latest l ON l.service_id = s.id
                JOIN ever_passed ep ON ep.service_id = s.id
                WHERE l.status = 'failed'
                ORDER BY l.completed_at DESC
            """)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def retry_failed_services() -> int:
    """Re-queue all failed services: reset status to pending & create new runs."""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Find failed services
            cur.execute("SELECT id FROM services WHERE status = 'failed'")
            failed = cur.fetchall()

            count = 0
            for row in failed:
                sid = row["id"]
                # Reset service status to pending
                cur.execute("""
                    UPDATE services
                    SET status = 'pending', failed_at_step = NULL, updated_at = NOW()
                    WHERE id = %s
                """, (sid,))
                # Create a new verification run
                cur.execute("""
                    INSERT INTO verification_runs (service_id, status, started_at, verifier_version)
                    VALUES (%s, 'running', NOW(), %s)
                """, (sid, "0.2.0"))
                count += 1

        conn.commit()
        return count
    finally:
        conn.close()
