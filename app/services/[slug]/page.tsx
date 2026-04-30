import { notFound } from "next/navigation";
import Link from "next/link";
import type { Metadata } from "next";
import { getServiceBySlug } from "@/lib/db";
import StatusBadge from "@/components/status-badge";
import SubmissionStatusPanel from "@/components/submission-status-panel";
import TestResultRow from "@/components/test-result-row";
import {
  hostnameForUrl,
  txtRecordName,
  expectedTxtValue,
} from "@/lib/domain-verification";
import type { VerificationResult } from "@/lib/types";
import { getServiceRequirements } from "@/lib/service-requirements";

export const dynamic = "force-dynamic";

// States where the service isn't done being evaluated yet. The detail
// page renders a status panel for these instead of the empty
// "Test Results" grid that otherwise says "Skipped (prior test failed)"
// for every row and confuses fresh submitters.
const NON_TERMINAL_STATUSES = new Set([
  "pending",
  "pending_domain_verification",
  "running",
  "awaiting_contract",
]);

interface PageProps {
  params: Promise<{ slug: string }>;
  // `?token=<domain_verification_token>` — proves the viewer is the
  // submitter and unlocks the TXT-record panel in
  // SubmissionStatusPanel. Non-matching / missing token: public view,
  // TXT secret stays hidden.
  searchParams: Promise<{ token?: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const service = await getServiceBySlug(slug);

  if (!service) {
    return { title: "Service Not Found — OnlyBots" };
  }

  const descriptionMap: Record<string, string> = {
    verified: `${service.name} is verified agent-first on OnlyBots. AI agents can autonomously sign up, own, and operate this service.`,
    failed: `${service.name} did not pass agent-first verification on OnlyBots.`,
    pending: `${service.name} is awaiting agent-first verification on OnlyBots.`,
  };

  return {
    title: `${service.name} — OnlyBots`,
    description: descriptionMap[service.status] ?? `${service.name} on OnlyBots Trust Registry.`,
  };
}

const TEST_NAMES = [
  "Autonomous signup",
  "Persistent account ownership",
  "Core workflow autonomy",
];

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
}

function getDuration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return "—";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  const secs = Math.round(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remainSecs = secs % 60;
  return `${mins}m ${remainSecs}s`;
}

