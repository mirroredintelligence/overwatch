"""Starting a tenant's offboarding (TEN-075; the rest of offboarding is TEN-074).

Who may, what is refused, that the notice period starts and the audit says when it ends, that two
operators cannot both start it, that the serving process is told at once, and that the edge then
refuses the tenant's token. No Neo4j: the recording fakes of `tests/support/provisioning_fakes`.
"""

import dataclasses
from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.inbound.fhir_rest.tenant_gate import TenantGate
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.tenancy import TenantMismatch
from diucs.application.use_cases.tenant_offboarding import (
    StartOffboardingCommand,
    StartTenantOffboarding,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.tenant import SuspendMode, SuspendReason, TenantStatus
from diucs.domain.rules.bff_token import BffClaims
from diucs.domain.rules.edge_access import EdgeVerdict
from diucs.domain.rules.tenant_lifecycle import OFFBOARDING_NOTICE
from tests.support.provisioning_fakes import (
    NOW,
    OTHER,
    TENANT,
    FakePlatform,
    FakeWorld,
    FixedNow,
    operator,
    provisioning_tenant,
)
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _active(**fields: Any) -> Any:
    base: dict[str, Any] = {"status": TenantStatus.ACTIVE, "activated_at": NOW}
    return provisioning_tenant(**{**base, **fields})


def _suspended() -> Any:
    return _active(
        status=TenantStatus.SUSPENDED,
        suspended_at=NOW,
        suspend_mode=SuspendMode.READ_ONLY,
        suspend_reason=SuspendReason.CONTRACT,
        epoch=2,
    )


def _use_case(platform: FakePlatform, world: FakeWorld, on_changed: Any = ()) -> Any:
    return StartTenantOffboarding(
        platform,  # type: ignore[arg-type]
        platform,  # type: ignore[arg-type]
        world.factory(),
        FixedNow(),
        on_changed,
    )


def _command(**fields: Any) -> StartOffboardingCommand:
    base: dict[str, Any] = {"actor": operator(), "confirm_tenant_id": TENANT}
    return StartOffboardingCommand(**{**base, **fields})


async def test_an_active_tenant_enters_its_notice_period_and_the_operators_step_is_audited() -> (
    None
):
    platform, world = FakePlatform(_active()), FakeWorld()

    with as_tenant(TENANT):
        result = await _use_case(platform, world).execute(_command())

    stored = platform.tenants[TENANT]
    assert stored.status is TenantStatus.OFFBOARDING
    assert stored.offboarding_started_at == NOW
    assert result.started_at == NOW and result.notice_ends_at == NOW + OFFBOARDING_NOTICE
    (entry,) = world.audit
    assert (entry.use_case, entry.actor.role, entry.actor.practitioner_id) == (
        "StartTenantOffboarding",
        Role.PLATFORM_OPERATOR,
        "operator-1",
    )
    assert entry.snapshot["from"] == "active"
    assert entry.snapshot["noticeEndsAt"] == (NOW + OFFBOARDING_NOTICE).isoformat()
    assert world.commits == 1


async def test_a_suspended_tenant_enters_it_too_and_loses_its_suspension() -> None:
    platform, world = FakePlatform(_suspended()), FakeWorld()

    with as_tenant(TENANT):
        await _use_case(platform, world).execute(_command())

    stored = platform.tenants[TENANT]
    assert stored.status is TenantStatus.OFFBOARDING
    assert (stored.suspend_mode, stored.suspend_reason, stored.suspended_at) == (None, None, None)
    assert world.audit[0].snapshot["from"] == "suspended"


@pytest.mark.parametrize(
    "status",
    [
        TenantStatus.PROVISIONING,
        TenantStatus.OFFBOARDING,
        TenantStatus.OFFBOARDED,
        TenantStatus.PURGED,
    ],
)
async def test_a_tenant_in_any_other_state_is_refused_and_nothing_is_written(
    status: TenantStatus,
) -> None:
    fields: dict[str, Any] = {"status": status}
    if status is not TenantStatus.PROVISIONING:
        fields["activated_at"] = NOW
    if status in (TenantStatus.OFFBOARDING, TenantStatus.OFFBOARDED, TenantStatus.PURGED):
        fields["offboarding_started_at"] = NOW
    if status in (TenantStatus.OFFBOARDED, TenantStatus.PURGED):
        fields["offboarded_at"] = NOW
    if status is TenantStatus.PURGED:
        fields["purged_at"] = NOW
    platform, world = FakePlatform(provisioning_tenant(**fields)), FakeWorld()
    before = platform.tenants[TENANT]

    with as_tenant(TENANT), pytest.raises(InvalidTransition):
        await _use_case(platform, world).execute(_command())

    assert platform.tenants[TENANT] == before and world.audit == []


@pytest.mark.parametrize("confirm", ["", "other-org", "NEW-ORG", None, 5])
async def test_the_operator_must_type_the_tenants_own_id(confirm: Any) -> None:
    platform, world = FakePlatform(_active()), FakeWorld()

    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await _use_case(platform, world).execute(_command(confirm_tenant_id=confirm))

    assert platform.tenants[TENANT].status is TenantStatus.ACTIVE
    assert platform.calls == [] and world.audit == []


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.PLATFORM_OPERATOR])
async def test_only_the_platform_operator_starts_it(role: Role) -> None:
    platform, world = FakePlatform(_active()), FakeWorld()

    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _use_case(platform, world).execute(_command(actor=operator(role=role)))

    assert platform.tenants[TENANT].status is TenantStatus.ACTIVE


