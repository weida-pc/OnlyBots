"""Database helpers for the verifier."""
import psycopg2
import psycopg2.extras
from config import DATABASE_URL


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def fetch_pending_runs():
    """Return verification runs with status='running' joined with service info."""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT vr.*, s.slug, s.name, s.url, s.signup_url,
                       s.category, s.description, s.core_workflow,
                       s.docs_url, s.pricing_url
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
