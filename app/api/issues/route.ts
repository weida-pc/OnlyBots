import { NextRequest, NextResponse } from "next/server";
import { createIssue, getIssues, serviceSlugExists } from "@/lib/db";
import { submitIssueSchema } from "@/lib/schema";

interface RateLimitEntry {
  count: number;
  resetAt: number;
}

const rateLimitMap = new Map<string, RateLimitEntry>();
const RATE_LIMIT_MAX = 20;
const RATE_LIMIT_WINDOW_MS = 60 * 60 * 1000; // 1 hour

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
 * GET /api/issues
 *
 * Public list of recent issues. Optional ?service=<slug> filter scopes to
 * a single service. Optional ?limit=<n> caps the page size (default 100,
 * hard max 500 enforced in lib/db.ts).
 */
export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const service_slug = searchParams.get("service") ?? undefined;
  const limitRaw = searchParams.get("limit");
  const limit = limitRaw ? Number.parseInt(limitRaw, 10) : undefined;

  const issues = await getIssues({
    service_slug,
    limit: Number.isFinite(limit) ? limit : undefined,
  });
  return NextResponse.json({ issues });
}

/**
 * POST /api/issues
 *
 * Anyone (human or agent) can file an issue. Required: title, body.
 * Optional: service_slug (filed against a specific service if it exists),
 * reporter_contact (free-form email/handle).
 *
 * Rate-limited per IP at 20/hour. No auth — by design, this is a public
 * dropbox.
 */
export async function POST(request: NextRequest) {
  const ip = getClientIp(request);
  const { allowed, remaining } = checkRateLimit(ip);

  if (!allowed) {
    return NextResponse.json(
      { error: "Rate limit exceeded. Try again in an hour." },
      {
        status: 429,
        headers: {
          "X-RateLimit-Limit": String(RATE_LIMIT_MAX),
          "X-RateLimit-Remaining": "0",
          "Retry-After": String(60 * 60),
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

  const result = submitIssueSchema.safeParse(body);
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

  // If a service slug was supplied, make sure it actually exists. Otherwise
  // an attacker could spam with random slugs and we'd silently accept them.
  if (input.service_slug) {
    const exists = await serviceSlugExists(input.service_slug);
    if (!exists) {
      return NextResponse.json(
        { error: `Unknown service slug: ${input.service_slug}` },
        { status: 400 }
      );
    }
  }

  const issue = await createIssue({
    title: input.title,
    body: input.body,
    service_slug: input.service_slug,
    reporter_contact: input.reporter_contact,
  });

  return NextResponse.json(
    {
      issue,
      message: "Issue recorded. Visit /issues to see it in the public list.",
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
