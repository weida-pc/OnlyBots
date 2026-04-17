"""Load and validate a JSON contract from disk into typed dataclasses.

Contracts live in verifier/contracts/{service_slug}.json and are hand-written
in v1 (no LLM generation yet — that's Phase 5).

Validation is strict: unknown fields, unknown step/assertion kinds, missing
required keys, and inconsistent produces/requires all raise ContractError.

Cross-test validation (new post-critique):
  - every `requires` key in persistence/workflow must be in signup's `produces`
  - duplicate step ids within a test are rejected
  - assertion step-refs must resolve to a step in the same test
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import (
    Contract, TestSpec, Sandbox,
    HttpStep, PutFileStep, InjectNonceStep, EnvSecretStep, WaitStep,
    HttpStatusOk, ArtifactPresent, ContentServesNonce,
)


class ContractError(ValueError):
    """Raised when a contract file is malformed or references unknown primitives."""
    pass


# Directory where hand-written contracts live. Resolved relative to the verifier
# package root so it works the same locally and on the deployed VM.
CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"


# ── Parse helpers ─────────────────────────────────────────────────────────────

_STEP_KIND_ALLOWED_FIELDS: dict[str, set[str]] = {
    "http": {"kind", "id", "method", "url", "headers", "body_json", "body_raw",
             "extract", "browser_fallback", "must_contain_artifact", "description"},
    "put_file": {"kind", "id", "url", "body_template", "content_type", "description"},
    "inject_nonce": {"kind", "id", "state_key", "prefix"},
    "env_secret": {"kind", "id", "env_var", "state_key", "required"},
    "wait": {"kind", "id", "seconds"},
}

_ASSERTION_KIND_ALLOWED_FIELDS: dict[str, set[str]] = {
    "http_status_ok": {"kind", "step", "description"},
    "artifact_present": {"kind", "artifact", "description"},
    "content_serves_nonce": {"kind", "step", "description"},
}


def _require_keys(d: dict, keys: list[str], ctx: str) -> None:
    for k in keys:
        if k not in d:
            raise ContractError(f"{ctx}: missing required key '{k}'")


def _reject_unknown(d: dict, allowed: set[str], ctx: str) -> None:
    extra = set(d.keys()) - allowed
    if extra:
        raise ContractError(f"{ctx}: unknown field(s) {sorted(extra)}; "
                            f"allowed: {sorted(allowed)}")


def _parse_step(raw: dict, ctx: str) -> Any:
    if not isinstance(raw, dict):
        raise ContractError(f"{ctx}: step must be a dict, got {type(raw).__name__}")
    _require_keys(raw, ["kind", "id"], ctx)
    kind = raw["kind"]
    if kind not in _STEP_KIND_ALLOWED_FIELDS:
        raise ContractError(f"{ctx}: unknown step kind '{kind}'; "
                            f"allowed: {sorted(_STEP_KIND_ALLOWED_FIELDS.keys())}")
    _reject_unknown(raw, _STEP_KIND_ALLOWED_FIELDS[kind], f"{ctx} ({kind})")

    if kind == "http":
        _require_keys(raw, ["method", "url"], ctx)
        method = raw["method"]
        if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            raise ContractError(f"{ctx}: unknown HTTP method '{method}'")
        return HttpStep(
            kind="http", id=raw["id"], method=method, url=raw["url"],
            headers=raw.get("headers", {}) or {},
            body_json=raw.get("body_json"),
            body_raw=raw.get("body_raw"),
            extract=raw.get("extract", {}) or {},
            browser_fallback=bool(raw.get("browser_fallback", False)),
            must_contain_artifact=raw.get("must_contain_artifact"),
            description=raw.get("description", ""),
        )
    if kind == "put_file":
        _require_keys(raw, ["url", "body_template"], ctx)
        return PutFileStep(
            kind="put_file", id=raw["id"], url=raw["url"],
            body_template=raw["body_template"],
            content_type=raw.get("content_type", "text/html"),
            description=raw.get("description", ""),
        )
    if kind == "inject_nonce":
        _require_keys(raw, ["state_key"], ctx)
        return InjectNonceStep(
            kind="inject_nonce", id=raw["id"], state_key=raw["state_key"],
            prefix=raw.get("prefix", "onlybots-verify"),
        )
    if kind == "env_secret":
        _require_keys(raw, ["env_var", "state_key"], ctx)
        return EnvSecretStep(
            kind="env_secret", id=raw["id"], env_var=raw["env_var"],
            state_key=raw["state_key"], required=bool(raw.get("required", True)),
        )
    if kind == "wait":
        _require_keys(raw, ["seconds"], ctx)
        return WaitStep(kind="wait", id=raw["id"], seconds=float(raw["seconds"]))
    raise ContractError(f"{ctx}: unreachable kind '{kind}'")


def _parse_assertion(raw: dict, ctx: str) -> Any:
    if not isinstance(raw, dict):
        raise ContractError(f"{ctx}: assertion must be a dict")
    _require_keys(raw, ["kind"], ctx)
    kind = raw["kind"]
    if kind not in _ASSERTION_KIND_ALLOWED_FIELDS:
        raise ContractError(f"{ctx}: unknown assertion kind '{kind}'; "
                            f"allowed: {sorted(_ASSERTION_KIND_ALLOWED_FIELDS.keys())}")
    _reject_unknown(raw, _ASSERTION_KIND_ALLOWED_FIELDS[kind], f"{ctx} ({kind})")

    if kind == "http_status_ok":
        _require_keys(raw, ["step"], ctx)
        return HttpStatusOk(kind="http_status_ok", step=raw["step"],
                            description=raw.get("description", ""))
    if kind == "artifact_present":
        _require_keys(raw, ["artifact"], ctx)
        return ArtifactPresent(kind="artifact_present", artifact=raw["artifact"],
                                description=raw.get("description", ""))
    if kind == "content_serves_nonce":
        _require_keys(raw, ["step"], ctx)
        return ContentServesNonce(kind="content_serves_nonce", step=raw["step"],
                                   description=raw.get("description", ""))
    raise ContractError(f"{ctx}: unreachable assertion kind '{kind}'")


def _parse_test(raw: dict, ctx: str) -> TestSpec:
    if not isinstance(raw, dict):
        raise ContractError(f"{ctx}: test must be a dict")
    _reject_unknown(raw, {"steps", "assertions", "produces", "requires"}, ctx)
    steps_raw = raw.get("steps", [])
    asserts_raw = raw.get("assertions", [])
    produces_raw = raw.get("produces", []) or []
    requires_raw = raw.get("requires", []) or []
    if not isinstance(steps_raw, list):
        raise ContractError(f"{ctx}.steps must be a list")
    if not isinstance(asserts_raw, list):
        raise ContractError(f"{ctx}.assertions must be a list")
    if not isinstance(produces_raw, list):
        raise ContractError(f"{ctx}.produces must be a list of state keys")
    if not isinstance(requires_raw, list):
        raise ContractError(f"{ctx}.requires must be a list of state keys")

    # Check step ids are unique
    ids = [s.get("id") for s in steps_raw if isinstance(s, dict)]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ContractError(f"{ctx}: duplicate step ids {sorted(dup)}")

    steps = [_parse_step(s, f"{ctx}.steps[{i}]") for i, s in enumerate(steps_raw)]
    assertions = [_parse_assertion(a, f"{ctx}.assertions[{i}]")
                  for i, a in enumerate(asserts_raw)]

    # Cross-check: assertions that reference a step id must reference an existing one
    step_ids = {s.id for s in steps}
    for i, a in enumerate(assertions):
        ref = getattr(a, "step", None)
        if ref is not None and ref not in step_ids:
            raise ContractError(
                f"{ctx}.assertions[{i}] references step '{ref}' which is not in "
                f"this test (available: {sorted(step_ids)})")

    return TestSpec(steps=steps, assertions=assertions,
                     produces=list(produces_raw), requires=list(requires_raw))


def _validate_cross_test_dataflow(tests: dict[str, TestSpec], source: str) -> None:
    """Every requires in persistence/workflow must be in signup's produces
    (or in the same test's produces, for internally-wired state).
    """
    signup = tests.get("signup")
    signup_produces = set(signup.produces) if signup else set()

    for test_name in ("persistence", "workflow"):
        t = tests.get(test_name)
        if not t:
            continue
        own_produces = set(t.produces)
        for req in t.requires:
            if req not in signup_produces and req not in own_produces:
                raise ContractError(
                    f"{source}.tests.{test_name}.requires: '{req}' is not in "
                    f"signup.produces {sorted(signup_produces)} or "
                    f"{test_name}.produces {sorted(own_produces)}. Add it to "
                    f"signup's produces, or have this test produce it itself "
                    f"(e.g. via env_secret).")


# ── Public API ────────────────────────────────────────────────────────────────

def parse_contract(raw: dict, source: str = "<dict>") -> Contract:
    if not isinstance(raw, dict):
        raise ContractError(f"{source}: contract must be a JSON object")
    _reject_unknown(raw, {"schema_version", "service_slug", "allowed_env",
                           "sandbox", "tests", "notes"}, source)
    _require_keys(raw, ["schema_version", "service_slug", "tests"], source)

    version = raw["schema_version"]
    if version != 1:
        raise ContractError(f"{source}: unsupported schema_version {version} (need 1)")

    sandbox_raw = raw.get("sandbox", {}) or {}
    _reject_unknown(sandbox_raw, {"url_allowlist"}, f"{source}.sandbox")
    sandbox = Sandbox(
        url_allowlist=list(sandbox_raw.get("url_allowlist", []) or []),
    )

    tests_raw = raw.get("tests") or {}
    if not isinstance(tests_raw, dict):
        raise ContractError(f"{source}.tests must be a JSON object")
    for name in tests_raw.keys():
        if name not in ("signup", "persistence", "workflow"):
            raise ContractError(
                f"{source}.tests: unknown test name '{name}' "
                f"(allowed: signup, persistence, workflow)")
    tests = {name: _parse_test(spec, f"{source}.tests.{name}")
             for name, spec in tests_raw.items()}

    _validate_cross_test_dataflow(tests, source)

    return Contract(
        schema_version=1,
        service_slug=raw["service_slug"],
        allowed_env=list(raw.get("allowed_env", []) or []),
        sandbox=sandbox,
        tests=tests,
        notes=raw.get("notes", ""),
    )


def load_contract(slug: str, contracts_dir: Path | None = None) -> Contract | None:
    """Load and parse the contract for `slug`. Returns None if no file exists."""
    root = contracts_dir or CONTRACTS_DIR
    path = root / f"{slug}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ContractError(f"{path}: invalid JSON at {e.lineno}:{e.colno}: {e.msg}")
    return parse_contract(raw, source=str(path))


def has_contract(slug: str, contracts_dir: Path | None = None) -> bool:
    root = contracts_dir or CONTRACTS_DIR
    return (root / f"{slug}.json").exists()
