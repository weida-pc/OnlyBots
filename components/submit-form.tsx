"use client";

import { useState, type ChangeEvent, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

const CATEGORIES = ["Communication", "Execution", "Hosting"] as const;
type Category = (typeof CATEGORIES)[number];

interface FormValues {
  name: string;
  url: string;
  signup_url: string;
  category: Category | "";
  description: string;
  core_workflow: string;
  docs_url: string;
  pricing_url: string;
  contact_email: string;
}

type FormErrors = Partial<Record<keyof FormValues, string>>;

const INITIAL: FormValues = {
  name: "",
  url: "",
  signup_url: "",
  category: "",
  description: "",
  core_workflow: "",
  docs_url: "",
  pricing_url: "",
  contact_email: "",
};

function isValidUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

function validate(values: FormValues): FormErrors {
  // Only `url` is actually required. Every other field is inferred from
  // the landing page server-side (lib/metadata.ts). We keep soft
  // validation on URL-shaped fields when the submitter does fill them
  // in, so a typo produces a clear message.
  const errors: FormErrors = {};

  if (!values.url.trim()) {
    errors.url = "URL is required.";
  } else if (!isValidUrl(values.url)) {
    errors.url = "Must be a valid URL (https://...).";
  }
  if (values.signup_url && !isValidUrl(values.signup_url))
    errors.signup_url = "Must be a valid URL (https://...) or left blank.";
  if (values.docs_url && !isValidUrl(values.docs_url))
    errors.docs_url = "Must be a valid URL or left blank.";
  if (values.pricing_url && !isValidUrl(values.pricing_url))
    errors.pricing_url = "Must be a valid URL or left blank.";
  if (values.contact_email && !values.contact_email.includes("@"))
    errors.contact_email = "Must be a valid email address.";

  return errors;
}

export default function SubmitForm() {
  const router = useRouter();
  const [values, setValues] = useState<FormValues>(INITIAL);
  const [errors, setErrors] = useState<FormErrors>({});
  const [topError, setTopError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function handleChange(
    e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
  ) {
    const { name, value } = e.target;
    setValues((prev) => ({ ...prev, [name]: value }));
    // Clear field error on change
    if (errors[name as keyof FormValues]) {
      setErrors((prev) => ({ ...prev, [name]: undefined }));
    }
    setTopError(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setTopError(null);

    const validationErrors = validate(values);
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }

    setLoading(true);
    try {
      // Only send fields the submitter actually filled in. The server
      // auto-fills missing ones from the landing page HTML.
      const body: Record<string, string> = { url: values.url.trim() };
      if (values.name.trim()) body.name = values.name.trim();
      if (values.signup_url.trim()) body.signup_url = values.signup_url.trim();
      if (values.category) body.category = values.category;
      if (values.description.trim()) body.description = values.description.trim();
      if (values.core_workflow.trim())
        body.core_workflow = values.core_workflow.trim();
      if (values.contact_email.trim())
        body.contact_email = values.contact_email.trim();
      if (values.docs_url.trim()) body.docs_url = values.docs_url.trim();
      if (values.pricing_url.trim()) body.pricing_url = values.pricing_url.trim();

      const res = await fetch("/api/services/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        const data = await res.json();
        router.push(`/services/${data.slug}`);
        return;
      }

      if (res.status === 409) {
        setTopError("A service with this URL already exists in the registry.");
      } else if (res.status === 429) {
        setTopError("Too many submissions. Please wait a moment and try again.");
      } else {
        const data = await res.json().catch(() => ({}));
        setTopError(
          data?.error ?? "Something went wrong. Please try again later."
        );
      }
    } catch {
      setTopError("Network error. Please check your connection and try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-6">
      {/* Top-level error banner */}
      {topError && (
        <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {topError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        {/* Name */}
        <Field
          label="Service Name"
          name="name"
          type="text"
          value={values.name}
          onChange={handleChange}
          error={errors.name}
          placeholder="Acme AI Agent"
          required
        />

        {/* Category */}
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="category"
            className="text-sm font-medium text-slate-700"
          >
            Category <span className="text-red-500">*</span>
          </label>
          <select
            id="category"
            name="category"
            value={values.category}
            onChange={handleChange}
            className={cn(
              "w-full rounded-md border px-3 py-2 text-sm text-slate-900 bg-white",
              "focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent",
              "transition",
              errors.category ? "border-red-400" : "border-slate-200"
            )}
          >
            <option value="">Select a category</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          {errors.category && (
            <p className="text-xs text-red-600">{errors.category}</p>
          )}
        </div>

        {/* URL */}
        <Field
          label="Service URL"
          name="url"
          type="url"
          value={values.url}
          onChange={handleChange}
          error={errors.url}
          placeholder="https://example.com"
          required
        />

        {/* Sign-up URL */}
        <Field
          label="Sign-up URL"
          name="signup_url"
          type="url"
          value={values.signup_url}
          onChange={handleChange}
          error={errors.signup_url}
          placeholder="https://example.com/signup"
          required
        />

        {/* Docs URL */}
        <Field
          label="Documentation URL"
          name="docs_url"
          type="url"
          value={values.docs_url}
          onChange={handleChange}
          error={errors.docs_url}
          placeholder="https://docs.example.com (optional)"
        />

        {/* Pricing URL */}
        <Field
          label="Pricing URL"
          name="pricing_url"
          type="url"
          value={values.pricing_url}
          onChange={handleChange}
          error={errors.pricing_url}
          placeholder="https://example.com/pricing (optional)"
        />

        {/* Contact Email */}
        <Field
          label="Contact Email"
          name="contact_email"
          type="email"
          value={values.contact_email}
          onChange={handleChange}
          error={errors.contact_email}
          placeholder="you@example.com"
          required
          className="sm:col-span-2"
        />
      </div>

      {/* Description */}
      <div className="flex flex-col gap-1.5">
        <label
          htmlFor="description"
          className="text-sm font-medium text-slate-700"
        >
          Description <span className="text-red-500">*</span>
        </label>
        <input
          id="description"
          name="description"
          type="text"
          value={values.description}
          onChange={handleChange}
          placeholder="One-sentence description of your service"
          className={cn(
            "w-full rounded-md border px-3 py-2 text-sm text-slate-900 placeholder-slate-400",
            "focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent",
            "transition",
            errors.description ? "border-red-400" : "border-slate-200"
          )}
        />
        {errors.description && (
          <p className="text-xs text-red-600">{errors.description}</p>
        )}
      </div>

      {/* Core Workflow */}
      <div className="flex flex-col gap-1.5">
        <label
          htmlFor="core_workflow"
          className="text-sm font-medium text-slate-700"
        >
          Core Workflow <span className="text-red-500">*</span>
        </label>
        <p className="text-xs text-slate-500">
          Describe the primary task flow an AI agent would follow when using
          your service — e.g., sign up, authenticate, perform the core action,
          retrieve results.
        </p>
        <textarea
          id="core_workflow"
          name="core_workflow"
          value={values.core_workflow}
          onChange={handleChange}
          rows={5}
          placeholder="1. Agent creates an account via the API&#10;2. Agent authenticates with an API key&#10;3. ..."
          className={cn(
            "w-full rounded-md border px-3 py-2 text-sm text-slate-900 placeholder-slate-400",
            "focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent",
            "transition resize-y",
            errors.core_workflow ? "border-red-400" : "border-slate-200"
          )}
        />
        {errors.core_workflow && (
          <p className="text-xs text-red-600">{errors.core_workflow}</p>
        )}
      </div>

      {/* Submit */}
      <div className="pt-2">
        <button
          type="submit"
          disabled={loading}
          className={cn(
            "inline-flex items-center gap-2 rounded-md px-5 py-2.5 text-sm font-semibold",
            "bg-green-600 text-white hover:bg-green-700 active:bg-green-800",
            "focus:outline-none focus:ring-2 focus:ring-green-600 focus:ring-offset-2",
            "transition disabled:opacity-60 disabled:cursor-not-allowed"
          )}
        >
          {loading && <Loader2 className="h-4 w-4 animate-spin" />}
          {loading ? "Submitting…" : "Submit for Verification"}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Reusable field sub-component (internal)
// ---------------------------------------------------------------------------

interface FieldProps {
  label: string;
  name: string;
  type: string;
  value: string;
  onChange: (e: ChangeEvent<HTMLInputElement>) => void;
  error?: string;
  placeholder?: string;
  required?: boolean;
  className?: string;
}

function Field({
  label,
  name,
  type,
  value,
  onChange,
  error,
  placeholder,
  required,
  className,
}: FieldProps) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={name} className="text-sm font-medium text-slate-700">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className={cn(
          "w-full rounded-md border px-3 py-2 text-sm text-slate-900 placeholder-slate-400",
          "focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent",
          "transition",
          error ? "border-red-400" : "border-slate-200"
        )}
      />
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
