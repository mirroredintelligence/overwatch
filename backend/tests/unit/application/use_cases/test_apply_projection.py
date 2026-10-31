"""The network projection apply step (TEN-054, DEC-543, DEC-132 items 3, 4 and 6).

The apply step binds the network scope, checks the message against the registry (the membership,
the grant, the admitted listing: the message is never the authority), and only then opens one
read-write unit of work in the network scope. In that unit it marks the message processed, makes
sure the member's source is open, writes the allowlisted row, appends one audit entry of ids and
commits. A rejected message opens no unit. The unit and the registry are stubs here; the real ones
are `tests/integration/application/test_project_network.py` (written, not run).
"""

import logging
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.network import ActiveGrant, RegisteredNetwork
from diucs.application.ports.outbound.projection import (
    ProjectionEndReason,
    SourceState,
    SourceStatus,
)
from diucs.application.projection import to_body
from diucs.application.tenancy import ScopeId, bind_network, bind_tenant
from diucs.application.use_cases.apply_projection import (
    ApplyOutcome,
    ApplyProjection,
    ApplyResult,
    ApplyUnitReadOnly,
    ProjectionMismatch,
)
from diucs.domain.events import (
    ProjectionApplied,
    ProjectionRejected,
    ProjectionRejectReason,
    ProjectionRequested,
)
from diucs.domain.model.network import GrantScope, ListingStatus, MembershipStatus
from diucs.domain.rules.projection import PROJECTION_ALLOWLIST_VERSION
from tests.support.network_samples import (
    MEMBER_B,
    NETWORK_ID,
    SETTINGS,
    make_grant,
    make_listing,
    make_member,
    make_network,
)
from tests.support.network_samples import (
    NOW as GRANT_NOW,
)
from tests.support.projection_samples import (
    sample_capacity_projection,
    sample_criteria_projection,
    sample_service_projection,
)

NOW = GRANT_NOW + timedelta(hours=1)
MESSAGE_ID = "msg-1"
NET = ScopeId.network(NETWORK_ID)


class _Processed:
    def __init__(self, unit: _Unit) -> None:
        self._unit = unit

    async def mark_if_new(self, message_id: str, consumer: str) -> bool:
        self._unit.calls.append(("mark", message_id, consumer))
        return self._unit.new


class _Projections:
    def __init__(self, unit: _Unit) -> None:
        self._unit = unit

    async def open_source(self, source: str, kind: GrantScope, grant: Any) -> None:
        self._unit.calls.append(("open", source, kind, grant.grant_id, grant.grant_version))

    async def upsert_service(self, source: str, dto: Any, *, grant: Any, projected_at: Any) -> bool:
        self._unit.calls.append(("upsert", "service", source, projected_at))
        return self._unit.written

    async def upsert_capacity(
        self, source: str, dto: Any, *, grant: Any, projected_at: Any
    ) -> bool:
        self._unit.calls.append(("upsert", "capacity", source, projected_at))
        return self._unit.written

    async def upsert_criteria(
        self, source: str, dto: Any, *, grant: Any, projected_at: Any
    ) -> bool:
        self._unit.calls.append(("upsert", "criteria", source, projected_at))
        return self._unit.written


class _View:
    def __init__(self, unit: _Unit) -> None:
        self._unit = unit

    async def source(self, source: str, kind: GrantScope) -> SourceState | None:
        self._unit.calls.append(("source", source, kind))
        return self._unit.state


class _Audit:
    def __init__(self, unit: _Unit) -> None:
        self._unit = unit

    async def append(self, entry: Any) -> None:
        self._unit.calls.append(("audit", entry))


class _Unit:
    def __init__(self, world: _World) -> None:
        self.calls: list[tuple[Any, ...]] = world.calls
        self.new = world.new
        self.written = world.written
        self.state = world.state
        self.read_only = world.read_only
        self.unit_scope = world.unit_scope
        self.processed = _Processed(self)
        self.projections = _Projections(self)
        self.network_view = _View(self)
        self.audit = _Audit(self)
        self._world = world

    async def __aenter__(self) -> _Unit:
        self.calls.append(("open-unit",))
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.calls.append(("close-unit",))

    async def commit(self) -> None:
        self.calls.append(("commit",))


class _World:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.new = True
        self.written = True
        self.state: SourceState | None = None
        self.read_only = False
        self.unit_scope: ScopeId | None = NET

    def factory(self) -> _Unit:
        return _Unit(self)


