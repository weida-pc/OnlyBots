import { NextRequest, NextResponse } from "next/server";
import { getJsonSchema } from "@/lib/schema";

export async function GET(_request: NextRequest) {
  const schema = getJsonSchema();

  return NextResponse.json(schema, {
    headers: {
      "Content-Type": "application/schema+json",
    },
  });
}
