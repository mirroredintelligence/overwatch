"""MissedReportLadder: the rows of the capacity-loop triage (KI-137, KI-139), on the real Neo4j.

- A reminder that cannot be sent (the reporter's role has ended, the holder has no phone, nobody
  could be texted at all) tells the lead at once. The service is marked Not updated as before, and
  the +90 minute escalation then raises nothing more (KI-139).
- A report cancels the ladder of every prompt it answers, not only the latest prompt of each role
  (KI-137).

Friday 23 October 2026 (BST). Sample values only.
"""

import dataclasses
from collections.abc import Awaitable, Callable

import pytest
from neo4j import AsyncDriver

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.missed_report_ladder import ESCALATED, IGNORED, REMINDED
from diucs.application.work import CANCELLED, DONE, SCHEDULED, WorkKind
from tests.support.ladder_rig import (
    PHONE_HASH_1,
    Rig,
    build_rig,
    london,
    reporter,
    seed_people,
    seed_report,
    virtual_ward,
)

Seed = Callable[..., Awaitable[None]]

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE = "vw-frailty"
FIGURE_AT = london(10, 5)


@pytest.fixture
def rig(uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str) -> Rig:
    return build_rig(uow_factory, neo4j_driver, tenant_id)


# --- KI-139: tell the lead when a reminder cannot be sent ----------------------------------------


@pytest.mark.parametrize("what", ["role-ended", "holder-without-phone", "holder-inactive"])
async def test_a_reminder_that_cannot_be_sent_tells_the_lead_at_once(
    what: str, rig: Rig, seed_service: Seed
) -> None:
    await seed_service(virtual_ward())
    await seed_people(rig.factory, reporter(1, PHONE_HASH_1))
    await seed_report(rig.factory, FIGURE_AT)
    result = await rig.prompt(london(12, 0))
    [prompt] = result.communication_ids
    practitioner, role = reporter(1, PHONE_HASH_1)
    if what == "role-ended":
        role = dataclasses.replace(role, active=False)
    elif what == "holder-without-phone":
        practitioner = dataclasses.replace(practitioner, phone_hash=None)
    else:
        practitioner = dataclasses.replace(practitioner, active=False)
    await seed_people(rig.factory, (practitioner, role))

    reminded = await rig.step(prompt, WorkKind.REMINDER, london(12, 30))

    assert reminded.action == REMINDED and reminded.communication_id is None
    [escalation] = await rig.events("ReportEscalated")
    assert escalation.payload["service_id"] == SERVICE
    assert len(await rig.events("StatusChanged")) == 1  # the board still reads Not updated


async def test_the_escalation_that_follows_raises_nothing_more(
    rig: Rig, seed_service: Seed
) -> None:
    await seed_service(virtual_ward())
    await seed_people(rig.factory, reporter(1, PHONE_HASH_1))
    await seed_report(rig.factory, FIGURE_AT)
    [prompt] = (await rig.prompt(london(12, 0))).communication_ids
    practitioner, role = reporter(1, PHONE_HASH_1)
    await seed_people(rig.factory, (dataclasses.replace(practitioner, phone_hash=None), role))
    await rig.step(prompt, WorkKind.REMINDER, london(12, 30))

    phone = await rig.step(prompt, WorkKind.PHONE_TASK, london(13, 0))
    lead = await rig.step(prompt, WorkKind.ESCALATE_TO_LEAD, london(13, 30))

    assert phone.action != IGNORED  # the advisors are still asked to phone
    assert lead.action == IGNORED
    assert len(await rig.events("ReportEscalated")) == 1


async def test_a_service_nobody_could_be_texted_for_tells_the_lead_at_the_reminder(
    rig: Rig, seed_service: Seed
) -> None:
    await seed_service(virtual_ward())
    await seed_report(rig.factory, FIGURE_AT)
    await rig.prompt(london(12, 0))  # no reporter: the ladder is about the service itself

    reminded = await rig.step(SERVICE, WorkKind.REMINDER, london(12, 30))

    assert reminded.action == REMINDED and reminded.communication_id is None
    assert len(await rig.events("ReportEscalated")) == 1
    lead = await rig.step(SERVICE, WorkKind.ESCALATE_TO_LEAD, london(13, 30))
    assert lead.action == IGNORED
    assert len(await rig.events("ReportEscalated")) == 1


async def test_a_reminder_that_is_sent_does_not_tell_the_lead_early(
    rig: Rig, seed_service: Seed
) -> None:
    await seed_service(virtual_ward())
    await seed_people(rig.factory, reporter(1, PHONE_HASH_1))
    await seed_report(rig.factory, FIGURE_AT)
    [prompt] = (await rig.prompt(london(12, 0))).communication_ids

    reminded = await rig.step(prompt, WorkKind.REMINDER, london(12, 30))

    assert reminded.communication_id is not None
    assert await rig.events("ReportEscalated") == []
    lead = await rig.step(prompt, WorkKind.ESCALATE_TO_LEAD, london(13, 30))
    assert lead.action == ESCALATED
    assert len(await rig.events("ReportEscalated")) == 1


# --- KI-137: a report stops the ladder of every prompt it answers --------------------------------


async def test_a_report_stops_the_ladders_of_every_prompt_it_answers_not_only_the_latest(
    rig: Rig, seed_service: Seed
) -> None:
    await seed_service(virtual_ward())
    await seed_people(rig.factory, reporter(1, PHONE_HASH_1))
    await seed_report(rig.factory, FIGURE_AT)
    [first] = (await rig.prompt(london(12, 0))).communication_ids
    [second] = (await rig.prompt(london(12, 20))).communication_ids

    await rig.report(london(12, 25), 4)

    for prompt in (first, second):
        statuses = {
            kind: (await rig.work(prompt, kind)).status
            for kind in (WorkKind.REMINDER, WorkKind.PHONE_TASK, WorkKind.ESCALATE_TO_LEAD)
        }
        assert set(statuses.values()) == {CANCELLED}, prompt


async def test_a_report_leaves_the_ladder_of_a_prompt_due_after_it(
    rig: Rig, seed_service: Seed
) -> None:
    await seed_service(virtual_ward())
    await seed_people(rig.factory, reporter(1, PHONE_HASH_1))
    await seed_report(rig.factory, FIGURE_AT)
    [first] = (await rig.prompt(london(12, 0))).communication_ids
    [later] = (await rig.prompt(london(12, 20))).communication_ids

    # A figure the lead recorded for 12:10: it answers the 12:00 prompt and not the 12:20 one.
    await rig.report(london(12, 25), 4, effective_at=london(12, 10))

    assert (await rig.work(first, WorkKind.REMINDER)).status == CANCELLED
    assert (await rig.work(later, WorkKind.REMINDER)).status == SCHEDULED


async def test_a_ladder_that_has_run_is_not_touched_by_a_later_report(
    rig: Rig, seed_service: Seed
) -> None:
    await seed_service(virtual_ward())
    await seed_people(rig.factory, reporter(1, PHONE_HASH_1))
    await seed_report(rig.factory, FIGURE_AT)
    [first] = (await rig.prompt(london(12, 0))).communication_ids
    await rig.step(first, WorkKind.REMINDER, london(12, 30))

    await rig.report(london(12, 40), 4)

    assert (await rig.work(first, WorkKind.REMINDER)).status == DONE
