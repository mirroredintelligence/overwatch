"""Suspending and resuming a tenant (TEN-073, DEC-507): who may, what is written first, what each
step leaves behind when the next one fails, and that the edge stops the tenant within its cache
interval.

No Neo4j: one recording fake over the tenants the directory and the registry hold, and a
recording unit of work with the few repositories a resume touches
(`tests/support/provisioning_fakes`). The flow on a real graph, with a second tenant that is never
touched, is `tests/integration/application/test_tenant_suspend.py`.
"""

import dataclasses
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from diucs.adapters.inbound.fhir_rest.tenant_gate import RECORD_TTL, TenantGate
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.tenancy import ScopeId, TenantMismatch, TenantNotBound
from diucs.application.use_cases.tenant_suspend import (
    ResumeTenant,
    ResumeTenantCommand,
    SuspendTenant,
    SuspendTenantCommand,
    resume_event_id,
    resume_marker,
)
from diucs.application.work import CANCELLED, SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
    Status,
)
from diucs.domain.errors import Conflict, InvalidTransition, NotFound, ValidationFailed
from diucs.domain.events import StatusChanged
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant import SuspendMode, SuspendReason, TenantStatus
from diucs.domain.rules.bff_token import BffClaims
from diucs.domain.rules.edge_access import EdgeVerdict
from tests.support.provisioning_fakes import (
    NOW,
    OTHER,
    TENANT,
    FakePlatform,
    FakeUnit,
    FakeWorld,
    FixedNow,
    operator,
    provisioning_tenant,
)
from tests.support.tenancy import as_tenant

OPERATOR = "operator-1"
NEW_YORK = ZoneInfo("America/New_York")


def _active(**fields: Any) -> Any:
    base: dict[str, Any] = {"status": TenantStatus.ACTIVE, "activated_at": NOW}
    return provisioning_tenant(**{**base, **fields})


def _suspended(mode: SuspendMode = SuspendMode.BLOCKED, epoch: int = 2) -> Any:
    return _active(
        status=TenantStatus.SUSPENDED,
        suspended_at=NOW,
        suspend_mode=mode,
        suspend_reason=SuspendReason.SECURITY_INCIDENT,
        epoch=epoch,
    )


def _suspend(platform: FakePlatform, world: FakeWorld, on_changed: Any = ()) -> SuspendTenant:
    return SuspendTenant(platform, platform, world.factory(), FixedNow(), on_changed)  # type: ignore[arg-type]


def _command(**fields: Any) -> SuspendTenantCommand:
    base: dict[str, Any] = {
        "actor": operator(),
        "mode": SuspendMode.BLOCKED,
        "reason": SuspendReason.SECURITY_INCIDENT,
    }
    return SuspendTenantCommand(**{**base, **fields})


# -- who may -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", [r for r in Role if r is not Role.PLATFORM_OPERATOR], ids=lambda r: r.value
)
async def test_only_the_platform_operator_suspends(role: Role) -> None:
    from diucs.domain.errors import NotAllowed

    platform, world = FakePlatform(_active()), FakeWorld()
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _suspend(platform, world).execute(_command(actor=operator(role=role)))
    assert platform.calls == [] and world.opened == 0


async def test_an_unnamed_operator_and_one_of_another_tenant_are_refused_first() -> None:
    from diucs.domain.errors import NotAllowed

    platform, world = FakePlatform(_active()), FakeWorld()
    with as_tenant(TENANT):
        with pytest.raises(NotAllowed):
            await _suspend(platform, world).execute(_command(actor=operator(ref=None)))
        with pytest.raises(TenantMismatch):
            await _suspend(platform, world).execute(_command(actor=operator(OTHER)))
    with pytest.raises(TenantNotBound):
        await _suspend(platform, world).execute(_command())
    assert platform.calls == [] and world.opened == 0


# -- SuspendTenant -------------------------------------------------------------------------------


async def test_an_active_tenant_is_suspended_with_its_mode_reason_and_a_new_epoch() -> None:
    platform, world = FakePlatform(_active()), FakeWorld()

    with as_tenant(TENANT):
        result = await _suspend(platform, world).execute(
            _command(mode=SuspendMode.READ_ONLY, reason=SuspendReason.CLINICAL_SAFETY)
        )

    stored = platform.tenants[TENANT]
    assert stored.status is TenantStatus.SUSPENDED
    assert stored.suspend_mode is SuspendMode.READ_ONLY
    assert stored.suspend_reason is SuspendReason.CLINICAL_SAFETY
    assert stored.suspended_at == NOW
    assert stored.epoch == 2 and result.epoch == 2  # a token issued before is now behind
    assert platform.calls == [("save", (TENANT, 1, TenantStatus.ACTIVE, TenantStatus.SUSPENDED))]
    assert world.audited() == ["SuspendTenant"]
    assert world.audit[0].snapshot == {"mode": "read-only", "reason": "clinical-safety", "epoch": 2}


