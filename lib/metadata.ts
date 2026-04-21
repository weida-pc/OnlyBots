/**
 * Best-effort metadata inference from a service's landing page.
 *
 * The submit endpoint used to require seven fields. For a registry of
 * agent-first services, that's hostile — the whole point is that an agent
 * should be able to submit with a single URL. This module fetches the URL
 * once and extracts what it can from the HTML.
 *
 * Anything we can't infer is left undefined; the caller supplies a default
 * or rejects the submission.
 */
export interface InferredMetadata {
  name?: string;
  description?: string;
  signup_url?: string;
  docs_url?: string;
  category?: "communication" | "execution" | "hosting";
  core_workflow?: string;
  contact_email?: string;
}

const FETCH_TIMEOUT_MS = 10_000;
const MAX_HTML_BYTES = 512 * 1024;

// Narrow category heuristics from the page body. Keeps the registry's
// three-bucket taxonomy while not requiring the submitter to know it.
const CATEGORY_SIGNALS: Record<InferredMetadata["category"] & string, RegExp[]> = {
  communication: [/\bemail\b/i, /\binbox\b/i, /\bsms\b/i, /\bchat\b/i, /\bmessag/i],
  execution: [/\bagent\b/i, /\btask\b/i, /\bworkflow\b/i, /\bapi\b/i, /\btool\b/i, /\bpayment/i, /\bwallet\b/i],
  hosting: [/\bhost/i, /\bdeploy/i, /\bserverless/i, /\bcontainer/i, /\bcloud\b/i, /\bvm\b/i, /\bdomain\b/i],
};

function firstMatch(html: string, re: RegExp): string | undefined {
  const m = html.match(re);
  return m?.[1]?.trim() || undefined;
}

function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ");
}

function inferCategory(html: string): InferredMetadata["category"] | undefined {
  const scores: Record<string, number> = {};
  for (const [cat, patterns] of Object.entries(CATEGORY_SIGNALS)) {
    scores[cat] = patterns.reduce((acc, re) => {
      const matches = html.match(new RegExp(re.source, "gi"));
      return acc + (matches ? matches.length : 0);
    }, 0);
  }
  const best = Object.entries(scores).sort((a, b) => b[1] - a[1])[0];
  if (!best || best[1] === 0) return undefined;
  return best[0] as InferredMetadata["category"];
}

/**
 * Try a few common signup paths. Returns the full URL or undefined.
 * We only pick one that the landing page actually links to — no guessing
 * `/signup` if the page doesn't link there.
 */
function inferSignupUrl(html: string, baseUrl: string): string | undefined {
  const origin = new URL(baseUrl).origin;
  // Hunt for <a href="..."> whose text or href suggests signup
  const linkRe = /<a\s+[^>]*href=["']([^"'#]+)["'][^>]*>([^<]{0,80})<\/a>/gi;
  let m: RegExpExecArray | null;
  const signupSignals = /sign.?up|register|get.?started|create.?account|join/i;
  while ((m = linkRe.exec(html)) !== null) {
    const href = m[1];
    const text = m[2];
    if (signupSignals.test(href) || signupSignals.test(text)) {
      try {
        return new URL(href, baseUrl).toString();
      } catch {
        continue;
      }
    }
  }
  // Fallback: landing page itself (many agent-first services sign up on root)
  return origin;
}

/**
 * Derive a contact email from a domain. This is an editable placeholder
 * — the submitter can override it. We never send email to it without
 * explicit opt-in; it's just a `mailto:` anchor for the registry page.
 */
function placeholderContactForUrl(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return `hello@${host}`;
  } catch {
    return "unknown@onlybots.invalid";
  }
}

export async function inferMetadataFromUrl(url: string): Promise<InferredMetadata> {
  let html = "";
  try {
    const res = await fetch(url, {
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
      headers: {
        "User-Agent": "OnlyBotsBot/1.0 (+https://onlybots.ai/bot)",
        Accept: "text/html,application/xhtml+xml",
      },
      redirect: "follow",
    });
    if (res.ok && res.headers.get("content-type")?.includes("text")) {
      const reader = res.body?.getReader();
      if (reader) {
        const decoder = new TextDecoder();
        let received = 0;
        while (received < MAX_HTML_BYTES) {
          const { done, value } = await reader.read();
          if (done) break;
          received += value.byteLength;
          html += decoder.decode(value, { stream: true });
        }
        html += decoder.decode();
      }
    }
  } catch {
    // Network / parse failure: fall back to hostname-derived defaults below.
  }

  // Match <meta> tags regardless of attribute order:
  //   <meta name="X" content="Y">
  //   <meta content="Y" name="X">
  // Two regexes OR'd together cover both shapes without a complex lookbehind.
  const metaContent = (attrKey: string, attrVal: string): string | undefined => {
    const aThenC = new RegExp(
      `<meta[^>]+${attrKey}=["']${attrVal}["'][^>]+content=["']([^"']+)["']`,
      "i"
    );
    const cThenA = new RegExp(
      `<meta[^>]+content=["']([^"']+)["'][^>]+${attrKey}=["']${attrVal}["']`,
      "i"
    );
    return firstMatch(html, aThenC) || firstMatch(html, cThenA);
  };

  const title =
    metaContent("property", "og:title") ||
    firstMatch(html, /<title[^>]*>([^<]+)<\/title>/i);

  const description =
    metaContent("name", "description") ||
    metaContent("property", "og:description") ||
    metaContent("property", "twitter:description");

  // Strip the common " | Brand", " — Brand" tagline suffix that <title> tags
  // often carry. Everything after the first `|` / `—` / ` - ` / `:` is noise
  // for registry naming purposes.
  const cleanName = (raw: string): string => {
    const decoded = decodeEntities(raw).trim();
    const cut = decoded.split(/\s*[|—]\s*|\s+-\s+|\s*:\s*/)[0].trim();
    return (cut || decoded).slice(0, 100);
  };

  const name = title ? cleanName(title) : undefined;
  const decodedDesc = description ? decodeEntities(description).slice(0, 300) : undefined;

  const docs_url = firstMatch(
    html,
    /<a\s+[^>]*href=["']([^"'#]*docs?[^"']*)["'][^>]*>/i
  );

  return {
    name,
    description: decodedDesc,
    signup_url: inferSignupUrl(html, url),
    docs_url: docs_url
      ? (() => {
          try {
            return new URL(docs_url, url).toString();
          } catch {
            return undefined;
          }
        })()
      : undefined,
    category: inferCategory(html),
    core_workflow: decodedDesc,
    contact_email: placeholderContactForUrl(url),
  };
}

/**
 * Fill defaults so the caller always has a complete, submittable record
 * even if the fetch failed or returned a bare HTML shell. Pure function —
 * no network.
 */
export function fillDefaults(
  url: string,
  partial: Partial<InferredMetadata>
): Required<Omit<InferredMetadata, "docs_url">> & { docs_url?: string } {
  const hostname = (() => {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return "unknown.invalid";
    }
  })();
  return {
    name: partial.name || hostname,
    description: partial.description || `Agent-first service at ${hostname}. (No description provided.)`,
    signup_url: partial.signup_url || url,
    docs_url: partial.docs_url,
    category: partial.category || "execution",
    core_workflow:
      partial.core_workflow ||
      `Core workflow for ${hostname} — autodetected. Submit a richer description to override.`,
    contact_email: partial.contact_email || placeholderContactForUrl(url),
  };
}
