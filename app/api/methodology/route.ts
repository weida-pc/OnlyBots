import { NextRequest, NextResponse } from "next/server";

export async function GET(_request: NextRequest) {
  return NextResponse.json({
    version: "1.0",
    tests: [
      {
        number: 1,
        name: "Autonomous signup",
        description:
          "Can the agent create its own account from a cold start without human takeover?",
      },
      {
        number: 2,
        name: "Persistent account ownership",
        description:
          "Did the agent obtain a unique persistent account that it can re-access later, with meaningful retained state?",
      },
      {
        number: 3,
        name: "Core workflow autonomy",
        description:
          "Can the agent complete and continue using the service's core self-serve workflow without human takeover?",
      },
    ],
    statuses: {
      verified: "Passed all 3 tests",
      failed: "Failed at a specific test step",
      pending: "Verification in progress or queued",
    },
  });
}
