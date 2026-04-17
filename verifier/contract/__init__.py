"""Contract-driven verification framework.

Each service is described by a hand-written JSON contract that specifies what
HTTP calls to make and what assertions to check. The contract runner executes
the contract against a fresh state, returning steps + verdict in the same shape
the legacy per-service executors produced — so the rest of the verifier
(test files, DB, frontend) sees no difference.

See `verifier/contracts/here-now.json` for a reference contract.
"""
from .schema import Contract, TestSpec, Step, Assertion
from .loader import load_contract, has_contract
from .runner import run_test_steps, evaluate_verdict

__all__ = [
    "Contract", "TestSpec", "Step", "Assertion",
    "load_contract", "has_contract",
    "run_test_steps", "evaluate_verdict",
]
