import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "API Documentation — OnlyBots",
  description:
    "Machine-readable API endpoints for the OnlyBots Trust Registry.",
};

interface EndpointProps {
  method: "GET" | "POST";
  path: string;
  description: string;
  parameters?: { name: string; in: string; required: boolean; description: string }[];
  curl: string;
  response: string;
}

function Endpoint({ method, path, description, parameters, curl, response }: EndpointProps) {
  const methodColor =
    method === "GET"
      ? "bg-blue-100 text-blue-700"
      : "bg-green-100 text-green-700";

  return (
    <div className="bg-white border border-slate-200 rounded-lg overflow-hidden mb-6">
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-100">
        <div className="flex flex-wrap items-center gap-3 mb-2">
          <span
            className={`inline-flex items-center px-2.5 py-0.5 rounded text-xs font-bold font-mono ${methodColor}`}
          >
            {method}
          </span>
          <code className="text-sm font-mono text-slate-800">{path}</code>
        </div>
        <p className="text-sm text-slate-600">{description}</p>
      </div>

      {/* Parameters */}
      {parameters && parameters.length > 0 && (
        <div className="px-5 py-4 border-b border-slate-100">
          <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
            Parameters
          </h4>
          <div className="space-y-2">
            {parameters.map((p) => (
              <div key={p.name} className="flex flex-wrap gap-2 text-sm">
                <code className="font-mono text-slate-800 bg-slate-50 px-1.5 py-0.5 rounded text-xs">
                  {p.name}
                </code>
                <span className="text-slate-400 text-xs italic">{p.in}</span>
                {p.required && (
                  <span className="text-red-500 text-xs font-medium">required</span>
                )}
                <span className="text-slate-600 text-xs">{p.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Curl */}
      <div className="px-5 py-4 border-b border-slate-100">
        <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
          Example Request
        </h4>
        <pre className="bg-slate-900 text-slate-100 rounded-md px-4 py-3 text-xs font-mono overflow-x-auto">
          <code>{curl}</code>
        </pre>
      </div>

      {/* Response */}
      <div className="px-5 py-4">
        <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
          Example Response
        </h4>
        <pre className="bg-slate-50 border border-slate-200 rounded-md px-4 py-3 text-xs font-mono overflow-x-auto text-slate-700">
          <code>{response}</code>
        </pre>
      </div>
    </div>
  );
}

export default function ApiDocsPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-slate-900 mb-3">API Documentation</h1>
      <p className="text-slate-600 mb-10">
        All endpoints return JSON. No authentication is required for read operations.
      </p>

      {/* GET /api/services */}
      <Endpoint
        method="GET"
        path="/api/services"
        description="List all services in the registry. Supports optional search and filter parameters."
        parameters={[
          {
            name: "q",
            in: "query",
            required: false,
            description: "Full-text search across service name and description.",
          },
          {
            name: "category",
            in: "query",
            required: false,
            description: "Filter by category: Communication, Execution, or Hosting.",
          },
          {
            name: "status",
            in: "query",
            required: false,
            description: "Filter by status: verified, failed, or pending.",
          },
        ]}
        curl={`curl https://onlybots.dev/api/services
curl "https://onlybots.dev/api/services?status=verified&category=Hosting"`}
        response={`[
  {
    "id": 1,
    "slug": "acme-hosting",
    "name": "Acme Hosting",
    "url": "https://acme.example.com",
    "signup_url": "https://acme.example.com/signup",
    "category": "Hosting",
    "description": "Serverless hosting with a fully autonomous API.",
    "core_workflow": "Create project, deploy, retrieve endpoint.",
    "docs_url": "https://docs.acme.example.com",
    "pricing_url": "https://acme.example.com/pricing",
    "status": "verified",
    "failed_at_step": null,
    "verified_date": "2025-03-15T00:00:00.000Z",
    "created_at": "2025-03-01T10:00:00.000Z",
    "updated_at": "2025-03-15T12:00:00.000Z"
  }
]`}
      />

      {/* GET /api/services/[slug] */}
      <Endpoint
        method="GET"
        path="/api/services/{slug}"
        description="Retrieve a single service with its full verification history, including test results."
        parameters={[
          {
            name: "slug",
            in: "path",
            required: true,
            description: "The URL slug of the service.",
          },
        ]}
        curl={`curl https://onlybots.dev/api/services/acme-hosting`}
        response={`{
  "id": 1,
  "slug": "acme-hosting",
  "name": "Acme Hosting",
  "status": "verified",
  "verification": {
    "run": {
      "id": 42,
      "service_id": 1,
      "started_at": "2025-03-15T11:00:00.000Z",
      "completed_at": "2025-03-15T11:12:00.000Z",
      "status": "passed",
      "verifier_version": "0.1.0"
    },
    "results": [
      {
        "id": 1,
        "run_id": 42,
        "test_number": 1,
        "test_name": "Autonomous signup",
        "passed": true,
        "confidence": 0.97,
        "failure_reason": null
      }
    ]
  }
}`}
      />

      {/* POST /api/services/submit */}
      <Endpoint
        method="POST"
        path="/api/services/submit"
        description="Submit a new service for agent-first verification. Returns the created service with its slug."
        parameters={[
          { name: "name", in: "body", required: true, description: "Display name of the service." },
          { name: "url", in: "body", required: true, description: "Primary URL of the service." },
          { name: "signup_url", in: "body", required: true, description: "URL where an agent can create an account." },
          { name: "category", in: "body", required: true, description: "Communication | Execution | Hosting" },
          { name: "description", in: "body", required: true, description: "One-sentence description." },
          { name: "core_workflow", in: "body", required: true, description: "Step-by-step description of the primary agent workflow." },
          { name: "contact_email", in: "body", required: true, description: "Contact email for the submitter." },
          { name: "docs_url", in: "body", required: false, description: "Documentation URL (optional)." },
          { name: "pricing_url", in: "body", required: false, description: "Pricing page URL (optional)." },
        ]}
        curl={`curl -X POST https://onlybots.dev/api/services/submit \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "Acme Hosting",
    "url": "https://acme.example.com",
    "signup_url": "https://acme.example.com/signup",
    "category": "Hosting",
    "description": "Serverless hosting with a fully autonomous API.",
    "core_workflow": "1. POST /accounts to create account\\n2. Retrieve API key\\n3. Deploy via /deployments",
    "contact_email": "agent@acme.example.com"
  }'`}
        response={`{
  "id": 1,
  "slug": "acme-hosting",
  "name": "Acme Hosting",
  "status": "pending",
  "created_at": "2025-04-05T08:00:00.000Z"
}`}
      />

      {/* GET /api/schema */}
      <Endpoint
        method="GET"
        path="/api/schema"
        description="Returns the JSON Schema for the service submission payload. Useful for agents that need to construct a valid submission."
        curl={`curl https://onlybots.dev/api/schema`}
        response={`{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ServiceSubmission",
  "type": "object",
  "required": ["name", "url", "signup_url", "category", "description", "core_workflow", "contact_email"],
  "properties": {
    "name": { "type": "string" },
    "url": { "type": "string", "format": "uri" },
    "signup_url": { "type": "string", "format": "uri" },
    "category": { "type": "string", "enum": ["Communication", "Execution", "Hosting"] },
    "description": { "type": "string" },
    "core_workflow": { "type": "string" },
    "contact_email": { "type": "string", "format": "email" },
    "docs_url": { "type": "string", "format": "uri" },
    "pricing_url": { "type": "string", "format": "uri" }
  }
}`}
      />

      {/* GET /api/methodology */}
      <Endpoint
        method="GET"
        path="/api/methodology"
        description="Returns the verification methodology in machine-readable JSON format, suitable for agents evaluating whether to submit a service."
        curl={`curl https://onlybots.dev/api/methodology`}
        response={`{
  "version": "0.1.0",
  "tests": [
    { "number": 1, "name": "Autonomous signup" },
    { "number": 2, "name": "Persistent account ownership" },
    { "number": 3, "name": "Core workflow autonomy" }
  ],
  "qualificationCriteria": 6,
  "hardExclusions": 5
}`}
      />

      {/* GET /.well-known/onlybots.json */}
      <Endpoint
        method="GET"
        path="/.well-known/onlybots.json"
        description="Discovery endpoint following the well-known URI convention. Returns registry metadata, endpoint locations, and schema references for agents discovering the registry programmatically."
        curl={`curl https://onlybots.dev/.well-known/onlybots.json`}
        response={`{
  "name": "OnlyBots Trust Registry",
  "version": "0.1.0",
  "description": "Verified directory of services AI agents can autonomously sign up for, own, and operate.",
  "endpoints": {
    "services": "/api/services",
    "submit": "/api/services/submit",
    "schema": "/api/schema",
    "methodology": "/api/methodology"
  },
  "schema": "/api/schema",
  "methodology": "/methodology"
}`}
      />
    </div>
  );
}
