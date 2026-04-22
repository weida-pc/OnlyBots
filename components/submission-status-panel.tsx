"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { Copy, RefreshCw, Check } from "lucide-react";

/**
 * Status panel rendered on /services/<slug> when a service has just been
 * submitted and isn't yet `verified` / `failed`. Covers four non-terminal
 * states explicitly, polls every 10s while non-terminal so the page
 * reflects reality without a manual refresh, and shows the TXT-record
 * instructions when the viewer holds the submitter's token
 * (passed as `?token=...`, surfaced in the original submission response).
 *
 * States:
 *   pending_domain_verification — waiting for TXT + /verify-domain call
 *   pending                     — domain verified, queued for verifier
 *   running                     — a verification run is in flight
 *   awaiting_contract           — generator couldn't produce a contract
 * Anything else (verified, failed) does not render this panel.
 */

interface Props {
  slug: string;
  status: string;
  // TXT record details only shown to a viewer who proved they're the
  // submitter by including the one-time token in the URL. Parent page
  // fetches them if the token matches.
  txtRecord?: {
    name: string;
    value: string;
  };
  token?: string;
}

const POLL_MS = 10_000;

function statusLabel(status: string): string {
  switch (status) {
    case "pending_domain_verification":
      return "Awaiting domain ownership proof";
    case "pending":
      return "Queued for verification";
    case "running":
      return "Verification in progress";
    case "awaiting_contract":
      return "Waiting for a verification contract";
    default:
      return status;
  }
}

function statusExplainer(status: string): string {
  switch (status) {
    case "pending_domain_verification":
      return "Prove you control this domain by publishing a short DNS TXT record, then click Verify domain below. The verifier won't run until this step succeeds.";
    case "pending":
      return "Your submission is in the queue. The verifier polls every 30s; your three tests should start running within a minute.";
    case "running":
      return "Gemini is running the three tests inside a fresh Daytona sandbox. Most services finish in 1–3 minutes.";
    case "awaiting_contract":
      return "The LLM couldn't produce a valid verification contract on its own. An operator will author one manually — check back later, or contact support.";
    default:
      return "";
  }
}

export default function SubmissionStatusPanel({
  slug,
  status,
  txtRecord,
  token,
}: Props) {
  const [copied, setCopied] = useState<string | null>(null);
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [verifyResult, setVerifyResult] = useState<string | null>(null);

  // Auto-refresh the page so a non-terminal status progresses visibly.
  // A full refresh is heavier than a partial re-fetch, but the rest of
  // the page derives a lot from the DB row, and re-rendering on the
  // server is simpler than duplicating that logic client-side.
  useEffect(() => {
    const terminal = status === "verified" || status === "failed";
    if (terminal) return;
    const id = setInterval(() => {
      // Preserve the token query param across reloads.
      if (typeof window !== "undefined") window.location.reload();
    }, POLL_MS);
    return () => clearInterval(id);
  }, [status]);

  async function copyToClipboard(text: string, key: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 1500);
    } catch {
      // clipboard blocked; not worth a fallback
    }
  }

  async function handleVerifyDomain() {
    setVerifyLoading(true);
    setVerifyResult(null);
    try {
      const res = await fetch(`/api/services/${slug}/verify-domain`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setVerifyResult("✓ Domain verified. Verification run queued.");
        setTimeout(() => window.location.reload(), 1500);
      } else {
        setVerifyResult(
          data?.error ??
            `Domain verification failed (HTTP ${res.status}). The TXT record may not have propagated yet; DNS can take several minutes.`
        );
      }
    } catch {
      setVerifyResult(
        "Network error contacting verify-domain endpoint. Try again."
      );
    } finally {
      setVerifyLoading(false);
    }
  }

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-amber-900">
            {statusLabel(status)}
          </h2>
          <p className="mt-1 text-sm text-amber-800">
            {statusExplainer(status)}
          </p>
        </div>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className={cn(
            "inline-flex items-center gap-1.5 text-xs font-medium",
            "text-amber-800 hover:text-amber-900 transition-colors"
          )}
          aria-label="Refresh status"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      {/* Domain-verification instructions — only when we have a token that
          proves the viewer is the submitter. Public visitors don't see
          the TXT details. */}
      {status === "pending_domain_verification" && txtRecord && (
        <div className="space-y-3 rounded-md bg-white border border-amber-200 p-4">
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">
              1 · Record name
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 break-all font-mono text-xs bg-slate-50 border border-slate-200 rounded px-2 py-1.5 text-slate-800">
                {txtRecord.name}
              </code>
              <button
                type="button"
                onClick={() => copyToClipboard(txtRecord.name, "name")}
                className="text-xs text-slate-600 hover:text-slate-900 inline-flex items-center gap-1"
                aria-label="Copy record name"
              >
                {copied === "name" ? (
                  <Check className="h-3.5 w-3.5 text-green-600" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">
              2 · Record value (TXT)
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 break-all font-mono text-xs bg-slate-50 border border-slate-200 rounded px-2 py-1.5 text-slate-800">
                {txtRecord.value}
              </code>
              <button
                type="button"
                onClick={() => copyToClipboard(txtRecord.value, "value")}
                className="text-xs text-slate-600 hover:text-slate-900 inline-flex items-center gap-1"
                aria-label="Copy record value"
              >
                {copied === "value" ? (
                  <Check className="h-3.5 w-3.5 text-green-600" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">
              3 · Confirm it&apos;s published
            </div>
            <button
              type="button"
              onClick={handleVerifyDomain}
              disabled={verifyLoading}
              className={cn(
                "inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium",
                "bg-amber-600 text-white hover:bg-amber-700",
                "focus:outline-none focus:ring-2 focus:ring-amber-600 focus:ring-offset-1",
                "transition disabled:opacity-60 disabled:cursor-not-allowed"
              )}
            >
              {verifyLoading ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : null}
              {verifyLoading ? "Checking DNS…" : "Verify domain"}
            </button>
            {verifyResult && (
              <p className="mt-2 text-xs text-slate-700">{verifyResult}</p>
            )}
          </div>
        </div>
      )}

      {/* Viewer without token: still explain but don't leak the TXT record. */}
      {status === "pending_domain_verification" && !txtRecord && (
        <p className="text-xs text-amber-700">
          The submitter has been sent instructions for proving domain
          ownership. This service will become testable once that&apos;s done.
        </p>
      )}

      {/* Non-domain non-terminal states: show the poll cadence. */}
      {status !== "pending_domain_verification" && (
        <p className="text-xs text-amber-700">
          This page auto-refreshes every {POLL_MS / 1000}s until the
          status is terminal (<span className="font-mono">verified</span> or{" "}
          <span className="font-mono">failed</span>).
          {token ? " Your submission token is attached so you'll keep seeing any private details if they appear." : ""}
        </p>
      )}
    </div>
  );
}
