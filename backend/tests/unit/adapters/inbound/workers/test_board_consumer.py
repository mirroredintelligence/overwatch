"""The board projector's consumer (TEN-039): the tenant is the message's, bound by
TenantBoundConsumer before the projector runs (I08), and a rebuild happens in that tenant's scope
only. The runners are the board-projector subscriptions of the two topics the board listens to.
No Docker and no Service Bus: the projector is a recorder and the runners are never started."""

from typing import Any

import pytest

from diucs.adapters.inbound.workers.board_consumer import (
    BOARD_SUBSCRIPTION,
    NOT_BOUND_REASON,
    BoardUpdateConsumer,
    board_consumer,
    board_runners,
)
from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.tenant_binding import (
    BAD_TENANT,
    UNKNOWN_TENANT,
    TenantBoundConsumer,
)
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.tenancy import bind_tenant, current_scope_or_none
from diucs.application.use_cases.board_projector import REBUILD_EVENTS
from tests.support.bus import message_with_tenant


class _Projector:
    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []
        self._raises = raises

    async def handle(self, event_type: str, payload: Any) -> bool:
        scope = current_scope_or_none()
        self.calls.append((event_type, dict(payload), None if scope is None else scope.value))
        if self._raises is not None:
            raise self._raises
        return event_type in REBUILD_EVENTS


def _message(tenant: str = "tenant-a", event_type: str = "StatusChanged") -> BusMessage:
    return BusMessage(
        id="m-1",
        topic="capacity.events",
        event_type=event_type,
        payload={"service_id": "svc-1", "at": "2026-10-23T13:12:00Z"},
        session_id="svc-1",
        tenant_id=tenant,
    )


async def test_a_rebuild_runs_in_the_scope_of_the_messages_tenant() -> None:
    projector = _Projector()
    consumer = board_consumer(projector, StaticTenants(["tenant-a", "tenant-b"]))  # type: ignore[arg-type]

    outcome = await consumer.handle(_message("tenant-b"))

    assert outcome == Outcome("completed")
    assert projector.calls == [
        ("StatusChanged", {"service_id": "svc-1", "at": "2026-10-23T13:12:00Z"}, "tenant-b")
    ]


async def test_the_consumer_is_the_tenant_binder_around_the_board_consumer() -> None:
    consumer = board_consumer(_Projector(), StaticTenants(["tenant-a"]))  # type: ignore[arg-type]

    assert isinstance(consumer, TenantBoundConsumer)
    assert isinstance(consumer._inner, BoardUpdateConsumer)


async def test_a_tenant_the_directory_does_not_list_is_dead_lettered_and_nothing_is_rebuilt() -> (
    None
):
    projector = _Projector()
    consumer = board_consumer(projector, StaticTenants(["tenant-a"]))  # type: ignore[arg-type]

    outcome = await consumer.handle(_message("tenant-b"))

    assert outcome == Outcome("dead-letter", UNKNOWN_TENANT)
    assert projector.calls == []


async def test_a_message_with_a_network_id_as_its_tenant_is_dead_lettered() -> None:
    projector = _Projector()
    consumer = board_consumer(projector, StaticTenants(["tenant-a"]))  # type: ignore[arg-type]
    message = message_with_tenant(
        "net-abcd1234", id="m-1", topic="capacity.events", event_type="StatusChanged"
    )

    assert await consumer.handle(message) == Outcome("dead-letter", BAD_TENANT)
    assert projector.calls == []


@pytest.mark.parametrize("event_type", ["AlertRaised", "RegistrationSubmitted", "Unknown"])
async def test_an_event_the_board_does_not_show_is_completed_and_changes_nothing(
    event_type: str,
) -> None:
    projector = _Projector()
    consumer = board_consumer(projector, StaticTenants(["tenant-a"]))  # type: ignore[arg-type]

    assert await consumer.handle(_message(event_type=event_type)) == Outcome("completed")


@pytest.mark.parametrize("event_type", sorted(REBUILD_EVENTS))
async def test_every_event_the_board_shows_is_rebuilt(event_type: str) -> None:
    projector = _Projector()
    consumer = board_consumer(projector, StaticTenants(["tenant-a"]))  # type: ignore[arg-type]

    await consumer.handle(_message(event_type=event_type))

    assert [call[0] for call in projector.calls] == [event_type]


async def test_a_failed_rebuild_is_retried_and_names_only_the_error_class() -> None:
    projector = _Projector(raises=ConnectionError("SECRET-CACHE-TEXT"))
    consumer = board_consumer(projector, StaticTenants(["tenant-a"]))  # type: ignore[arg-type]

    outcome = await consumer.handle(_message())

    assert outcome == Outcome("retry", "ConnectionError")


async def test_the_inner_consumer_refuses_a_message_when_no_tenant_is_bound() -> None:
    projector = _Projector()

    outcome = await BoardUpdateConsumer(projector).handle(_message())  # type: ignore[arg-type]

    assert outcome == Outcome("dead-letter", NOT_BOUND_REASON)
    assert projector.calls == []


async def test_the_inner_consumer_refuses_a_message_for_another_tenant_than_the_bound_one() -> None:
    projector = _Projector()

    with bind_tenant("tenant-b"):
        outcome = await BoardUpdateConsumer(projector).handle(_message("tenant-a"))  # type: ignore[arg-type]

    assert outcome == Outcome("dead-letter", NOT_BOUND_REASON)
    assert projector.calls == []


def test_the_runners_are_the_board_projector_subscriptions_and_each_binds_the_tenant() -> None:
    runners = board_runners(None, _Projector(), StaticTenants(["tenant-a"]))  # type: ignore[arg-type]

    assert [(r._entity, r._subscription, r._sessions) for r in runners] == [
        ("capacity.events", BOARD_SUBSCRIPTION, True),
        ("booking.events", BOARD_SUBSCRIPTION, False),
    ]
    assert BOARD_SUBSCRIPTION == "board-projector"
    assert all(isinstance(r._consumer, TenantBoundConsumer) for r in runners)
