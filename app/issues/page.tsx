import type { Metadata } from "next";
import Link from "next/link";
import IssueForm from "@/components/issue-form";
import { getIssues } from "@/lib/db";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Issues — OnlyBots",
  description:
    "Report bugs, contract problems, or general feedback against the OnlyBots Trust Registry. Issues are recorded publicly.",
};

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const STATUS_COLOR: Record<string, string> = {
  open: "bg-blue-100 text-blue-700",
  acknowledged: "bg-amber-100 text-amber-700",
  closed: "bg-slate-100 text-slate-600",
};

interface PageProps {
  // ?service=<slug> — when present, the form locks the service field to
  // that slug and the recent-issues list filters down to just that
  // service. Used by the "Report an issue with this service" link from
  // /services/[slug].
  searchParams: Promise<{ service?: string }>;
}

export default async function IssuesPage({ searchParams }: PageProps) {
  const { service: serviceFilter } = await searchParams;
  const issues = await getIssues({
    service_slug: serviceFilter,
    limit: 100,
  });

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-10">
      <header className="space-y-3">
        <h1 className="text-3xl font-bold text-slate-900">
          Issues
          {serviceFilter && (
            <span className="ml-2 text-base font-normal text-slate-500">
              · filed against{" "}
              <Link
                href={`/services/${serviceFilter}`}
                className="font-mono text-green-700 hover:underline"
              >
                {serviceFilter}
              </Link>
            </span>
          )}
        </h1>
        <p className="text-slate-600">
          Spotted a bug, a wrong verdict, a stale contract, or have feedback
          about the registry itself? File it here. Issues are recorded
          publicly so anyone can see what&apos;s outstanding. To file against a
          specific service, paste its slug — or use the &ldquo;Report an
          issue&rdquo; link from any service detail page.
        </p>
        {serviceFilter && (
          <p>
            <Link
              href="/issues"
              className="text-sm text-slate-500 hover:text-green-700 hover:underline"
            >
              ← Show all issues
            </Link>
          </p>
        )}
      </header>

      <section
        aria-labelledby="issue-form-heading"
        className="bg-white border border-slate-200 rounded-lg p-6"
      >
        <h2 id="issue-form-heading" className="text-lg font-semibold text-slate-900 mb-4">
          Submit a new issue
        </h2>
        <IssueForm defaultServiceSlug={serviceFilter} />
      </section>

      <section aria-labelledby="recent-issues-heading">
        <h2
          id="recent-issues-heading"
          className="text-lg font-semibold text-slate-900 mb-4"
        >
          Recent issues{" "}
          <span className="text-sm font-normal text-slate-400">
            ({issues.length})
          </span>
        </h2>

        {issues.length === 0 ? (
          <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
            No issues filed yet. Be the first.
          </div>
        ) : (
          <ul className="space-y-3">
            {issues.map((issue) => (
              <li
                key={issue.id}
                className="rounded-lg border border-slate-200 bg-white p-4"
              >
                <div className="flex items-start justify-between gap-3 mb-1.5">
                  <h3 className="text-sm font-semibold text-slate-900 break-words">
                    {issue.title}
                  </h3>
                  <span
                    className={`shrink-0 text-xs font-mono px-2 py-0.5 rounded ${
                      STATUS_COLOR[issue.status] ?? "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {issue.status}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 mb-2">
                  <span>#{issue.id}</span>
                  <span>{formatTimestamp(issue.created_at)}</span>
                  {issue.service_slug ? (
                    <Link
                      href={`/services/${issue.service_slug}`}
                      className="text-green-700 hover:underline font-mono"
                    >
                      {issue.service_slug}
                    </Link>
                  ) : (
                    <span className="text-slate-400">general</span>
                  )}
                </div>
                <p className="text-sm text-slate-700 whitespace-pre-wrap break-words">
                  {issue.body}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
