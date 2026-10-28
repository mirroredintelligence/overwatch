"""Shared helpers for timed work (U03, DEC-115).

A use case never calls the event bus. It calls schedule_work or cancel_work inside its unit of
work. schedule_work writes a ScheduledWork row (status scheduled) and a ScheduleWork outbox message
on the scheduled.work queue. cancel_work sets the row cancelled and adds a CancelWork message. The
outbox relay (I03) makes the bus calls and stores the sequence number on the row. Handlers ignore
work that is not scheduled.

Every instant is converted to UTC before it is stored or sent, so a London time that falls in the
clock change names one real instant (lessons L4 and L52).
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Final

from diucs.application.idempotency import format_instant
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.application.work import CANCELLED, SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.errors import ValidationFailed

SCHEDULED_WORK_TOPIC: Final = "scheduled.work"
SCHEDULE_WORK: Final = "ScheduleWork"
CANCEL_WORK: Final = "CancelWork"


def _utc(field: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


async def schedule_work(
    uow: UnitOfWork,
    ids: IdGenerator,
    *,
    kind: WorkKind,
    about_id: str,
    due_at: datetime,
    now: datetime,
) -> ScheduledWork:
    """Write one scheduled job and its ScheduleWork message in the caller's unit of work. The
    caller commits. The row has no sequence number until the relay has scheduled the message."""
    due = _utc("due_at", due_at)
    created = _utc("now", now)
    work = ScheduledWork(
        id=ids.new_id(),
        kind=kind,
        due_at=due,
        about_id=about_id,
        sequence_number=None,
        status=SCHEDULED,
    )
    await uow.scheduled_work.add(work)
    await uow.outbox.add(
        OutboxMessage(
            id=ids.new_id(),
            topic=SCHEDULED_WORK_TOPIC,
            event_type=SCHEDULE_WORK,
            payload={
                "work_id": work.id,
                "kind": kind.value,
                "about_id": about_id,
                "enqueue_at": format_instant(due),
            },
            created_at=created,
        )
    )
    return work


async def cancel_work(uow: UnitOfWork, work: ScheduledWork, now: datetime) -> None:
    """Cancel a scheduled job in the caller's unit of work. The stored row decides, not the copy
    the caller holds: work that is not scheduled (done, or already cancelled) is left alone, and a
    sequence number the relay stored is kept. The message id is derived from the work id, so one
    job is cancelled once."""
    created = _utc("now", now)
    stored = await uow.scheduled_work.get(work.id)
    if stored.status != SCHEDULED:
        return
    await uow.scheduled_work.save(replace(stored, status=CANCELLED))
    await uow.outbox.add(
        OutboxMessage(
            id=f"cancel-{work.id}",
            topic=SCHEDULED_WORK_TOPIC,
            event_type=CANCEL_WORK,
            payload={"work_id": work.id},
            created_at=created,
        )
    )
