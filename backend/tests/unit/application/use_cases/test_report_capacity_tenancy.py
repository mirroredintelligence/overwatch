"""ReportCapacity and the tenant (TEN-024, DEC-130 to DEC-134, reworks U01).

No Neo4j: a recording fake stands in for the unit of work and fails the test when anything is
touched that the case says must not be. What is proved here is the order of the checks, never the
store. The two-tenant proof against a real graph is in
`tests/integration/application/test_report_capacity_tenants.py`.

The rules kept from U01 (DEC-100, DEC-104, DEC-106, DEC-139, DEC-140): the service is loaded before
the permission is checked, a stored command key is decided before any other check, and every
refusal writes nothing.
"""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from types import TracebackType
from typing import Any, Self

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.tenancy import (
    ScopeId,
    TenantMismatch,
    TenantNotBound,
    bind_scope,
    bind_tenant,
)
from diucs.application.use_cases.report_capacity import (
    PERFORMER_NOT_FOUND,
    ReportCapacity,
    ReportCapacityCommand,
    _fingerprint,
    check_performer,
)
from diucs.application.use_cases.report_flags import LOOKBACK, report_lookback
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ReportSource,
    Role,
    ServiceCategory,
)
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.people import PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.report_flags import MANY_CHANGES_WINDOW, PHONED_WINDOW

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"

PROFILE = ServiceProfile(
    id="ucr-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)


def _actor(tenant: str = TENANT_A, practitioner: str | None = "prac-1") -> Actor:
    return Actor(
        role=Role.REPORTER,
        practitioner_id=practitioner,
        device_id="device-1",
        channel="text",
        service_ids=frozenset({"ucr-west"}),
        tenant_id=tenant,
    )


def _command(actor: Actor | None = None, **fields: Any) -> ReportCapacityCommand:
    base: dict[str, Any] = {
        "idempotency_key": "key-1",
        "actor": _actor() if actor is None else actor,
        "service_id": "ucr-west",
        "value": 4,
        "source": ReportSource.TEXT,
    }
    return ReportCapacityCommand(**{**base, **fields})


def _role(**fields: Any) -> PractitionerRole:
    base: dict[str, Any] = {
        "id": "role-1",
        "practitioner_id": "prac-1",
        "service_id": "ucr-west",
        "code": PractitionerRoleCode.DUTY_MANAGER,
        "active": True,
        "channel": Channel.TEXT,
        "period_start": datetime(2026, 1, 1, tzinfo=UTC),
    }
    return PractitionerRole(**{**base, **fields})


# -- the fakes ---------------------------------------------------------------------------------


class _Untouched:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"touched: {name}")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the unit of work factory was called")


