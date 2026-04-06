export interface Service {
  id: number;
  slug: string;
  name: string;
  url: string;
  signup_url: string;
  category: string;
  description: string;
  core_workflow: string;
  docs_url: string | null;
  pricing_url: string | null;
  contact_email: string;
  status: "pending" | "verified" | "failed";
  failed_at_step: number | null;
  verified_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface VerificationRun {
  id: number;
  service_id: number;
  started_at: string;
  completed_at: string | null;
  status: "running" | "passed" | "failed";
  verifier_version: string;
  evidence_path: string | null;
}

export interface VerificationResult {
  id: number;
  run_id: number;
  test_number: number;
  test_name: string;
  passed: boolean;
  confidence: number;
  failure_reason: string | null;
  evidence_artifacts: Record<string, unknown>;
  details: Record<string, unknown>;
}

export interface ServiceWithVerification extends Service {
  verification?: {
    run: VerificationRun;
    results: VerificationResult[];
  } | null;
}