class _Registry:
    def __init__(self) -> None:
        self.membership: Any = make_member(MEMBER_B)
        self.active: list[ActiveGrant] = []
        self.listings: list[Any] = [make_listing()]
        self.reads: list[str] = []

    async def active_membership(self, network_id: str, tenant_id: str) -> Any:
        self.reads.append("membership")
        return self.membership

    async def active_grants_for(self, tenant_id: str, scope: GrantScope, now: datetime) -> Any:
        self.reads.append("grants")
        return [
            a
            for a in self.active
            if a.grant.scope is scope and a.grant.grantor_tenant_id == tenant_id
        ]

    async def listings_of(self, network_id: str, tenant_id: str) -> Any:
        self.reads.append("listings")
        return self.listings


class _Notifier:
    def __init__(self) -> None:
        self.applied_events: list[ProjectionApplied] = []
        self.rejected_events: list[ProjectionRejected] = []
        self.fail = False

    async def applied(self, event: ProjectionApplied) -> None:
        if self.fail:
            raise RuntimeError("the board could not be rebuilt for Ms Jane Smith")
        self.applied_events.append(event)

    async def rejected(self, event: ProjectionRejected) -> None:
        self.rejected_events.append(event)


def _request(kind: GrantScope = GrantScope.CAPACITY, **changes: Any) -> ProjectionRequested:
    dto: Any = {
        GrantScope.CAPACITY: sample_capacity_projection(),
        GrantScope.DIRECTORY: sample_service_projection(),
        GrantScope.CRITERIA: sample_criteria_projection(),
    }[kind]
    version = dto.version if kind is GrantScope.CRITERIA else dto.source_version
    fields: dict[str, Any] = {
        "network_id": NETWORK_ID,
        "source_tenant_id": MEMBER_B,
        "grant_id": f"grant-{kind.value}",
        "grant_version": 1,
        "kind": kind,
        "source_service_id": "svc-1",
        "source_version": version,
        "allowlist_version": PROJECTION_ALLOWLIST_VERSION,
        "body": to_body(dto),
        "at": NOW,
    }
    fields.update(changes)
    return ProjectionRequested(**fields)


class _Rig:
    def __init__(self, kind: GrantScope = GrantScope.CAPACITY) -> None:
        self.world = _World()
        self.registry = _Registry()
        self.notifier = _Notifier()
        network = make_network()
        grant = make_grant(id=f"grant-{kind.value}", scope=kind)
        self.registry.active = [
            ActiveGrant(RegisteredNetwork(network, SETTINGS), grant, make_member(MEMBER_B))
        ]
        self.use_case = ApplyProjection(
            self.world.factory,  # type: ignore[arg-type]
            self.registry,  # type: ignore[arg-type]
            FixedClock(NOW),
            self.notifier,
        )

    async def run(self, request: ProjectionRequested, **kw: Any) -> ApplyResult:
        with bind_network(NETWORK_ID):
            return await self.use_case.execute(
                request,
                message_id=kw.get("message_id", MESSAGE_ID),
                source_tenant_id=kw.get("source_tenant_id", request.source_tenant_id),
            )

    def names(self) -> list[str]:
        return [str(call[0]) for call in self.world.calls]


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


# Applied


@pytest.mark.parametrize("kind", list(GrantScope))
async def test_a_valid_message_is_applied_in_one_unit_in_order_and_then_announced(
    kind: GrantScope,
) -> None:
    rig = _Rig(kind)
    result = await rig.run(_request(kind))
    assert result == ApplyResult(ApplyOutcome.APPLIED)
    assert rig.names() == [
        "open-unit", "mark", "source", "open", "upsert", "audit", "commit", "close-unit",
    ]  # fmt: skip
    assert rig.world.calls[1] == ("mark", MESSAGE_ID, "network-projector")
    assert rig.world.calls[3] == ("open", MEMBER_B, kind, f"grant-{kind.value}", 1)
    assert [e.kind for e in rig.notifier.applied_events] == [kind]
    event = rig.notifier.applied_events[0]
    assert (event.network_id, event.source_tenant_id, event.item_id) == (
        NETWORK_ID,
        MEMBER_B,
        "svc-1",
    )
    assert event.at == NOW


async def test_the_registry_is_asked_before_any_unit_opens(rig: _Rig) -> None:
    await rig.run(_request())
    assert rig.registry.reads == ["membership", "grants", "listings"]
    assert rig.names().index("open-unit") == 0  # the unit is the first call of the stub world


async def test_the_audit_entry_names_ids_and_versions_and_no_value(rig: _Rig) -> None:
    await rig.run(_request())
    entry = next(call[1] for call in rig.world.calls if call[0] == "audit")
    assert entry.use_case == "ApplyProjection" and entry.action == "C"
    assert entry.entity_ids == (f"{MEMBER_B}/svc-1",)
    assert entry.actor.tenant_id == MEMBER_B
    assert set(entry.snapshot) == {
        "kind", "source_service_id", "source_version", "grant_id", "grant_version",
    }  # fmt: skip
    text = repr(entry.snapshot)
    for value in ("UCR West", "referrals", "Sampletown"):
        assert value not in text