export default async function ServiceDetailPage({ params, searchParams }: PageProps) {
  const { slug } = await params;
  const { token } = await searchParams;
  const service = await getServiceBySlug(slug);

  if (!service) {
    notFound();
  }

  const run = service.verification?.run;
  const results = service.verification?.results ?? [];
  const requirements = getServiceRequirements(slug);

  // Only the submitter (proven by URL-token match) sees the TXT-record
  // instructions. Public visitors to the same page see the status but
  // not the secret.
  const serviceWithToken = service as typeof service & {
    domain_verification_token?: string | null;
  };
  const tokenMatches = Boolean(
    token &&
      serviceWithToken.domain_verification_token &&
      token === serviceWithToken.domain_verification_token
  );
  const hostname = (() => {
    try {
      return hostnameForUrl(service.url);
    } catch {
      return service.url;
    }
  })();
  const txtRecord =
    tokenMatches && serviceWithToken.domain_verification_token
      ? {
          name: txtRecordName(hostname),
          value: expectedTxtValue(serviceWithToken.domain_verification_token),
        }
      : undefined;

  const isNonTerminal = NON_TERMINAL_STATUSES.has(service.status);
  // When no tests have run AND status is non-terminal, don't render
  // the "Test Results" section — it otherwise shows three "Skipped
  // (prior test failed)" rows for a fresh submission, which is wrong.
  const showTestResults = results.length > 0 || !isNonTerminal;

  function getResult(testNumber: number): VerificationResult | null {
    return results.find((r) => r.test_number === testNumber) ?? null;
  }

  // Extract harness/model honestly — prefer the model the contract's
  // agent_task actually invoked (recorded as `agent_task_model` per
  // tests/_common.py). Fall back to the legacy `model` field for rows
  // written before that change shipped. If the test has no agent_task
  // (pure-HTTP contract), `agent_task_model` is null and we render
  // an explicit "no LLM used" rather than a misleading default.
  const firstResult = results[0];
  const firstDetails = (firstResult?.details ?? {}) as Record<string, unknown>;
  const harness = (firstDetails.harness as string) || "unknown";
  // Find the first test that actually invoked an LLM, then report its
  // model. If none did, model stays null and the UI hides the label.
  const firstAgentDetails = results.find((r) => {
    const d = (r.details ?? {}) as Record<string, unknown>;
    return typeof d.agent_task_model === "string" && d.agent_task_model;
  })?.details as Record<string, unknown> | undefined;
  const model =
    (firstAgentDetails?.agent_task_model as string) ??
    (firstDetails.model as string) ??
    null;

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Back link */}
      <div className="mb-6">
        <Link
          href="/"
          className="text-sm text-slate-500 hover:text-slate-700 transition-colors"
        >
          &larr; Back to Registry
        </Link>
      </div>

      {/* Header */}
      <div className="mb-8">
        <div className="flex flex-wrap items-start gap-4 mb-2">
          <h1 className="text-3xl font-bold text-slate-900">{service.name}</h1>
          <span className="mt-1.5">
            <StatusBadge status={service.status} failedAtStep={service.failed_at_step} />
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm text-slate-500">
          <a
            href={service.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-green-600 hover:text-green-700 hover:underline transition-colors"
          >
            {service.url} &nearr;
          </a>
          <span className="text-slate-300">&middot;</span>
          <span className="inline-flex items-center px-2 py-0.5 rounded bg-slate-100 text-slate-600 text-xs font-medium">
            {service.category}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main content */}
        <div className="lg:col-span-2 space-y-6">
          {/* ── Submission Status ─────────────────────────────────────────
              Rendered while the service is still in a non-terminal
              state. Shows the TXT-record instructions to the submitter
              (proven by ?token=), a Verify-domain button, and auto-
              refreshes so the page reflects the verifier's progress
              without the submitter manually reloading. */}
          {isNonTerminal && (
            <SubmissionStatusPanel
              slug={service.slug}
              status={service.status}
              txtRecord={txtRecord}
              token={token}
            />
          )}

          {/* ── Verification Signature ────────────────────────────────────── */}
          {run && (
            <div className="bg-white border border-slate-200 rounded-lg p-6">
              <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-4">
                Verification Signature
              </h2>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div>
                  <div className="text-xs font-medium text-slate-400">Status</div>
                  <div className="mt-0.5">
                    <StatusBadge status={service.status} failedAtStep={service.failed_at_step} />
                  </div>
                </div>
                <div>
                  <div className="text-xs font-medium text-slate-400">Verifier Version</div>
                  <div className="text-sm font-mono text-slate-700 mt-0.5">
                    v{run.verifier_version}
                  </div>
                </div>
                <div>
                  <div className="text-xs font-medium text-slate-400">Test Harness</div>
                  <div className="text-sm text-slate-700 mt-0.5 capitalize">
                    {harness === "unknown" ? "—" : `${harness} CLI`}
                  </div>
                </div>
                <div>
                  <div className="text-xs font-medium text-slate-400">Underlying LLM</div>
                  <div className="text-sm font-mono text-slate-700 mt-0.5">
                    {model ? (
                      model
                    ) : (
                      <span className="italic text-slate-400 font-sans">
                        none (pure-HTTP contract)
                      </span>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-xs font-medium text-slate-400">Run Timestamp</div>
                  <div className="text-sm text-slate-700 mt-0.5">
                    {formatTimestamp(run.started_at)}
                  </div>
                </div>
                <div>
                  <div className="text-xs font-medium text-slate-400">Run Duration</div>
                  <div className="text-sm text-slate-700 mt-0.5">
                    {getDuration(run.started_at, run.completed_at)}
                  </div>
                </div>
              </div>

              {/* Verified date highlight */}
              {service.status === "verified" && service.verified_date && (
                <div className="mt-4 pt-3 border-t border-slate-100">
                  <p className="text-sm text-green-700">
                    Verified on{" "}
                    <span className="font-semibold">{formatTimestamp(service.verified_date)}</span>
                  </p>
                </div>
              )}
              {service.status === "failed" && service.failed_at_step != null && (
                <div className="mt-4 pt-3 border-t border-slate-100">
                  <p className="text-sm text-red-700">
                    Verification failed at{" "}
                    <span className="font-semibold">Test {service.failed_at_step}</span>
                    {TEST_NAMES[service.failed_at_step - 1] && (
                      <span className="text-red-500">
                        {" "}&mdash; {TEST_NAMES[service.failed_at_step - 1]}
                      </span>
                    )}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* ── Test Results ──────────────────────────────────────────────── */}
          {showTestResults && (
            <div>
              <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-4">
                Test Results
              </h2>
              <div className="space-y-3">
                {TEST_NAMES.map((name, i) => (
                  <TestResultRow
                    key={i + 1}
                    testNumber={i + 1}
                    testName={name}
                    result={getResult(i + 1)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* ── Agent Integration Requirements ────────────────────────────── */}
          {requirements && (
            <div className="bg-white border border-slate-200 rounded-lg p-6 space-y-6">
              <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide">
                Agent Integration Requirements
              </h2>

              {/* Native signup row */}
              <div className="flex items-start gap-3">
                <span className={`mt-0.5 shrink-0 text-base ${
                  requirements.nativeSignup === "yes" ? "text-green-500" :
                  requirements.nativeSignup === "partial" ? "text-yellow-500" :
                  "text-red-500"
                }`}>
                  {requirements.nativeSignup === "yes" ? "✓" :
                   requirements.nativeSignup === "partial" ? "◑" : "✗"}
                </span>
                <div>
                  <div className="text-sm font-medium text-slate-700">
                    {requirements.nativeSignup === "yes"
                      ? "Native programmatic signup"
                      : requirements.nativeSignup === "partial"
                      ? "Partial programmatic signup"
                      : "No native programmatic signup"}
                  </div>
                  <div className="text-xs text-slate-500 mt-0.5">{requirements.nativeSignupNote}</div>
                </div>
              </div>

              {/* Human setup */}
              <div className="flex items-start gap-3">
                {requirements.humanSetup.required ? (
                  <>
                    <span className="mt-0.5 shrink-0 text-base text-yellow-500">⚠</span>
                    <div>
                      <div className="text-sm font-medium text-slate-700">Human setup required (one-time)</div>
                      <ol className="mt-1.5 space-y-1 list-decimal list-inside">
                        {requirements.humanSetup.steps.map((step, i) => (
                          <li key={i} className="text-xs text-slate-600">{step}</li>
                        ))}
                      </ol>
                    </div>
                  </>
                ) : (
                  <>
                    <span className="mt-0.5 shrink-0 text-base text-green-500">✓</span>
                    <div className="text-sm font-medium text-green-700">No human needed</div>
                  </>
                )}
              </div>

              {/* Inputs table */}
              <div>
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                  Required Inputs
                </div>
                <div className="border border-slate-200 rounded-md overflow-hidden">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-50">
                      <tr>
                        <th className="text-left px-3 py-2 font-semibold text-slate-500 w-1/4">Input</th>
                        <th className="text-left px-3 py-2 font-semibold text-slate-500">Description</th>
                        <th className="text-left px-3 py-2 font-semibold text-slate-500 w-24">When</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {requirements.inputs.map((input, i) => (
                        <tr key={i} className="bg-white">
                          <td className="px-3 py-2 font-mono text-slate-700 align-top">{input.name}</td>
                          <td className="px-3 py-2 text-slate-600 align-top">{input.description}</td>
                          <td className="px-3 py-2 align-top">
                            <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${
                              input.when === "pre-setup"
                                ? "bg-amber-50 text-amber-700"
                                : "bg-blue-50 text-blue-700"
                            }`}>
                              {input.when === "pre-setup" ? "Pre-setup" : "Runtime"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* API calls */}
              <div>
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                  API Calls Made
                </div>
                <div className="border border-slate-200 rounded-md overflow-hidden">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-50">
                      <tr>
                        <th className="text-left px-3 py-2 font-semibold text-slate-500 w-8">#</th>
                        <th className="text-left px-3 py-2 font-semibold text-slate-500 w-12">Method</th>
                        <th className="text-left px-3 py-2 font-semibold text-slate-500">Endpoint</th>
                        <th className="text-left px-3 py-2 font-semibold text-slate-500">Purpose</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {requirements.apiCalls.map((call, i) => (
                        <tr key={i} className={call.step.includes("human") ? "bg-amber-50" : "bg-white"}>
                          <td className="px-3 py-2 text-slate-400 align-top">{call.step}</td>
                          <td className="px-3 py-2 align-top">
                            {call.method !== "—" ? (
                              <span className={`font-mono font-semibold ${
                                call.method === "GET" ? "text-blue-600" :
                                call.method === "POST" ? "text-green-600" :
                                call.method === "PUT" ? "text-purple-600" :
                                "text-slate-500"
                              }`}>{call.method}</span>
                            ) : (
                              <span className="text-amber-600 font-semibold">HUMAN</span>
                            )}
                          </td>
                          <td className="px-3 py-2 font-mono text-slate-600 break-all align-top">{call.endpoint}</td>
                          <td className="px-3 py-2 text-slate-600 align-top">{call.purpose}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ── Reproduce This Verification ───────────────────────────────────
              Honest reproducer — points at the ACTUAL contract file the
              verifier executed and the command that re-runs it.
              Previous version rendered made-up `npm install -g openclaw`
              lines (no such package) and a handwritten "Visit X and
              determine..." prompt that has nothing to do with how the
              verifier actually works (contract-driven, not single-prompt).
              See docs/VERIFIER_DESIGN.md for the contract architecture. */}
          {run && (
            <div className="bg-slate-900 text-slate-100 rounded-lg p-6">
              <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-3">
                Reproduce This Verification
              </h2>
              <p className="text-xs text-slate-400 mb-3">
                The executable definition is{" "}
                <a
                  href={`https://github.com/weida-pc/OnlyBots/blob/main/verifier/contracts/${service.slug}.json`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-green-400 hover:underline font-mono"
                >
                  verifier/contracts/{service.slug}.json
                </a>
                . Each test runs the contract&apos;s steps + assertions; the
                inner <code className="text-green-400">agent_task</code> prompt
                (when present) is executed inside a fresh Daytona sandbox via
                the Gemini CLI. Clone the repo, install the Python venv, set
                your Gemini API key, and run:
              </p>
              <div className="bg-slate-800 rounded-md p-3 font-mono text-xs leading-relaxed overflow-x-auto">
                <div className="text-slate-500"># Clone + install</div>
                <div className="text-green-400">
                  git clone https://github.com/weida-pc/OnlyBots &amp;&amp; cd OnlyBots/verifier
                </div>
                <div className="text-green-400">
                  python -m venv venv &amp;&amp; source venv/bin/activate &amp;&amp; pip install -r requirements.txt
                </div>
                <div className="text-slate-500 mt-2">
                  # Daytona for the sandboxed agent_task + Gemini for the LLM calls
                </div>
                <div className="text-green-400">
                  export DAYTONA_API_KEY=your_daytona_key
                </div>
                <div className="text-green-400">
                  export GEMINI_API_KEY=your_gemini_key
                </div>
                <div className="text-slate-500 mt-2">
                  # Run the three tests against this exact contract
                </div>
                <div className="text-green-400">
                  python -c &quot;from executor import execute_signup, execute_persist, execute_workflow; state={'{}'}; import json; [print(t, json.dumps(f(&apos;{service.slug}&apos;, state), indent=2)) for t, f in [(&apos;signup&apos;, execute_signup), (&apos;persist&apos;, execute_persist), (&apos;workflow&apos;, execute_workflow)]]&quot;
                </div>
              </div>
              <div className="mt-3 text-xs text-slate-500">
                Verifier v{run.verifier_version} &middot;{" "}
                <a
                  href={`https://github.com/weida-pc/OnlyBots/blob/main/verifier/contracts/${service.slug}.json`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:underline"
                >
                  contract
                </a>{" "}
                &middot; ran at {formatTimestamp(run.started_at)}
                {run.completed_at && (
                  <>
                    , took {getDuration(run.started_at, run.completed_at)}
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── Sidebar: Service Info ───────────────────────────────────────── */}
        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-lg p-6">
            <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-4">
              Service Info
            </h2>
            <div className="space-y-4">
              <div>
                <div className="text-xs font-medium text-slate-400 mb-1">Description</div>
                <p className="text-sm text-slate-700">{service.description}</p>
              </div>
              <div>
                <div className="text-xs font-medium text-slate-400 mb-1">Core Workflow</div>
                <p className="text-sm text-slate-700 whitespace-pre-line">{service.core_workflow}</p>
              </div>
              <div>
                <div className="text-xs font-medium text-slate-400 mb-1">Sign-up URL</div>
                <a
                  href={service.signup_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-green-600 hover:underline break-all"
                >
                  {service.signup_url}
                </a>
              </div>
              {service.docs_url && (
                <div>
                  <div className="text-xs font-medium text-slate-400 mb-1">Documentation</div>
                  <a
                    href={service.docs_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-green-600 hover:underline break-all"
                  >
                    {service.docs_url}
                  </a>
                </div>
              )}
              {service.pricing_url && (
                <div>
                  <div className="text-xs font-medium text-slate-400 mb-1">Pricing</div>
                  <a
                    href={service.pricing_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-green-600 hover:underline break-all"
                  >
                    {service.pricing_url}
                  </a>
                </div>
              )}
              <div className="pt-3 border-t border-slate-100">
                <Link
                  href={`/issues?service=${service.slug}`}
                  className="text-sm text-slate-500 hover:text-green-700 hover:underline"
                >
                  Report an issue with this service →
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
