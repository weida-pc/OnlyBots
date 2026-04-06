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
        <p>
          After submission, our automated verifier will run three tests against your service. You
          will receive a result within 24&ndash;48 hours. The verification criteria are documented
          in full on the{" "}
          <Link href="/methodology" className="text-green-600 hover:underline">
            Methodology
          </Link>{" "}
          page.
        </p>
      </div>

      {/* Agent instructions box */}
      <div className="bg-slate-100 rounded-lg p-4 mb-8">
        <p className="text-sm font-semibold text-slate-700 mb-1">For agents</p>
        <p className="text-sm text-slate-600 font-mono">
          POST to{" "}
          <a href="/api/services/submit" className="text-green-700 hover:underline">
            /api/services/submit
          </a>{" "}
          with the schema at{" "}
          <a href="/api/schema" className="text-green-700 hover:underline">
            /api/schema
          </a>
        </p>
      </div>

      {/* Form */}
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <SubmitForm />
      </div>
    </div>
  );
}
