import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy — OnlyBots",
  description: "Privacy Policy for the OnlyBots Trust Registry.",
};

export default function PrivacyPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-slate-900 mb-2">Privacy Policy</h1>
      <p className="text-sm text-slate-400 mb-10">Last updated: April 2026</p>

      <div className="prose prose-slate max-w-none space-y-8 text-sm text-slate-700 leading-relaxed">

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">1. What We Collect</h2>
          <p>When you submit a service to the registry, we collect:</p>
          <ul className="list-disc list-inside mt-2 space-y-1">
            <li>Service name, URL, and description fields you provide</li>
            <li>Your contact email address</li>
            <li>Your IP address (for rate limiting, not stored permanently)</li>
          </ul>
          <p className="mt-3">
            We do not collect account information, cookies, or behavioral tracking data from
            visitors browsing the registry.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">2. How We Use It</h2>
          <ul className="list-disc list-inside space-y-1">
            <li>Contact email: used only to follow up on your submission if needed</li>
            <li>Service data: published publicly as part of the registry</li>
            <li>IP address: used transiently for abuse prevention, not stored</li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">3. What We Publish</h2>
          <p>
            All service fields (name, URL, description, category, status, verification results)
            are published publicly via the registry website and API. Your contact email is
            <strong> not</strong> published.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">4. Data Retention</h2>
          <p>
            Service submissions and verification results are stored indefinitely as part of the
            public registry. If you want your submission removed, contact us and we will evaluate
            the request.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">5. Third-Party Services</h2>
          <p>
            Our verification process makes automated API calls to third-party services. These
            interactions are subject to those services&rsquo; own privacy policies. We do not
            share your personal data with any third party.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-900 mb-3">6. Contact</h2>
          <p>
            For privacy-related questions or removal requests, open an issue on our{" "}
            <a
              href="https://github.com/weida-pc/OnlyBots"
              className="text-green-600 hover:underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub repository
            </a>.
          </p>
        </section>

      </div>
    </div>
  );
}
