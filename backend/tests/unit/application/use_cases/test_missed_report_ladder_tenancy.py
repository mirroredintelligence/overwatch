"""MissedReportLadder and the tenant's policy and zone (TEN-027, DEC-500; reworks U06, DEC-166).

No Neo4j. The ladder's offsets are the tenant's (a step belongs to the prompt its own offset
earlier), the actor's tenant must be the bound one, and the constructor takes a tenant source for
the link and the zone. The flow on a real graph is in `test_missed_report_ladder_tenants.py`.
"""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.tenancy import ScopeId, TenantMismatch
from diucs.application.tenant_settings import FixedLinkBase, LondonZones
from diucs.application.use_cases.missed_report_ladder import (
    LadderStepCommand,
    MissedReportLadder,
    ladder_due,
    ladder_offsets,
)
from diucs.application.work import SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.codes import Role
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from tests.support.actors import ACTOR_TENANT

DUE = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)
SLOW = dataclasses.replace(
    DEFAULT_POLICY,
    reminder_after=timedelta(minutes=45),
    phone_task_after=timedelta(minutes=75),
    escalate_after=timedelta(minutes=120),
)


def _work(kind: WorkKind, due_at: datetime) -> ScheduledWork:
    return ScheduledWork(
        id="work-1", kind=kind, due_at=due_at, about_id="comm-1", sequence_number=None,
        status=SCHEDULED,
    )  # fmt: skip


def test_the_offsets_are_the_policys() -> None:
    assert ladder_offsets(DEFAULT_POLICY) == {
        WorkKind.REMINDER: timedelta(minutes=30),
        WorkKind.PHONE_TASK: timedelta(minutes=60),
        WorkKind.ESCALATE_TO_LEAD: timedelta(minutes=90),
    }
    assert ladder_offsets(SLOW)[WorkKind.ESCALATE_TO_LEAD] == timedelta(minutes=120)


@pytest.mark.parametrize(
    ("kind", "offset"),
    [
        (WorkKind.REMINDER, timedelta(minutes=45)),
        (WorkKind.PHONE_TASK, timedelta(minutes=75)),
        (WorkKind.ESCALATE_TO_LEAD, timedelta(minutes=120)),
    ],
)
def test_a_step_belongs_to_the_prompt_the_tenants_offset_earlier(
    kind: WorkKind, offset: timedelta
) -> None:
    assert ladder_due(_work(kind, DUE + offset), SLOW) == DUE


def test_with_no_policy_the_default_offsets_apply() -> None:
    assert ladder_due(_work(WorkKind.REMINDER, DUE + timedelta(minutes=30))) == DUE


class _Untouched:
    def __init__(self, scope: ScopeId | None) -> None:
        self.unit_scope = scope

    async def __aenter__(self) -> "_Untouched":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the unit of work was touched: {name}")


def _actor(tenant: str) -> Actor:
    return Actor(
        role=Role.OWNER,
        practitioner_id=None,
        device_id=None,
        channel="scheduler",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


async def test_an_actor_of_another_tenant_is_refused_before_anything_is_read() -> None:
    use_case = MissedReportLadder(
        lambda: _Untouched(ScopeId.tenant(ACTOR_TENANT)),  # type: ignore[arg-type, return-value]
        FixedClock(DUE),
        SequentialIds(),
        lambda repo: None,  # type: ignore[arg-type, return-value]
        FixedLinkBase("diucs.example"),
        None,  # type: ignore[arg-type]
        zones=LondonZones(),
    )
    with pytest.raises(TenantMismatch):
        await use_case.execute(
            LadderStepCommand(idempotency_key="k", actor=_actor("tenant-zzz"), work_id="work-1")
        )


# -- a report stops the ladders of the tenant's offsets ------------------------------------------


class _Works:
    def __init__(self, works: list[ScheduledWork]) -> None:
        self.stored = {work.id: work for work in works}
        self.saved: list[ScheduledWork] = []

    async def for_about(self, about_id: str, kind: WorkKind | None = None) -> list[ScheduledWork]:
        return [w for w in self.stored.values() if w.about_id == about_id and w.kind is kind]

    async def get(self, work_id: str) -> ScheduledWork:
        return self.stored[work_id]

    async def save(self, work: ScheduledWork) -> None:
        self.saved.append(work)


class _Outbox:
    async def add(self, message: Any) -> None:
        return None


class _People:
    async def reporter_roles_for_service(self, service_id: str, now: datetime) -> list[Any]:
        return []


def _uow(works: list[ScheduledWork]) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(scheduled_work=_Works(works), outbox=_Outbox(), people=_People())


async def test_a_report_stops_the_step_of_the_tenants_own_offset() -> None:
    from diucs.application.use_cases.missed_report_ladder import stop_answered_ladders

    step = ScheduledWork(
        id="w-1", kind=WorkKind.REMINDER, due_at=DUE + timedelta(minutes=45),
        about_id="svc-1", sequence_number=None, status=SCHEDULED,
    )  # fmt: skip
    answered_at = DUE + timedelta(minutes=5)

    default = _uow([step])
    assert await stop_answered_ladders(
        default, "svc-1", answered_at=answered_at, now=answered_at
    ) == ()
    slow = _uow([step])
    assert await stop_answered_ladders(
        slow, "svc-1", answered_at=answered_at, now=answered_at, policy=SLOW
    ) == ("w-1",)
