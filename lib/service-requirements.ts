/**
 * Static per-service integration requirements.
 * Shows human owners exactly what to provide once so the agent can run fully autonomously.
 */

export interface InputRequirement {
  name: string;
  description: string;
  when: "pre-setup" | "runtime";
}

export interface ServiceRequirements {
  /** Does the service expose a programmatic signup API (no browser needed)? */
  nativeSignup: "yes" | "partial" | "no";
  nativeSignupNote: string;
  /** What the human owner must do once before the agent can operate */
  humanSetup: {
    required: boolean;
    steps: string[]; // empty if not required
  };
  /** All inputs the agent needs — pre-setup (provisioned once) or runtime (per call) */
  inputs: InputRequirement[];
  /** The actual API calls made, in order */
  apiCalls: {
    step: string;
    method: string;
    endpoint: string;
    purpose: string;
  }[];
}

const requirements: Record<string, ServiceRequirements> = {
  "agentmail-to": {
    nativeSignup: "yes",
    nativeSignupNote:
      "POST /v0/agent/sign-up returns api_key and inbox_id in the response body — no browser, no dashboard.",
    humanSetup: {
      required: false,
      steps: [],
    },
    inputs: [
      {
        name: "human_email",
        description: "Owner's email address — for account recovery and dashboard access",
        when: "pre-setup",
      },
      {
        name: "username",
        description: "Desired agent username prefix — determines the inbox email address",
        when: "pre-setup",
      },
      {
        name: "to[]",
        description: "Recipient email address(es)",
        when: "runtime",
      },
      {
        name: "subject",
        description: "Email subject line",
        when: "runtime",
      },
      {
        name: "body",
        description: "Email body content",
        when: "runtime",
      },
    ],
    apiCalls: [
      {
        step: "1",
        method: "POST",
        endpoint: "https://api.agentmail.to/v0/agent/sign-up",
        purpose: "Register agent — returns API key and inbox instantly",
      },
      {
        step: "2",
        method: "GET",
        endpoint: "https://api.agentmail.to/v0/inboxes",
        purpose: "Verify API key persists",
      },
      {
        step: "3",
        method: "POST",
        endpoint: "https://api.agentmail.to/v0/inboxes/{id}/messages/send",
        purpose: "Send email from agent inbox",
      },
      {
        step: "4",
        method: "GET",
        endpoint: "https://api.agentmail.to/v0/inboxes/{id}/messages",
        purpose: "List inbox messages to verify workflow",
      },
    ],
  },

  "here-now": {
    nativeSignup: "yes",
    nativeSignupNote:
      "Fully anonymous — no account or API key required. POST /api/v1/publish directly.",
    humanSetup: {
      required: false,
      steps: [],
    },
    inputs: [
      {
        name: "html_content",
        description: "HTML content to publish as a page",
        when: "runtime",
      },
    ],
    apiCalls: [
      {
        step: "1",
        method: "POST",
        endpoint: "https://here.now/api/v1/publish",
        purpose: "Request publish slot — returns presigned upload URL",
      },
      {
        step: "2",
        method: "PUT",
        endpoint: "{presigned_upload_url}",
        purpose: "Upload HTML content",
      },
      {
        step: "3",
        method: "POST",
        endpoint: "{finalize_url}",
        purpose: "Finalize the publish — makes page live",
      },
      {
        step: "4",
        method: "GET",
        endpoint: "{site_url}",
        purpose: "Verify page is live",
      },
    ],
  },

  moltbook: {
    nativeSignup: "yes",
    nativeSignupNote:
      "POST /api/v1/agents/register returns a working API key instantly — full programmatic signup. The claim flow (email + tweet) is a separate one-time ownership verification layer, not a signup blocker.",
    humanSetup: {
      required: true,
      steps: [
        "Provide an email address the agent can use for the claim",
        "Post one verification tweet from the owner's X/Twitter account (text is pre-generated)",
        "Complete X OAuth connect (read-only) so Moltbook can detect the tweet",
      ],
    },
    inputs: [
      {
        name: "email",
        description: "Owner's email address — receives the claim verification link",
        when: "pre-setup",
      },
      {
        name: "twitter_account",
        description: "Owner's X/Twitter handle — must post the one-time verification tweet",
        when: "pre-setup",
      },
      {
        name: "submolt_name",
        description: "Community/submolt to post in (e.g. 'general')",
        when: "runtime",
      },
      {
        name: "title",
        description: "Post title",
        when: "runtime",
      },
      {
        name: "content",
        description: "Post body content",
        when: "runtime",
      },
    ],
    apiCalls: [
      {
        step: "1",
        method: "POST",
        endpoint: "https://www.moltbook.com/api/v1/agents/register",
        purpose: "Register agent — returns API key",
      },
      {
        step: "2",
        method: "POST",
        endpoint: "https://www.moltbook.com/api/v1/agents/verify-email",
        purpose: "Trigger claim email to owner's address",
      },
      {
        step: "3",
        method: "GET",
        endpoint: "{email_verification_link}",
        purpose: "Confirm email ownership (link from inbox)",
      },
      {
        step: "4 (human)",
        method: "—",
        endpoint: "twitter.com/intent/tweet",
        purpose: "Owner posts verification tweet from X account",
      },
      {
        step: "5",
        method: "GET",
        endpoint: "https://www.moltbook.com/api/v1/agents/me",
        purpose: "Verify API key persists post-claim",
      },
      {
        step: "6",
        method: "POST",
        endpoint: "https://www.moltbook.com/api/v1/posts",
        purpose: "Create post",
      },
      {
        step: "7",
        method: "POST",
        endpoint: "https://www.moltbook.com/api/v1/posts/{id}/comments",
        purpose: "Comment on post",
      },
      {
        step: "8",
        method: "POST",
        endpoint: "https://www.moltbook.com/api/v1/posts/{id}/upvote",
        purpose: "Upvote post",
      },
    ],
  },

  signbee: {
    nativeSignup: "no",
    nativeSignupNote:
      "No programmatic signup API. Account and API key must be created at signbee.com dashboard. Without an API key, each send triggers an email OTP the agent cannot solve.",
    humanSetup: {
      required: true,
      steps: [
        "Go to signbee.com and create an account",
        "Navigate to the API Keys section in the dashboard",
        "Create a new API key and copy it into SIGNBEE_API_KEY in the agent's config",
      ],
    },
    inputs: [
      {
        name: "SIGNBEE_API_KEY",
        description: "API key from signbee.com dashboard — required for all calls",
        when: "pre-setup",
      },
      {
        name: "recipient_name",
        description: "Full name of the document recipient",
        when: "runtime",
      },
      {
        name: "recipient_email",
        description: "Email address of the document recipient",
        when: "runtime",
      },
      {
        name: "markdown",
        description: "Document content in Markdown format",
        when: "runtime",
      },
    ],
    apiCalls: [
      {
        step: "1",
        method: "POST",
        endpoint: "https://signb.ee/api/v1/send",
        purpose: "Send document — returns document_id, status: pending_recipient",
      },
      {
        step: "2",
        method: "GET",
        endpoint: "https://signb.ee/api/v1/documents/{id}",
        purpose: "Check document status to verify persistence",
      },
    ],
  },

  "browser-use": {
    nativeSignup: "no",
    nativeSignupNote:
      "No programmatic signup API. Account must be created at cloud.browser-use.com with email verification. API key is then copied from the dashboard.",
    humanSetup: {
      required: true,
      steps: [
        "Go to cloud.browser-use.com and sign up",
        "Verify your email address via the confirmation email",
        "Navigate to Settings → API Keys and create a new key",
        "Copy the key into BROWSER_USE_API_KEY in the agent's config",
      ],
    },
    inputs: [
      {
        name: "BROWSER_USE_API_KEY",
        description: "API key from cloud.browser-use.com dashboard — required for all calls",
        when: "pre-setup",
      },
      {
        name: "task",
        description: "Natural language description of the browser automation task",
        when: "runtime",
      },
    ],
    apiCalls: [
      {
        step: "1",
        method: "GET",
        endpoint: "https://api.browser-use.com/api/v3/sessions",
        purpose: "Verify API key is valid — lists existing sessions",
      },
      {
        step: "2",
        method: "POST",
        endpoint: "https://api.browser-use.com/api/v3/sessions",
        purpose: "Create browser automation session with task",
      },
      {
        step: "3",
        method: "GET",
        endpoint: "https://api.browser-use.com/api/v3/sessions/{id}",
        purpose: "Check session/task status",
      },
    ],
  },
};

export function getServiceRequirements(slug: string): ServiceRequirements | null {
  return requirements[slug] ?? null;
}
