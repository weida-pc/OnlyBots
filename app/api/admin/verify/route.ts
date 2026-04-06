import { NextRequest, NextResponse } from "next/server";
import { query, getServiceBySlug, createVerificationRun, updateServiceStatus } from "@/lib/db";
import { Service } from "@/lib/types";

function isAuthorized(request: NextRequest): boolean {
  const adminApiKey = process.env.ADMIN_API_KEY;
  if (!adminApiKey) return false;

  const authHeader = request.headers.get("authorization");
  return authHeader === `Bearer ${adminApiKey}`;
}

export async function POST(request: NextRequest) {
  if (!isAuthorized(request)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }

  const payload = body as Record<string, unknown>;

  // Verify all pending services
  if (payload.all_pending === true) {
    const result = await query(
      "SELECT * FROM services WHERE status = 'pending'"
    );
    const pendingServices = result.rows as Service[];

    const runIds: number[] = [];

    for (const service of pendingServices) {
      const run = await createVerificationRun(service.id);
      runIds.push(run.id);
    }

    return NextResponse.json({
      runs_created: runIds.length,
      run_ids: runIds,
    });
  }

  // Verify a single service by slug
  if (typeof payload.slug === "string") {
    const { slug } = payload;

    const service = await getServiceBySlug(slug);
    if (!service) {
      return NextResponse.json({ error: "Service not found" }, { status: 404 });
    }

    await updateServiceStatus(service.id, "pending", null, null);
    const run = await createVerificationRun(service.id);

    return NextResponse.json({
      runs_created: 1,
      run_ids: [run.id],
    });
  }

  return NextResponse.json(
    { error: 'Body must include either "slug" (string) or "all_pending" (true).' },
    { status: 400 }
  );
}
