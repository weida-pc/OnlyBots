"""Contract schema — the shape every service contract must conform to.

A Contract describes three tests (signup, persistence, workflow). Each test is
a sequence of Steps (HTTP calls, file uploads, etc.) followed by a sequence of
Assertions that decide pass/fail against the recorded steps and state.

The vocabulary is deliberately tiny. Extending it should require two different
services to need the new primitive — otherwise we add inline logic somewhere
instead of polluting the vocabulary.

Step kinds (6):
  - http          : one HTTP request; optional extraction into state
  - put_file      : raw-bytes PUT (for presigned URLs)
  - inject_nonce  : mint a unique nonce; store under state[key]
  - env_secret    : load env var into state
  - wait          : sleep N seconds (for async API propagation)
  - shell         : escape hatch (requires contract.sandbox.shell_approved=true)

Assertion kinds (5):
  - http_status_ok       : named step's response status is 2xx
  - http_body_contains   : step's body contains a literal or artifact value
  - artifact_present     : named state artifact is non-empty
  - content_serves_nonce : a step did a resilient GET and found the nonce
  - auth_still_valid     : semantic alias — a step with credentials got 2xx
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# ── Step kinds ────────────────────────────────────────────────────────────────

StepKind = Literal["http", "put_file", "inject_nonce", "env_secret", "wait", "shell"]


@dataclass
class HttpStep:
    """One HTTP request, optionally extracting named values from the response."""
    kind: Literal["http"]
    id: str                                  # unique within the test; referenced by assertions
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
    url: str                                 # may contain {template} vars
    headers: dict[str, str] = field(default_factory=dict)
    body_json: Any = None                    # dict/list; templated recursively
    body_raw: str | None = None              # used when body isn't JSON (templated)
    extract: dict[str, str] = field(default_factory=dict)
    # Extract map: state_key -> JSONPath-ish expression. Supports
    # dotted paths with numeric indices and `||` fallback chains.
    # e.g. "upload.uploads.0.url || files.0.uploadUrl"
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


@dataclass
class WaitStep:
    kind: Literal["wait"]
    id: str
    seconds: float


@dataclass
class ShellStep:
    """Escape hatch. Disabled unless contract.sandbox.shell_approved == true.

    Not implemented in v1 — reserved so the schema doesn't need to change
    when we first encounter a service that genuinely needs it.
    """
    kind: Literal["shell"]
    id: str
    command: str
    timeout_s: float = 30.0


Step = HttpStep | PutFileStep | InjectNonceStep | EnvSecretStep | WaitStep | ShellStep


# ── Assertion kinds ───────────────────────────────────────────────────────────

@dataclass
class HttpStatusOk:
    kind: Literal["http_status_ok"]
    step: str                                # step id
    description: str = ""


@dataclass
class HttpBodyContains:
    kind: Literal["http_body_contains"]
    step: str
    needle: str | None = None                # literal to search for
    needle_artifact: str | None = None       # or state key holding the value
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
    content-publishing services honestly — and encoding it as three separate
    primitives (fetch + status_ok + body_contains) makes contracts unreadable.
    """
    kind: Literal["content_serves_nonce"]
    step: str                                # http step with browser_fallback=true
    description: str = ""


@dataclass
class AuthStillValid:
    """Semantic alias for http_status_ok when the step uses stored credentials.

    Generates clearer failure messages ('API key rejected' vs 'HTTP non-2xx').
    """
    kind: Literal["auth_still_valid"]
    step: str
    description: str = ""


Assertion = (HttpStatusOk | HttpBodyContains | ArtifactPresent
             | ContentServesNonce | AuthStillValid)


# ── Top-level ─────────────────────────────────────────────────────────────────

@dataclass
class TestSpec:
    steps: list[Step]
    assertions: list[Assertion]


@dataclass
class Sandbox:
    """Security constraints for this contract.

    url_allowlist: step URLs must match one of these host patterns after
      template substitution. Wildcards: '*.example.com' matches any subdomain.
    shell_approved: must be explicitly true to allow ShellStep execution.
    """
    url_allowlist: list[str] = field(default_factory=list)
    shell_approved: bool = False


@dataclass
class Contract:
    schema_version: int                      # must be 1
    service_slug: str
    allowed_env: list[str]                   # env vars EnvSecretStep may read
    sandbox: Sandbox
    tests: dict[str, TestSpec]               # keys: signup, persistence, workflow
    notes: str = ""                          # optional free-text rationale
