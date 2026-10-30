"""The consumer of the network board projector's subscription (TEN-058, DEC-547).

The governance events (`network.events`) carry the acting tenant as the message's tenant, checked
against the directory by `TenantBoundConsumer`; the network a board belongs to is the payload's
`network_id`, validated by the projector and confirmed against the registry when the board is
rebuilt (an unknown or inactive network is a permanent error). An event the board does not show is
acknowledged and builds nothing. No outcome reason holds a payload value.
"""

from typing import Any

import pytest

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.network_board_consumer import (
    NETWORK_BOARD_SUBSCRIPTION,
    NETWORK_EVENTS_TOPIC,
    NetworkBoardConsumer,
    network_board_consumer,
    network_board_runners,
)
from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.tenancy import current_scope_or_none
from diucs.domain.errors import NotFound, ValidationFailed
from tests.support.network_samples import MEMBER_B, NETWORK_ID
from tests.unit.adapters.inbound.workers.test_network_projector import _Tenants


class _Projector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], Any]] = []
        self.error: Exception | None = None

    async def handle(self, event_type: str, payload: Any) -> bool:
        self.calls.append((event_type, dict(payload), current_scope_or_none()))
        if self.error is not None:
            raise self.error
        return True


def _message(event_type: str = "GrantEnded", **payload: Any) -> BusMessage:
    return BusMessage(
        id="m-1",
        topic=NETWORK_EVENTS_TOPIC,
        event_type=event_type,
        payload={"network_id": NETWORK_ID, **payload},
        tenant_id=MEMBER_B,
    )


async def _handle(projector: _Projector, message: BusMessage) -> Outcome:
    consumer = network_board_consumer(projector, _Tenants([MEMBER_B]))  # type: ignore[arg-type]
    return await consumer.handle(message)


async def test_an_event_is_handed_to_the_projector_in_the_bound_tenants_scope() -> None:
    projector = _Projector()
    outcome = await _handle(projector, _message())
    assert outcome == Outcome("completed")
    [(event_type, payload, scope)] = projector.calls
    assert (event_type, payload["network_id"]) == ("GrantEnded", NETWORK_ID)
    assert (
        scope is not None and scope.value == MEMBER_B
    )  # the tenant of the message, not the network


async def test_an_unknown_tenant_is_dead_lettered_before_the_projector() -> None:
    projector = _Projector()
    consumer = network_board_consumer(projector, _Tenants([]))  # type: ignore[arg-type]
    outcome = await consumer.handle(_message())
    assert (outcome.kind, outcome.reason) == ("dead-letter", "tenant-unknown")
    assert projector.calls == []


async def test_the_consumer_alone_refuses_a_message_with_no_tenant_bound() -> None:
    outcome = await NetworkBoardConsumer(_Projector()).handle(_message())  # type: ignore[arg-type]
    assert outcome.kind == "dead-letter"


@pytest.mark.parametrize(
    ("error", "kind", "reason"),
    [
        (ValidationFailed("network_id", "is not a valid id"), "dead-letter", "message-invalid"),
        (NotFound("the network was not found"), "dead-letter", "network-unknown"),
        (ConnectionError("down"), "retry", "ConnectionError"),
    ],
)
async def test_a_failure_is_a_fixed_word_or_the_class_of_the_error(
    error: Exception, kind: str, reason: str
) -> None:
    projector = _Projector()
    projector.error = error
    outcome = await _handle(projector, _message())
    assert (outcome.kind, outcome.reason) == (kind, reason)


# the runner


def test_the_runner_reads_the_network_events_subscription_through_a_tenant_bound_consumer() -> None:
    [runner] = network_board_runners(None, _Projector(), _Tenants([MEMBER_B]))  # type: ignore[arg-type]
    assert (runner._entity, runner._subscription, runner._sessions) == (
        "network.events",
        NETWORK_BOARD_SUBSCRIPTION,
        False,
    )
    assert NETWORK_BOARD_SUBSCRIPTION == "network-board-projector"
    assert isinstance(runner._consumer, TenantBoundConsumer)
