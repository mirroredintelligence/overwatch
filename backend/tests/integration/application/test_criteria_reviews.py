"""Integration tests for the daily criteria review job (U31), on the real Neo4j.

WRITTEN, NOT RUN in the build wave (no Neo4j per build-wave rules); verification runs them.
The "after ConfirmCriteria" case moves review-by forward directly, standing in for U30's confirm
(U30 clears the flag itself; this job only sets it). Sample values only; service "UCR West".
"""

import itertools
from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.criteria_reviews import (
    RunCriteriaReviews,
    RunCriteriaReviewsCommand,
    ensure_daily_schedule,
)
from diucs.application.work import WorkKind
from diucs.domain.codes import Channel, CriteriaStatus, PractitionerRoleCode
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.people import Practitioner, PractitionerRole
from tests.support.ladder_rig import virtual_ward
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

LONDON = ZoneInfo("Europe/London")
SERVICE = "ucr-west"
OWNER_ROLE = "owner-role-1"
# Each job gets its own id prefix, so two jobs at one time never reuse an outbox id (lesson L134).
_RUN_IDS = itertools.count(1)
SECRETS = FixedSecretStore({"link-token": b"link-token-test-secret-0123456789abcdef"})


def london(year: int, month: int, day: int, hour: int = 7) -> datetime:
    return datetime(year, month, day, hour, tzinfo=LONDON).astimezone(UTC)


def _criteria(service: str, review_by: date, role: str = OWNER_ROLE) -> ServiceCriteria:
    return ServiceCriteria(
        id=f"crit-{service}-1",
        service_id=service,
        version=1,
        status=CriteriaStatus.CURRENT,
        age_min=18,
        age_max=None,
        districts=frozenset({"DT4"}),
        accepts=frozenset(),
        excludes=frozenset(),
        review_by=review_by,
        owner_role_id=role,
    )


def _job(uow_factory: UnitOfWorkFactory, at: datetime) -> RunCriteriaReviews:
    return RunCriteriaReviews(
        uow_factory,
        SequentialIds(f"run-{at:%d%H%M}-{next(_RUN_IDS)}"),
        FixedClock(at),
        AesGcmContentSealer(SECRETS),
    )


async def _run(uow_factory: UnitOfWorkFactory, at: datetime, work_id: str):
    return await _job(uow_factory, at).execute(RunCriteriaReviewsCommand(work_id=work_id))


async def _send_messages(uow_factory: UnitOfWorkFactory) -> list:
    async with uow_factory() as uow:
        pending = await uow.outbox.pending(1000)
    return [m for m in pending if m.event_type == "SendMessage"]


async def _scheduled(uow_factory: UnitOfWorkFactory, tenant: str) -> list:
    async with uow_factory() as uow:
        return await uow.scheduled_work.for_about(tenant, WorkKind.CRITERIA_REVIEW_REMINDER)


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    """UCR West with a current criteria version reviewed 12 December 2026, owned by an email
    criteria owner. Its audit head exists for the run tenant."""
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.services.save(virtual_ward(SERVICE, name="UCR West"))
        await uow.people.save_practitioner(
            Practitioner(id="owner-1", active=True, display_name="Owner", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id=OWNER_ROLE,
                practitioner_id="owner-1",
                service_id=SERVICE,
                code=PractitionerRoleCode.CRITERIA_OWNER,
                active=True,
                channel=Channel.EMAIL,
                period_start=london(2026, 10, 1),
            )
        )
        await uow.criteria.add(_criteria(SERVICE, date(2026, 12, 12)))
        await uow.commit()


async def test_a_reminder_is_queued_fourteen_days_before_review_by(
    uow_factory: UnitOfWorkFactory, seeded: None
) -> None:
    result = await _run(uow_factory, london(2026, 11, 28), "work-1")

    assert result.reminders_sent == 1
    assert len(await _send_messages(uow_factory)) == 1


async def test_a_second_run_on_the_same_day_with_a_new_work_id_sends_nothing(
    uow_factory: UnitOfWorkFactory, seeded: None
) -> None:
    await _run(uow_factory, london(2026, 11, 28), "work-1")
    result = await _run(uow_factory, london(2026, 11, 28), "work-2")

    assert result.reminders_sent == 0
    assert len(await _send_messages(uow_factory)) == 1


async def test_after_review_by_the_service_is_flagged_once(
    uow_factory: UnitOfWorkFactory, seeded: None
) -> None:
    first = await _run(uow_factory, london(2026, 12, 13), "work-3")
    second = await _run(uow_factory, london(2026, 12, 13), "work-4")

    async with uow_factory() as uow:
        flags = [f for f in await uow.flags.service_flags(SERVICE) if f.code == "criteria-overdue"]
    assert first.flags_set == 1 and second.flags_set == 0
    assert len(flags) == 1
    assert flags[0].reason == "review-by passed"


async def test_after_criteria_are_confirmed_the_next_run_sets_no_flag(
    uow_factory: UnitOfWorkFactory, seeded: None
) -> None:
    async with uow_factory() as uow:
        current = await uow.criteria.current_for_service(SERVICE)
        assert current is not None
        await uow.criteria.save(replace(current, review_by=date(2027, 3, 13)))
        await uow.commit()

    result = await _run(uow_factory, london(2026, 12, 13), "work-5")

    assert result.flags_set == 0
    async with uow_factory() as uow:
        assert await uow.flags.service_flags(SERVICE) == []


async def test_the_next_run_is_due_at_seven_london_across_the_clock_change(
    uow_factory: UnitOfWorkFactory, tenant_id: str, seeded: None
) -> None:
    await _run(uow_factory, london(2026, 10, 23), "work-6")
    await _run(uow_factory, london(2026, 10, 24), "work-7")

    due = sorted(work.due_at for work in await _scheduled(uow_factory, tenant_id))
    assert due == [
        datetime(2026, 10, 24, 6, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 7, 0, tzinfo=UTC),
    ]


async def test_the_same_work_id_delivered_twice_makes_one_next_run_and_no_reminder(
    uow_factory: UnitOfWorkFactory, tenant_id: str, seeded: None
) -> None:
    await _run(uow_factory, london(2026, 11, 28), "work-8")
    again = await _run(uow_factory, london(2026, 11, 28), "work-8")

    assert again.reminders_sent == 0
    assert len(await _scheduled(uow_factory, tenant_id)) == 1


async def test_the_daily_schedule_is_created_once(
    uow_factory: UnitOfWorkFactory, tenant_id: str, seeded: None
) -> None:
    clock = FixedClock(london(2026, 10, 23))
    ids = SequentialIds("start")
    first = await ensure_daily_schedule(uow_factory, ids, clock)
    second = await ensure_daily_schedule(uow_factory, ids, clock)

    assert (first, second) == (True, False)
    assert len(await _scheduled(uow_factory, tenant_id)) == 1


async def test_a_run_for_tenant_a_never_reminds_or_flags_tenant_b(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    other_tenant_id: str,
    tenant_id: str,
    seeded: None,
) -> None:
    await ensure_audit_heads(neo4j_driver, other_tenant_id)
    async with uow_factory_b() as uow:
        await uow.services.save(virtual_ward("ucr-east", name="UCR East"))
        await uow.criteria.add(_criteria("ucr-east", date(2026, 12, 1), role="none"))
        await uow.commit()

    result = await _run(uow_factory_a, london(2026, 12, 13), "work-b")

    assert result.flags_set == 1
    async with uow_factory_b() as uow:
        assert await uow.flags.service_flags("ucr-east") == []
        assert await uow.outbox.pending(1000) == []
