import { z } from "zod";

export const submitServiceSchema = z.object({
  name: z.string().min(1).max(100),
  url: z.string().url(),
  signup_url: z.string().url(),
  category: z.enum(["communication", "execution", "hosting"]),
  description: z.string().min(10).max(300),
  core_workflow: z.string().min(10).max(1000),
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
  contact_email: z.string().email(),
});

export type SubmitServiceInput = z.infer<typeof submitServiceSchema>;

export function getJsonSchema() {
  return {
    $schema: "http://json-schema.org/draft-07/schema#",
    type: "object",
    required: [
      "name",
      "url",
      "signup_url",
      "category",
      "description",
      "core_workflow",
      "contact_email",
    ],
    properties: {
      name: {
        type: "string",
        minLength: 1,
        maxLength: 100,
      },
      url: {
        type: "string",
        format: "uri",
      },
      signup_url: {
        type: "string",
        format: "uri",
      },
      category: {
        type: "string",
        enum: ["communication", "execution", "hosting"],
      },
      description: {
        type: "string",
        minLength: 10,
        maxLength: 300,
      },
      core_workflow: {
        type: "string",
        minLength: 10,
        maxLength: 1000,
      },
      docs_url: {
        type: "string",
        format: "uri",
      },
      pricing_url: {
        type: "string",
        format: "uri",
      },
      contact_email: {
        type: "string",
        format: "email",
      },
    },
    additionalProperties: false,
  };
}
