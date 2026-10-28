"""Pure mapping between application results and FHIR resources for the FHIR API (R05).

Stub for the red commit (DEC-010): the names and signatures only.
"""

from typing import Any

from diucs.application.use_cases.query_board import Board
from diucs.domain.model.capacity import CapacityReport


def board_to_parameters(board: Board) -> dict[str, Any]:
    raise NotImplementedError


def report_to_fhir(report: CapacityReport) -> dict[str, Any]:
    raise NotImplementedError
