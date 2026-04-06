import { Pool } from "pg";

const DATABASE_URL = process.env.DATABASE_URL;

if (!DATABASE_URL) {
  console.error("ERROR: DATABASE_URL environment variable is not set.");
  process.exit(1);
}

const pool = new Pool({
  connectionString: DATABASE_URL,
  max: 5,
});

async function createTables(client: Awaited<ReturnType<Pool["connect"]>>) {
  await client.query(`
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
    )
  `);

  await client.query(`
    CREATE TABLE IF NOT EXISTS verification_runs (
      id SERIAL PRIMARY KEY,
      service_id INTEGER NOT NULL REFERENCES services(id),
      started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      completed_at TIMESTAMPTZ,
      status VARCHAR(20) NOT NULL DEFAULT 'running',
      verifier_version VARCHAR(50) NOT NULL,
      evidence_path TEXT
    )
  `);

  await client.query(`
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
    )
  `);

  console.log("Tables created (or already exist).");
}

interface SeedEntry {
  slug: string;
  name: string;
  url: string;
  signup_url: string;
  category: string;
  description: string;
  core_workflow: string;
  docs_url: string | null;
  pricing_url: string | null;
  contact_email: string;
}

const seeds: SeedEntry[] = [
  {
    slug: "agentmail-to",
    name: "AgentMail",
    url: "https://agentmail.to",
    signup_url: "https://console.agentmail.to",
    category: "communication",
    description:
      "Email inbox API for AI agents — create inboxes, send and receive email programmatically",
    core_workflow:
      "Create inbox via API, receive email at generated address, send reply",
    docs_url: "https://docs.agentmail.to",
    pricing_url: "https://agentmail.to/pricing",
    contact_email: "hello@agentmail.to",
  },
  {
    slug: "here-now",
    name: "here.now",
    url: "https://here.now",
    signup_url: "https://here.now",
    category: "hosting",
    description:
      "Free instant web hosting for agents — publish files and get a live URL in seconds",
    core_workflow:
      "POST files to API, receive live URL at name.here.now",
    docs_url: "https://here.now/docs",
    pricing_url: "https://here.now",
    contact_email: "support@here.now",
  },
  {
    slug: "moltbook",
    name: "Moltbook",
    url: "https://moltbook.com",
    signup_url: "https://moltbook.com/register",
    category: "communication",
    description:
      "Social network exclusively for AI agents — post, comment, and vote in topic-specific groups",
    core_workflow:
      "Register account, create post in a submolt, comment and vote",
    docs_url: "https://moltbook.com/skill.md",
    pricing_url: "https://moltbook.com",
    contact_email: "support@moltbook.com",
  },
  {
    slug: "signbee",
    name: "Signbee",
    url: "https://signb.ee",
    signup_url: "https://signb.ee/signup",
    category: "execution",
    description:
      "Document signing API for AI agents — send, sign, and verify documents with a single API call",
    core_workflow:
      "Send document via API, collect recipient signature, retrieve signed PDF with certificate",
    docs_url: "https://signb.ee/docs",
    pricing_url: "https://signb.ee/pricing",
    contact_email: "hello@signb.ee",
  },
  {
    slug: "browser-use",
    name: "Browser Use",
    url: "https://browser-use.com",
    signup_url: "https://browser-use.com",
    category: "execution",
    description:
      "Browser automation for AI agents — control stealth browsers via API with LLM-solvable signup",
    core_workflow:
      "Solve signup math challenge, obtain API key, start and control browser session",
    docs_url: "https://docs.browser-use.com",
    pricing_url: "https://browser-use.com/pricing",
    contact_email: "support@browser-use.com",
  },
];

async function seedServices(client: Awaited<ReturnType<Pool["connect"]>>) {
  for (const s of seeds) {
    await client.query(
      `INSERT INTO services
         (slug, name, url, signup_url, category, description, core_workflow,
          docs_url, pricing_url, contact_email, status)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'pending')
       ON CONFLICT (slug) DO UPDATE SET
         name          = EXCLUDED.name,
         url           = EXCLUDED.url,
         signup_url    = EXCLUDED.signup_url,
         category      = EXCLUDED.category,
         description   = EXCLUDED.description,
         core_workflow = EXCLUDED.core_workflow,
         docs_url      = EXCLUDED.docs_url,
         pricing_url   = EXCLUDED.pricing_url,
         contact_email = EXCLUDED.contact_email,
         updated_at    = NOW()`,
      [
        s.slug,
        s.name,
        s.url,
        s.signup_url,
        s.category,
        s.description,
        s.core_workflow,
        s.docs_url,
        s.pricing_url,
        s.contact_email,
      ]
    );
    console.log(`Upserted: ${s.name} (${s.slug})`);
  }
}

async function main() {
  const client = await pool.connect();
  try {
    await createTables(client);
    await seedServices(client);
    console.log("Seed complete.");
  } finally {
    client.release();
    await pool.end();
  }
}

main().catch((err) => {
  console.error("Seed failed:", err);
  process.exit(1);
});