async def test_the_record_is_written_before_anything_else_and_the_serving_process_is_told() -> None:
    platform, world = FakePlatform(_active()), FakeWorld()
    order: list[str] = []

    def told(tenant_id: str) -> None:
        order.append(f"told:{tenant_id}:{platform.tenants[tenant_id].status.value}")

    with as_tenant(TENANT):
        await _suspend(platform, world, (told,)).execute(_command())

    # By the time the process is told, the record already says suspended; the audit comes after.
    assert order == [f"told:{TENANT}:suspended"]
    assert world.audit and world.opened == 1


@pytest.mark.parametrize("mode", ["blocked", "read-only", None])
async def test_a_mode_or_reason_that_is_not_an_exact_member_is_refused_and_nothing_is_written(
    mode: Any,
) -> None:
    platform, world = FakePlatform(_active()), FakeWorld()
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await _suspend(platform, world).execute(_command(mode=mode))
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await _suspend(platform, world).execute(_command(reason="a free text reason"))
    assert platform.calls == [] and world.audit == []


@pytest.mark.parametrize(
    "status",
    [TenantStatus.PROVISIONING, TenantStatus.SUSPENDED, TenantStatus.OFFBOARDING],
)
async def test_only_an_active_tenant_is_suspended(status: TenantStatus) -> None:
    extra: dict[str, Any] = {}
    if status is TenantStatus.SUSPENDED:
        stored = _suspended()
    elif status is TenantStatus.OFFBOARDING:
        stored = _active(status=status, offboarding_started_at=NOW)
    else:
        stored = provisioning_tenant(**extra)
    platform, world = FakePlatform(stored), FakeWorld()
    with as_tenant(TENANT), pytest.raises(InvalidTransition):
        await _suspend(platform, world).execute(_command())
    assert platform.calls == [] and world.audit == []


async def test_a_tenant_nobody_created_is_not_found() -> None:
    platform, world = FakePlatform(), FakeWorld()
    with as_tenant(TENANT), pytest.raises(NotFound):
        await _suspend(platform, world).execute(_command())


async def test_a_record_that_moved_since_it_was_read_is_a_conflict_and_nobody_is_told() -> None:
    platform, world = FakePlatform(_active()), FakeWorld()
    platform.reject_save = True
    told: list[str] = []
    with as_tenant(TENANT), pytest.raises(Conflict):
        await _suspend(platform, world, (told.append,)).execute(_command())
    assert told == [] and world.audit == []
    assert platform.tenants[TENANT].status is TenantStatus.ACTIVE


# -- the edge stops the tenant within the cache interval -----------------------------------------


def _claims(epoch: int) -> BffClaims:
    return BffClaims(
        sub="prac-1",
        role=Role.LEAD,
        services=frozenset(),
        expires_at=NOW + timedelta(hours=8),
        tenant=TENANT,
        epoch=epoch,
    )


def test_the_cache_interval_is_at_most_a_minute() -> None:
    """A suspension takes effect within this, never at a token's expiry: lengthening it is a
    decision about how long a suspended tenant's staff may go on working."""
    assert timedelta(seconds=60) >= RECORD_TTL


async def test_a_suspended_tenants_token_is_refused_within_the_cache_interval() -> None:
    platform, world = FakePlatform(_active()), FakeWorld()
    clock = FixedClock(NOW)
    gate = TenantGate(platform, clock)  # type: ignore[arg-type]
    token = _claims(epoch=1)
    assert await gate.verdict(token, "GET") is EdgeVerdict.ALLOWED  # the record is now cached

    with as_tenant(TENANT):
        await _suspend(platform, world).execute(_command())

    # Another process (or this one, had nobody told it) still holds the cached record ...
    clock.set(NOW + RECORD_TTL - timedelta(seconds=1))
    assert await gate.verdict(token, "GET") is EdgeVerdict.ALLOWED
    # ... and reads it again by the time the interval has passed.
    clock.set(NOW + RECORD_TTL)
    assert await gate.verdict(token, "GET") is EdgeVerdict.REFUSED


