import { z } from "zod";

/**
 * Submission schema — URL is the only required field. Everything else is
 * either supplied by the submitter or inferred from the landing page by
 * lib/metadata.ts. The goal is for an agent to submit itself with a single
 * `curl -X POST ... -d '{"url":"https://x"}'` and have the registry fill
 * the rest. Submitters who want control can always pass the full object.
 */
export const submitServiceSchema = z.object({
  url: z.string().url(),
  name: z.string().min(1).max(100).optional(),
  signup_url: z.string().url().optional(),
  category: z.enum(["communication", "execution", "hosting"]).optional(),
  description: z.string().min(10).max(300).optional(),
  core_workflow: z.string().min(10).max(1000).optional(),
  docs_url: z
    .string()
    .url()
    .optional()
    .or(z.literal(""))
    .transform((v) => v || undefined),
  pricing_url: z
    .string()
    .url()
    .optional()
    .or(z.literal(""))
    .transform((v) => v || undefined),
  contact_email: z.string().email().optional(),
});

export type SubmitServiceInput = z.infer<typeof submitServiceSchema>;

/**
 * Issue submission schema. Title + body are required. service_slug is
 * optional — when present, the issue is filed against that service;
 * otherwise it's a general site/registry issue. reporter_contact is a
 * free-form string (email or @handle) so people can leave a way to be
 * reached without us doing real email validation.
 */
export const submitIssueSchema = z.object({
  title: z.string().trim().min(5).max(200),
  body: z.string().trim().min(10).max(5000),
  service_slug: z
    .string()
    .trim()
    .max(150)
    .optional()
    .or(z.literal(""))
    .transform((v) => (v ? v : undefined)),
  reporter_contact: z
    .string()
    .trim()
    .max(200)
    .optional()
    .or(z.literal(""))
    .transform((v) => (v ? v : undefined)),
});

export type SubmitIssueInput = z.infer<typeof submitIssueSchema>;

export function getJsonSchema() {
  return {
    $schema: "http://json-schema.org/draft-07/schema#",
    type: "object",
    required: ["url"],
    description:
      "Submit a service to OnlyBots. Only `url` is required; missing " +
      "fields are inferred from the landing page HTML.",
    properties: {
      url: { type: "string", format: "uri" },
      name: { type: "string", minLength: 1, maxLength: 100 },
      signup_url: { type: "string", format: "uri" },
      category: {
        type: "string",
        enum: ["communication", "execution", "hosting"],
      },
      description: { type: "string", minLength: 10, maxLength: 300 },
      core_workflow: { type: "string", minLength: 10, maxLength: 1000 },
      docs_url: { type: "string", format: "uri" },
      pricing_url: { type: "string", format: "uri" },
      contact_email: { type: "string", format: "email" },
    },
    additionalProperties: false,
  };
}
