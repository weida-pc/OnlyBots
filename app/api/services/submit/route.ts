import { NextRequest, NextResponse } from "next/server";
import { checkDuplicateUrl, createService } from "@/lib/db";
import { submitServiceSchema } from "@/lib/schema";
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

  const data = result.data;

  const isDuplicate = await checkDuplicateUrl(data.url);
  if (isDuplicate) {
    return NextResponse.json(
      { error: "A service with this URL has already been submitted." },
      { status: 409 }
    );
  }

  // Phase 6: domain ownership verification gate. Don't queue a verification
  // run yet — wait for the submitter to publish the TXT record and call
  // POST /api/services/:slug/verify-domain.
  const token = generateVerificationToken();
  const service = await createService({ ...data, domain_verification_token: token });

  const hostname = hostnameForUrl(service.url);
  return NextResponse.json(
    {
      service,
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