async def test_the_projected_time_is_the_clocks_and_not_the_messages(rig: _Rig) -> None:
    await rig.run(_request(at=NOW - timedelta(days=2)))
    upsert = next(call for call in rig.world.calls if call[0] == "upsert")
    assert upsert[3] == NOW


# Not applied: duplicate and stale


async def test_a_message_already_processed_writes_nothing_and_commits_nothing(rig: _Rig) -> None:
    rig.world.new = False
    result = await rig.run(_request())
    assert result == ApplyResult(ApplyOutcome.DUPLICATE)
    assert rig.names() == ["open-unit", "mark", "close-unit"]
    assert rig.notifier.applied_events == []


async def test_an_older_version_is_stale_and_only_the_marker_is_committed(rig: _Rig) -> None:
    rig.world.written = False
    result = await rig.run(_request())
    assert result == ApplyResult(ApplyOutcome.STALE)
    assert "audit" not in rig.names()
    assert rig.names()[-2:] == ["commit", "close-unit"]
    assert rig.notifier.applied_events == []


# Rejected before any unit opens


_R = ProjectionRejectReason
_REJECTIONS = [
    ("none", {"allowlist_version": PROJECTION_ALLOWLIST_VERSION + 1}, _R.ALLOWLIST_MISMATCH),
    ("none", {"body": {"service_name": "x"}}, _R.INVALID_BODY),
    ("none", {"source_service_id": "svc-other"}, _R.INVALID_BODY),
    ("none", {"source_version": 7}, _R.INVALID_BODY),
    ("no-membership", {}, _R.MEMBER_NOT_ACTIVE),
    ("no-grant", {}, _R.GRANT_NOT_EFFECTIVE),
    ("none", {"grant_id": "grant-other"}, _R.GRANT_NOT_EFFECTIVE),
    ("none", {"grant_version": 2}, _R.GRANT_NOT_EFFECTIVE),
    ("no-listing", {}, _R.LISTING_NOT_ADMITTED),
    ("pending-listing", {}, _R.LISTING_NOT_ADMITTED),
    ("other-service-listing", {}, _R.LISTING_NOT_ADMITTED),
]


def _setup(rig: _Rig, name: str) -> None:
    if name == "no-membership":
        rig.registry.membership = None
    elif name == "no-grant":
        rig.registry.active = []
    elif name == "no-listing":
        rig.registry.listings = []
    elif name == "pending-listing":
        rig.registry.listings = [make_listing(admitted=False)]
    elif name == "other-service-listing":
        rig.registry.listings = [make_listing(service="svc-other")]


@pytest.mark.parametrize(("setup", "request_changes", "reason"), _REJECTIONS)
async def test_a_message_the_registry_or_the_allowlist_refuses_is_rejected_and_opens_no_unit(
    rig: _Rig, setup: str, request_changes: dict[str, Any], reason: ProjectionRejectReason
) -> None:
    _setup(rig, setup)
    result = await rig.run(_request(**request_changes))
    assert result == ApplyResult(ApplyOutcome.REJECTED, reason)
    assert rig.world.calls == []
    assert [e.reason for e in rig.notifier.rejected_events] == [reason]
    assert rig.notifier.applied_events == []


async def test_a_body_with_a_key_off_the_allowlist_is_rejected_whatever_its_value(
    rig: _Rig,
) -> None:
    body = dict(to_body(sample_capacity_projection()))
    body["extra_field"] = "x"
    result = await rig.run(_request(body=body))
    assert result.reason is ProjectionRejectReason.INVALID_BODY
    assert rig.world.calls == []


async def test_the_source_tenant_of_the_message_is_checked_against_the_registry_not_the_payload(
    rig: _Rig,
) -> None:
    """A payload that names another member's grant is refused by the gate: the grant must be the
    verified source tenant's own."""
    other = make_grant(id="grant-of-c", tenant="tenant-c")
    rig.registry.active = [
        ActiveGrant(RegisteredNetwork(make_network(), SETTINGS), other, make_member("tenant-c"))
    ]
    result = await rig.run(_request(grant_id="grant-of-c"))
    assert result.reason in (
        ProjectionRejectReason.GRANT_NOT_EFFECTIVE,
        ProjectionRejectReason.MEMBER_NOT_ACTIVE,
    )
    assert rig.world.calls == []


# The source of an ended grant


def _ended_state(ended_at: datetime) -> SourceState:
    return SourceState(
        source_tenant_id=MEMBER_B,
        kind=GrantScope.CAPACITY,
        status=SourceStatus.ENDED,
        grant_id="grant-capacity",
        ended_at=ended_at,
        end_reason=ProjectionEndReason.GRANT_ENDED,
    )


