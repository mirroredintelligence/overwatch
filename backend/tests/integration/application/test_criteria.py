"""Integration tests for the criteria use cases (U30), against the real Neo4j the harness starts.

Seeds UCR West with versions 1 to 3 (3 current), the owner and a clinical lead. Every assertion
reads back through a fresh unit of work or the harness helpers. Values are synthetic; there is no
patient data. Times are on Friday 23 October 2026 (London is on BST, one hour ahead of UTC).
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.criteria import (
    ApproveCriteria,
    ApproveCriteriaCommand,
    ChangeCriteria,
    ChangeCriteriaCommand,
    ConfirmCriteria,
    ConfirmCriteriaCommand,
    CriteriaHistory,
    CriteriaHistoryQuery,
    CriteriaValues,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    PractitionerRoleCode,
    Role,
    ServiceCategory,
)
from diucs.domain.errors import Conflict, NotAllowed
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.flags import SERVICE_FLAG_CRITERIA_OVERDUE, ServiceFlag
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile

Seed = Callable[..., Awaitable[None]]
pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE = "ucr-west"
UCR_WEST = ServiceProfile(
    id=SERVICE,
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
OWNER_ROLE = "role-owner-west"
DAY = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
OWNER = Actor(
    role=Role.OWNER,
    practitioner_id="prac-owner",
    device_id=None,
    channel="web",
    service_ids=frozenset({SERVICE}),
)
LEAD = Actor(
    role=Role.CLINICAL,
    practitioner_id="prac-lead",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)


def _values(age_min: int) -> CriteriaValues:
    return CriteriaValues(
        age_min=age_min,
        age_max=None,
        accepts=frozenset({NeedCategory.FRAILTY}),
        excludes=frozenset(),
        districts=frozenset({"DT4"}),
    )


def _version(number: int, status: CriteriaStatus, age_min: int) -> ServiceCriteria:
    return ServiceCriteria(
        id=f"crit-ucr-west-{number}",
        service_id=SERVICE,
        version=number,
        status=status,
        age_min=age_min,
        age_max=None,
        districts=frozenset({"DT4"}),
        accepts=frozenset({NeedCategory.FRAILTY}),
        excludes=frozenset(),
        review_by=date(2026, 6, 1),
        owner_role_id=OWNER_ROLE,
        supersedes_id=None if number == 1 else f"crit-ucr-west-{number - 1}",
    )


@pytest.fixture
def seed_criteria(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> Seed:
    async def seed() -> None:
        await seed_service(UCR_WEST)
        async with uow_factory() as uow:
            for practitioner in (
                Practitioner(id="prac-owner", active=True, display_name="Owner", phone_hash=None),
                Practitioner(id="prac-lead", active=True, display_name="Lead", phone_hash=None),
            ):
                await uow.people.save_practitioner(practitioner)
            await uow.people.save_role(
                PractitionerRole(
                    id=OWNER_ROLE,
                    practitioner_id="prac-owner",
                    service_id=SERVICE,
                    code=PractitionerRoleCode.CRITERIA_OWNER,
                    active=True,
                    channel=Channel.TEXT,
                    period_start=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
            await uow.people.save_role(
                PractitionerRole(
                    id="role-lead",
                    practitioner_id="prac-lead",
                    service_id=None,
                    code=PractitionerRoleCode.CLINICAL_LEAD,
                    active=True,
                    channel=None,
                    period_start=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
            await uow.commit()
        async with uow_factory() as uow:
            await uow.criteria.add(_version(1, CriteriaStatus.SUPERSEDED, 18))
            await uow.criteria.add(_version(2, CriteriaStatus.SUPERSEDED, 18))
            await uow.criteria.add(_version(3, CriteriaStatus.CURRENT, 18))
            await uow.commit()

    return seed


def _change(key: str = "change-1", age_min: int = 16, months: int = 6) -> ChangeCriteriaCommand:
    return ChangeCriteriaCommand(
        idempotency_key=key,
        actor=OWNER,
        service_id=SERVICE,
        values=_values(age_min),
        change_reason="lower youngest age after referral review",
        review_months=months,
    )


def _clock(at: datetime = DAY) -> FixedClock:
    return FixedClock(at)


async def _versions(uow_factory: UnitOfWorkFactory) -> dict[int, ServiceCriteria]:
    async with uow_factory() as uow:
        return {version.version: version for version in await uow.criteria.history(SERVICE)}


async def _current(uow_factory: UnitOfWorkFactory) -> ServiceCriteria | None:
    async with uow_factory() as uow:
        return await uow.criteria.current_for_service(SERVICE)


async def test_the_owner_changes_youngest_age_and_version_four_waits_for_approval(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_criteria: Seed
) -> None:
    await seed_criteria()
    result = await ChangeCriteria(uow_factory, SequentialIds(), _clock()).execute(_change())
    versions = await _versions(uow_factory)
    assert result.version == 4
    assert versions[4].status is CriteriaStatus.PENDING_APPROVAL
    assert versions[4].age_min == 16
    assert versions[4].supersedes_id == "crit-ucr-west-3"
    assert (await _current(uow_factory)).version == 3  # advisors still see version 3


async def test_a_second_change_while_one_is_pending_is_a_conflict_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_criteria: Seed
) -> None:
    await seed_criteria()
    change = ChangeCriteria(uow_factory, SequentialIds(), _clock())
    await change.execute(_change("change-1"))
    with pytest.raises(Conflict):
        await change.execute(_change("change-2", age_min=14))
    assert 5 not in await _versions(uow_factory)


async def test_the_author_approving_their_own_change_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_criteria: Seed
) -> None:
    await seed_criteria()
    changed = await ChangeCriteria(uow_factory, SequentialIds(), _clock()).execute(_change())
    approve = ApproveCriteria(uow_factory, SequentialIds(), _clock())
    with pytest.raises(NotAllowed):
        await approve.execute(
            ApproveCriteriaCommand("approve-own", OWNER, changed.criteria_id, "approve")
        )


async def test_the_clinical_lead_approves_and_version_three_is_superseded_not_deleted(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_criteria: Seed
) -> None:
    await seed_criteria()
    changed = await ChangeCriteria(uow_factory, SequentialIds(), _clock()).execute(_change())
    approved = await ApproveCriteria(uow_factory, SequentialIds(), _clock()).execute(
        ApproveCriteriaCommand("approve-1", LEAD, changed.criteria_id, "approve")
    )
    versions = await _versions(uow_factory)
    assert versions[4].status is CriteriaStatus.CURRENT
    assert versions[3].status is CriteriaStatus.SUPERSEDED
    assert (await _current(uow_factory)).version == 4
    # 23 Oct 2026 in London is 23 Oct; six months after approval is 23 Apr 2027.
    assert approved.review_by == date(2027, 4, 23)
    async with uow_factory() as uow:
        pending = await uow.outbox.pending()
    assert [m.event_type for m in pending].count("CriteriaApproved") == 1


async def test_send_back_returns_the_pending_version_to_draft_and_version_three_stays_current(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_criteria: Seed
) -> None:
    await seed_criteria()
    changed = await ChangeCriteria(uow_factory, SequentialIds(), _clock()).execute(_change())
    await ApproveCriteria(uow_factory, SequentialIds(), _clock()).execute(
        ApproveCriteriaCommand("back-1", LEAD, changed.criteria_id, "send-back", note="more detail")
    )
    assert (await _versions(uow_factory))[4].status is CriteriaStatus.DRAFT
    assert (await _current(uow_factory)).version == 3


async def test_confirming_six_months_sets_review_by_and_clears_the_overdue_flag(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_criteria: Seed
) -> None:
    await seed_criteria()
    async with uow_factory() as uow:
        await uow.flags.set_service_flag(
            ServiceFlag(
                service_id=SERVICE,
                code=SERVICE_FLAG_CRITERIA_OVERDUE,
                active=True,
                reason="review date passed",
                actor_id="system",
                at=DAY,
            )
        )
        await uow.commit()
    confirmed = await ConfirmCriteria(uow_factory, _clock()).execute(
        ConfirmCriteriaCommand("confirm-1", OWNER, SERVICE, review_months=6)
    )
    assert confirmed.review_by == date(2027, 4, 23)
    assert (await _versions(uow_factory))[3].review_by == date(2027, 4, 23)
    async with uow_factory() as uow:
        assert SERVICE not in await uow.flags.services_with_flag(SERVICE_FLAG_CRITERIA_OVERDUE)


async def test_history_returns_versions_four_to_one_newest_first(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_criteria: Seed
) -> None:
    await seed_criteria()
    await ChangeCriteria(uow_factory, SequentialIds(), _clock()).execute(_change())
    views = await CriteriaHistory(uow_factory).execute(CriteriaHistoryQuery(OWNER, SERVICE))
    assert [view.version for view in views] == [4, 3, 2, 1]
    assert {view.author_role_id for view in views} == {OWNER_ROLE}


async def test_a_key_replayed_with_another_command_is_a_conflict(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_criteria: Seed
) -> None:
    await seed_criteria()
    change = ChangeCriteria(uow_factory, SequentialIds(), _clock())
    await change.execute(_change("same-key"))
    with pytest.raises(Conflict):
        await change.execute(_change("same-key", age_min=12))


async def test_a_replayed_change_returns_the_first_result_and_writes_nothing_more(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_criteria: Seed
) -> None:
    await seed_criteria()
    change = ChangeCriteria(uow_factory, SequentialIds(), _clock())
    first = await change.execute(_change("replay"))
    again: Any = await change.execute(_change("replay"))
    assert again.criteria_id == first.criteria_id
    assert again.replayed is True
