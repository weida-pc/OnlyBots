CREATE TABLE IF NOT EXISTS services (
  id SERIAL PRIMARY KEY,
  slug VARCHAR(150) UNIQUE NOT NULL,
  name VARCHAR(100) NOT NULL,
  url VARCHAR(500) NOT NULL,
  signup_url VARCHAR(500) NOT NULL,
  category VARCHAR(50) NOT NULL,
  description TEXT NOT NULL,
  core_workflow TEXT NOT NULL,
  docs_url VARCHAR(500),
  pricing_url VARCHAR(500),
  contact_email VARCHAR(200) NOT NULL,
  -- 40 chars holds 'pending_domain_verification' (27) and 'awaiting_contract' (17).
  status VARCHAR(40) NOT NULL DEFAULT 'pending',
  failed_at_step INTEGER,
  verified_date TIMESTAMPTZ,
  -- Phase 6: domain ownership verification for submissions.
  -- Submitters must publish the token in a _onlybots-verify TXT record on
  -- their service's domain. Until domain_verified_at is set, the verifier
  -- skips the service (prevents spam submissions for domains you don't own).
  domain_verification_token VARCHAR(64),
  domain_verified_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotent migrations for existing deployments.
ALTER TABLE services ADD COLUMN IF NOT EXISTS domain_verification_token VARCHAR(64);
ALTER TABLE services ADD COLUMN IF NOT EXISTS domain_verified_at TIMESTAMPTZ;
-- Widen status column to fit 'pending_domain_verification' / 'awaiting_contract'.
ALTER TABLE services ALTER COLUMN status TYPE VARCHAR(40);

CREATE TABLE IF NOT EXISTS verification_runs (
  id SERIAL PRIMARY KEY,
  service_id INTEGER NOT NULL REFERENCES services(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL DEFAULT 'running',
  verifier_version VARCHAR(50) NOT NULL,
  evidence_path TEXT
);

CREATE TABLE IF NOT EXISTS verification_results (
  id SERIAL PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES verification_runs(id),
  test_number INTEGER NOT NULL,
  test_name VARCHAR(100) NOT NULL,
  passed BOOLEAN NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.0,
  failure_reason TEXT,
  evidence_artifacts JSONB DEFAULT '{}',
  details JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS twilio_inbound_sms (
  id SERIAL PRIMARY KEY,
  message_sid VARCHAR(64) UNIQUE NOT NULL,  -- Twilio's SMS SID (idempotent webhook)
  from_number VARCHAR(32) NOT NULL,
  to_number VARCHAR(32) NOT NULL,
  body TEXT NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_twilio_sms_to_received
  ON twilio_inbound_sms (to_number, received_at DESC);

-- Public issue tracker. Anyone (human or agent) can file an issue against
-- the registry as a whole or against a specific service. Issues are
-- intentionally low-ceremony — title + body, optional contact, optional
-- service slug. No auth, rate-limited per IP at the API layer.
CREATE TABLE IF NOT EXISTS issues (
  id SERIAL PRIMARY KEY,
  -- NULL = general/site-level issue. When set, must match an existing
  -- services.slug, but we don't enforce FK to keep deletes simple and to
  -- allow referencing un-canonicalised slugs from the form.
  service_slug VARCHAR(150),
  title VARCHAR(200) NOT NULL,
  body TEXT NOT NULL,
  -- Optional email or @handle. We don't validate beyond "looks plausible"
  -- — the registry doesn't email people, this is just so reporters can
  -- leave a way to be contacted.
  reporter_contact VARCHAR(200),
  status VARCHAR(20) NOT NULL DEFAULT 'open',  -- open | acknowledged | closed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_issues_service_slug
  ON issues (service_slug);
CREATE INDEX IF NOT EXISTS idx_issues_created_at
  ON issues (created_at DESC);

-- Grant the app role read/write on the issues table. Idempotent — re-running
-- is a no-op. Wrapped in a DO block so a fresh DB without an `onlybots` role
-- (e.g. a contributor's local instance) doesn't fail the migration.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onlybots') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON issues TO onlybots;
    GRANT USAGE, SELECT ON SEQUENCE issues_id_seq TO onlybots;
  END IF;
END
$$;
