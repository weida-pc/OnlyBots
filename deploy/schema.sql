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
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  failed_at_step INTEGER,
  verified_date TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
