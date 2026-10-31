"""`ScheduledWorkRepository.save` does not undo a cancel or a finish (KI-89), on real Neo4j.

`save` wrote every field of the copy the caller had read, so a cancel committed between the read
and the save was overwritten with `scheduled`, and the cancelled work ran. The status now moves only
forward from `scheduled`: a work that is done or cancelled keeps its status whatever a stale copy
says, and the rest of the copy (the sequence number the relay stores) is still saved.
"""

import dataclasses
from datetime import UTC, datetime

import pytest

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.work import CANCELLED, DONE, SCHEDULED, ScheduledWork, WorkKind
from tests.support.relay_rig import ListIds

pytestmark = pytest.mark.asyncio(loop_scope="session")

DUE = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


async def _work(factory: UnitOfWorkFactory) -> ScheduledWork:
    async with factory() as uow:
        work = await schedule_work(
            uow,
            ListIds("work-1", "out-1"),
            kind=WorkKind.REMINDER,
            about_id="HealthcareService/svc-1",
            due_at=DUE,
            now=DUE,
        )
        await uow.commit()
    return work


async def _stored(factory: UnitOfWorkFactory) -> ScheduledWork:
    async with factory() as uow:
        return await uow.scheduled_work.get("work-1")


async def test_a_stale_copy_does_not_undo_a_cancel(uow_factory: UnitOfWorkFactory) -> None:
    stale = await _work(uow_factory)
    async with uow_factory() as uow:
        await uow.scheduled_work.save(dataclasses.replace(stale, status=CANCELLED))
        await uow.commit()

    async with uow_factory() as uow:
        # The relay read the work before the cancel, and stores the number it got from the bus.
        await uow.scheduled_work.save(dataclasses.replace(stale, sequence_number=42))
        await uow.commit()

    stored = await _stored(uow_factory)
    assert stored.status == CANCELLED
    assert stored.sequence_number == 42


async def test_a_stale_copy_does_not_undo_a_finish(uow_factory: UnitOfWorkFactory) -> None:
    stale = await _work(uow_factory)
    async with uow_factory() as uow:
        await uow.scheduled_work.save(dataclasses.replace(stale, status=DONE))
        await uow.commit()

    async with uow_factory() as uow:
        await uow.scheduled_work.save(dataclasses.replace(stale, sequence_number=7))
        await uow.commit()

    assert (await _stored(uow_factory)).status == DONE


async def test_a_cancel_does_not_turn_a_finished_work_cancelled(
    uow_factory: UnitOfWorkFactory,
) -> None:
    work = await _work(uow_factory)
    async with uow_factory() as uow:
        await uow.scheduled_work.save(dataclasses.replace(work, status=DONE))
        await uow.commit()

    async with uow_factory() as uow:
        await uow.scheduled_work.save(dataclasses.replace(work, status=CANCELLED))
        await uow.commit()

    assert (await _stored(uow_factory)).status == DONE


@pytest.mark.parametrize("status", [DONE, CANCELLED])
async def test_a_scheduled_work_can_still_be_finished_or_cancelled(
    status: str, uow_factory: UnitOfWorkFactory
) -> None:
    work = await _work(uow_factory)

    async with uow_factory() as uow:
        await uow.scheduled_work.save(dataclasses.replace(work, status=status))
        await uow.commit()

    assert (await _stored(uow_factory)).status == status


async def test_the_sequence_number_is_stored_on_a_scheduled_work(
    uow_factory: UnitOfWorkFactory,
) -> None:
    work = await _work(uow_factory)

    async with uow_factory() as uow:
        await uow.scheduled_work.save(dataclasses.replace(work, sequence_number=9))
        await uow.commit()

    stored = await _stored(uow_factory)
    assert (stored.status, stored.sequence_number) == (SCHEDULED, 9)
