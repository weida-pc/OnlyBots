import Link from "next/link";
import type { Service } from "@/lib/types";
import StatusBadge from "@/components/status-badge";
import { getServiceRequirements } from "@/lib/service-requirements";

interface ServiceCardProps {
  service: Service;
}

function formatVerifiedDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function ServiceCard({ service }: ServiceCardProps) {
  const reqs = getServiceRequirements(service.slug);
  const noHumanNeeded = reqs && !reqs.humanSetup.required;

  return (
    <Link
      href={`/services/${service.slug}`}
      className="group block bg-white border border-slate-200 rounded-lg p-5 hover:shadow-md transition-shadow duration-200"
    >
      {/* Top */}
      <div className="flex items-start justify-between gap-3 mb-2">
        <span className="text-base font-semibold text-slate-900 group-hover:text-green-700 transition-colors leading-snug">
          {service.name}
        </span>
        <span className="shrink-0 inline-block rounded px-2 py-0.5 text-xs font-medium bg-slate-100 text-slate-500 mt-0.5">
          {service.category}
        </span>
      </div>

      {/* Middle */}
      <p className="text-sm text-slate-600 leading-relaxed line-clamp-1 mb-4">
        {service.description}
      </p>

      {/* Bottom */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <StatusBadge
            status={service.status}
            failedAtStep={service.failed_at_step}
          />

          {service.status === "verified" && service.verified_date && (
            <span className="text-xs text-slate-400">
              Verified {formatVerifiedDate(service.verified_date)}
            </span>
          )}

          {service.status === "failed" && service.failed_at_step != null && (
            <span className="text-xs text-slate-400">
              Stopped at test {service.failed_at_step}
            </span>
          )}
        </div>

        {reqs && (
          <span className={`shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${
            noHumanNeeded
              ? "bg-green-50 text-green-700"
              : "bg-amber-50 text-amber-700"
          }`}>
            {noHumanNeeded ? "✓ No human setup" : "⚠ Setup required"}
          </span>
        )}
      </div>
    </Link>
  );
}
