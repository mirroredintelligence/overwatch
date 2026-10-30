"""The two-scope runner and the runners of the network projector (TEN-055, DEC-545).

The producer subscriptions bind the message's tenant (`TenantBoundConsumer`). The apply queue's
consumer binds a network scope for the handling of a message, so it declares `binds_network`; the
runner serves a consumer that declares either binding and refuses one that declares neither, and a
marker is the value `True` itself, not a truthy one. No Docker: runners are built over no client.
"""

from typing import ClassVar

import pytest

from diucs.adapters.inbound.workers.network_projector import (
    APPLY_QUEUE,
    NETWORK_SUBSCRIPTION,
    PRODUCER_CONSUMER_NAME,
    PRODUCER_EVENTS,
    NetworkApplyConsumer,
    network_runners,
)
from diucs.adapters.inbound.workers.servicebus_runner import (
    ConsumerNotTenantBound,
    ServiceBusRunner,
)
from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer
from diucs.application.ports.outbound.event_bus import QUEUES, TOPICS
from diucs.domain import events
from diucs.domain.events import PROJECTION_WORK
from tests.support.network_samples import MEMBER_B
from tests.unit.adapters.inbound.workers.test_network_projector import (
    _Apply,
    _Producer,
    _Registry,
    _Tenants,
)


class _Network:
    binds_network: ClassVar[bool] = True

    async def handle(self, message: object) -> object:
        raise AssertionError("not used")


class _Neither:
    async def handle(self, message: object) -> object:
        raise AssertionError("not used")


def _runner(consumer: object) -> ServiceBusRunner:
    return ServiceBusRunner(None, "projection.work", None, consumer)  # type: ignore[arg-type]


def test_a_consumer_that_binds_a_network_is_accepted() -> None:
    assert _runner(_Network()) is not None


def test_a_consumer_that_binds_neither_is_refused_when_the_runner_is_built() -> None:
    with pytest.raises(ConsumerNotTenantBound):
        _runner(_Neither())


def test_the_network_marker_cannot_be_claimed_by_a_truthy_value() -> None:
    class Truthy:
        binds_network = "yes"

        async def handle(self, message: object) -> object:
            raise AssertionError("not used")

    with pytest.raises(ConsumerNotTenantBound):
        _runner(Truthy())


def test_the_apply_consumer_declares_the_network_binding_and_not_the_tenant_one() -> None:
    consumer = NetworkApplyConsumer(_Apply(), _Registry(), _Tenants([MEMBER_B]))  # type: ignore[arg-type]
    assert consumer.binds_network is True
    assert getattr(consumer, "binds_tenant", False) is False
    assert _runner(consumer) is not None


# the runners of the projector


def _runners() -> list[ServiceBusRunner]:
    return network_runners(
        None,  # type: ignore[arg-type]
        _Producer(),  # type: ignore[arg-type]
        NetworkApplyConsumer(_Apply(), _Registry(), _Tenants([MEMBER_B])),  # type: ignore[arg-type]
        _Tenants([MEMBER_B]),
    )


def test_the_runners_are_the_four_producer_subscriptions_and_the_apply_queue() -> None:
    assert [(r._entity, r._subscription, r._sessions) for r in _runners()] == [
        ("capacity.events", NETWORK_SUBSCRIPTION, True),
        ("booking.events", NETWORK_SUBSCRIPTION, False),
        ("criteria.events", NETWORK_SUBSCRIPTION, False),
        ("registration.events", NETWORK_SUBSCRIPTION, False),
        (APPLY_QUEUE, None, False),
    ]
    assert NETWORK_SUBSCRIPTION == PRODUCER_CONSUMER_NAME == "network-projector"
    assert APPLY_QUEUE == PROJECTION_WORK


def test_the_producer_runners_bind_the_tenant_and_the_apply_runner_binds_the_network() -> None:
    *producers, apply = _runners()
    assert all(isinstance(r._consumer, TenantBoundConsumer) for r in producers)
    assert isinstance(apply._consumer, NetworkApplyConsumer)


def test_every_name_the_runners_read_is_a_known_topic_or_queue() -> None:
    for runner in _runners():
        if runner._subscription is None:
            assert runner._entity in QUEUES
        else:
            assert runner._entity in TOPICS


def test_every_producer_event_has_a_topic_the_projector_subscribes_to() -> None:
    topic_of = {cls.event_type: topic for cls, topic in events._TOPIC_BY_CLASS.items()}
    topics = {r._entity for r in _runners() if r._subscription is not None}
    for event_type in PRODUCER_EVENTS:
        assert topic_of[event_type] in topics
