"""Contract schema — the shape every service contract must conform to.

A Contract describes three tests (signup, persistence, workflow). Each test is
a sequence of Steps (HTTP calls, file uploads, etc.) followed by a sequence of
Assertions that decide pass/fail against the recorded steps and state.

Tests declare `produces` (state keys they will write) and `requires` (state
keys they will read). The loader cross-validates: every key a later test
requires must appear in an earlier test's produces. This makes the data flow
between tests explicit, loader-checkable, and no longer punned through
convention.

The vocabulary is deliberately tiny (v1 post-critique):
  Step kinds (7):
    - http          : one HTTP request; optional extraction into state
    - put_file      : raw-bytes PUT (for presigned URLs)
    - inject_nonce  : mint a unique nonce; store under state[key]
    - env_secret    : load env var into state (gated by contract.allowed_env)
    - wait          : sleep N seconds (for async API propagation)
    - poll_until    : poll a URL until a JMESPath condition is truthy
    - receive_email : poll an AgentMail inbox until a matching message arrives

  Assertion kinds (3):
    - http_status_ok       : named step's response status is 2xx
    - artifact_present     : named state artifact is non-empty
    - content_serves_nonce : a step did a resilient GET and found the nonce

The shell step, http_body_contains, and auth_still_valid from the v1.0 draft
were removed in the post-critique revision: shell was speculative (no user),
http_body_contains had zero usage, auth_still_valid was sugar for
http_status_ok with cosmetically-different error text.

Extraction syntax is JMESPath (https://jmespath.org/). Array indexing uses
brackets: `upload.uploads[0].url`. Fallback chains use `||`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


StepKind = Literal["http", "put_file", "inject_nonce", "env_secret", "wait", "poll_until", "receive_email", "send_sms", "receive_sms"]


@dataclass
class HttpStep:
    """One HTTP request, optionally extracting named values from the response."""
    kind: Literal["http"]
    id: str                                  # unique within the test
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
    url: str                                 # may contain {template} vars
    headers: dict[str, str] = field(default_factory=dict)
    body_json: Any = None                    # dict/list; templated recursively
    body_raw: str | None = None              # used when body isn't JSON (templated)
    extract: dict[str, str] = field(default_factory=dict)
    # Extract map: state_key -> JMESPath expression. Fallback chains with ||.
    # e.g. "upload.uploads[0].url || files[0].uploadUrl"
    browser_fallback: bool = False           # if GET fails/blocked, escalate to curl_cffi
    must_contain_artifact: str | None = None # when browser_fallback=true, require nonce match
    description: str = ""                    # human-readable step label


@dataclass
class PutFileStep:
    """Raw-bytes PUT, typically to a presigned upload URL."""
    kind: Literal["put_file"]
    id: str
    url: str                                 # templated
    body_template: str                       # templated; encoded to UTF-8 bytes
    content_type: str = "text/html"          # templated
    description: str = ""


@dataclass
class InjectNonceStep:
    """Mint a new unique nonce and store it under state[key].

    Used to prove our specific content was served, not just that some 200
    came back. Pair with content_serves_nonce assertion.
    """
    kind: Literal["inject_nonce"]
    id: str
    state_key: str                           # where to store the nonce
    prefix: str = "onlybots-verify"          # nonce format: {prefix}-{hex16}
    description: str = ""


@dataclass
class EnvSecretStep:
    """Load an env var into state. Used for pre-provisioned API keys.

    The verifier only injects env vars whose names appear in contract.allowed_env.
    This prevents a contract from silently reading credentials it shouldn't see.
    """
    kind: Literal["env_secret"]
    id: str
    env_var: str                             # e.g. MOLTBOOK_API_KEY
    state_key: str                           # where to store the value
    required: bool = True                    # if false, missing env var is not an error
    description: str = ""


@dataclass
class WaitStep:
    kind: Literal["wait"]
    id: str
    seconds: float
    description: str = ""


@dataclass
class PollUntilStep:
    """Poll a URL until a JMESPath condition is truthy, or fail after max_attempts."""
    kind: Literal["poll_until"]
    id: str
    url: str                            # templated
    condition: str                      # JMESPath expression on parsed JSON response
    method: Literal["GET", "POST"] = "GET"
    headers: dict[str, str] = field(default_factory=dict)  # templated values
    body_json: Any = None               # templated recursively
    extract: dict[str, str] = field(default_factory=dict)  # JMESPath, run on final successful response
    interval_s: float = 5.0
    max_attempts: int = 12
    description: str = ""


@dataclass
class ReceiveEmailStep:
    """Poll an AgentMail inbox until a matching message arrives.

    match keys (all optional, ANDed):
      from_contains  — substring check on the From address/display name
      subject_regex  — Python regex applied to the Subject header
      body_contains  — substring check on the plain-text body

    extract map: state_key -> "regex:PATTERN" (first capture group from body)
                           or JMESPath expression (applied to the message JSON).

    Uses server-side ?after= filtering so only messages after step entry are
    considered. Falls back to client-side timestamp comparison as a guard.
    """
    kind: Literal["receive_email"]
    id: str
    inbox: str                      # templated — email address of the inbox to poll
    match: dict[str, str] = field(default_factory=dict)  # {from_contains?, subject_regex?, body_contains?}
    extract: dict[str, str] = field(default_factory=dict)  # {state_key: "regex:PATTERN" or JMESPath}
    interval_s: float = 3.0
    max_attempts: int = 20
    description: str = ""


@dataclass
class SendSmsStep:
    """Send an outbound SMS via Twilio using API key auth.

    Credentials are read from env: TWILIO_ACCOUNT_SID, TWILIO_API_KEY_SID,
    TWILIO_API_KEY_SECRET, TWILIO_PHONE_NUMBER. All must appear in
    contract.allowed_env. The target host (api.twilio.com) must be in
    contract.sandbox.url_allowlist.
    """
    kind: Literal["send_sms"]
    id: str
    to: str                                  # templated; E.164 format required
    body: str                                # templated
    description: str = ""


@dataclass
class ReceiveSmsStep:
    """Poll the twilio_inbound_sms DB table until a matching SMS arrives.

    Watches `to_number` (defaults to env TWILIO_PHONE_NUMBER) for messages
    arriving after step entry. All match filters are ANDed. Extract values
    are written to state for later steps/assertions.

    match keys (all optional, ANDed):
      from_contains  — substring check on from_number
      body_contains  — substring check on body
      body_regex     — Python re.search on body

    extract values:
      "regex:PATTERN" — first capture group from body
      "body"          — the SMS body text
      "from_number"   — sender number
      "received_at"   — ISO 8601 timestamp
    """
    kind: Literal["receive_sms"]
    id: str
    to_number: str = ""                      # templated; defaults to env TWILIO_PHONE_NUMBER
    match: dict[str, str] = field(default_factory=dict)
    extract: dict[str, str] = field(default_factory=dict)
    interval_s: float = 3.0
    max_attempts: int = 20
    description: str = ""


Step = HttpStep | PutFileStep | InjectNonceStep | EnvSecretStep | WaitStep | PollUntilStep | ReceiveEmailStep | SendSmsStep | ReceiveSmsStep


# ── Assertion kinds ───────────────────────────────────────────────────────────

@dataclass
class HttpStatusOk:
    kind: Literal["http_status_ok"]
    step: str                                # step id
    description: str = ""


@dataclass
class ArtifactPresent:
    kind: Literal["artifact_present"]
    artifact: str                            # state key that must be non-empty
    description: str = ""


@dataclass
class ContentServesNonce:
    """The named GET step (with browser_fallback) found the nonce in the body.

    This is the one compound assertion. It exists because "fetch a URL with
    escalation and verify our content served" is the only way to verify
    content-publishing services honestly — encoding it as three separate
    primitives (fetch + status_ok + body_contains) makes contracts unreadable.
    """
    kind: Literal["content_serves_nonce"]
    step: str                                # http step with browser_fallback=true
    description: str = ""


Assertion = HttpStatusOk | ArtifactPresent | ContentServesNonce


# ── Agent task (Phase 2 prototype) ────────────────────────────────────────────

@dataclass
class AgentTask:
    """Ask an LLM agent to perform the task itself, then have the verifier
    spot-check the artifacts it reports.

    The agent runs BEFORE the TestSpec's steps. Artifacts it reports are merged
    into state, so the existing step primitives can probe them exactly as they
    would artifacts extracted by a direct http step.

    Keeping this as an optional field means Phase 1 contracts (no agent_task)
    continue to run unchanged — the verifier drives. Phase 2 contracts add
    agent_task to have the agent drive.
    """
    prompt: str                              # task description (no output format — runtime adds that)
    expected_artifacts: list[str]            # keys the agent must return
    model: str = "gemini-2.5-flash"
    timeout_s: int = 180


# ── Top-level ─────────────────────────────────────────────────────────────────

@dataclass
class TestSpec:
    steps: list[Step]
    assertions: list[Assertion]
    # Data-flow declarations. The loader verifies at load time that:
    #   - every key in `requires` appears in an earlier test's `produces`
    #   - (advisory) every key in `produces` is actually written by at least
    #     one step's `extract` block or inject_nonce/env_secret step
    produces: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    # Phase 2: optional. If set, runs before `steps` and merges reported
    # artifacts into state. `steps` then act as verifier probes against
    # what the agent claims to have done.
    agent_task: AgentTask | None = None


@dataclass
class Sandbox:
    """Security constraints for this contract.

    url_allowlist: step URLs must match one of these host patterns. Wildcards:
      '*.example.com' matches any subdomain. An EMPTY allowlist fails closed —
      no URL is permitted. This is a change from the v1.0 draft (which treated
      empty as "no restriction, development mode") because that interpretation
      was security-theater code that lied to readers.

    NOTE: this check is a speed bump, not a real sandbox. It does not block:
      - IP literals (169.254.169.254, 127.0.0.1)
      - non-http schemes via curl_cffi
      - oversized request bodies
      - per-domain rate limits
    Real sandboxing lives in Phase 3. Until then, treat this allowlist as a
    typo-prevention check, not a security boundary.
    """
    url_allowlist: list[str] = field(default_factory=list)


@dataclass
class Contract:
    schema_version: int                      # must be 1
    service_slug: str
    allowed_env: list[str]                   # env vars EnvSecretStep may read
    sandbox: Sandbox
    tests: dict[str, TestSpec]               # keys: signup, persistence, workflow
    notes: str = ""                          # optional free-text rationale
