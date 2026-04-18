import { NextRequest, NextResponse } from "next/server";
import { getServices, redactServiceSecrets } from "@/lib/db";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;

  const filters = {
    q: searchParams.get("q") ?? undefined,
    category: searchParams.get("category") ?? undefined,
    status: searchParams.get("status") ?? undefined,
  };

  const services = await getServices(filters);

  // Redact per-row: a bulk listing would otherwise leak every pending
  // service's token.
  return NextResponse.json(services.map(redactServiceSecrets), {
    headers: {
      Link: '</api/schema>; rel="describedby"',
    },
  });
}
