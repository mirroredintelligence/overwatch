"""AskCapacityNow: the shift lead, an advisor or a clinical advisor (DEC-1377) asks a service for
its capacity figure now (DEC-1335).

The service's queued prompts are cancelled and one is queued to be due now. The prompt sender then
sends the capacity request, records it as the open question so the reply matches it, and schedules
the next prompt from now, as it does for any due prompt. This use case sends nothing itself, and
starts no second chain: a prompt already due is left alone, so a second press sends nothing more.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.ids import IdGenerator
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.scheduling import cancel_work, schedule_work
from overwatch.application.work import SCHEDULED, WorkKind
from overwatch.domain.codes import Role
from overwatch.domain.errors import Conflict, NotAllowed, NotFound

AUDIT_ACTION = "ask-capacity"
USE_CASE = "AskCapacityNow"
ASK_ROLES: Final = (Role.LEAD, Role.ADVISOR, Role.ADVISOR_V2, Role.CLINICAL)
NOT_ASKER = (
    "only the shift lead, an advisor or a clinical advisor may ask a service for its capacity"
)
NO_SERVICE = "no service with this id"
NOT_ACTIVE = "this service is not active"
ALREADY_DUE = "a capacity request is already due for this service"


@dataclass(frozen=True, slots=True)
class AskCapacityResult:
    service_id: str
    due_at: datetime


class AskCapacityNow:
    def __init__(self, uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock

    async def execute(self, actor: Actor, service_id: str) -> AskCapacityResult:
        if actor.role not in ASK_ROLES:
            raise NotAllowed(NOT_ASKER)
        if actor.role is Role.LEAD and actor.practitioner_id is None:
            raise NotAllowed(NOT_ASKER)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            profile = await uow.services.get(service_id)
            if profile is None:
                raise NotFound(NO_SERVICE)
            if not profile.active:
                raise Conflict(NOT_ACTIVE)
            queued = [
                work
                for work in await uow.scheduled_work.for_about(service_id)
                if work.kind is WorkKind.PROMPT_DUE and work.status == SCHEDULED
            ]
            if any(work.due_at <= now for work in queued):
                raise Conflict(ALREADY_DUE)
            for work in queued:
                await cancel_work(uow, work, now)
            await schedule_work(
                uow,
                self._ids,
                kind=WorkKind.PROMPT_DUE,
                about_id=service_id,
                due_at=now,
                now=now,
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=actor,
                    entity_ids=(service_id,),
                    snapshot={"cancelled": len(queued)},
                    at=now,
                )
            )
            await uow.commit()
        return AskCapacityResult(service_id=service_id, due_at=now)
