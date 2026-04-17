import { Pool } from "pg";
import { slugify } from "./utils";
import type { Service, ServiceWithVerification, VerificationRun } from "./types";

// Pool is only initialised when DATABASE_URL is available so the app doesn't
// crash at build time or in environments without a database.
let pool: Pool | null = null;

function getPool(): Pool | null {
  if (!process.env.DATABASE_URL) return null;
  if (!pool) {
    pool = new Pool({
      connectionString: process.env.DATABASE_URL,
      max: 5,
    });
  }
  return pool;
}

export async function query(text: string, params?: unknown[]) {
  const p = getPool();
  if (!p) return { rows: [], rowCount: 0 };
  return p.query(text, params as unknown[]);
}

export async function getServices(filters?: {
  q?: string;
  category?: string;
  status?: string;
}): Promise<Service[]> {
  const p = getPool();
  if (!p) return [];

  const conditions: string[] = [];
  const params: unknown[] = [];
  let idx = 1;

  if (filters?.q) {
    conditions.push(
      `(name ILIKE $${idx} OR description ILIKE $${idx})`
    );
    params.push(`%${filters.q}%`);
    idx++;
  }

  if (filters?.category) {
    conditions.push(`category = $${idx}`);
    params.push(filters.category);
    idx++;
  }

  if (filters?.status) {
    conditions.push(`status = $${idx}`);
    params.push(filters.status);
    idx++;
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

  const sql = `
    SELECT *
    FROM services
    ${where}
    ORDER BY
      CASE status
        WHEN 'verified' THEN 1
        WHEN 'failed'   THEN 2
        WHEN 'pending'  THEN 3
        ELSE 4
      END,
      name ASC
  `;

  const result = await p.query(sql, params);
  return result.rows as Service[];
}

export async function getServiceBySlug(
  slug: string
): Promise<ServiceWithVerification | null> {
  const p = getPool();
  if (!p) return null;

  const serviceResult = await p.query(
    "SELECT * FROM services WHERE slug = $1",
    [slug]
  );

  if (serviceResult.rows.length === 0) return null;

  const service = serviceResult.rows[0] as Service;

  // Fetch the most recent verification run for this service
  const runResult = await p.query(
    `SELECT * FROM verification_runs
     WHERE service_id = $1
     ORDER BY started_at DESC
     LIMIT 1`,
    [service.id]
  );

  if (runResult.rows.length === 0) {
    return { ...service, verification: null };
  }

  const run = runResult.rows[0] as VerificationRun;

  const resultsResult = await p.query(
    `SELECT * FROM verification_results
     WHERE run_id = $1
     ORDER BY test_number ASC`,
    [run.id]
  );

  return {
    ...service,
    verification: {
      run,
      results: resultsResult.rows,
    },
  };
}

export async function createService(data: {
  name: string;
  url: string;
  signup_url: string;
  category: string;
  description: string;
  core_workflow: string;
  docs_url?: string;
  pricing_url?: string;
  contact_email: string;
  domain_verification_token: string;
}): Promise<Service> {
  const p = getPool();
  if (!p) throw new Error("DATABASE_URL is not configured");

  // Generate a unique slug
  const baseSlug = slugify(data.name);
  let slug = baseSlug;
  let attempt = 1;

  while (true) {
    const existing = await p.query("SELECT id FROM services WHERE slug = $1", [
      slug,
    ]);
    if (existing.rows.length === 0) break;
    attempt++;
    slug = `${baseSlug}-${attempt}`;
  }

  // New submissions land in pending_domain_verification. The verifier
  // skips this status; only after the domain TXT record is confirmed does
  // the service flip to 'pending' and become eligible for verification.
  const result = await p.query(
    `INSERT INTO services
       (slug, name, url, signup_url, category, description, core_workflow,
        docs_url, pricing_url, contact_email, status,
        domain_verification_token)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
             'pending_domain_verification', $11)
     RETURNING *`,
    [
      slug,
      data.name,
      data.url,
      data.signup_url,
      data.category,
      data.description,
      data.core_workflow,
      data.docs_url ?? null,
      data.pricing_url ?? null,
      data.contact_email,
      data.domain_verification_token,
    ]
  );

  return result.rows[0] as Service;
}


/**
 * Mark a service's domain as verified: timestamp it and flip status to
 * 'pending' so the verifier picks it up. Returns the updated row, or null
 * if the slug doesn't exist.
 */
export async function markDomainVerified(slug: string): Promise<Service | null> {
  const p = getPool();
  if (!p) throw new Error("DATABASE_URL is not configured");
  const result = await p.query(
    `UPDATE services
       SET domain_verified_at = NOW(),
           status = 'pending',
           updated_at = NOW()
     WHERE slug = $1
       AND domain_verified_at IS NULL
     RETURNING *`,
    [slug]
  );
  return (result.rows[0] ?? null) as Service | null;
}

export async function createVerificationRun(
  serviceId: number
): Promise<VerificationRun> {
  const p = getPool();
  if (!p) throw new Error("DATABASE_URL is not configured");

  const result = await p.query(
    `INSERT INTO verification_runs (service_id, status, verifier_version)
     VALUES ($1, 'running', '0.1.0')
     RETURNING *`,
    [serviceId]
  );

  return result.rows[0] as VerificationRun;
}

export async function updateServiceStatus(
  serviceId: number,
  status: string,
  failedAtStep: number | null,
  verifiedDate: string | null
): Promise<void> {
  const p = getPool();
  if (!p) throw new Error("DATABASE_URL is not configured");

  await p.query(
    `UPDATE services
     SET status = $1,
         failed_at_step = $2,
         verified_date = $3,
         updated_at = NOW()
     WHERE id = $4`,
    [status, failedAtStep, verifiedDate, serviceId]
  );
}

export async function checkDuplicateUrl(url: string): Promise<boolean> {
  const p = getPool();
  if (!p) return false;

  const result = await p.query(
    "SELECT id FROM services WHERE url = $1 LIMIT 1",
    [url]
  );

  return result.rows.length > 0;
}
