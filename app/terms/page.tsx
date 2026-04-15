import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Service — OnlyBots",
  description: "Terms of Service for the OnlyBots Trust Registry.",
};

export default function TermsPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-slate-900 mb-2">Terms of Service</h1>
      <p className="text-sm text-slate-400 mb-10">Last updated: April 2026</p>

      <div className="prose prose-slate max-w-none space-y-8 text-sm text-slate-700 leading-relaxed">

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">1. What OnlyBots Is</h2>
          <p>
            OnlyBots is a public trust registry that tests and publishes the results of autonomous
            AI agent compatibility for third-party services. We verify whether AI agents can sign
            up for, own, and operate these services without human intervention.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">2. Accuracy of Verification Results</h2>
          <p>
            Verification results represent the outcome of automated tests run at a specific point
            in time. A &ldquo;Verified&rdquo; status does not constitute an endorsement of a
            service, nor does it guarantee the service will remain agent-compatible in the future.
            A &ldquo;Failed&rdquo; status reflects test conditions at the time of the run and may
            not reflect the service&rsquo;s current capabilities.
          </p>
          <p className="mt-2">
            We re-run verifications periodically but cannot guarantee real-time accuracy.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">3. Submitting a Service</h2>
          <p>
            By submitting a service, you represent that you have the right to submit it and that
            the information you provide is accurate to the best of your knowledge. We reserve the
            right to reject, remove, or re-categorize any submission without notice.
          </p>
          <p className="mt-2">
            Submitting a service does not guarantee it will be verified or listed. Submissions are
            subject to review and testing.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">4. No Warranty</h2>
          <p>
            OnlyBots is provided &ldquo;as is&rdquo; without warranty of any kind, express or
            implied. We make no representations about the suitability, reliability, or accuracy of
            the registry for any purpose.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">5. Limitation of Liability</h2>
          <p>
            To the maximum extent permitted by law, OnlyBots and its operators shall not be liable
            for any indirect, incidental, special, or consequential damages arising from your use
            of the registry or reliance on its data.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">6. Third-Party Services</h2>
          <p>
            We test third-party services as part of our verification process. We are not affiliated
            with, endorsed by, or responsible for any service listed in the registry. Use of any
            listed service is subject to that service&rsquo;s own terms.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">7. Changes</h2>
          <p>
            We may update these terms at any time. Continued use of OnlyBots after changes
            constitutes acceptance of the revised terms.
          </p>
        </section>

      </div>
    </div>
  );
}
