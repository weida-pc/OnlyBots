import { NextRequest, NextResponse } from "next/server";
import {
  getServiceBySlug,
  markDomainVerified,
  createVerificationRun,
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
 * verification run is queued. Otherwise we return what we found so the
 * submitter can debug.
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
        service,
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
        service,
        domain_verification: {
          status: "pending",
          record_name: txtRecordName(hostname),
          expected_value: expectedTxtValue(token),
          records_found: records,
          hint:
            records.length === 0
              ? "No TXT records found. DNS may still be propagating (up to a few minutes)."
              : "TXT records exist but none contain the expected token value.",
        },
      },
      { status: 422 }
    );
  }

  // Verified: flip status and queue the first verification run.
  const updated = await markDomainVerified(slug);
  if (updated) {
    await createVerificationRun(updated.id);
  }

  return NextResponse.json(
    {
      service: updated ?? service,
      message:
        "Domain verified. Service queued for verification (you will see " +
        "results within 24–48 hours).",
      domain_verification: {
        status: "verified",
        verified_at: updated?.domain_verified_at,
      },
    },
    { status: 200 }
  );
}
