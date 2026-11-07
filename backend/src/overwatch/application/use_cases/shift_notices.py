"""The two texts about the end of a duty manager's shift (DEC-1341 item 4).

When a person checks in, two jobs are scheduled for their role: one 15 minutes before the planned
end and one 15 minutes after. Each says "your shift ends at ..." or "your shift ended at ...", and
tells the person how to carry on (ON) or finish (OFF). A job acts only while it is still about the
shift it was made for: a shift that was extended, replaced by the next person, or signed off has a
different end (or none), and its old jobs are cancelled and, if one runs anyway, do nothing.

A person on several services gets one text naming them all, not one for each: the text is sent
once for a person and a shift end, whichever of their jobs runs first.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Final

from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.ids import IdGenerator
from overwatch.application.ports.outbound.sealing import ContentSealer
from overwatch.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from overwatch.application.scheduling import cancel_work, schedule_work
from overwatch.application.sealed_send import queue_message
from overwatch.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from overwatch.application.tenant_settings import TenantZones, as_zones
from overwatch.application.work import SCHEDULED, ScheduledWork, WorkKind
from overwatch.domain.codes import Channel, PractitionerRoleCode
from overwatch.domain.messages.catalogue import MessageId
from overwatch.domain.messages.templates import render
from overwatch.domain.model.people import PractitionerRole
from overwatch.domain.rules.london_time import format_hhmm

BEFORE_END: Final = timedelta(minutes=15)
AFTER_END: Final = timedelta(minutes=15)
CONSUMER: Final = "shift-notice"
SHIFT_KINDS: Final = (WorkKind.SHIFT_ENDING, WorkKind.SHIFT_ENDED)


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def planned_end_of(work: ScheduledWork) -> datetime:
    """The shift end a job was scheduled for: its due time is 15 minutes either side of it."""
    if work.kind is WorkKind.SHIFT_ENDING:
        return _utc(work.due_at) + BEFORE_END
    return _utc(work.due_at) - AFTER_END


async def schedule_shift_notices(
    uow: UnitOfWork, ids: IdGenerator, role: PractitionerRole, now: datetime
) -> None:
    """The two jobs for a shift that has just started, in the caller's unit of work."""
    assert role.period_end is not None
    for kind, due in (
        (WorkKind.SHIFT_ENDING, role.period_end - BEFORE_END),
        (WorkKind.SHIFT_ENDED, role.period_end + AFTER_END),
    ):
        await schedule_work(uow, ids, kind=kind, about_id=role.id, due_at=due, now=now)


async def cancel_shift_notices(uow: UnitOfWork, role_id: str, now: datetime) -> None:
    """Cancel the jobs still waiting for a role's shift: it ended, changed or was replaced."""
    for work in await uow.scheduled_work.for_about(role_id):
        if work.kind in SHIFT_KINDS and work.status == SCHEDULED:
            await cancel_work(uow, work, now)


WorkHandler = Callable[[ScheduledWork], Awaitable[None]]


def _scope(uow: UnitOfWork) -> ScopeId:
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


class SendShiftNotice:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        sealer: ContentSealer,
        zones: TenantZones | None = None,
    ) -> None:
        """`zones` gives the tenant's time zone for the end named in the text; the serving process
        passes `DirectoryZones`, and none means Europe/London (the rigs)."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._sealer = sealer
        self._zones = as_zones(zones)

    async def execute(self, work: ScheduledWork) -> None:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            role = await uow.people.get_role(work.about_id)
            if (
                role is None
                or role.code is not PractitionerRoleCode.ROSTER_DUTY_MANAGER
                or not role.active
                or role.period_end is None
                or _utc(role.period_end) != planned_end_of(work)
            ):
                return  # the shift is not the one this job was made for
            ended = _utc(role.period_end) <= _utc(now)
            if (work.kind is WorkKind.SHIFT_ENDING) == ended:
                return  # a "ends at" text after the end, or an "ended at" text before it
            practitioner = await uow.people.get_practitioner(role.practitioner_id)
            if practitioner is None or practitioner.phone_hash is None:
                return
            mine = [
                other
                for other in await uow.people.roster_roles_for_phone_hash(practitioner.phone_hash)
                if other.active
                and other.period_end is not None
                and _utc(other.period_end) == _utc(role.period_end)
                and other.service_id is not None
            ]
            if not mine:
                return
            end_text = _utc(role.period_end).isoformat()
            key = f"shift-notice:{work.kind.value}:{practitioner.id}:{end_text}"
            if not await uow.processed.mark_if_new(key, CONSUMER):
                return  # another of this person's jobs already told them
            names: list[str] = []
            for other in sorted(mine, key=lambda item: item.id):
                profile = await uow.services.get(other.service_id or "")
                if profile is not None and profile.active:
                    names.append(profile.name)
            if not names:
                return
            names.sort()  # the same order in every text, whichever job runs first
            first = min(mine, key=lambda item: item.id)
            zone = await self._zones.zone_of(_scope(uow))
            message = MessageId.S4 if work.kind is WorkKind.SHIFT_ENDING else MessageId.S5
            await queue_message(
                uow,
                self._ids,
                self._sealer,
                scope=_scope(uow),
                rendered=render(
                    message,
                    Channel.TEXT,
                    services=_in_words(names),
                    until=format_hhmm(role.period_end, zone=zone),
                ),
                recipient_role_id=first.id,
                about_id=first.service_id,
                now=now,
            )
            await uow.commit()


def _in_words(names: list[str]) -> str:
    unique = list(dict.fromkeys(names))
    if len(unique) <= 1:
        return "".join(unique)
    return ", ".join(unique[:-1]) + " and " + unique[-1]


def shift_notice_handlers(notice: SendShiftNotice) -> dict[WorkKind, WorkHandler]:
    """The dispatch entries for the two kinds: each stored job runs the notice for itself."""

    async def run(work: ScheduledWork) -> None:
        await notice.execute(work)

    return {WorkKind.SHIFT_ENDING: run, WorkKind.SHIFT_ENDED: run}
