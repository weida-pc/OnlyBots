"""Base class for verification tests."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TestResult:
    """Result of a single verification test."""
    passed: bool
    confidence: float  # 0.0 – 1.0
    failure_reason: str | None = None
    evidence_artifacts: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


class BaseTest:
    """Interface every verification test must implement."""

    test_number: int
    test_name: str

    async def run(self, service: dict, state: dict, run_id: int) -> TestResult:
        """Execute the test.

        Args:
            service: Row dict from the services table (slug, name, url, signup_url, …).
            state: Mutable dict shared across tests in a single run.
                   Test 1 stores credentials here so Test 2+3 can reuse them.
            run_id: The verification_runs.id for evidence storage.

        Returns:
            TestResult with pass/fail, confidence, and evidence.
        """
        raise NotImplementedError
