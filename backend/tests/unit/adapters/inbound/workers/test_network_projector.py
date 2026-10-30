"""The network projector's two consumers (TEN-054, DEC-543, DEC-130 item 7, DEC-132 item 4).

The producer consumer runs inside `TenantBoundConsumer`: the tenant is bound from the message
property after the directory has listed it as active, and the events it understands name the
projection kinds to refresh. The apply consumer takes a `ProjectionRequested` message: the tenant
property is the source tenant (checked against the directory and against the payload), and the
network it binds is the payload's, but only after the registry says that network exists and is
active. Neither takes a tenant or a network from anywhere else, and no outcome reason holds a
payload value. The use cases are stubs here.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.inbound.workers.network_projector import (
    PRODUCER_CONSUMER_NAME,
    PRODUCER_EVENTS,
    NetworkApplyConsumer,
    NetworkProducerConsumer,
    producer_consumer,
)
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.network import RegisteredNetwork
from diucs.application.projection import to_body
from diucs.application.tenancy import ScopeKind, bind_tenant, current_scope_or_none
from diucs.application.use_cases.apply_projection import (
    ApplyOutcome,
    ApplyResult,
    ProjectionMismatch,
)
from diucs.application.use_cases.project_network import ProjectionRun
from diucs.domain.events import ProjectionRejectReason, ProjectionRequested
from diucs.domain.model.network import GrantScope, NetworkStatus
from diucs.domain.rules.projection import PROJECTION_ALLOWLIST_VERSION
from tests.support.network_samples import MEMBER_B, NETWORK_ID, SETTINGS, make_network
from tests.support.projection_samples import sample_capacity_projection

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
C, D, K = GrantScope.CAPACITY, GrantScope.DIRECTORY, GrantScope.CRITERIA


class _Producer:
    def __init__(self) -> None:
        self.calls: list[tuple[GrantScope, str, Any]] = []
        self.error: Exception | None = None

    async def project(self, kind: GrantScope, service_id: str) -> ProjectionRun:
        self.calls.append((kind, service_id, current_scope_or_none()))
        if self.error is not None:
            raise self.error
        return ProjectionRun(1, 0)


class _Tenants:
    def __init__(self, active: list[str]) -> None:
        self._active = active
        self.error: Exception | None = None

    async def active_tenant_ids(self) -> list[str]:
        if self.error is not None:
            raise self.error
        return self._active


def _event(event_type: str, **payload: Any) -> BusMessage:
    return BusMessage(
        id="m-1",
        topic="capacity.events",
        event_type=event_type,
        payload=payload,
        tenant_id=MEMBER_B,
    )


# The events


def test_the_events_the_producer_understands_name_the_kinds_to_refresh() -> None:
    assert dict(PRODUCER_EVENTS) == {
        "CapacityReported": (C,),
        "StatusChanged": (C,),
        "BookingResponded": (C,),
        "BookingExpired": (C,),
        "CriteriaApproved": (K,),
        "RegistrationApproved": (D, C, K),
        "ServiceDirectoryChanged": (D, C),
    }
    assert PRODUCER_CONSUMER_NAME == "network-projector"


@pytest.mark.parametrize(("event_type", "kinds"), sorted(PRODUCER_EVENTS.items()))
async def test_an_event_projects_its_service_for_each_kind_in_the_message_tenants_scope(
    event_type: str, kinds: tuple[GrantScope, ...]
) -> None:
    producer = _Producer()
    with bind_tenant(MEMBER_B):
        outcome = await NetworkProducerConsumer(producer).handle(  # type: ignore[arg-type]
            _event(event_type, service_id="svc-1")
        )
    assert outcome.kind == "completed"
    assert [(kind, sid) for kind, sid, _ in producer.calls] == [(k, "svc-1") for k in kinds]
    assert all(
        scope.kind is ScopeKind.TENANT and scope.value == MEMBER_B for _, _, scope in producer.calls
    )


async def test_an_event_the_projector_does_not_follow_is_completed_and_does_nothing() -> None:
    producer = _Producer()
    with bind_tenant(MEMBER_B):
        outcome = await NetworkProducerConsumer(producer).handle(  # type: ignore[arg-type]
            _event("AlertRaised", service_id="svc-1")
        )
    assert outcome.kind == "completed" and producer.calls == []


@pytest.mark.parametrize(
    "payload", [{}, {"service_id": 7}, {"service_id": ""}, {"service_id": None}]
)
async def test_a_followed_event_with_no_service_is_dead_lettered_with_a_fixed_word(
    payload: dict[str, Any],
) -> None:
    producer = _Producer()
    with bind_tenant(MEMBER_B):
        outcome = await NetworkProducerConsumer(producer).handle(  # type: ignore[arg-type]
            _event("CapacityReported", **payload)
        )
    assert (outcome.kind, outcome.reason) == ("dead-letter", "service-missing")
    assert producer.calls == []


async def test_a_failure_is_a_retry_that_names_the_class_and_never_the_text() -> None:
    producer = _Producer()
    producer.error = RuntimeError("could not read the board of Ms Jane Smith")
    with bind_tenant(MEMBER_B):
        outcome = await NetworkProducerConsumer(producer).handle(  # type: ignore[arg-type]
            _event("CapacityReported", service_id="svc-1")
        )
    assert (outcome.kind, outcome.reason) == ("retry", "RuntimeError")


async def test_the_producer_consumer_refuses_a_message_that_is_not_bound_to_its_tenant() -> None:
    producer = _Producer()
    consumer = NetworkProducerConsumer(producer)  # type: ignore[arg-type]
    outcome = await consumer.handle(_event("CapacityReported", service_id="svc-1"))
    assert outcome.kind == "dead-letter"
    with bind_tenant("tenant-c"):
        outcome = await consumer.handle(_event("CapacityReported", service_id="svc-1"))
    assert outcome.kind == "dead-letter" and producer.calls == []


async def test_the_wrapped_producer_binds_the_tenant_after_the_directory_lists_it() -> None:
    producer = _Producer()
    wrapped = producer_consumer(producer, _Tenants([MEMBER_B]))  # type: ignore[arg-type]
    outcome = await wrapped.handle(_event("CapacityReported", service_id="svc-1"))
    assert outcome.kind == "completed" and len(producer.calls) == 1
    unknown = producer_consumer(_Producer(), _Tenants(["tenant-c"]))  # type: ignore[arg-type]
    outcome = await unknown.handle(_event("CapacityReported", service_id="svc-1"))
    assert (outcome.kind, outcome.reason) == ("dead-letter", "tenant-unknown")


# The apply consumer


class _Apply:
    def __init__(self) -> None:
        self.calls: list[tuple[ProjectionRequested, str, str, Any]] = []
        self.result = ApplyResult(ApplyOutcome.APPLIED)
        self.error: Exception | None = None

    async def execute(
        self, request: ProjectionRequested, *, message_id: str, source_tenant_id: str
    ) -> ApplyResult:
        self.calls.append((request, message_id, source_tenant_id, current_scope_or_none()))
        if self.error is not None:
            raise self.error
        return self.result


class _Registry:
    def __init__(self, status: NetworkStatus | None = NetworkStatus.ACTIVE) -> None:
        self.status = status
        self.asked: list[str] = []
        self.error: Exception | None = None

    async def get_network(self, network_id: str) -> RegisteredNetwork | None:
        self.asked.append(network_id)
        if self.error is not None:
            raise self.error
        if self.status is None:
            return None
        return RegisteredNetwork(make_network(self.status), SETTINGS)


def _request(**changes: Any) -> ProjectionRequested:
    dto = sample_capacity_projection()
    fields: dict[str, Any] = {
        "network_id": NETWORK_ID,
        "source_tenant_id": MEMBER_B,
        "grant_id": "grant-capacity",
        "grant_version": 1,
        "kind": C,
        "source_service_id": "svc-1",
        "source_version": dto.source_version,
        "allowlist_version": PROJECTION_ALLOWLIST_VERSION,
        "body": to_body(dto),
        "at": NOW,
    }
    fields.update(changes)
    return ProjectionRequested(**fields)


def _message(request: ProjectionRequested | None = None, **changes: Any) -> BusMessage:
    request = request or _request()
    fields: dict[str, Any] = {
        "id": "m-9",
        "topic": "projection.work",
        "event_type": "ProjectionRequested",
        "payload": request.to_payload(),
        "tenant_id": request.source_tenant_id,
    }
    fields.update(changes)
    return BusMessage(**fields)


def _consumer(
    apply: _Apply | None = None,
    registry: _Registry | None = None,
    tenants: _Tenants | None = None,
) -> tuple[NetworkApplyConsumer, _Apply, _Registry, _Tenants]:
    apply = apply or _Apply()
    registry = registry or _Registry()
    tenants = tenants or _Tenants([MEMBER_B])
    return NetworkApplyConsumer(apply, registry, tenants), apply, registry, tenants  # type: ignore[arg-type]


async def test_a_message_is_applied_in_the_network_scope_with_the_verified_source() -> None:
    consumer, apply, registry, _ = _consumer()
    outcome = await consumer.handle(_message())
    assert outcome.kind == "completed"
    [(request, message_id, source, scope)] = apply.calls
    assert request == _request()
    assert (message_id, source) == ("m-9", MEMBER_B)
    assert scope.kind is ScopeKind.NETWORK and scope.value == NETWORK_ID
    assert registry.asked == [NETWORK_ID]
    assert current_scope_or_none() is None  # the binding is gone with the message


@pytest.mark.parametrize(
    "result",
    [
        ApplyResult(ApplyOutcome.DUPLICATE),
        ApplyResult(ApplyOutcome.STALE),
        ApplyResult(ApplyOutcome.REJECTED, ProjectionRejectReason.GRANT_NOT_EFFECTIVE),
    ],
)
async def test_a_duplicate_a_stale_and_a_rejected_message_are_acknowledged_not_retried(
    result: ApplyResult,
) -> None:
    apply = _Apply()
    apply.result = result
    consumer, *_ = _consumer(apply)
    assert (await consumer.handle(_message())).kind == "completed"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"payload": {"network_id": NETWORK_ID}}, "message-invalid"),
        ({"payload": {}}, "message-invalid"),
        ({"tenant_id": "tenant-c"}, "source-mismatch"),
    ],
)
async def test_a_message_that_cannot_be_what_it_says_is_dead_lettered_and_applies_nothing(
    changes: dict[str, Any], reason: str
) -> None:
    consumer, apply, registry, _ = _consumer()
    outcome = await consumer.handle(_message(**changes))
    assert (outcome.kind, outcome.reason) == ("dead-letter", reason)
    assert apply.calls == [] and registry.asked == []


async def test_a_source_tenant_the_directory_does_not_list_is_dead_lettered() -> None:
    consumer, apply, registry, _ = _consumer(tenants=_Tenants(["tenant-c"]))
    outcome = await consumer.handle(_message())
    assert (outcome.kind, outcome.reason) == ("dead-letter", "tenant-unknown")
    assert apply.calls == [] and registry.asked == []


@pytest.mark.parametrize(
    "status", [None, NetworkStatus.SUSPENDED, NetworkStatus.CLOSED, NetworkStatus.DRAFT]
)
async def test_a_network_that_is_missing_or_not_active_is_dead_lettered_and_never_bound(
    status: NetworkStatus | None,
) -> None:
    consumer, apply, _, _ = _consumer(registry=_Registry(status))
    outcome = await consumer.handle(_message())
    assert (outcome.kind, outcome.reason) == ("dead-letter", "network-unknown")
    assert apply.calls == []


async def test_a_mismatch_from_the_use_case_is_dead_lettered_with_a_fixed_word() -> None:
    apply = _Apply()
    apply.error = ProjectionMismatch("the payload of Ms Jane Smith")
    consumer, *_ = _consumer(apply)
    outcome = await consumer.handle(_message())
    assert (outcome.kind, outcome.reason) == ("dead-letter", "projection-mismatch")


@pytest.mark.parametrize("where", ["directory", "registry", "use-case"])
async def test_any_other_failure_is_a_retry_that_names_the_class_only(where: str) -> None:
    apply, registry, tenants = _Apply(), _Registry(), _Tenants([MEMBER_B])
    error = ConnectionError("could not reach Ms Jane Smith")
    {"directory": tenants, "registry": registry, "use-case": apply}[where].error = error
    consumer, *_ = _consumer(apply, registry, tenants)
    outcome = await consumer.handle(_message())
    assert (outcome.kind, outcome.reason) == ("retry", "ConnectionError")
