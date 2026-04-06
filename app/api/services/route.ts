import { NextRequest, NextResponse } from "next/server";
import { getServices } from "@/lib/db";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;

  const filters = {
    q: searchParams.get("q") ?? undefined,
    category: searchParams.get("category") ?? undefined,
    status: searchParams.get("status") ?? undefined,
  };

  const services = await getServices(filters);

  return NextResponse.json(services, {
    headers: {
      Link: '</api/schema>; rel="describedby"',
    },
  });
}
