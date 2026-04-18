import { NextRequest, NextResponse } from "next/server";
import { getServiceBySlug, redactServiceSecrets } from "@/lib/db";

interface RouteParams {
  params: Promise<{ slug: string }>;
}

export async function GET(_request: NextRequest, { params }: RouteParams) {
  const { slug } = await params;

  const service = await getServiceBySlug(slug);

  if (!service) {
    return NextResponse.json({ error: "Service not found" }, { status: 404 });
  }

  // Strip the domain_verification_token before returning. It's a one-time
  // secret echoed only at submit time.
  return NextResponse.json(redactServiceSecrets(service));
}
