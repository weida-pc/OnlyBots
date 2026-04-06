"""Evidence capture — screenshots and logs for each verification run."""
import os
import json
from pathlib import Path
from datetime import datetime, timezone
from config import EVIDENCE_DIR


def get_evidence_dir(run_id: int) -> Path:
    """Create and return the evidence directory for a run."""
    path = Path(EVIDENCE_DIR) / str(run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_screenshot(run_id: int, name: str, screenshot_bytes: bytes) -> str:
    """Save a screenshot and return its relative path."""
    evidence_dir = get_evidence_dir(run_id)
    filename = f"{name}.png"
    filepath = evidence_dir / filename
    filepath.write_bytes(screenshot_bytes)
    return str(filepath)


def save_log(run_id: int, name: str, content: str) -> str:
    """Save a text log and return its path."""
    evidence_dir = get_evidence_dir(run_id)
    filename = f"{name}.log"
    filepath = evidence_dir / filename
    filepath.write_text(content)
    return str(filepath)


def save_artifact(run_id: int, name: str, data: dict) -> str:
    """Save a JSON artifact and return its path."""
    evidence_dir = get_evidence_dir(run_id)
    filename = f"{name}.json"
    filepath = evidence_dir / filename
    filepath.write_text(json.dumps(data, indent=2, default=str))
    return str(filepath)
