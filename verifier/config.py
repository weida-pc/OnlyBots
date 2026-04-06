"""Verifier configuration — reads from environment or .env file."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
# Also load local .env if present
load_dotenv(Path(__file__).resolve().parent / ".env")

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://onlybots:onlybots@localhost:5432/onlybots"
)
EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR", "/opt/onlybots/evidence")
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
VERIFIER_VERSION = "0.3.0"

# ── API Keys ────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
CURSOR_API_KEY = os.environ.get("CURSOR_API_KEY", "")

# ── Agent Harnesses ─────────────────────────────────────────────────────────
# Each harness: (cli_command, model_flag, default_model, env_key_name)
HARNESSES = {
    "gemini": {
        "cmd": "gemini",
        "model_flag": "-m",
        "default_model": "gemini-3.1-pro-preview",
        "api_key_env": "GEMINI_API_KEY",
        "api_key": GEMINI_API_KEY,
    },
    "claude": {
        "cmd": "claude",
        "model_flag": "--model",
        "default_model": "sonnet",
        "api_key_env": "ANTHROPIC_API_KEY",
        "api_key": ANTHROPIC_API_KEY,
    },
    "codex": {
        "cmd": "codex",
        "model_flag": "--model",
        "default_model": "o4-mini",
        "api_key_env": "OPENAI_API_KEY",
        "api_key": OPENAI_API_KEY,
    },
    "openclaw": {
        "cmd": "openclaw",
        "model_flag": "--provider",
        "default_model": "gemini/gemini-3-flash",
        "api_key_env": "GEMINI_API_KEY",
        "api_key": GEMINI_API_KEY,
    },
    "cursor": {
        "cmd": "cursor",
        "model_flag": "--model",
        "default_model": "composer-2",
        "api_key_env": "CURSOR_API_KEY",
        "api_key": CURSOR_API_KEY,
    },
}

# ── Service → Harness mapping ───────────────────────────────────────────────
# Which harness+model to use for each service verification.
# Format: {slug: (harness_name, model_override_or_None)}
# Default: gemini with gemini-3.1-pro-preview
SERVICE_HARNESS_MAP = {
    "agentmail-to": ("gemini", "gemini-3-flash-preview"),
    "here-now": ("gemini", "gemini-3-flash-preview"),
    "moltbook": ("gemini", "gemini-3-flash-preview"),
    "signbee": ("gemini", "gemini-3-flash-preview"),
    "browser-use": ("gemini", "gemini-3-flash-preview"),
}
DEFAULT_HARNESS = ("gemini", "gemini-3-flash-preview")
