import { NextRequest, NextResponse } from "next/server";
import { getServiceBySlug } from "@/lib/db";

interface RouteParams {
  params: Promise<{ slug: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  const { slug } = await params;

  const service = await getServiceBySlug(slug);

  if (!service) {
    return NextResponse.json({ error: "Service not found" }, { status: 404 });
  }

  return NextResponse.json(service);
}
