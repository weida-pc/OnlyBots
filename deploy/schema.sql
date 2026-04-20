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
