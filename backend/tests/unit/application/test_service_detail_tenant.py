"""ReadServiceDetail refuses work with no tenant bound or another tenant's actor itself (DEC-1367).

The board it reads checks the same thing, so a test of the whole read cannot tell whether this use
case's own check is there. Here the board read is replaced by one that finds no service: without
the use case's own check the answer is NotFound, with it the answer is the tenancy refusal.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.application.actor import Actor
from overwatch.application.tenancy import TenancyError
from overwatch.application.use_cases.query_board import Board, QueryBoard
from overwatch.application.use_cases.service_detail import ReadServiceDetail
from overwatch.domain.codes import Role
from overwatch.domain.rules.pressure import Pressure

NOW = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)


def _actor(role: Role) -> Actor:
    return Actor(
        role=role,
        practitioner_id="p-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id="tenant-a",
    )


def _no_unit() -> Any:
    raise AssertionError("no unit of work may open")


@pytest.fixture
def empty_board(monkeypatch: pytest.MonkeyPatch) -> None:
    async def execute(self: QueryBoard, query: Any) -> Board:
        return Board(
            entries=(), pressure=next(iter(Pressure)), all_limited_or_worse=False, generated_at=NOW
        )

    monkeypatch.setattr(QueryBoard, "execute", execute)


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.ADVISOR_V2, Role.ANALYTICS_USER])
async def test_no_tenant_bound_is_refused_before_anything_is_read(
    empty_board: None, role: Role
) -> None:
    read = ReadServiceDetail(_no_unit, FixedClock(NOW))

    with pytest.raises(TenancyError):
        await read.execute(_actor(role), "svc-a")
