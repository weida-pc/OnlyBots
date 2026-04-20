import { NextRequest, NextResponse } from "next/server";
import {
  getServiceBySlug,
  markDomainVerifiedAndQueueRun,
  redactServiceSecrets,
} from "@/lib/db";

/**
 * POST /api/admin/services/:slug/force-verify
 *
 * Operator-only bypass of the domain-ownership TXT-record gate. Used when
 * testing services the operator doesn't own (which is most of them).
 *
 * Without this endpoint, an operator has to either:
 *   - Own the target domain (rarely true)
 *   - Manually UPDATE the services row via psql (we did exactly this during
 *     the Coinos validation — fragile, no audit trail)
 *
 * Auth: requires the same `ADMIN_API_KEY` env var already used elsewhere.
 * The key is passed as `X-Admin-Key` header. Missing or mismatching → 401.
 *
 * Behavior (idempotent):
 *   - 200 if the service exists; flips domain_verified_at → NOW() if unset,
 *     status → 'pending', and queues a verification run
 *   - 200 no-op if domain was already verified
 *   - 404 if the slug doesn't exist
 *   - 401 if admin key missing/wrong
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string }> }
) {
  const expectedKey = process.env.ADMIN_API_KEY;
  if (!expectedKey) {
    return NextResponse.json(
      { error: "ADMIN_API_KEY not configured on server" },
      { status: 503 }
    );
  }

  const provided = request.headers.get("x-admin-key") ?? "";
  if (provided !== expectedKey) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const { slug } = await params;
  const existing = await getServiceBySlug(slug);
  if (!existing) {
    return NextResponse.json({ error: "service not found" }, { status: 404 });
  }

  // Idempotent: if already verified, just return the current state.
  if (existing.domain_verified_at) {
    return NextResponse.json(
      {
        service: redactServiceSecrets(existing),
        message: "already verified (no-op)",
        action: "none",
      },
      { status: 200 }
    );
  }

  const updated = await markDomainVerifiedAndQueueRun(slug);
  if (!updated) {
    // Race: concurrent force-verify or verify-domain won. Re-fetch.
    const fresh = await getServiceBySlug(slug);
    return NextResponse.json(
      {
        service: fresh ? redactServiceSecrets(fresh) : null,
        message: "already verified by concurrent request",
        action: "none",
      },
      { status: 200 }
    );
  }

  return NextResponse.json(
    {
      service: redactServiceSecrets(updated),
      message:
        "Domain force-verified by admin. Verification run queued. " +
        "Results within ~24h.",
      action: "force_verified",
    },
    { status: 200 }
  );
}
