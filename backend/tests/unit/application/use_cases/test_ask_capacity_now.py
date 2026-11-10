"""AskCapacityNow (DEC-1335): queued prompts are replaced by one due now, so the existing sender
sends the request and no second chain starts; a prompt already due is left alone. Samples only."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from overwatch.application.actor import Actor
from overwatch.application.use_cases.ask_capacity_now import (
    ASK_ROLES,
    NOT_ASKER,
    AskCapacityNow,
    AskCapacityResult,
)
from overwatch.application.work import SCHEDULED, ScheduledWork, WorkKind
from overwatch.domain.codes import Role
from overwatch.domain.errors import Conflict, NotAllowed, NotFound

NOW = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)
SERVICE = "svc-1"


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Ids:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"id-{self._n}"


class _Work:
    def __init__(self) -> None:
        self.rows: dict[str, ScheduledWork] = {}

    async def for_about(self, about_id: str) -> list[ScheduledWork]:
        return [row for row in self.rows.values() if row.about_id == about_id]

    async def get(self, work_id: str) -> ScheduledWork:
        return self.rows[work_id]

    async def save(self, work: ScheduledWork) -> None:
        self.rows[work.id] = work

    async def add(self, work: ScheduledWork) -> None:
        self.rows[work.id] = work


class _Outbox:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def add(self, message: Any) -> None:
        self.messages.append(message)


class _Audit:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    async def append(self, entry: Any) -> None:
        self.entries.append(entry)


@dataclass
class _Profile:
    id: str = SERVICE
    active: bool = True


class _Services:
    def __init__(self, profile: _Profile | None) -> None:
        self._profile = profile

    async def get(self, service_id: str) -> _Profile | None:
        return self._profile if self._profile and self._profile.id == service_id else None


class _Uow:
    def __init__(self, profile: _Profile | None, works: _Work) -> None:
        self.services = _Services(profile)
        self.scheduled_work = works
        self.outbox = _Outbox()
        self.audit = _Audit()
        self.committed = False

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


@dataclass
class _World:
    profile: _Profile | None = field(default_factory=_Profile)
    works: _Work = field(default_factory=_Work)
    units: list[_Uow] = field(default_factory=list)

    def factory(self) -> _Uow:
        uow = _Uow(self.profile, self.works)
        self.units.append(uow)
        return uow


def _lead() -> Actor:
    return Actor(
        role=Role.LEAD,
        practitioner_id="prac-lead",
        device_id=None,
        channel="app",
        service_ids=frozenset({SERVICE}),
        tenant_id="tenant-a",
    )


def _prompt(due: datetime, *, status: str = SCHEDULED) -> ScheduledWork:
    return ScheduledWork(
        id=f"work-{due.isoformat()}",
        kind=WorkKind.PROMPT_DUE,
        due_at=due,
        about_id=SERVICE,
        sequence_number=None,
        status=status,
    )


async def test_the_queued_prompt_is_replaced_by_one_due_now() -> None:
    world = _World()
    later = _prompt(NOW + timedelta(hours=1))
    world.works.rows[later.id] = later
    result = await AskCapacityNow(world.factory, _Ids(), _Clock()).execute(_lead(), SERVICE)  # type: ignore[arg-type]
    assert result.due_at == NOW
    assert world.works.rows[later.id].status == "cancelled"
    due_now = [r for r in world.works.rows.values() if r.status == SCHEDULED]
    assert [(r.kind, r.due_at) for r in due_now] == [(WorkKind.PROMPT_DUE, NOW)]
    assert world.units[0].committed


async def test_a_prompt_already_due_is_left_alone_so_a_second_press_sends_nothing_more() -> None:
    world = _World()
    world.works.rows["due"] = _prompt(NOW - timedelta(minutes=1))
    with pytest.raises(Conflict):
        await AskCapacityNow(world.factory, _Ids(), _Clock()).execute(_lead(), SERVICE)  # type: ignore[arg-type]
    assert world.works.rows["due"].status == SCHEDULED
    assert not world.units[0].outbox.messages


async def test_only_the_shift_lead_may_ask() -> None:
    world = _World()
    reporter = Actor(
        role=Role.REPORTER,
        practitioner_id="prac-rep",
        device_id=None,
        channel="text",
        service_ids=frozenset({SERVICE}),
        tenant_id="tenant-a",
    )
    with pytest.raises(NotAllowed):
        await AskCapacityNow(world.factory, _Ids(), _Clock()).execute(reporter, SERVICE)  # type: ignore[arg-type]


async def test_an_unknown_or_inactive_service_is_refused() -> None:
    with pytest.raises(NotFound):
        await AskCapacityNow(_World(profile=None).factory, _Ids(), _Clock()).execute(
            _lead(), SERVICE
        )  # type: ignore[arg-type]
    with pytest.raises(Conflict):
        await AskCapacityNow(
            _World(profile=_Profile(active=False)).factory, _Ids(), _Clock()
        ).execute(_lead(), SERVICE)  # type: ignore[arg-type]


def _actor(role: Role, practitioner: str | None) -> Actor:
    return Actor(
        role=role,
        practitioner_id=practitioner,
        device_id=None,
        channel="app",
        service_ids=frozenset(),
        tenant_id="tenant-a",
    )


async def _ask(world: _World, actor: Actor) -> AskCapacityResult:
    return await AskCapacityNow(world.factory, _Ids(), _Clock()).execute(actor, SERVICE)  # type: ignore[arg-type]


@pytest.mark.parametrize("role", list(ASK_ROLES))
async def test_the_four_roles_may_ask_and_the_actor_is_audited(role: Role) -> None:
    world = _World()
    actor = _actor(role, "prac-1")
    await _ask(world, actor)
    (entry,) = world.units[0].audit.entries
    assert entry.actor == actor
    assert entry.entity_ids == (SERVICE,)


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.ADVISOR_V2, Role.CLINICAL])
async def test_an_advisor_or_clinical_actor_needs_no_practitioner(role: Role) -> None:
    world = _World()
    result = await _ask(world, _actor(role, None))
    assert result.due_at == NOW
    assert world.units[0].audit.entries[0].actor.practitioner_id is None


async def test_the_shift_lead_still_needs_a_practitioner() -> None:
    with pytest.raises(NotAllowed):
        await _ask(_World(), _actor(Role.LEAD, None))


@pytest.mark.parametrize(
    "role", [Role.REPORTER, Role.WALL, Role.OWNER, Role.EXEC, Role.ANALYTICS_USER]
)
async def test_the_other_roles_are_refused_with_the_roles_named(role: Role) -> None:
    world = _World()
    with pytest.raises(NotAllowed) as refused:
        await _ask(world, _actor(role, "prac-1"))
    assert str(refused.value) == NOT_ASKER
    assert "shift lead, an advisor or a clinical advisor" in NOT_ASKER
    assert not world.units
