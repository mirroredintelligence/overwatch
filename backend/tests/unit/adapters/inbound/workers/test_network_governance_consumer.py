"""The consumer of the network projector's subscription of `network.events` (TEN-056, DEC-545 item
6): the tenant of the message is bound and checked against the directory, the handler is called
with the verified sender, and every failure is a fixed word or the class of an error."""

from typing import Any

import pytest

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.network_governance_consumer import (
    NETWORK_GOVERNANCE_SUBSCRIPTION,
    NetworkGovernanceConsumer,
    network_governance_consumer,
    network_governance_runners,
)
from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.tenancy import current_scope_or_none
from diucs.application.use_cases.network_governance import GovernanceOutcome
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed
from tests.support.network_samples import MEMBER_B, NETWORK_ID
from tests.unit.adapters.inbound.workers.test_network_projector import _Tenants


class _Governance:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, str, Any]] = []
        self.error: Exception | None = None

    async def handle(self, event_type: str, payload: Any, *, bus_tenant: str) -> GovernanceOutcome:
        self.calls.append((event_type, dict(payload), bus_tenant, current_scope_or_none()))
        if self.error is not None:
            raise self.error
        return GovernanceOutcome.HANDLED


def _message(event_type: str = "GrantEnded") -> BusMessage:
    return BusMessage(
        id="m-1",
        topic="network.events",
        event_type=event_type,
        payload={"network_id": NETWORK_ID},
        tenant_id=MEMBER_B,
    )


async def _handle(governance: _Governance, message: BusMessage) -> Outcome:
    consumer = network_governance_consumer(governance, _Tenants([MEMBER_B]))  # type: ignore[arg-type]
    return await consumer.handle(message)


async def test_the_event_is_handled_with_the_verified_sender_in_the_senders_scope() -> None:
    governance = _Governance()
    assert await _handle(governance, _message()) == Outcome("completed")
    [(event_type, payload, sender, scope)] = governance.calls
    assert (event_type, payload["network_id"], sender) == ("GrantEnded", NETWORK_ID, MEMBER_B)
    assert scope is not None and scope.value == MEMBER_B


async def test_an_unknown_tenant_is_dead_lettered_before_the_handler() -> None:
    governance = _Governance()
    consumer = network_governance_consumer(governance, _Tenants([]))  # type: ignore[arg-type]
    outcome = await consumer.handle(_message())
    assert (outcome.kind, outcome.reason) == ("dead-letter", "tenant-unknown")
    assert governance.calls == []


async def test_the_consumer_alone_refuses_a_message_with_no_tenant_bound() -> None:
    outcome = await NetworkGovernanceConsumer(_Governance()).handle(_message())
    assert outcome.kind == "dead-letter"


@pytest.mark.parametrize(
    ("error", "kind", "reason"),
    [
        (ValidationFailed("network_id", "is not a valid id"), "dead-letter", "message-invalid"),
        (NotFound("the grant was not found"), "dead-letter", "not-found"),
        (NotAllowed("the sender is not a party to this"), "dead-letter", "sender-mismatch"),
        (ConnectionError("down"), "retry", "ConnectionError"),
    ],
)
async def test_a_failure_is_a_fixed_word_or_the_class_of_the_error(
    error: Exception, kind: str, reason: str
) -> None:
    governance = _Governance()
    governance.error = error
    outcome = await _handle(governance, _message())
    assert (outcome.kind, outcome.reason) == (kind, reason)


async def test_no_outcome_reason_holds_the_text_of_an_error() -> None:
    governance = _Governance()
    governance.error = RuntimeError(f"secret {MEMBER_B} {NETWORK_ID}")
    outcome = await _handle(governance, _message())
    assert outcome.reason == "RuntimeError"


def test_the_runner_reads_the_network_events_subscription_of_the_projector() -> None:
    [runner] = network_governance_runners(None, _Governance(), _Tenants([MEMBER_B]))  # type: ignore[arg-type]
    assert (runner._entity, runner._subscription, runner._sessions) == (
        "network.events",
        NETWORK_GOVERNANCE_SUBSCRIPTION,
        False,
    )
    assert NETWORK_GOVERNANCE_SUBSCRIPTION == "network-projector"
    assert isinstance(runner._consumer, TenantBoundConsumer)
