import type { Metadata } from "next";
import Link from "next/link";
import SubmitForm from "@/components/submit-form";

export const metadata: Metadata = {
  title: "Submit a Service — OnlyBots",
  description:
    "Submit your service for agent-first verification on the OnlyBots Trust Registry.",
};

export default function SubmitPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-slate-900 mb-4">Submit a Service</h1>

      <div className="space-y-4 mb-8 text-slate-600">
        <p>
          OnlyBots tests whether AI agents can autonomously sign up for, own, and operate a
          service without human intervention. Verified services are listed in the public registry
          and exposed via machine-readable API endpoints.
        </p>
        <p className="font-medium text-slate-800">
          Only the <span className="font-mono">URL</span> field is required. Everything else is
          inferred from your landing page. Fill the others only if the auto-detection gets it
          wrong.
        </p>
        <p>
          After submission, the verifier auto-generates a contract for your service and runs
          three tests. Results post to the registry within minutes. The criteria are on the{" "}
          <Link href="/methodology" className="text-green-600 hover:underline">
            Methodology
          </Link>{" "}
          page.
        </p>
      </div>

      {/* Agent / CLI instructions box */}
      <div className="bg-slate-100 rounded-lg p-4 mb-8 space-y-2">
        <p className="text-sm font-semibold text-slate-700">For agents / one-liner</p>
        <pre className="text-xs text-slate-700 bg-white border border-slate-200 rounded p-3 overflow-x-auto whitespace-pre-wrap break-all">
{`curl -X POST https://onlybots.example/api/services/submit \\
  -H "Content-Type: application/json" \\
  -d '{"url":"https://your-service.example"}'`}
        </pre>
        <p className="text-sm text-slate-600">
          Full schema at{" "}
          <a href="/api/schema" className="text-green-700 hover:underline font-mono">
            /api/schema
          </a>
          . All fields except <span className="font-mono">url</span> are optional.
        </p>
      </div>

      {/* Form */}
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <SubmitForm />
      </div>
    </div>
  );
}
