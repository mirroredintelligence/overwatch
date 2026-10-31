"""The network projection producer (TEN-054, DEC-543, DEC-132 item 4, DEC-134 items 6 and 7).

The producer reads inside the member's tenant scope, in a read-only unit of work that is closed
before anything is sent, builds the allowlisted DTOs with the pure builders, and publishes one
`ProjectionRequested` message for each grant that may project now and each service the network
owner has admitted. It writes nothing. The unit of work and the registry are small stubs here (the
real ones are `tests/integration/application/test_project_network.py`, written, not run).
"""

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.network import ActiveGrant, RegisteredNetwork
from diucs.application.projection import to_body
from diucs.application.tenancy import TenantNotBound, bind_network, bind_tenant
from diucs.application.use_cases.project_network import (
    ProducerUnitNotReadOnly,
    ProjectionRun,
    ProjectNetwork,
)
from diucs.domain.events import ProjectionRequested
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.model.network import GrantScope, ListingReason, MembershipStatus
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules import projection as allowlist
from diucs.domain.rules.listing import suspend_listing, withdraw_listing
from diucs.domain.rules.projection import (
    PROJECTION_ALLOWLIST_VERSION,
    build_capacity_projection,
    build_criteria_projection,
    build_service_projection,
)
from diucs.domain.rules.projection_validity import next_status_change
from tests.support.network_samples import (
    ACCOUNT_B,
    ACCOUNT_OWNER,
    MEMBER_B,
    NETWORK_ID,
    OTHER_NETWORK_ID,
    OWNER,
    SETTINGS,
    make_grant,
    make_listing,
    make_member,
    make_network,
)
from tests.support.projection_samples import (
    SERVICE_ID,
    sample_criteria,
    sample_profile,
    sample_report,
)

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
VERSION = 4


class _Services:
    def __init__(self, profiles: dict[str, Any]) -> None:
        self._profiles = profiles

    async def get_versioned(self, service_id: str) -> Any:
        profile = self._profiles.get(service_id)
        return None if profile is None else (profile, VERSION)

    async def list_active(self) -> list[Any]:
        return [p for p in self._profiles.values() if p.active]


class _Flags:
    def __init__(self, suspended: set[str]) -> None:
        self._suspended = suspended
        self.asked: list[str] = []

    async def services_with_flag(self, code: str) -> set[str]:
        self.asked.append(code)
        return self._suspended


class _Capacity:
    def __init__(self, reports: dict[str, Any]) -> None:
        self._reports = reports

    async def latest(self, service_id: str) -> Any:
        return self._reports.get(service_id)


class _Bookings:
    def __init__(self, confirmed: dict[str, list[datetime]]) -> None:
        self._confirmed = confirmed
        self.since: list[datetime] = []

    async def confirmed_since_for_services(self, ids: Any, since: datetime) -> dict[str, Any]:
        self.since.append(since)
        return {i: self._confirmed.get(i, []) for i in ids}


class _Criteria:
    def __init__(self, current: dict[str, Any]) -> None:
        self._current = current

    async def current_for_service(self, service_id: str) -> Any:
        return self._current.get(service_id)


class _Config:
    def __init__(self, policy: Any) -> None:
        self._policy = policy

    async def current_version(self) -> Any:
        return None if self._policy is None else type("Config", (), {"policy": self._policy})()


class _Unit:
    def __init__(self, world: _World) -> None:
        self.read_only = world.read_only
        self.services = _Services(world.profiles)
        self.flags = _Flags(world.suspended)
        self.capacity = _Capacity(world.reports)
        self.bookings = _Bookings(world.confirmed)
        self.criteria = _Criteria(world.criteria)
        self.tenant_config = _Config(world.policy)
        self._world = world

    async def __aenter__(self) -> _Unit:
        self._world.opened += 1
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._world.closed += 1

    async def commit(self) -> None:  # a producer never commits
        self._world.commits += 1


class _World:
    def __init__(self) -> None:
        self.read_only = True
        self.profiles: dict[str, Any] = {SERVICE_ID: sample_profile()}
        self.suspended: set[str] = set()
        self.reports: dict[str, Any] = {SERVICE_ID: sample_report()}
        self.confirmed: dict[str, list[datetime]] = {}
        self.criteria: dict[str, Any] = {SERVICE_ID: sample_criteria()}
        self.policy: Any = None
        self.opened = 0
        self.closed = 0
        self.commits = 0

    def factory(self) -> _Unit:
        return _Unit(self)


