"""IdempotentConsumer and the tenant (TEN-025, DEC-130 item 7, DEC-165).

The tenant property of a bus message is unsigned (TEN-020 decision: signing needs a secret in every
publisher), so it is trusted for nothing until it has been checked, and what it says is checked
twice more after the directory has listed it: the scope bound for the work is the message's tenant,
and so is the scope of the unit of work that opens. A message whose tenant disagrees with either is
dead-lettered with `tenant-mismatch` before a unit opens, or before the message is marked processed,
so nothing is written under another tenant's scope and nothing is marked. No Docker: the unit of
work is a recording fake.
"""

from types import TracebackType
from typing import Any, Self

import pytest

from diucs.adapters.inbound.workers.consumer import (
    TENANT_MISMATCH,
    IdempotentConsumer,
    Outcome,
)
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.tenancy import ScopeId, bind_scope, bind_tenant

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


def _message(tenant: str = TENANT_A) -> BusMessage:
    return BusMessage(
        id="m-1",
        topic="capacity.events",
        event_type="CapacityReported",
        payload={},
        tenant_id=tenant,
    )


class _Processed:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def mark_if_new(self, message_id: str, consumer: str) -> bool:
        self._events.append("mark")
        return True


class _Unit:
    def __init__(self, events: list[str], scope: ScopeId | None) -> None:
        self.unit_scope = scope
        self.processed = _Processed(events)
        self._events = events

    async def __aenter__(self) -> Self:
        self._events.append("open")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self._events.append("commit")


def _consumer(events: list[str], unit_scope: ScopeId | None) -> IdempotentConsumer:
    async def handler(message: BusMessage, uow: Any) -> None:
        events.append("handler")

    return IdempotentConsumer(
        "board-projector",
        handler,
        lambda: _Unit(events, unit_scope),  # type: ignore[arg-type, return-value]
    )


async def test_a_message_for_the_bound_tenant_runs_and_commits() -> None:
    events: list[str] = []
    with bind_tenant(TENANT_A):
        outcome = await _consumer(events, ScopeId.tenant(TENANT_A)).handle(_message(TENANT_A))
    assert outcome == Outcome("completed")
    assert events == ["open", "mark", "handler", "commit"]


async def test_a_message_for_another_tenant_than_the_bound_one_opens_no_unit() -> None:
    events: list[str] = []
    with bind_tenant(TENANT_B):
        outcome = await _consumer(events, ScopeId.tenant(TENANT_B)).handle(_message(TENANT_A))
    assert outcome == Outcome("dead-letter", TENANT_MISMATCH)
    assert events == []


async def test_a_message_with_no_tenant_bound_opens_no_unit() -> None:
    events: list[str] = []
    outcome = await _consumer(events, None).handle(_message(TENANT_A))
    assert outcome == Outcome("dead-letter", TENANT_MISMATCH)
    assert events == []


async def test_a_network_scope_is_not_the_tenant_of_a_message() -> None:
    events: list[str] = []
    with bind_scope(ScopeId.network("net-members")):
        outcome = await _consumer(events, ScopeId.network("net-members")).handle(_message())
    assert outcome == Outcome("dead-letter", TENANT_MISMATCH)
    assert events == []


@pytest.mark.parametrize("unit_scope", [None, ScopeId.tenant(TENANT_B), ScopeId.network("net-x1")])
async def test_a_unit_that_opened_under_another_scope_marks_nothing_and_runs_nothing(
    unit_scope: ScopeId | None,
) -> None:
    events: list[str] = []
    with bind_tenant(TENANT_A):
        outcome = await _consumer(events, unit_scope).handle(_message(TENANT_A))
    assert outcome == Outcome("dead-letter", TENANT_MISMATCH)
    assert events == ["open"]


def test_the_reason_is_the_fixed_word_of_the_bus_contract() -> None:
    assert TENANT_MISMATCH == "tenant-mismatch"
