import { NextRequest, NextResponse } from "next/server";
import {
  checkDuplicateUrl,
  createService,
  markDomainVerifiedAndQueueRun,
  redactServiceSecrets,
} from "@/lib/db";
import { submitServiceSchema } from "@/lib/schema";
import { inferMetadataFromUrl, fillDefaults } from "@/lib/metadata";
import { generateVerificationToken } from "@/lib/domain-verification";

/**
 * POST /api/admin/quick-submit
 *
 * Operator shortcut: submit + force-verify-domain + queue a run in one call.
 * Takes the same body as POST /api/services/submit (minimum `{"url":"..."}`)
 * plus requires an `X-Admin-Key` header matching ADMIN_API_KEY.
 *
 * This is how we test the submission path end-to-end for services whose
 * domains we don't own. The public submit endpoint still enforces the TXT
 * anti-spam gate for everyone else.
 *
 * Returns the created service and the id of the queued verification run.
 */
export async function POST(request: NextRequest) {
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

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const parsed = submitServiceSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      {
        error: "Validation failed",
        details: parsed.error.flatten().fieldErrors,
      },
      { status: 400 }
    );
  }

  const input = parsed.data;

  const needsInference =
    !input.name ||
    !input.description ||
    !input.signup_url ||
    !input.category ||
    !input.core_workflow ||
    !input.contact_email;

  const inferred = needsInference ? await inferMetadataFromUrl(input.url) : {};

  if (inferred.squatter) {
    return NextResponse.json(
      {
        error:
          "Submitted URL appears to be a domain parking / 'for sale' page, " +
          "not a live service. Refusing to add it to the registry.",
        inferred_name: inferred.name,
        inferred_description: inferred.description,
      },
      { status: 400 }
    );
  }

  const merged = fillDefaults(input.url, {
    name: input.name || inferred.name,
    description: input.description || inferred.description,
    signup_url: input.signup_url || inferred.signup_url,
    docs_url: input.docs_url || inferred.docs_url,
    category: input.category || inferred.category,
    core_workflow: input.core_workflow || inferred.core_workflow,
    contact_email: input.contact_email || inferred.contact_email,
  });

  if (await checkDuplicateUrl(input.url)) {
    return NextResponse.json(
      { error: "A service with this URL has already been submitted." },
      { status: 409 }
    );
  }

  const token = generateVerificationToken();
  const service = await createService({
    ...merged,
    url: input.url,
    pricing_url: input.pricing_url,
    domain_verification_token: token,
  });

  // Bypass the TXT gate: mark the domain verified and enqueue the run in a
  // single transaction. Same primitive used by /api/admin/services/:slug/
  // force-verify — reusing it keeps the "operator-force-verified" audit
  // trail consistent.
  const verified = await markDomainVerifiedAndQueueRun(service.slug);

  return NextResponse.json(
    {
      service: redactServiceSecrets(verified ?? service),
      inferred: needsInference ? inferred : null,
      run_queued: !!verified,
      action: "submitted_and_force_verified",
      message:
        "Service submitted and domain force-verified by admin. A verification " +
        "run is queued; poll GET /api/services/" +
        service.slug +
        " for results (typical ~1-3 min).",
    },
    { status: 201 }
  );
}