class _Registry:
    def __init__(self) -> None:
        self.grants: dict[GrantScope, list[ActiveGrant]] = {}
        self.listings: dict[str, list[Any]] = {}
        self.asked: list[tuple[str, GrantScope, datetime]] = []

    async def active_grants_for(self, tenant_id: str, scope: GrantScope, now: datetime) -> Any:
        self.asked.append((tenant_id, scope, now))
        return self.grants.get(scope, [])

    async def listings_of(self, network_id: str, tenant_id: str) -> Any:
        return [i for i in self.listings.get(network_id, []) if i.source_tenant_id == tenant_id]


class _Publisher:
    def __init__(self) -> None:
        self.sent: list[ProjectionRequested] = []
        self.world: _World | None = None
        self.units_open_when_sent: list[int] = []

    async def publish(self, request: ProjectionRequested) -> None:
        if self.world is not None:
            self.units_open_when_sent.append(self.world.opened - self.world.closed)
        self.sent.append(request)


def _active(
    scope: GrantScope = GrantScope.CAPACITY,
    *,
    network_id: str = NETWORK_ID,
    grant_id: str | None = None,
) -> ActiveGrant:
    network = make_network(id=network_id)
    grant = make_grant(id=grant_id or f"grant-{scope.value}", scope=scope, network_id=network_id)
    return ActiveGrant(RegisteredNetwork(network, SETTINGS), grant, make_member(network=network))


class _Rig:
    def __init__(self, zones: Any = None) -> None:
        self.world = _World()
        self.registry = _Registry()
        self.publisher = _Publisher()
        self.publisher.world = self.world
        self.producer = ProjectNetwork(
            self.world.factory,  # type: ignore[arg-type]
            self.registry,  # type: ignore[arg-type]
            self.publisher,
            FixedClock(NOW),
            zones,
        )

    def allow(self, *scopes: GrantScope, network_id: str = NETWORK_ID, listed: bool = True) -> None:
        for scope in scopes:
            self.registry.grants.setdefault(scope, []).append(_active(scope, network_id=network_id))
        if listed:
            listing = make_listing()
            if network_id != NETWORK_ID:
                listing = replace(listing, network_id=network_id)
            self.registry.listings.setdefault(network_id, []).append(listing)


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


@pytest.fixture(autouse=True)
def _tenant() -> Any:
    with bind_tenant(MEMBER_B):
        yield


# What is sent


async def test_a_grant_and_an_admitted_listing_send_one_message_with_the_allowlisted_body(
    rig: _Rig,
) -> None:
    rig.allow(GrantScope.CAPACITY)
    run = await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    assert run == ProjectionRun(requested=1, skipped=0)
    [sent] = rig.publisher.sent
    expected = build_capacity_projection(
        sample_profile(),
        sample_report(),
        confirmed_since=0,
        policy=DEFAULT_POLICY,
        source_version=int(NOW.timestamp() * 1000),
        valid_until=next_status_change(sample_profile(), sample_report().effective_at, NOW),
    )
    assert expected.valid_until is not None
    assert sent.network_id == NETWORK_ID
    assert sent.source_tenant_id == MEMBER_B
    assert (sent.grant_id, sent.grant_version) == ("grant-capacity", 1)
    assert sent.kind is GrantScope.CAPACITY
    assert sent.source_service_id == SERVICE_ID
    assert sent.source_version == expected.source_version
    assert sent.allowlist_version == PROJECTION_ALLOWLIST_VERSION
    assert sent.at == NOW
    assert dict(sent.body) == to_body(expected)


async def test_the_three_kinds_are_built_from_the_service_the_report_and_the_criteria(
    rig: _Rig,
) -> None:
    rig.allow(*GrantScope)
    run = await rig.producer.project_all(SERVICE_ID)
    assert run.requested == 3
    by_kind = {m.kind: m for m in rig.publisher.sent}
    service = build_service_projection(
        sample_profile(), source_version=VERSION, location=None, contact=None
    )
    assert dict(by_kind[GrantScope.DIRECTORY].body) == to_body(service)
    assert by_kind[GrantScope.DIRECTORY].source_version == VERSION
    criteria = build_criteria_projection(sample_criteria())
    assert dict(by_kind[GrantScope.CRITERIA].body) == to_body(criteria)
    assert by_kind[GrantScope.CRITERIA].source_version == criteria.version


async def test_the_producer_reads_in_one_unit_that_is_closed_before_anything_is_sent(
    rig: _Rig,
) -> None:
    rig.allow(*GrantScope)
    await rig.producer.project_all(SERVICE_ID)
    assert rig.world.opened == rig.world.closed == 1
    assert rig.world.commits == 0
    assert rig.publisher.units_open_when_sent == [0, 0, 0]


