import { NextRequest, NextResponse } from "next/server";
import { checkDuplicateUrl, createService } from "@/lib/db";
import { submitServiceSchema } from "@/lib/schema";
import { inferMetadataFromUrl, fillDefaults } from "@/lib/metadata";
import {
  generateVerificationToken,
  hostnameForUrl,
  txtRecordName,
  expectedTxtValue,
} from "@/lib/domain-verification";

interface RateLimitEntry {
  count: number;
  resetAt: number;
}

const rateLimitMap = new Map<string, RateLimitEntry>();

const RATE_LIMIT_MAX = 10;
const RATE_LIMIT_WINDOW_MS = 24 * 60 * 60 * 1000; // 24 hours

function getClientIp(request: NextRequest): string {
  return request.headers.get("x-forwarded-for")?.split(",")[0].trim() ?? "unknown";
}

function checkRateLimit(ip: string): { allowed: boolean; remaining: number } {
  const now = Date.now();
  const entry = rateLimitMap.get(ip);

  if (!entry || now >= entry.resetAt) {
    rateLimitMap.set(ip, { count: 1, resetAt: now + RATE_LIMIT_WINDOW_MS });
    return { allowed: true, remaining: RATE_LIMIT_MAX - 1 };
  }

  if (entry.count >= RATE_LIMIT_MAX) {
    return { allowed: false, remaining: 0 };
  }

  entry.count += 1;
  return { allowed: true, remaining: RATE_LIMIT_MAX - entry.count };
}

/**
 * POST /api/services/submit
 *
 * Minimum payload: {"url": "https://example.com"}. Everything else is
 * either supplied by the submitter or inferred from the landing page.
 *
 * Flow:
 *   1. Rate-limit per IP (10 / 24h)
 *   2. Parse + validate — only `url` is required
 *   3. For missing fields, fetch the URL once and infer from HTML
 *   4. Check duplicate URL
 *   5. Generate a domain-verification token + create the service row
 *   6. Return the TXT-record instructions. Verification runs after
 *      domain ownership is proven via /api/services/:slug/verify-domain.
 */
export async function POST(request: NextRequest) {
  const ip = getClientIp(request);
  const { allowed, remaining } = checkRateLimit(ip);

  if (!allowed) {
    return NextResponse.json(
      { error: "Rate limit exceeded. You may submit up to 10 services per 24 hours." },
      {
        status: 429,
        headers: {
          "X-RateLimit-Limit": String(RATE_LIMIT_MAX),
          "X-RateLimit-Remaining": "0",
          "Retry-After": String(60 * 60 * 24),
        },
      }
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const result = submitServiceSchema.safeParse(body);

  if (!result.success) {
    return NextResponse.json(
      {
        error: "Validation failed",
        details: result.error.flatten().fieldErrors,
      },
      { status: 400 }
    );
  }

  const input = result.data;

  // Fill missing fields by fetching the landing page. This runs once per
  // submission and is best-effort — any field we can't infer falls back
  // to a hostname-derived default in fillDefaults().
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

  const isDuplicate = await checkDuplicateUrl(input.url);
  if (isDuplicate) {
    return NextResponse.json(
      { error: "A service with this URL has already been submitted." },
      { status: 409 }
    );
  }

  // Phase 6 anti-spam: domain ownership gate. Run is queued by
  // /api/services/:slug/verify-domain once the TXT record is published.
  const token = generateVerificationToken();
  const service = await createService({
    ...merged,
    url: input.url,
    pricing_url: input.pricing_url,
    domain_verification_token: token,
  });

  const hostname = hostnameForUrl(service.url);
  return NextResponse.json(
    {
      service,
      inferred: needsInference ? inferred : null,
      message:
        "Service submitted. Before verification runs, prove domain ownership " +
        "by publishing a TXT record and calling /api/services/:slug/verify-domain.",
      domain_verification: {
        status: "pending",
        record_name: txtRecordName(hostname),
        record_value: expectedTxtValue(token),
        record_type: "TXT",
        instructions:
          `Add a DNS TXT record on "${txtRecordName(hostname)}" with the ` +
          `value "${expectedTxtValue(token)}". Then POST to ` +
          `/api/services/${service.slug}/verify-domain. The verifier will ` +
          `not run until this step succeeds.`,
        verify_url: `/api/services/${service.slug}/verify-domain`,
      },
    },
    {
      status: 201,
      headers: {
        "X-RateLimit-Limit": String(RATE_LIMIT_MAX),
        "X-RateLimit-Remaining": String(remaining),
      },
    }
  );
}
