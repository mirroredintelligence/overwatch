"""OperationOutcome error bodies and their exception mapping (R01).

Stub for the red commit (DEC-010).
"""

from fastapi import Response


def operation_outcome(
    status: int, code: str, diagnostics: str, expression: str | None = None
) -> Response:
    raise NotImplementedError("R01: operation_outcome is not built yet")