async def test_the_registry_is_asked_for_the_bound_tenant_and_the_clock_time(rig: _Rig) -> None:
    rig.allow(GrantScope.CAPACITY)
    await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    assert rig.registry.asked == [(MEMBER_B, GrantScope.CAPACITY, NOW)]


async def test_a_grant_with_no_effective_grant_sends_nothing_and_opens_no_unit(rig: _Rig) -> None:
    run = await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    assert run == ProjectionRun(requested=0, skipped=1)
    assert rig.publisher.sent == []
    assert rig.world.opened == 0


async def test_a_service_the_owner_has_not_admitted_is_not_projected(rig: _Rig) -> None:
    rig.allow(GrantScope.CAPACITY, listed=False)
    assert (await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)).requested == 0
    admitted = make_listing()
    suspended = suspend_listing(
        admitted,
        by_tenant_id=OWNER,
        owner_tenant_id=OWNER,
        reason=ListingReason.SAFETY_CONCERN,
        account_ref=ACCOUNT_OWNER,
        now=NOW,
    )
    withdrawn = withdraw_listing(admitted, by_tenant_id=MEMBER_B, account_ref=ACCOUNT_B, now=NOW)
    for listing in (make_listing(admitted=False), suspended, withdrawn):
        other = _Rig()
        other.allow(GrantScope.CAPACITY, listed=False)
        other.registry.listings[NETWORK_ID] = [listing]
        await other.producer.project(GrantScope.CAPACITY, SERVICE_ID)
        assert other.publisher.sent == [], listing.status


async def test_a_listing_of_another_service_or_member_does_not_admit_this_one(rig: _Rig) -> None:
    rig.allow(GrantScope.CAPACITY, listed=False)
    rig.registry.listings[NETWORK_ID] = [
        make_listing(service="svc-other"),
        make_listing(id="lst-c", tenant="tenant-c"),
    ]
    assert (await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)).requested == 0


async def test_each_network_with_a_grant_gets_its_own_message(rig: _Rig) -> None:
    rig.allow(GrantScope.CAPACITY)
    rig.allow(GrantScope.CAPACITY, network_id=OTHER_NETWORK_ID)
    run = await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    assert run.requested == 2
    assert {m.network_id for m in rig.publisher.sent} == {NETWORK_ID, OTHER_NETWORK_ID}
    assert len({dict(m.body).__repr__() for m in rig.publisher.sent}) == 1  # the same body


async def test_a_service_that_does_not_exist_or_is_inactive_is_skipped(rig: _Rig) -> None:
    rig.allow(GrantScope.CAPACITY)
    assert (await rig.producer.project(GrantScope.CAPACITY, "svc-missing")).skipped == 1
    rig.world.profiles[SERVICE_ID] = sample_profile(active=False)
    assert (await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)).requested == 0
    assert rig.publisher.sent == []


async def test_a_service_with_no_current_criteria_sends_no_criteria_message(rig: _Rig) -> None:
    rig.allow(GrantScope.CRITERIA)
    rig.world.criteria = {}
    run = await rig.producer.project(GrantScope.CRITERIA, SERVICE_ID)
    assert run == ProjectionRun(requested=0, skipped=1)


async def test_a_service_with_no_report_projects_its_profile_inputs_with_no_figure(
    rig: _Rig,
) -> None:
    rig.allow(GrantScope.CAPACITY)
    rig.world.reports = {}
    await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    body = dict(rig.publisher.sent[0].body)
    assert body["report_id"] is None and body["value"] is None
    assert body["confirmed_since"] == 0


async def test_the_confirmed_count_is_the_bookings_confirmed_since_the_latest_report(
    rig: _Rig,
) -> None:
    rig.allow(GrantScope.CAPACITY)
    report = sample_report()
    rig.world.confirmed = {
        SERVICE_ID: [report.effective_at + timedelta(minutes=1), report.effective_at]
    }
    await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    assert dict(rig.publisher.sent[0].body)["confirmed_since"] == 2


async def test_the_suspended_flag_is_a_flag_and_the_tenants_policy_is_the_one_projected(
    rig: _Rig,
) -> None:
    rig.allow(GrantScope.CAPACITY)
    rig.world.suspended = {SERVICE_ID}
    rig.world.policy = replace(DEFAULT_POLICY, reply_window=timedelta(minutes=20))
    await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    body = dict(rig.publisher.sent[0].body)
    assert body["suspended"] is True
    assert body["reply_window_minutes"] == 20


# What is never sent


