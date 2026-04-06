import { NextRequest, NextResponse } from "next/server";

export async function GET(_request: NextRequest) {
  return NextResponse.json({
    name: "OnlyBots",
    description: "Trust registry for agent-first services",
    registry_api: "/api/services",
    submission_endpoint: "/api/services/submit",
    submission_schema: "/api/schema",
    methodology: "/api/methodology",
    documentation: "/api-docs",
    version: "1.0",
  });
}