async def test_an_ended_source_is_reopened_only_by_a_grant_approved_after_it_ended(
    rig: _Rig,
) -> None:
    grant_approved = rig.registry.active[0].grant.owner_approval.at  # type: ignore[union-attr]
    rig.world.state = _ended_state(grant_approved - timedelta(hours=1))
    assert (await rig.run(_request())).outcome is ApplyOutcome.APPLIED
    assert "open" in rig.names()


async def test_an_ended_source_is_not_reopened_by_a_grant_approved_before_it_ended() -> None:
    rig = _Rig()
    grant_approved = rig.registry.active[0].grant.owner_approval.at  # type: ignore[union-attr]
    rig.world.state = _ended_state(grant_approved + timedelta(hours=1))
    result = await rig.run(_request())
    assert result == ApplyResult(ApplyOutcome.REJECTED, ProjectionRejectReason.GRANT_NOT_EFFECTIVE)
    assert "open" not in rig.names() and "upsert" not in rig.names() and "commit" not in rig.names()


async def test_a_grant_approved_before_the_end_but_starting_after_it_reopens_the_source() -> None:
    """The end was a lapse between two grants: the next grant was already approved, and starts after
    the end, so it is a new grant for the source and not an old one coming back (TEN-056)."""
    rig = _Rig()
    grant = rig.registry.active[0].grant
    approved = grant.owner_approval.at  # type: ignore[union-attr]
    ended = approved + timedelta(hours=1)
    rig.registry.active[0] = replace(
        rig.registry.active[0], grant=replace(grant, effective_from=ended + timedelta(minutes=1))
    )
    rig.world.state = _ended_state(ended)
    assert (await rig.run(_request())).outcome is ApplyOutcome.APPLIED
    assert "open" in rig.names()


async def test_an_active_source_is_left_as_it_is() -> None:
    rig = _Rig()
    rig.world.state = replace(
        _ended_state(NOW), status=SourceStatus.ACTIVE, ended_at=None, end_reason=None
    )
    await rig.run(_request())
    assert "open" not in rig.names()
    assert "upsert" in rig.names()


# Scope and unit guards


async def test_the_apply_step_needs_the_network_scope_of_the_message(rig: _Rig) -> None:
    request = _request()
    with bind_tenant(MEMBER_B), pytest.raises(ProjectionMismatch):
        await rig.use_case.execute(request, message_id=MESSAGE_ID, source_tenant_id=MEMBER_B)
    with pytest.raises(ProjectionMismatch):
        await rig.use_case.execute(request, message_id=MESSAGE_ID, source_tenant_id=MEMBER_B)
    with bind_network("net-other"), pytest.raises(ProjectionMismatch):
        await rig.use_case.execute(request, message_id=MESSAGE_ID, source_tenant_id=MEMBER_B)
    assert rig.world.calls == [] and rig.registry.reads == []


async def test_a_message_whose_tenant_is_not_the_payloads_source_is_a_mismatch(rig: _Rig) -> None:
    with pytest.raises(ProjectionMismatch):
        await rig.run(_request(), source_tenant_id="tenant-c")
    assert rig.world.calls == [] and rig.registry.reads == []


async def test_a_read_only_unit_or_a_unit_in_another_scope_is_refused_before_a_write(
    rig: _Rig,
) -> None:
    rig.world.read_only = True
    with pytest.raises(ApplyUnitReadOnly):
        await rig.run(_request())
    assert "mark" not in rig.names()
    other = _Rig()
    other.world.unit_scope = ScopeId.network("net-other")
    with pytest.raises(ProjectionMismatch):
        await other.run(_request())
    assert "mark" not in other.names()


# After the commit


async def test_a_notifier_that_fails_does_not_undo_or_fail_the_projection(
    rig: _Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.notifier.fail = True
    with caplog.at_level(logging.WARNING):
        result = await rig.run(_request())
    assert result == ApplyResult(ApplyOutcome.APPLIED)
    assert "commit" in rig.names()
    assert "RuntimeError" in caplog.text
    assert "Jane" not in caplog.text


async def test_no_notifier_is_needed() -> None:
    rig = _Rig()
    rig.use_case = ApplyProjection(rig.world.factory, rig.registry, FixedClock(NOW))  # type: ignore[arg-type]
    assert (await rig.run(_request())).outcome is ApplyOutcome.APPLIED


async def test_a_left_member_and_a_left_listing_status_are_not_applied() -> None:
    rig = _Rig()
    rig.registry.membership = None
    assert (await rig.run(_request())).reason is ProjectionRejectReason.MEMBER_NOT_ACTIVE
    assert MembershipStatus.LEFT.value == "left" and ListingStatus.WITHDRAWN.value == "withdrawn"
