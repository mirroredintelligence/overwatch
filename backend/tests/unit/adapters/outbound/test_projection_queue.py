"""The projection queue publisher (TEN-055, DEC-545, DEC-132 item 4).

A producer hands the publisher a `ProjectionRequested`; the publisher puts it on `projection.work`
as a message of the source tenant (the producer is bound to that tenant, and the bus refuses a
message for any other). The message id is derived from what the request says, so a producer that
runs twice for the same state sends the same id and the apply step's processed marker drops the
second. The message carries the allowlisted body and the request's identifiers, and no tenant or
network in a property other than the tenant property.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.outbound.projection_queue import (
    BusProjectionPublisher,
    projection_message,
    projection_message_id,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.event_bus import MAX_WIRE_ID_LENGTH, QUEUES, to_wire
from diucs.application.ports.outbound.projection import ProjectionPublisher
from diucs.application.projection import to_body
from diucs.application.tenancy import bind_network, bind_tenant
from diucs.domain.errors import ValidationFailed
from diucs.domain.events import PROJECTION_WORK, ProjectionRequested
from diucs.domain.model.network import GrantScope
from diucs.domain.rules.projection import PROJECTION_ALLOWLIST_VERSION
from tests.support.network_samples import MEMBER_B, NETWORK_ID, OTHER_NETWORK_ID, OWNER
from tests.support.projection_samples import (
    sample_capacity_projection,
    sample_criteria_projection,
)

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)


def _request(**changes: Any) -> ProjectionRequested:
    dto = sample_capacity_projection()
    fields: dict[str, Any] = {
        "network_id": NETWORK_ID,
        "source_tenant_id": MEMBER_B,
        "grant_id": "grant-capacity",
        "grant_version": 1,
        "kind": GrantScope.CAPACITY,
        "source_service_id": "svc-1",
        "source_version": dto.source_version,
        "allowlist_version": PROJECTION_ALLOWLIST_VERSION,
        "body": to_body(dto),
        "at": NOW,
    }
    fields.update(changes)
    return ProjectionRequested(**fields)


def _bus() -> ManualEventBus:
    return ManualEventBus(FixedClock(NOW))


def test_the_projection_queue_is_a_registered_queue() -> None:
    assert PROJECTION_WORK == "projection.work"
    assert PROJECTION_WORK in QUEUES


def test_the_publisher_is_the_port() -> None:
    publisher: ProjectionPublisher = BusProjectionPublisher(_bus())
    assert publisher is not None


async def test_a_request_is_enqueued_on_the_projection_queue_for_the_source_tenant() -> None:
    bus = _bus()
    request = _request()
    with bind_tenant(MEMBER_B):
        await BusProjectionPublisher(bus).publish(request)
    [message] = bus.enqueued_to(PROJECTION_WORK)
    assert message.tenant_id == MEMBER_B
    assert message.topic == PROJECTION_WORK
    assert message.event_type == "ProjectionRequested"
    assert message.session_id is None
    assert message.payload == request.to_payload()
    assert ProjectionRequested.decode(message.payload) == request
    assert bus.published == []  # a queue message, not a topic event


async def test_nothing_but_the_event_type_and_the_tenant_becomes_a_property() -> None:
    message = projection_message(_request())
    view = to_wire(message)
    assert dict(view.application_properties) == {
        "event_type": "ProjectionRequested",
        "tenantId": MEMBER_B,
    }
    assert NETWORK_ID not in view.message_id


async def test_the_message_is_refused_when_the_producer_is_bound_to_another_tenant() -> None:
    bus = _bus()
    with bind_tenant(OWNER), pytest.raises(ValidationFailed):
        await BusProjectionPublisher(bus).publish(_request())
    assert bus.enqueued_to(PROJECTION_WORK) == []


async def test_the_message_is_refused_from_a_network_binding() -> None:
    bus = _bus()
    with bind_network(NETWORK_ID), pytest.raises(ValidationFailed):
        await BusProjectionPublisher(bus).publish(_request())
    assert bus.enqueued_to(PROJECTION_WORK) == []


# the message id


def test_the_same_request_has_the_same_id_and_the_time_it_was_asked_is_not_part_of_it() -> None:
    later = datetime(2026, 10, 31, 9, 5, tzinfo=UTC)
    assert projection_message_id(_request()) == projection_message_id(_request(at=later))


@pytest.mark.parametrize(
    "changes",
    [
        {"network_id": OTHER_NETWORK_ID},
        {"source_tenant_id": OWNER},
        {"grant_id": "grant-other"},
        {"grant_version": 2},
        {"source_service_id": "svc-2"},
        {"source_version": 2},
        {"allowlist_version": PROJECTION_ALLOWLIST_VERSION + 1},
    ],
)
def test_a_change_of_anything_the_request_says_changes_the_id(changes: dict[str, Any]) -> None:
    assert projection_message_id(_request()) != projection_message_id(_request(**changes))


def test_the_kind_is_part_of_the_id() -> None:
    criteria = _request(
        kind=GrantScope.CRITERIA, body=to_body(sample_criteria_projection()), source_version=1
    )
    capacity_same_version = _request(source_version=1)
    assert projection_message_id(criteria) != projection_message_id(capacity_same_version)


def test_the_id_fits_the_wire_with_the_longest_tenant_and_holds_none_of_the_ids() -> None:
    request = _request(
        source_tenant_id="t" * 31,
        grant_id="g" * 64,
        source_service_id="s" * 64,
        network_id="net-" + "n" * 20,
    )
    message_id = projection_message_id(request)
    assert len(f"{'t' * 31}:{message_id}") <= MAX_WIRE_ID_LENGTH
    assert "g" * 8 not in message_id and "s" * 8 not in message_id
    assert to_wire(projection_message(request)).message_id.startswith("t" * 31 + ":")


async def test_two_runs_for_the_same_state_send_the_same_id() -> None:
    bus = _bus()
    publisher = BusProjectionPublisher(bus)
    with bind_tenant(MEMBER_B):
        await publisher.publish(_request())
        await publisher.publish(_request())
    first, second = bus.enqueued_to(PROJECTION_WORK)
    assert first.id == second.id
