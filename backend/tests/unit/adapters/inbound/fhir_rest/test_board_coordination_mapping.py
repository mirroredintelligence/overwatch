"""The board answer with the coordination phone (W7A-B8): pure."""

from datetime import UTC, datetime

from diucs.adapters.inbound.fhir_rest.mapping import board_to_parameters
from diucs.application.use_cases.query_board import Board
from diucs.domain.rules.pressure import Pressure

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)


def _board() -> Board:
    return Board(entries=(), pressure=Pressure.NORMAL, all_limited_or_worse=False, generated_at=NOW)


def test_the_phone_is_a_string_part_before_the_generated_time() -> None:
    parts = board_to_parameters(_board(), coordination_phone="01234 567890")["parameter"]

    names = [part["name"] for part in parts]
    assert {"name": "coordinationPhone", "valueString": "01234 567890"} in parts
    assert names.index("coordinationPhone") < names.index("generatedAt")


def test_no_phone_sends_no_part() -> None:
    names = [part["name"] for part in board_to_parameters(_board())["parameter"]]

    assert "coordinationPhone" not in names
    assert names[-3:] == ["pressure", "allLimitedOrWorse", "generatedAt"]
