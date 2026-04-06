import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Verification Methodology — OnlyBots",
  description:
    "How OnlyBots tests and verifies that services can be autonomously used by AI agents.",
};

export default function MethodologyPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-slate-900 mb-8">Verification Methodology</h1>

      {/* What We Test */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-slate-900 mb-4">What We Test</h2>
        <p className="text-slate-600 mb-6">
          Every service in the registry is subjected to three sequential tests. A service must pass
          all three to receive Verified status.
        </p>
        <div className="space-y-4">
          <div className="bg-white border border-slate-200 rounded-lg p-5">
            <div className="flex items-center gap-3 mb-2">
              <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-slate-100 text-slate-600 text-xs font-bold shrink-0">
                1
              </span>
              <h3 className="font-semibold text-slate-800">Autonomous Signup</h3>
            </div>
            <p className="text-sm text-slate-600 ml-10">
              An AI agent attempts to create an account using only information it can generate
              autonomously — no human-supplied credentials, CAPTCHA solving, or phone verification.
              The agent must reach a fully active account state without any human intervention.
            </p>
          </div>
          <div className="bg-white border border-slate-200 rounded-lg p-5">
            <div className="flex items-center gap-3 mb-2">
              <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-slate-100 text-slate-600 text-xs font-bold shrink-0">
                2
              </span>
              <h3 className="font-semibold text-slate-800">Persistent Account Ownership</h3>
            </div>
            <p className="text-sm text-slate-600 ml-10">
              The agent authenticates to the account it created in Test 1 in a fresh session,
              demonstrating that it can maintain persistent, unassisted control of the account over
              time. Credentials must be retrievable by the agent without human involvement.
            </p>
          </div>
          <div className="bg-white border border-slate-200 rounded-lg p-5">
            <div className="flex items-center gap-3 mb-2">
              <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-slate-100 text-slate-600 text-xs font-bold shrink-0">
                3
              </span>
              <h3 className="font-semibold text-slate-800">Core Workflow Autonomy</h3>
            </div>
            <p className="text-sm text-slate-600 ml-10">
              The agent executes the service&rsquo;s declared core workflow end-to-end without
              human assistance. The workflow must produce a verifiable output or side-effect that
              confirms successful autonomous execution.
            </p>
          </div>
        </div>
      </section>

      {/* What Qualifies as Agent-First */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-slate-900 mb-4">
          What Qualifies as Agent-First
        </h2>
        <p className="text-slate-600 mb-4">
          A service qualifies as agent-first if it meets all six of the following criteria:
        </p>
        <ol className="space-y-3">
          {[
            "Account creation requires no human-only verification steps (no CAPTCHA, no SMS, no government ID).",
            "Authentication can be performed programmatically using API keys, OAuth tokens, or equivalent machine-readable credentials.",
            "The core workflow is fully accessible via API, CLI, or a structured web interface that an agent can navigate without visual reasoning.",
            "Account ownership is durable — credentials do not expire within 30 days and can be stored and retrieved by an agent.",
            "The service does not require a physical or legal entity as the account holder.",
            "Terms of service do not explicitly prohibit non-human account holders or automated use of core features.",
          ].map((criterion, i) => (
            <li key={i} className="flex gap-3 text-sm text-slate-600">
              <span className="font-semibold text-slate-400 shrink-0 mt-0.5">{i + 1}.</span>
              <span>{criterion}</span>
            </li>
          ))}
        </ol>
      </section>

      {/* Hard Exclusion Rules */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-slate-900 mb-4">Hard Exclusion Rules</h2>
        <p className="text-slate-600 mb-4">
          The following automatically disqualify a service regardless of other factors:
        </p>
        <ul className="space-y-2">
          {[
            "Mandatory identity verification using government-issued documents.",
            "Phone number or SMS verification required at any stage of signup or authentication.",
            "CAPTCHA or similar human-presence checks that cannot be bypassed via API.",
            "Terms of service that explicitly ban automated or non-human account holders.",
            "Core workflow requires physical hardware or in-person interaction.",
          ].map((rule, i) => (
            <li key={i} className="flex gap-2 text-sm text-slate-600">
              <span className="text-red-500 mt-0.5 shrink-0">&#x2715;</span>
              <span>{rule}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Evidence */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-slate-900 mb-4">Evidence</h2>
        <p className="text-slate-600 mb-4">
          For each verification run, the following evidence is collected and stored:
        </p>
        <ul className="space-y-2">
          {[
            "Screenshots of each step in the signup, authentication, and workflow execution flows.",
            "Full HTTP request/response traces for all API calls made during the run.",
            "Agent execution logs showing the reasoning and actions taken at each step.",
            "Final state confirmation (e.g., API response confirming workflow completion).",
            "Timestamps and verifier version for auditability.",
          ].map((item, i) => (
            <li key={i} className="flex gap-2 text-sm text-slate-600">
              <span className="text-green-600 mt-0.5 shrink-0">&#x2713;</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Status Definitions */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-slate-900 mb-4">Status Definitions</h2>
        <div className="space-y-4">
          <div className="bg-white border border-slate-200 rounded-lg p-5">
            <div className="flex items-center gap-2 mb-2">
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-600 shrink-0" />
              <h3 className="font-semibold text-slate-800">Verified</h3>
            </div>
            <p className="text-sm text-slate-600">
              The service passed all three tests in its most recent verification run. An AI agent
              can autonomously sign up, maintain account ownership, and execute the core workflow.
            </p>
          </div>
          <div className="bg-white border border-slate-200 rounded-lg p-5">
            <div className="flex items-center gap-2 mb-2">
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-600 shrink-0" />
              <h3 className="font-semibold text-slate-800">Failed</h3>
            </div>
            <p className="text-sm text-slate-600">
              The service did not pass one or more tests. The registry shows which test caused the
              failure and why. Services can be re-submitted after addressing the failure.
            </p>
          </div>
          <div className="bg-white border border-slate-200 rounded-lg p-5">
            <div className="flex items-center gap-2 mb-2">
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-400 shrink-0" />
              <h3 className="font-semibold text-slate-800">Pending</h3>
            </div>
            <p className="text-sm text-slate-600">
              The service has been submitted and is awaiting its first verification run, or a run
              is currently in progress. Results are typically available within 24&ndash;48 hours.
            </p>
          </div>
        </div>
      </section>

      {/* Scope Rule */}
      <section className="mb-8">
        <h2 className="text-xl font-semibold text-slate-900 mb-4">Scope Rule</h2>
        <div className="bg-slate-50 border border-slate-200 rounded-lg p-5">
          <p className="text-sm text-slate-600">
            Verification is judged against the service&rsquo;s <strong>declared core workflow</strong>,
            not edge cases or advanced features. A service that autonomously handles its primary
            value proposition qualifies as agent-first even if some secondary features require
            human involvement. The core workflow must be explicitly declared at submission and is
            published in the registry alongside the verification result.
          </p>
        </div>
      </section>
    </div>
  );
}