class _Store:
    """The idempotency store: records its reads and writes nothing."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def get(self, key: str) -> None:
        self._events.append("early-get")

    async def put(self, key: str, result: object) -> None:
        raise AssertionError("nothing may be stored")


class _Capacity:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def lock_service(self, service_id: str) -> None:
        self._events.append("lock")

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"capacity touched: {name}")


class _Idempotency:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def get(self, key: str) -> None:
        self._events.append("unit-get")

    async def put(self, key: str, result: object) -> None:
        raise AssertionError("nothing may be stored")


class _Services:
    def __init__(self, events: list[str], profile: ServiceProfile | None) -> None:
        self._events = events
        self._profile = profile

    async def get(self, service_id: str) -> ServiceProfile | None:
        self._events.append("service")
        return self._profile


class _People:
    def __init__(self, events: list[str], role: PractitionerRole | None) -> None:
        self._events = events
        self._role = role

    async def get_role(self, role_id: str) -> PractitionerRole | None:
        self._events.append("role")
        return self._role

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"people touched: {name}")


class _Unit:
    """A unit of work that has opened under `scope` and holds only what a refusal reads."""

    def __init__(
        self,
        events: list[str],
        scope: ScopeId | None,
        profile: ServiceProfile | None = PROFILE,
        role: PractitionerRole | None = None,
    ) -> None:
        self.unit_scope = scope
        self.capacity = _Capacity(events)
        self.idempotency = _Idempotency(events)
        self.services = _Services(events, profile)
        self.people = _People(events, role)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        raise AssertionError("nothing may be committed")

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unit of work touched: {name}")


def _use_case(factory: Any, events: list[str]) -> ReportCapacity:
    return ReportCapacity(factory, FixedClock(NOW), SequentialIds(), _Store(events))  # type: ignore[arg-type]


# -- the tenant guard --------------------------------------------------------------------------


async def test_an_actor_of_another_tenant_than_the_bound_one_is_refused_before_any_read() -> None:
    events: list[str] = []
    use_case = _use_case(_Untouched(), events)
    with bind_tenant(TENANT_B), pytest.raises(TenantMismatch):
        await use_case.execute(_command(_actor(TENANT_A)))
    assert events == []  # not even the early replay read


async def test_with_no_tenant_bound_nothing_is_read() -> None:
    events: list[str] = []
    with pytest.raises(TenantNotBound):
        await _use_case(_Untouched(), events).execute(_command())
    assert events == []


async def test_a_network_scope_is_not_a_tenant_for_a_report() -> None:
    events: list[str] = []
    with bind_scope(ScopeId.network("net-members")), pytest.raises(TenantNotBound):
        await _use_case(_Untouched(), events).execute(_command())
    assert events == []


async def test_a_unit_opened_under_another_tenant_than_the_actors_takes_no_lock() -> None:
    events: list[str] = []
    unit = _Unit(events, ScopeId.tenant(TENANT_B))
    with bind_tenant(TENANT_A), pytest.raises(TenantMismatch):
        await _use_case(lambda: unit, events).execute(_command(_actor(TENANT_A)))
    assert events == ["early-get"]  # no lock, no unit read, no write


async def test_a_unit_with_no_scope_or_a_network_scope_takes_no_lock() -> None:
    for scope in (None, ScopeId.network("net-members")):
        events: list[str] = []
        unit = _Unit(events, scope)
        with bind_tenant(TENANT_A), pytest.raises(TenantNotBound):
            await _use_case(lambda unit=unit: unit, events).execute(_command(_actor(TENANT_A)))  # type: ignore[misc]
        assert events == ["early-get"]


# -- the command fingerprint -------------------------------------------------------------------


def test_the_fingerprint_names_the_tenant() -> None:
    assert _fingerprint(_command(_actor(TENANT_A))) != _fingerprint(_command(_actor(TENANT_B)))


def test_the_same_command_has_the_same_fingerprint() -> None:
    assert _fingerprint(_command(_actor(TENANT_A))) == _fingerprint(_command(_actor(TENANT_A)))


def test_a_different_value_or_performer_still_changes_the_fingerprint() -> None:
    base = _fingerprint(_command())
    assert _fingerprint(_command(value=5)) != base
    assert _fingerprint(_command(performer_role_id="role-1")) != base


# -- ordering: the service is loaded first, then permission, then the performer ----------------


async def test_a_service_that_is_not_in_the_tenant_is_not_found_and_the_role_is_never_read() -> (
    None
):
    events: list[str] = []
    unit = _Unit(events, ScopeId.tenant(TENANT_A), profile=None)
    with bind_tenant(TENANT_A), pytest.raises(NotFound, match="no active service with this id"):
        await _use_case(lambda: unit, events).execute(
            _command(_actor(TENANT_A), performer_role_id="role-1")
        )
    assert events == ["early-get", "lock", "unit-get", "service"]


async def test_a_reporter_for_another_service_is_refused_before_the_role_is_read() -> None:
    events: list[str] = []
    unit = _Unit(events, ScopeId.tenant(TENANT_A), role=_role())
    command = _command(_actor(TENANT_A), service_id="ucr-west", performer_role_id="role-1")
    other = Actor(
        role=Role.REPORTER,
        practitioner_id="prac-1",
        device_id=None,
        channel="text",
        service_ids=frozenset({"ucr-east"}),
        tenant_id=TENANT_A,
    )
    with bind_tenant(TENANT_A), pytest.raises(NotAllowed):
        await _use_case(lambda: unit, events).execute(replace(command, actor=other))
    assert "role" not in events


async def test_a_performer_that_is_not_found_refuses_the_report_and_writes_nothing() -> None:
    events: list[str] = []
    unit = _Unit(events, ScopeId.tenant(TENANT_A), role=None)
    with bind_tenant(TENANT_A), pytest.raises(NotFound, match=PERFORMER_NOT_FOUND):
        await _use_case(lambda: unit, events).execute(
            _command(_actor(TENANT_A), performer_role_id="role-unknown")
        )
    assert events == ["early-get", "lock", "unit-get", "service", "role"]


async def test_a_performer_of_another_person_refuses_the_report_and_writes_nothing() -> None:
    events: list[str] = []
    unit = _Unit(events, ScopeId.tenant(TENANT_A), role=_role(practitioner_id="prac-2"))
    with bind_tenant(TENANT_A), pytest.raises(NotFound, match=PERFORMER_NOT_FOUND):
        await _use_case(lambda: unit, events).execute(
            _command(_actor(TENANT_A), performer_role_id="role-1")
        )
    assert events[-1] == "role"


# -- the performer rule ------------------------------------------------------------------------


def test_the_owner_of_the_role_may_be_the_performer() -> None:
    check_performer(_role(), service_id="ucr-west", actor=_actor(), now=NOW)


def test_the_practitioner_covering_the_role_may_be_the_performer() -> None:
    covered = _role(
        practitioner_id="prac-owner",
        covered_by_practitioner_id="prac-1",
        covered_until=datetime(2026, 10, 24, tzinfo=UTC),
    )
    check_performer(covered, service_id="ucr-west", actor=_actor(practitioner="prac-1"), now=NOW)


def test_the_owner_of_a_covered_role_may_still_be_the_performer() -> None:
    # A reply sent before the cover ended and processed after it must not be refused.
    covered = _role(
        practitioner_id="prac-1",
        covered_by_practitioner_id="prac-2",
        covered_until=datetime(2026, 10, 22, tzinfo=UTC),
    )
    check_performer(covered, service_id="ucr-west", actor=_actor(practitioner="prac-1"), now=NOW)


@pytest.mark.parametrize(
    ("role", "practitioner"),
    [
        (None, "prac-1"),
        (_role(active=False), "prac-1"),
        (_role(service_id="ucr-east"), "prac-1"),
        (_role(service_id=None), "prac-1"),
        (_role(code=PractitionerRoleCode.SHIFT_LEAD), "prac-1"),
        (_role(practitioner_id="prac-2"), "prac-1"),
        (_role(), None),
        (_role(period_start=datetime(2026, 12, 1, tzinfo=UTC)), "prac-1"),
    ],
    ids=[
        "unknown",
        "inactive",
        "another-service",
        "no-service",
        "not-a-reporter-role",
        "another-person",
        "actor-is-no-person",
        "not-started",
    ],
)
def test_any_other_performer_is_one_fixed_not_found(
    role: PractitionerRole | None, practitioner: str | None
) -> None:
    with pytest.raises(NotFound) as refused:
        check_performer(
            role, service_id="ucr-west", actor=_actor(practitioner=practitioner), now=NOW
        )
    assert str(refused.value) == PERFORMER_NOT_FOUND
    assert "role-1" not in str(refused.value)


# -- the tenant's policy reaches the flag rules ------------------------------------------------


def test_the_flag_lookback_is_the_longer_of_the_tenants_two_windows() -> None:
    assert report_lookback() == LOOKBACK == max(MANY_CHANGES_WINDOW, PHONED_WINDOW)
    wide = replace(DEFAULT_POLICY, phoned_window=timedelta(hours=4))
    assert report_lookback(wide) == timedelta(hours=4)
    many = replace(
        DEFAULT_POLICY,
        many_changes_window=timedelta(minutes=30),
        phoned_window=timedelta(minutes=15),
    )
    assert report_lookback(many) == timedelta(minutes=30)
