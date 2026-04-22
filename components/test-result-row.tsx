import { CheckCircle, XCircle, MinusCircle, Clock, Cpu, Globe } from "lucide-react";
import type { VerificationResult } from "@/lib/types";

interface TestResultRowProps {
  testNumber: number;
  testName: string;
  result: VerificationResult | null;
}

export default function TestResultRow({
  testNumber,
  testName,
  result,
}: TestResultRowProps) {
  const isSkipped = result === null;
  const isPassed = result?.passed === true;
  const details = (result?.details ?? {}) as Record<string, unknown>;

  const harness = (details.harness as string) || null;
  // Prefer the model the contract's agent_task actually invoked (recorded
  // since tests/_common.py). Fall back to the legacy `model` field.
  // `agent_task_model: null` means the test ran no LLM (pure-HTTP
  // contract) — in that case don't render a model label at all.
  const agentTaskModel =
    "agent_task_model" in details
      ? (details.agent_task_model as string | null)
      : undefined;
  const model =
    agentTaskModel ??
    (agentTaskModel === null ? null : (details.model as string) || null);
  const urlTested = (details.url_tested as string) || null;
  const responseTime = (details.response_time_s as number) || null;
  const agentReasoning = (details.agent_reasoning as string) || null;
  const blockerType = (details.blocker_type as string) || null;
  const confidence = result?.confidence ?? 0;

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div
        className={`px-4 py-3 flex items-center justify-between ${
          isSkipped
            ? "bg-slate-50"
            : isPassed
            ? "bg-green-50 border-b border-green-100"
            : "bg-red-50 border-b border-red-100"
        }`}
      >
        <div className="flex items-center gap-3">
          {isSkipped ? (
            <MinusCircle className="h-5 w-5 shrink-0 text-slate-300" />
          ) : isPassed ? (
            <CheckCircle className="h-5 w-5 shrink-0 text-green-600" />
          ) : (
            <XCircle className="h-5 w-5 shrink-0 text-red-600" />
          )}
          <div>
            <span className="text-sm font-medium text-slate-900">
              Test {testNumber}: {testName}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!isSkipped && (
            <span
              className={`text-xs font-mono px-2 py-0.5 rounded ${
                isPassed
                  ? "bg-green-100 text-green-700"
                  : "bg-red-100 text-red-700"
              }`}
            >
              {isPassed ? "PASS" : "FAIL"} {Math.round(confidence * 100)}%
            </span>
          )}
          {isSkipped && (
            <span className="text-xs text-slate-400">Skipped (prior test failed)</span>
          )}
        </div>
      </div>

      {/* Body — only for non-skipped tests */}
      {!isSkipped && (
        <div className="px-4 py-3 space-y-3">
          {/* Agent reasoning */}
          {agentReasoning && (
            <div>
              <div className="text-xs font-medium text-slate-400 mb-1">Agent Analysis</div>
              <p className="text-sm text-slate-700 leading-relaxed">{agentReasoning}</p>
            </div>
          )}

          {/* Failure reason with actionable guidance */}
          {!isPassed && result?.failure_reason && (
            <div className="bg-red-50 border border-red-200 rounded-md p-3">
              <div className="text-xs font-semibold text-red-800 mb-1">
                {blockerType ? `Blocker: ${blockerType}` : "Failure Details"}
              </div>
              <p className="text-sm text-red-700">{result.failure_reason}</p>
            </div>
          )}

          {/* Metadata row */}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400 pt-1 border-t border-slate-100">
            {harness && model && (
              <span className="inline-flex items-center gap-1">
                <Cpu className="h-3 w-3" />
                {harness}/{model}
              </span>
            )}
            {urlTested && (
              <span className="inline-flex items-center gap-1">
                <Globe className="h-3 w-3" />
                <a
                  href={urlTested}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-slate-600 hover:underline truncate max-w-[200px]"
                >
                  {urlTested}
                </a>
              </span>
            )}
            {responseTime != null && responseTime > 0 && (
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {responseTime}s
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