async def test_the_serving_process_that_is_told_refuses_at_once() -> None:
    platform, world = FakePlatform(_active()), FakeWorld()
    gate = TenantGate(platform, FixedClock(NOW))  # type: ignore[arg-type]
    assert await gate.verdict(_claims(epoch=1), "GET") is EdgeVerdict.ALLOWED

    with as_tenant(TENANT):
        await _suspend(platform, world, (gate.forget,)).execute(_command())

    assert await gate.verdict(_claims(epoch=1), "GET") is EdgeVerdict.REFUSED
    assert await gate.verdict(_claims(epoch=2), "POST") is EdgeVerdict.REFUSED


async def test_a_read_only_suspension_lets_the_tenant_administrator_read_and_nothing_else() -> None:
    platform, world = FakePlatform(_active()), FakeWorld()
    gate = TenantGate(platform, FixedClock(NOW))  # type: ignore[arg-type]
    with as_tenant(TENANT):
        await _suspend(platform, world, (gate.forget,)).execute(
            _command(mode=SuspendMode.READ_ONLY)
        )
    admin = dataclasses.replace(_claims(epoch=2), role=Role.TENANT_ADMIN)
    lead = _claims(epoch=2)
    assert await gate.verdict(admin, "GET") is EdgeVerdict.ALLOWED
    assert await gate.verdict(admin, "POST") is EdgeVerdict.REFUSED
    assert await gate.verdict(lead, "GET") is EdgeVerdict.REFUSED


async def test_a_token_from_before_a_suspension_stays_refused_after_the_resume() -> None:
    scene = _Scene()
    scene.platform.tenants[TENANT] = _active()
    gate = TenantGate(scene.platform, FixedClock(NOW))  # type: ignore[arg-type]
    suspend = SuspendTenant(
        scene.platform,
        scene.platform,
        scene.factory(),
        FixedNow(),
        (gate.forget,),  # type: ignore[arg-type]
    )
    with as_tenant(TENANT):
        await suspend.execute(_command())
        await _resume(scene.platform, scene.world, (gate.forget,), scene=scene).execute(
            ResumeTenantCommand(operator())
        )

    assert scene.platform.tenants[TENANT].epoch == 3
    assert await gate.verdict(_claims(epoch=1), "GET") is EdgeVerdict.REFUSED  # before the suspend
    assert await gate.verdict(_claims(epoch=2), "GET") is EdgeVerdict.REFUSED  # during it
    assert await gate.verdict(_claims(epoch=3), "GET") is EdgeVerdict.ALLOWED  # signed in again


# -- ResumeTenant ---------------------------------------------------------------------------------

