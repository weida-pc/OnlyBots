import { CheckCircle, XCircle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  status:
    | "verified"
    | "failed"
    | "pending"
    | "pending_domain_verification"
    | "awaiting_contract";
  failedAtStep?: number | null;
}

export default function StatusBadge({ status, failedAtStep }: StatusBadgeProps) {
  if (status === "verified") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5",
          "bg-green-600 text-white text-xs font-medium"
        )}
      >
        <CheckCircle className="h-3.5 w-3.5 shrink-0" />
        Verified
      </span>
    );
  }

  if (status === "failed") {
    const label =
      failedAtStep != null ? `Failed at Test ${failedAtStep}` : "Failed";
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5",
          "bg-red-600 text-white text-xs font-medium"
        )}
      >
        <XCircle className="h-3.5 w-3.5 shrink-0" />
        {label}
      </span>
    );
  }

  if (status === "pending_domain_verification") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5",
          "bg-blue-100 text-blue-800 text-xs font-medium"
        )}
      >
        <Clock className="h-3.5 w-3.5 shrink-0" />
        Awaiting domain verification
      </span>
    );
  }

  if (status === "awaiting_contract") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5",
          "bg-slate-200 text-slate-700 text-xs font-medium"
        )}
      >
        <Clock className="h-3.5 w-3.5 shrink-0" />
        Awaiting contract
      </span>
    );
  }

  // pending
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5",
        "bg-amber-100 text-amber-800 text-xs font-medium"
      )}
    >
      <Clock className="h-3.5 w-3.5 shrink-0" />
      Pending
    </span>
  );
}
