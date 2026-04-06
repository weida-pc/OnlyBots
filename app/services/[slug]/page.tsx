import { notFound } from "next/navigation";
import Link from "next/link";
import type { Metadata } from "next";
import { getServiceBySlug } from "@/lib/db";
import StatusBadge from "@/components/status-badge";
import TestResultRow from "@/components/test-result-row";
import type { VerificationResult } from "@/lib/types";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ slug: string }>;
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

export default async function ServiceDetailPage({ params }: PageProps) {
  const { slug } = await params;
  const service = await getServiceBySlug(slug);

  if (!service) {
    notFound();
  }

  const run = service.verification?.run;
  const results = service.verification?.results ?? [];

  function getResult(testNumber: number): VerificationResult | null {
    return results.find((r) => r.test_number === testNumber) ?? null;
  }

  // Extract harness/model from first available test result
  const firstResult = results[0];
  const firstDetails = (firstResult?.details ?? {}) as Record<string, unknown>;
  const harness = (firstDetails.harness as string) || "unknown";
  const model = (firstDetails.model as string) || "unknown";

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
                  <div className="text-sm text-slate-700 mt-0.5 capitalize">{harness} CLI</div>
                </div>
                <div>
                  <div className="text-xs font-medium text-slate-400">Underlying LLM</div>
                  <div className="text-sm font-mono text-slate-700 mt-0.5">{model}</div>
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

          {/* ── Reproduce This Verification ───────────────────────────────── */}
          {run && (
            <div className="bg-slate-900 text-slate-100 rounded-lg p-6">
              <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-3">
                Reproduce This Verification
              </h2>
              <p className="text-xs text-slate-400 mb-3">
                Run the same test with the same harness and model to reproduce these results.
              </p>
              <div className="bg-slate-800 rounded-md p-3 font-mono text-xs leading-relaxed overflow-x-auto">
                <div className="text-slate-500"># Install the agent CLI</div>
                <div className="text-green-400">
                  npm install -g {harness === "gemini" ? "@google/gemini-cli" : harness === "claude" ? "@anthropic-ai/claude-code" : harness === "codex" ? "@openai/codex" : harness === "openclaw" ? "openclaw" : harness}
                </div>
                <div className="text-slate-500 mt-2"># Set your API key</div>
                <div className="text-green-400">
                  export {harness === "gemini" || harness === "openclaw" ? "GEMINI_API_KEY" : harness === "claude" ? "ANTHROPIC_API_KEY" : harness === "codex" ? "OPENAI_API_KEY" : "API_KEY"}=your_key_here
                </div>
                <div className="text-slate-500 mt-2"># Run verification (Test 1 example)</div>
                <div className="text-green-400">
                  {harness === "gemini" ? `gemini -m ${model} -p` : harness === "claude" ? `claude --model ${model} --print` : harness === "openclaw" ? `openclaw --provider ${model} -p` : `${harness} --model ${model} --print`} &quot;Visit {service.signup_url} and determine if an AI agent can autonomously sign up...&quot;
                </div>
              </div>
              <div className="mt-3 text-xs text-slate-500">
                Verifier v{run.verifier_version} &middot; {harness}/{model} &middot; {formatTimestamp(run.started_at)}
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
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
