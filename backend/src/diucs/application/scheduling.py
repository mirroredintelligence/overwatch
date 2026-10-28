"""Shared helpers for timed work (U03). Stub for the red commit (DEC-010)."""

from datetime import datetime

from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.application.work import ScheduledWork, WorkKind


async def schedule_work(
    uow: UnitOfWork,
    ids: IdGenerator,
    *,
    kind: WorkKind,
    about_id: str,
    due_at: datetime,
    now: datetime,
) -> ScheduledWork:
    return ScheduledWork(
        id="stub", kind=kind, due_at=due_at, about_id=about_id, sequence_number=None, status="done"
    )


async def cancel_work(uow: UnitOfWork, work: ScheduledWork, now: datetime) -> None:
    return None