async def test_an_operator_with_no_name_is_refused() -> None:
    platform, world = FakePlatform(_active()), FakeWorld()

    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _use_case(platform, world).execute(_command(actor=operator(ref=None)))

    assert platform.tenants[TENANT].status is TenantStatus.ACTIVE


async def test_an_operator_bound_to_another_tenant_is_a_wiring_fault() -> None:
    platform, world = FakePlatform(_active(), _active(id=OTHER)), FakeWorld()

    with as_tenant(OTHER), pytest.raises(TenantMismatch):
        await _use_case(platform, world).execute(_command())

    assert platform.tenants[TENANT].status is TenantStatus.ACTIVE
    assert platform.tenants[OTHER].status is TenantStatus.ACTIVE


async def test_a_tenant_that_is_not_there_is_not_found() -> None:
    platform, world = FakePlatform(), FakeWorld()

    with as_tenant(TENANT), pytest.raises(NotFound):
        await _use_case(platform, world).execute(_command())


async def test_two_operators_who_read_the_same_record_cannot_both_start_it() -> None:
    platform, world = FakePlatform(_active()), FakeWorld()
    platform.reject_save = True

    with as_tenant(TENANT), pytest.raises(Conflict):
        await _use_case(platform, world).execute(_command())

    assert platform.tenants[TENANT].status is TenantStatus.ACTIVE
    assert world.audit == []


async def test_the_serving_process_is_told_at_once_and_only_about_this_tenant() -> None:
    platform, world = FakePlatform(_active(), _active(id=OTHER)), FakeWorld()
    told: list[str] = []

    with as_tenant(TENANT):
        await _use_case(platform, world, (told.append,)).execute(_command())

    assert told == [TENANT]


async def test_a_started_offboarding_is_not_told_when_it_did_not_start() -> None:
    platform, world = FakePlatform(_active()), FakeWorld()
    platform.reject_save = True
    told: list[str] = []

    with as_tenant(TENANT), pytest.raises(Conflict):
        await _use_case(platform, world, (told.append,)).execute(_command())

    assert told == []


async def test_the_edge_refuses_the_tenants_token_after_the_record_is_read_again() -> None:
    platform, world = FakePlatform(_active()), FakeWorld()
    clock = FixedClock(NOW)
    gate = TenantGate(platform, clock)  # type: ignore[arg-type]
    claims = BffClaims(
        sub="prac-1",
        role=Role.TENANT_ADMIN,
        services=frozenset(),
        expires_at=NOW + timedelta(hours=8),
        tenant=TENANT,
        epoch=1,
    )
    assert await gate.verdict(claims, "GET") is EdgeVerdict.ALLOWED

    with as_tenant(TENANT):
        await _use_case(platform, world, (gate.forget,)).execute(_command())

    for role in (Role.TENANT_ADMIN, Role.LEAD, Role.ADVISOR):
        for method in ("GET", "POST"):
            refused = await gate.verdict(dataclasses.replace(claims, role=role), method)
            assert refused is EdgeVerdict.REFUSED