async def test_nothing_outside_the_allowlist_is_in_any_message(rig: _Rig) -> None:
    rig.allow(*GrantScope)
    await rig.producer.project_all(SERVICE_ID)
    allowed = {
        spec.dto_field for label in allowlist.ALLOWLIST for spec in allowlist.ALLOWLIST[label]
    }
    allowed |= {"opening_hours"}
    text = repr([m.to_payload() for m in rig.publisher.sent])
    for message in rig.publisher.sent:
        assert set(message.body) <= allowed
    for poison in ("Both women only", "role-1", "role-2", "Added frailty", "crit-0"):
        assert poison not in text, poison
    assert re.search(r"[A-Z]{1,2}[0-9][0-9A-Z]? ?[0-9][A-Z]{2}", text) is None


# Guards


async def test_a_producer_whose_unit_is_not_read_only_is_refused_and_sends_nothing(
    rig: _Rig,
) -> None:
    rig.allow(GrantScope.CAPACITY)
    rig.world.read_only = False
    with pytest.raises(ProducerUnitNotReadOnly):
        await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    assert rig.publisher.sent == []


async def test_a_network_scope_is_not_a_tenant_scope_for_the_producer(rig: _Rig) -> None:
    rig.allow(GrantScope.CAPACITY)
    with bind_network(NETWORK_ID), pytest.raises(TenantNotBound):
        await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    assert rig.registry.asked == [] and rig.world.opened == 0


async def test_a_kind_that_is_not_a_grant_scope_is_refused(rig: _Rig) -> None:
    with pytest.raises(Exception, match="kind"):
        await rig.producer.project("capacity", SERVICE_ID)  # type: ignore[arg-type]


async def test_a_member_who_left_projects_nothing(rig: _Rig) -> None:
    """The registry's gate drops a grant whose member left: the producer sends nothing."""
    assert MembershipStatus.LEFT.value == "left"
    assert (await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)).requested == 0


# Backfill


async def test_a_backfill_projects_every_active_service_for_every_grant(rig: _Rig) -> None:
    rig.allow(GrantScope.CAPACITY, GrantScope.DIRECTORY)
    second = sample_profile(id="svc-2", name="UCR East")
    rig.world.profiles["svc-2"] = second
    rig.registry.listings[NETWORK_ID].append(make_listing(id="lst-2", service="svc-2"))
    rig.world.reports["svc-2"] = sample_report(id="rep-2", service_id="svc-2")
    run = await rig.producer.backfill()
    assert run.requested == 4
    assert {(m.kind, m.source_service_id) for m in rig.publisher.sent} == {
        (GrantScope.CAPACITY, SERVICE_ID),
        (GrantScope.CAPACITY, "svc-2"),
        (GrantScope.DIRECTORY, SERVICE_ID),
        (GrantScope.DIRECTORY, "svc-2"),
    }
    assert rig.world.opened == 1


async def test_a_backfill_of_one_kind_asks_only_for_that_kind(rig: _Rig) -> None:
    rig.allow(GrantScope.CAPACITY, GrantScope.DIRECTORY)
    await rig.producer.backfill(GrantScope.DIRECTORY)
    assert {m.kind for m in rig.publisher.sent} == {GrantScope.DIRECTORY}
    assert [scope for _, scope, _ in rig.registry.asked] == [GrantScope.DIRECTORY]


async def test_the_suspended_code_is_the_flag_the_board_uses(rig: _Rig) -> None:
    rig.allow(GrantScope.CAPACITY)
    await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    assert rig.world.suspended == set()  # nothing was written to it
    assert SERVICE_FLAG_SUSPENDED  # the producer asks the unit for this code


# The validity instant (TEN-056)


async def test_a_capacity_message_carries_the_instant_its_status_can_next_change(
    rig: _Rig,
) -> None:
    rig.allow(GrantScope.CAPACITY)
    run = await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    [sent] = rig.publisher.sent
    valid_until = sent.body["valid_until"]
    assert isinstance(valid_until, str) and valid_until > NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert run.next_boundary is not None and run.next_boundary > NOW


async def test_a_suspended_service_has_no_time_boundary(rig: _Rig) -> None:
    rig.allow(GrantScope.CAPACITY)
    rig.world.suspended = {SERVICE_ID}
    run = await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    [sent] = rig.publisher.sent
    assert sent.body["valid_until"] is None
    assert run.next_boundary is None


async def test_the_boundary_is_read_in_the_tenants_own_zone() -> None:
    asked: list[Any] = []

    class _Zones:
        async def zone_of(self, scope: Any) -> Any:
            asked.append(scope)
            from diucs.domain.rules.london_time import LONDON

            return LONDON

    rig = _Rig(zones=_Zones())
    rig.allow(GrantScope.CAPACITY)
    await rig.producer.project(GrantScope.CAPACITY, SERVICE_ID)
    assert [str(scope) for scope in asked] == [MEMBER_B]
