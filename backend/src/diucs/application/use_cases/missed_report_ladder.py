"""MissedReportLadder (U06). STUB (DEC-010): U06 red commit. The real module follows in the next
commit."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.use_cases.send_prompts import LinkTokenServiceFactory
from diucs.application.work import ScheduledWork, WorkKind

REMINDED: Final = "reminded"
PHONE_TASK_RAISED: Final = "phone-task"
ESCALATED: Final = "escalated"
STOPPED: Final = "stopped"
IGNORED: Final = "ignored"

LADDER_KINDS: Final = (WorkKind.REMINDER, WorkKind.PHONE_TASK, WorkKind.ESCALATE_TO_LEAD)
REMINDER_REPLY_WINDOW: Final = timedelta(minutes=0)


@dataclass(frozen=True, slots=True)
class LadderStepCommand:
    idempotency_key: str
    actor: Actor
    work_id: str


@dataclass(frozen=True, slots=True)
class LadderStepResult:
    action: str
    communication_id: str | None = None
    replayed: bool = False


def ladder_due(work: ScheduledWork) -> datetime:
    return work.due_at


def prompt_answered(effective_at: datetime, due: datetime) -> bool:
    return False


async def stop_answered_ladders(
    uow: UnitOfWork, service_id: str, *, answered_at: datetime, now: datetime
) -> tuple[str, ...]:
    return ()


class MissedReportLadder:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        link_tokens: LinkTokenServiceFactory,
        link_base_url: str,
        sealer: ContentSealer,
    ) -> None:
        self._uow_factory = uow_factory

    async def execute(self, command: LadderStepCommand) -> LadderStepResult:
        return LadderStepResult(IGNORED)
