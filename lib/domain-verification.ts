/**
 * Phase 6 anti-spam: domain ownership verification via DNS TXT records.
 *
 * Submitters prove they control a service's domain by publishing a verifier-
 * issued token in `_onlybots-verify.<domain>` TXT record. The verifier only
 * runs on services whose `domain_verified_at` is set.
 *
 * Rationale for picking TXT-records over a honeypot (e.g. "type 'six toes'"):
 *  - OnlyBots is agent-facing. Agents read the schema and would include any
 *    fixed phrase, so a honeypot doesn't filter bots from agents.
 *  - TXT record control is a meaningful proof of ownership. Bots submitting
 *    random URLs they don't own can't publish the record. Legitimate agents
 *    operating a real service can.
 *
 * We use Cloudflare's DNS-over-HTTPS API so the verifier has no dependency
 * on the deployment's resolv.conf / blocked DNS (some hosting environments
 * block direct port-53 DNS).
 */

const DOH_ENDPOINT = "https://cloudflare-dns.com/dns-query";

/**
 * Generate a URL-safe verification token. 24 bytes = 192 bits of entropy,
 * more than enough for a 1-of-N anti-forgery marker.
 */
export function generateVerificationToken(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Buffer.from(bytes).toString("base64url");
}

/**
 * Extract the apex domain we expect to find the TXT record on.
 * Accepts any URL and returns its hostname. Does not attempt to collapse
 * subdomains to their eTLD+1 — the TXT record check uses the exact hostname
 * so `docs.example.com` and `example.com` would require separate records.
 */
export function hostnameForUrl(url: string): string {
  return new URL(url).hostname;
}

/**
 * The record name submitters are told to create, and the exact value we'll
 * look for. Keeping the naming convention stable matters — changing it means
 * every already-verified domain needs to republish.
 */
export function txtRecordName(hostname: string): string {
  return `_onlybots-verify.${hostname}`;
}

export function expectedTxtValue(token: string): string {
  return `onlybots-verify=${token}`;
}

/**
 * DoH TXT lookup. Returns the list of TXT record values found on the name.
 * Each TXT record can be multi-string (space-separated quoted strings in
 * classic DNS); we concatenate them since DoH returns them as one `data`
 * field per record.
 */
export async function lookupTxt(name: string): Promise<string[]> {
  const url = `${DOH_ENDPOINT}?name=${encodeURIComponent(name)}&type=TXT`;
  const res = await fetch(url, {
    headers: { Accept: "application/dns-json" },
    // Short timeout — DNS should be fast. If this ever hangs, fail open.
    signal: AbortSignal.timeout(5000),
  });
  if (!res.ok) return [];
  const body = (await res.json()) as {
    Answer?: Array<{ name: string; type: number; data: string }>;
  };
  const answers = body.Answer ?? [];
  return answers
    .filter((a) => a.type === 16) // TXT records are type 16
    .map((a) => {
      // DoH returns TXT data as a quoted string, potentially concatenated:
      //   '"chunk1" "chunk2"' — strip quotes and join chunks.
      return a.data
        .split(/"\s+"/g)
        .map((s) => s.replace(/^"|"$/g, ""))
        .join("");
    });
}

/**
 * True if the expected token value appears in any TXT record for the given
 * hostname. Uses includes() to tolerate extra DNS-provider formatting.
 */
export async function verifyDomainTxt(
  hostname: string,
  token: string
): Promise<{ verified: boolean; records: string[] }> {
  const expected = expectedTxtValue(token);
  const records = await lookupTxt(txtRecordName(hostname));
  const verified = records.some((r) => r.includes(expected));
  return { verified, records };
}
