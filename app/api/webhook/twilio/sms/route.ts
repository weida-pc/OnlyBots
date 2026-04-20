/**
 * POST /api/webhook/twilio/sms
 *
 * Receives inbound SMS callbacks from Twilio (application/x-www-form-urlencoded).
 * Stores each unique message in twilio_inbound_sms so the receive_sms contract
 * primitive can poll for it.
 *
 * Signature validation: we implement HMAC-SHA1 manually (~15 lines) to avoid
 * adding the full `twilio` npm package as a production dependency. The algorithm
 * is: HMAC-SHA1( authToken, fullUrl + sortedConcatBodyParams ), base64-encoded,
 * must equal the X-Twilio-Signature header.
 *
 * SECURITY NOTE: If TWILIO_AUTH_TOKEN is not set this handler logs a loud warning
 * and accepts the request anyway. This is an intentional fail-open to unblock
 * integration before the Auth Token env var is provisioned. Remove or tighten
 * this once TWILIO_AUTH_TOKEN is in the environment.
 */

import { NextRequest, NextResponse } from "next/server";
import { createHmac } from "crypto";
import { query } from "@/lib/db";

const TWIML_EMPTY =
  '<?xml version="1.0" encoding="UTF-8"?><Response></Response>';

function validateTwilioSignature(
  authToken: string,
  signature: string,
  url: string,
  params: Record<string, string>
): boolean {
  // Build the signed string: URL + sorted key-value pairs concatenated.
  const sortedKeys = Object.keys(params).sort();
  const paramStr = sortedKeys.map((k) => `${k}${params[k]}`).join("");
  const signingInput = url + paramStr;

  const expected = createHmac("sha1", authToken)
    .update(signingInput, "utf8")
    .digest("base64");

  // Use a timing-safe comparison to prevent timing attacks.
  if (expected.length !== signature.length) return false;
  let mismatch = 0;
  for (let i = 0; i < expected.length; i++) {
    mismatch |= expected.charCodeAt(i) ^ signature.charCodeAt(i);
  }
  return mismatch === 0;
}

export async function POST(request: NextRequest) {
  // 1. Read form-encoded body (Twilio sends application/x-www-form-urlencoded)
  const text = await request.text();
  const params: Record<string, string> = {};
  for (const [k, v] of new URLSearchParams(text)) {
    params[k] = v;
  }

  // 2. Validate Twilio signature
  const authToken = process.env.TWILIO_AUTH_TOKEN;
  const signature = request.headers.get("x-twilio-signature") ?? "";

  if (!authToken) {
    // Intentional fail-open: accept requests but log a loud, grep-friendly warning.
    // This unblocks integration before TWILIO_AUTH_TOKEN is provisioned.
    // TODO: once TWILIO_AUTH_TOKEN is set, tighten this to reject unsigned requests.
    console.warn(
      "[twilio.webhook.WARNING] signature validation skipped — TWILIO_AUTH_TOKEN not set"
    );
  } else {
    // Reconstruct the full URL Twilio signed (must match what Twilio sees).
    const url = request.url;
    const valid = validateTwilioSignature(authToken, signature, url, params);
    if (!valid) {
      console.error("[twilio.webhook.ERROR] invalid signature — rejecting request");
      return new NextResponse("Forbidden", { status: 403 });
    }
  }

  // 3. Extract required fields from the form body
  const messageSid = params["MessageSid"];
  const from = params["From"];
  const to = params["To"];
  const body = params["Body"] ?? "";

  if (!messageSid || !from || !to) {
    return new NextResponse("Bad Request — missing MessageSid/From/To", {
      status: 400,
    });
  }

  // 4. Insert into DB; ON CONFLICT DO NOTHING handles Twilio retries idempotently
  await query(
    `INSERT INTO twilio_inbound_sms (message_sid, from_number, to_number, body)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (message_sid) DO NOTHING`,
    [messageSid, from, to, body]
  );

  // 5. Return empty TwiML so Twilio doesn't warn about missing response
  return new NextResponse(TWIML_EMPTY, {
    status: 200,
    headers: { "Content-Type": "text/xml" },
  });
}
