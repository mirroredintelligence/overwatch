"""Service moves (P20): the record of a move, its open state and its refusals."""

from datetime import UTC, datetime

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.service_move import ServiceMove

UNTIL = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)
DONE = datetime(2026, 10, 25, 18, 30, tzinfo=UTC)


def _move(**changes: object) -> ServiceMove:
    fields: dict[str, object] = {
        "id": "move-1",
        "service_id": "svc-ucr-east",
        "from_practitioner_id": "p-1",
        "to_phone_hash": "h9",
        "until": UNTIL,
    }
    fields.update(changes)
    return ServiceMove(**fields)  # type: ignore[arg-type]


def test_a_new_move_is_open_and_holds_only_a_phone_hash() -> None:
    move = _move()

    assert move.is_open
    assert move.to_phone_hash == "h9"
    assert not hasattr(move, "to_phone")


def test_a_completed_move_is_not_open() -> None:
    assert not _move(completed_at=DONE).is_open


def test_a_cancelled_move_is_not_open() -> None:
    assert not _move(cancelled_at=DONE).is_open


@pytest.mark.parametrize("field", ["id", "service_id", "from_practitioner_id", "to_phone_hash"])
def test_a_move_needs_its_identifiers(field: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _move(**{field: " "})

    assert refused.value.field == field


def test_a_move_refuses_a_naive_time() -> None:
    with pytest.raises(ValidationFailed) as refused:
        _move(until=datetime(2026, 10, 25, 19, 0))

    assert refused.value.field == "until"


def test_a_move_is_completed_or_cancelled_not_both() -> None:
    with pytest.raises(ValidationFailed):
        _move(completed_at=DONE, cancelled_at=DONE)
