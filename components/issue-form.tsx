"use client";

import { useState, type ChangeEvent, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

interface IssueFormProps {
  /**
   * Optional service slug to pre-scope the issue to. When set, the field
   * becomes a read-only label and the issue is filed against that
   * service.
   */
  defaultServiceSlug?: string;
}

interface FormValues {
  title: string;
  body: string;
  service_slug: string;
  reporter_contact: string;
}

type FormErrors = Partial<Record<keyof FormValues, string>>;

const TITLE_MIN = 5;
const TITLE_MAX = 200;
const BODY_MIN = 10;
const BODY_MAX = 5000;

export default function IssueForm({ defaultServiceSlug }: IssueFormProps) {
  const router = useRouter();
  const [values, setValues] = useState<FormValues>({
    title: "",
    body: "",
    service_slug: defaultServiceSlug ?? "",
    reporter_contact: "",
  });
  const [errors, setErrors] = useState<FormErrors>({});
  const [topMessage, setTopMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [loading, setLoading] = useState(false);

  function handleChange(
    e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) {
    const { name, value } = e.target;
    setValues((prev) => ({ ...prev, [name]: value }));
    if (errors[name as keyof FormValues]) {
      setErrors((prev) => ({ ...prev, [name]: undefined }));
    }
    setTopMessage(null);
  }

  function validate(v: FormValues): FormErrors {
    const e: FormErrors = {};
    const titleLen = v.title.trim().length;
    if (titleLen < TITLE_MIN) e.title = `Title must be at least ${TITLE_MIN} characters.`;
    else if (titleLen > TITLE_MAX) e.title = `Title must be at most ${TITLE_MAX} characters.`;
    const bodyLen = v.body.trim().length;
    if (bodyLen < BODY_MIN) e.body = `Body must be at least ${BODY_MIN} characters.`;
    else if (bodyLen > BODY_MAX) e.body = `Body must be at most ${BODY_MAX} characters.`;
    return e;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setTopMessage(null);

    const validationErrors = validate(values);
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }

    setLoading(true);
    try {
      const body: Record<string, string> = {
        title: values.title.trim(),
        body: values.body.trim(),
      };
      if (values.service_slug.trim()) body.service_slug = values.service_slug.trim();
      if (values.reporter_contact.trim())
        body.reporter_contact = values.reporter_contact.trim();

      const res = await fetch("/api/issues", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        setTopMessage({
          kind: "ok",
          text: "Thanks — your issue is recorded. It will appear in the list shortly.",
        });
        // Clear form (preserve preset slug, since we may still be on that page).
        setValues((prev) => ({
          title: "",
          body: "",
          service_slug: defaultServiceSlug ?? "",
          reporter_contact: prev.reporter_contact, // keep contact for follow-on issues
        }));
        // Refresh the page so the SSR list picks up the new issue.
        router.refresh();
        return;
      }

      if (res.status === 429) {
        setTopMessage({
          kind: "err",
          text: "Too many issues from this IP in the last hour. Try again later.",
        });
      } else {
        const data = await res.json().catch(() => ({}));
        setTopMessage({
          kind: "err",
          text: data?.error ?? "Something went wrong. Please try again.",
        });
      }
    } catch {
      setTopMessage({
        kind: "err",
        text: "Network error. Please check your connection and try again.",
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      {topMessage && (
        <div
          className={cn(
            "rounded-md border px-4 py-3 text-sm",
            topMessage.kind === "ok"
              ? "bg-green-50 border-green-200 text-green-800"
              : "bg-red-50 border-red-200 text-red-700"
          )}
          role="status"
        >
          {topMessage.text}
        </div>
      )}

      {/* Service slug — locked to the prefilled value when one was passed in */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="service_slug" className="text-sm font-medium text-slate-700">
          Service slug{" "}
          <span className="font-normal text-slate-400">
            (optional — leave blank for a general/registry issue)
          </span>
        </label>
        <input
          id="service_slug"
          name="service_slug"
          type="text"
          value={values.service_slug}
          onChange={handleChange}
          placeholder="e.g. agentmail-to"
          readOnly={Boolean(defaultServiceSlug)}
          className={cn(
            "w-full rounded-md border px-3 py-2 text-sm text-slate-900 placeholder-slate-400",
            "focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent",
            "transition",
            defaultServiceSlug ? "bg-slate-50 cursor-not-allowed" : "",
            "border-slate-200"
          )}
        />
      </div>

      {/* Title */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="title" className="text-sm font-medium text-slate-700">
          Title<span className="text-red-500 ml-0.5">*</span>
        </label>
        <input
          id="title"
          name="title"
          type="text"
          value={values.title}
          onChange={handleChange}
          maxLength={TITLE_MAX}
          required
          placeholder="Short summary of the issue"
          className={cn(
            "w-full rounded-md border px-3 py-2 text-sm text-slate-900 placeholder-slate-400",
            "focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent",
            "transition",
            errors.title ? "border-red-400" : "border-slate-200"
          )}
        />
        {errors.title && <p className="text-xs text-red-600">{errors.title}</p>}
      </div>

      {/* Body */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="body" className="text-sm font-medium text-slate-700">
          Details<span className="text-red-500 ml-0.5">*</span>
        </label>
        <textarea
          id="body"
          name="body"
          value={values.body}
          onChange={handleChange}
          rows={6}
          maxLength={BODY_MAX}
          required
          placeholder="What did you expect? What did you see? Include URLs, slugs, request IDs if you have them."
          className={cn(
            "w-full rounded-md border px-3 py-2 text-sm text-slate-900 placeholder-slate-400",
            "focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent",
            "transition resize-y",
            errors.body ? "border-red-400" : "border-slate-200"
          )}
        />
        <div className="flex justify-between text-xs">
          {errors.body ? (
            <p className="text-red-600">{errors.body}</p>
          ) : (
            <span className="text-slate-400">
              Markdown not rendered. {BODY_MIN}–{BODY_MAX} chars.
            </span>
          )}
          <span className="text-slate-400">
            {values.body.length}/{BODY_MAX}
          </span>
        </div>
      </div>

      {/* Reporter contact */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="reporter_contact" className="text-sm font-medium text-slate-700">
          Your contact{" "}
          <span className="font-normal text-slate-400">(optional — email or @handle)</span>
        </label>
        <input
          id="reporter_contact"
          name="reporter_contact"
          type="text"
          value={values.reporter_contact}
          onChange={handleChange}
          maxLength={200}
          placeholder="you@example.com or @yourhandle"
          className={cn(
            "w-full rounded-md border px-3 py-2 text-sm text-slate-900 placeholder-slate-400",
            "focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent",
            "transition border-slate-200"
          )}
        />
      </div>

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
          {loading ? "Submitting…" : "Submit issue"}
        </button>
      </div>
    </form>
  );
}
