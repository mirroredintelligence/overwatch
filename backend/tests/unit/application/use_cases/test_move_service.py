"""Moving services between phones (U38): the checks that run before any unit of work.

Every case here is refused before the store is used, so no Neo4j is needed; the factories are guards
that fail the test if they are opened. The moves, cover and additions against the graph are in
tests/integration/application/test_move_service.py. Sample values only.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.use_cases.move_service import StartServiceMove, StartServiceMoveCommand
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, ValidationFailed


class _Untouched:
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the store must not be used")


def _actor(role: Role) -> Actor:
    return Actor(
        role=role,
        practitioner_id="lead-1" if role is Role.LEAD else "reporter-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
    )


def _command(role: Role = Role.LEAD, mobile: str = "07700 900456") -> StartServiceMoveCommand:
    return StartServiceMoveCommand(
        actor=_actor(role),
        service_id="ucr-east",
        to_mobile=mobile,
        until=None,
    )


def _use_case() -> StartServiceMove:
    return StartServiceMove(_Untouched(), _Untouched(), _Untouched(), _Untouched())


async def test_a_reporter_cannot_start_a_move() -> None:
    with pytest.raises(NotAllowed):
        await _use_case().execute(_command(Role.REPORTER))


async def test_an_advisor_cannot_start_a_move() -> None:
    with pytest.raises(NotAllowed):
        await _use_case().execute(_command(Role.ADVISOR))


async def test_a_number_that_is_not_a_uk_mobile_is_refused_without_echoing_it() -> None:
    # The input is distinctive; the example number in the message shares some digits with
    # other inputs, so the check uses a value that appears nowhere else.
    with pytest.raises(ValidationFailed) as refused:
        await _use_case().execute(_command(mobile="07700 9001x9"))
    assert refused.value.field == "to_mobile"
    assert "9001x9" not in str(refused.value)


async def test_a_cover_that_ends_in_the_past_is_refused() -> None:
    now = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
    past = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    command = StartServiceMoveCommand(
        actor=_actor(Role.LEAD), service_id="ucr-east", to_mobile="07700 900456", until=past
    )
    use_case = StartServiceMove(_Untouched(), _Untouched(), FixedClock(now), _Untouched())
    with pytest.raises(ValidationFailed) as refused:
        await use_case.execute(command)
    assert refused.value.field == "until"
