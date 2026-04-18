import { NextRequest, NextResponse } from "next/server";
import {
  getServiceBySlug,
  markDomainVerifiedAndQueueRun,
  redactServiceSecrets,
} from "@/lib/db";
import {
  hostnameForUrl,
  txtRecordName,
  expectedTxtValue,
  verifyDomainTxt,
} from "@/lib/domain-verification";

/**
 * Phase 6 — domain ownership verification endpoint.
 *
 * POST /api/services/:slug/verify-domain
 *
 * Performs a DoH TXT lookup on `_onlybots-verify.<hostname>` for the service's
 * URL hostname. If the record contains the token stored on the service, the
 * service is flipped from `pending_domain_verification` to `pending` and a
 * verification run is queued — atomically — so concurrent requests can't
 * produce duplicate runs.
 *
 * SECURITY: this endpoint never echoes the domain_verification_token. The
 * token is returned ONCE at submission time. Exposing it in subsequent
 * responses would let anyone who guesses the slug retrieve it and set up
 * the TXT record themselves.
 */
export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;
  const service = await getServiceBySlug(slug);
  if (!service) {
    return NextResponse.json({ error: "Service not found" }, { status: 404 });
  }

  if (service.domain_verified_at) {
    return NextResponse.json(
      {
        service: redactServiceSecrets(service),
        message: "Domain already verified.",
        domain_verification: {
          status: "verified",
          verified_at: service.domain_verified_at,
        },
      },
      { status: 200 }
    );
  }

  const token = service.domain_verification_token;
  if (!token) {
    return NextResponse.json(
      { error: "Service has no verification token. Re-submit the service." },
      { status: 400 }
    );
  }

  const hostname = hostnameForUrl(service.url);
  const { verified, records } = await verifyDomainTxt(hostname, token);

  if (!verified) {
    return NextResponse.json(
      {
        service: redactServiceSecrets(service),
        domain_verification: {
          status: "pending",
          record_name: txtRecordName(hostname),
          // NOTE: we deliberately do NOT include the expected token value
          // here — it's the token itself. Submitters have the expected value
          // from the submit response; this endpoint just confirms/denies.
          records_found: records,
          hint:
            records.length === 0
              ? "No TXT records found at this name. DNS may still be propagating (wait 1–5 minutes). If you've added the record recently, try again shortly."
              : "TXT records exist but none contain the expected token. Double-check for trailing whitespace, stray quotes, or a typo; the value must match the submit response exactly.",
        },
      },
      { status: 422 }
    );
  }

  // Atomic flip + queue. Returns null if a concurrent request already
  // verified (a racing caller may see the service row but the UPDATE
  // predicate `domain_verified_at IS NULL` guarantees only one wins).
  const updated = await markDomainVerifiedAndQueueRun(slug);
  if (!updated) {
    // A concurrent request verified first. Return the already-verified state.
    const fresh = await getServiceBySlug(slug);
    return NextResponse.json(
      {
        service: fresh ? redactServiceSecrets(fresh) : null,
        message: "Domain already verified by a concurrent request.",
        domain_verification: {
          status: "verified",
          verified_at: fresh?.domain_verified_at,
        },
      },
      { status: 200 }
    );
  }

  return NextResponse.json(
    {
      service: redactServiceSecrets(updated),
      message:
        "Domain verified. Service queued for verification (you will see " +
        "results within 24–48 hours).",
      domain_verification: {
        status: "verified",
        verified_at: updated.domain_verified_at,
      },
    },
    { status: 200 }
  );
}