PROFILE = ServiceProfile(
    id="svc-a",
    name="Service A",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals in the next 2 hrs",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(2, 0), time(23, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)


class _Services:
    def __init__(self, *profiles: ServiceProfile) -> None:
        self._profiles = list(profiles)

    async def list_active(self) -> list[ServiceProfile]:
        return list(self._profiles)


class _Flags:
    def __init__(self, flags: dict[str, list[ServiceFlag]]) -> None:
        self._flags = flags

    async def service_flags(self, service_id: str) -> list[ServiceFlag]:
        return self._flags.get(service_id, [])


class _Works:
    def __init__(self, works: list[ScheduledWork]) -> None:
        self.stored = {w.id: w for w in works}

    async def for_about(self, about_id: str, kind: WorkKind | None = None) -> list[ScheduledWork]:
        return [w for w in self.stored.values() if w.about_id == about_id and w.kind is kind]

    async def get(self, work_id: str) -> ScheduledWork:
        return self.stored[work_id]

    async def save(self, work: ScheduledWork) -> None:
        self.stored[work.id] = work

    async def add(self, work: ScheduledWork) -> None:
        self.stored[work.id] = work


class _Capacity:
    def __init__(self, latest: dict[str, CapacityReport]) -> None:
        self._latest = latest

    async def latest(self, service_id: str) -> CapacityReport | None:
        return self._latest.get(service_id)


class _Bookings:
    async def confirmed_since(self, service_id: str, since: datetime) -> list[datetime]:
        return []


class _Outbox:
    def __init__(self) -> None:
        self.every: list[Any] = []

    @property
    def added(self) -> list[Any]:
        """The StatusChanged messages: the scheduling messages of the prompts are not these."""
        return [m for m in self.every if m.event_type == "StatusChanged"]

    async def add(self, message: Any) -> None:
        self.every.append(message)


class _Idempotency:
    def __init__(self) -> None:
        self.stored: dict[str, object] = {}

    async def get(self, key: str) -> object | None:
        return self.stored.get(key)

    async def put(self, key: str, value: object) -> None:
        self.stored[key] = value


class _Scene:
    """What the tenant's scope holds when it is resumed."""

    def __init__(
        self,
        services: tuple[ServiceProfile, ...] = (PROFILE,),
        works: tuple[ScheduledWork, ...] = (),
        flags: dict[str, list[ServiceFlag]] | None = None,
        latest: dict[str, CapacityReport] | None = None,
    ) -> None:
        self.platform = FakePlatform(_suspended())
        self.world = FakeWorld()
        self.services = _Services(*services)
        self.flags = _Flags(flags or {})
        self.works = _Works(list(works))
        self.capacity = _Capacity(latest or {})
        self.outbox = _Outbox()
        self.idempotency = _Idempotency()

    def factory(self) -> Any:
        def make() -> FakeUnit:
            from diucs.application.tenancy import current_scope_or_none

            unit = FakeUnit(self.world, current_scope_or_none())
            unit.services = self.services  # type: ignore[attr-defined]
            unit.flags = self.flags  # type: ignore[attr-defined]
            unit.scheduled_work = self.works  # type: ignore[attr-defined]
            unit.capacity = self.capacity  # type: ignore[attr-defined]
            unit.bookings = _Bookings()  # type: ignore[attr-defined]
            unit.outbox = self.outbox  # type: ignore[attr-defined]
            unit.idempotency = self.idempotency  # type: ignore[attr-defined]
            return unit

        return make


def _resume(
    platform: FakePlatform, world: FakeWorld, on_changed: Any = (), **kw: Any
) -> ResumeTenant:
    scene = kw.pop("scene", None)
    factory = world.factory() if scene is None else scene.factory()
    return ResumeTenant(  # type: ignore[arg-type]
        platform, platform, factory, SequentialIds(), FixedNow(), kw.get("zones"), on_changed
    )


def _prompt(work_id: str, due: datetime, status: str = SCHEDULED) -> ScheduledWork:
    return ScheduledWork(
        id=work_id,
        kind=WorkKind.PROMPT_DUE,
        due_at=due,
        about_id="svc-a",
        sequence_number=None,
        status=status,
    )


async def _run_resume(scene: _Scene, **kw: Any) -> Any:
    use_case = _resume(scene.platform, scene.world, scene=scene, **kw)
    with as_tenant(TENANT):
        return await use_case.execute(ResumeTenantCommand(operator()))


async def test_a_suspended_tenant_is_resumed_with_its_services_prompted_and_announced() -> None:
    scene = _Scene()

    result = await _run_resume(scene)

    stored = scene.platform.tenants[TENANT]
    assert stored.status is TenantStatus.ACTIVE and stored.epoch == 3
    assert (stored.suspend_mode, stored.suspend_reason, stored.suspended_at) == (None,) * 3
    assert (result.services_prompted, result.services_announced) == (1, 1)
    # The record is written once, last, from the suspended record as read.
    assert scene.platform.calls == [
        ("save", (TENANT, 2, TenantStatus.SUSPENDED, TenantStatus.ACTIVE))
    ]
    [prompt] = [w for w in scene.works.stored.values() if w.kind is WorkKind.PROMPT_DUE]
    assert prompt.status == SCHEDULED and prompt.due_at > NOW
    assert prompt.about_id == "svc-a"
    assert scene.world.audited() == ["ResumeTenant"]


async def test_the_next_prompt_is_the_services_own_next_due_time_in_the_tenants_zone() -> None:
    from diucs.domain.rules.schedule import next_due

    class _Zones:
        async def zone_of(self, scope: ScopeId) -> ZoneInfo:
            return NEW_YORK

    # Once a day at noon: noon in New York is not noon in London, so the zone shows in the instant.
    noon = dataclasses.replace(
        PROFILE,
        cadence=Cadence.ONCE_A_DAY,
        available_times=(AvailableTime.every_day(time(12, 0), time(20, 0)),),
    )
    scene = _Scene(services=(noon,))
    await _run_resume(scene, zones=_Zones())

    [prompt] = [w for w in scene.works.stored.values() if w.kind is WorkKind.PROMPT_DUE]
    from diucs.domain.model.tenant_policy import DEFAULT_POLICY

    assert prompt.due_at == next_due(noon, NOW, DEFAULT_POLICY, NEW_YORK)
    assert prompt.due_at != next_due(noon, NOW)  # not London's: the zone reached the rule


async def test_a_prompt_that_fell_due_during_the_suspension_is_cancelled_and_replaced() -> None:
    stale = _prompt("work-stale", NOW - timedelta(hours=2))
    scene = _Scene(works=(stale,))

    result = await _run_resume(scene)

    assert scene.works.stored["work-stale"].status == CANCELLED
    [fresh] = [
        w
        for w in scene.works.stored.values()
        if w.id != "work-stale" and w.kind is WorkKind.PROMPT_DUE
    ]
    assert fresh.status == SCHEDULED and fresh.due_at > NOW
    assert result.services_prompted == 1


async def test_a_prompt_still_ahead_is_kept_and_no_second_one_is_made() -> None:
    ahead = _prompt("work-ahead", NOW + timedelta(hours=1))
    scene = _Scene(works=(ahead,))

    result = await _run_resume(scene)

    prompts = [w for w in scene.works.stored.values() if w.kind is WorkKind.PROMPT_DUE]
    assert [w.id for w in prompts] == ["work-ahead"] and prompts[0].status == SCHEDULED
    assert result.services_prompted == 0 and result.services_announced == 1


async def test_a_service_the_lead_suspended_stays_suspended() -> None:
    flag = ServiceFlag(
        service_id="svc-a", code=SERVICE_FLAG_SUSPENDED, active=True, reason="other",
        actor_id="prac-lead", at=NOW - timedelta(days=1),
    )  # fmt: skip
    scene = _Scene(flags={"svc-a": [flag]})

    result = await _run_resume(scene)

    assert result.services_prompted == 0 and result.services_announced == 0
    assert [w for w in scene.works.stored.values() if w.kind is WorkKind.PROMPT_DUE] == []
    assert scene.outbox.added == []
    assert scene.platform.tenants[TENANT].status is TenantStatus.ACTIVE  # the tenant itself is back


async def test_each_service_gets_a_status_changed_from_not_updated_to_what_it_reads_now() -> None:
    fresh = CapacityReport(
        id="obs-1",
        service_id="svc-a",
        value=4,
        measure=PROFILE.measure,
        effective_at=NOW - timedelta(minutes=10),
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )
    scene = _Scene(latest={"svc-a": fresh})

    await _run_resume(scene)

    [message] = scene.outbox.added
    assert message.id == resume_event_id(3, "svc-a") == "tenant-resume-3-svc-a"
    event = StatusChanged.decode(message.payload)
    assert event.before is Status.NOT_UPDATED and event.after is not Status.NOT_UPDATED
    assert event.service_id == "svc-a" and event.at == NOW


async def test_a_service_with_no_figure_reads_not_updated() -> None:
    scene = _Scene()
    await _run_resume(scene)
    [message] = scene.outbox.added
    assert StatusChanged.decode(message.payload).after is Status.NOT_UPDATED


async def test_a_resume_that_stopped_before_the_record_is_finished_without_repeating_its_work() -> (
    None
):
    scene = _Scene()
    scene.platform.reject_save = True
    with pytest.raises(Conflict):
        await _run_resume(scene)
    assert resume_marker(ScopeId.tenant(TENANT), 2) in scene.idempotency.stored
    first_prompts = [w.id for w in scene.works.stored.values()]
    first_events = len(scene.outbox.added)

    scene.platform.reject_save = False
    result = await _run_resume(scene)

    assert result.resumed_again is True
    assert [w.id for w in scene.works.stored.values()] == first_prompts  # no second prompt
    assert len(scene.outbox.added) == first_events == 1  # no second event
    assert scene.platform.tenants[TENANT].status is TenantStatus.ACTIVE


async def test_the_tenants_work_is_done_before_the_record_so_a_failure_never_leaves_it_silent() -> (
    None
):
    scene = _Scene()
    scene.platform.reject_save = True
    with pytest.raises(Conflict):
        await _run_resume(scene)
    # The record is still suspended (nothing is served) and the prompts are already waiting.
    assert scene.platform.tenants[TENANT].status is TenantStatus.SUSPENDED
    assert any(w.kind is WorkKind.PROMPT_DUE for w in scene.works.stored.values())


async def test_only_a_suspended_tenant_is_resumed() -> None:
    scene = _Scene()
    scene.platform.tenants[TENANT] = _active()
    with pytest.raises(InvalidTransition):
        await _run_resume(scene)
    assert scene.platform.calls == [] and scene.world.opened == 0


async def test_a_tenant_nobody_created_is_not_found_on_resume() -> None:
    scene = _Scene()
    scene.platform.tenants.clear()
    with pytest.raises(NotFound):
        await _run_resume(scene)


async def test_the_serving_process_is_told_after_the_record_is_active() -> None:
    scene = _Scene()
    seen: list[str] = []

    def told(tenant_id: str) -> None:
        seen.append(scene.platform.tenants[tenant_id].status.value)

    await _run_resume(scene, on_changed=(told,))

    assert seen == ["active"]
