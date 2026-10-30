"""Two-tenant tests for the criteria use cases (U30, DEC-130 to DEC-132, DEC-142).

Tenant A holds a service with criteria and a pending change. Tenant B holds its own service and
its own clinical lead, and nothing else. B must not change A's service (NotFound, because the
service is tenant-scoped and B does not hold it), and B must not approve A's pending version by its
id, nor read A's history.

The criteria statements (Q-CRIT-*) are tenant-scoped (TEN-012, on integration/build), so all three
tests run as ordinary tests. Only tenant A seeds criteria: B holds no criteria of its own, so B's
reads of A's service must come back empty rather than borrow A's rows. Runs on
contracted_container() (DEC-159, lesson L168).
"""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, date, datetime, time

import pytest
import pytest_asyncio
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
from diucs.domain.errors import NotFound
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import wipe_all
from tests.support.tenant_seed import contracted_container

pytestmark = pytest.mark.asyncio(loop_scope="session")

A_SERVICE = "ucr-west-a"
B_SERVICE = "ucr-west"
A_OWNER_ROLE = "role-owner-a"
B_LEAD_ROLE = "role-lead-b"
A_PENDING = "crit-ucr-west-a-4"
TODAY = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
B_LEAD = Actor(
    role=Role.CLINICAL,
    practitioner_id="prac-lead-b",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
A_OWNER = Actor(
    role=Role.OWNER,
    practitioner_id="prac-owner-a",
    device_id=None,
    channel="web",
    service_ids=frozenset({A_SERVICE}),
    tenant_id=ACTOR_TENANT,
)


def _profile(service_id: str) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=service_id.upper(),
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


def _version(number: int, status: CriteriaStatus, *, id_: str | None = None) -> ServiceCriteria:
    return ServiceCriteria(
        id=id_ or f"crit-ucr-west-a-{number}",
        service_id=A_SERVICE,
        version=number,
        status=status,
        age_min=18,
        age_max=None,
        districts=frozenset({"DT4"}),
        accepts=frozenset({NeedCategory.FRAILTY}),
        excludes=frozenset(),
        review_by=date(2026, 6, 1),
        owner_role_id=A_OWNER_ROLE,
        supersedes_id=None if number == 1 else f"crit-ucr-west-a-{number - 1}",
        review_months=3 if status is CriteriaStatus.PENDING_APPROVAL else None,
    )


async def _seed_a(factory: UnitOfWorkFactory) -> None:
    async with factory() as uow:
        await uow.services.save(_profile(A_SERVICE))
        for practitioner in (
            Practitioner(id="prac-owner-a", active=True, display_name="Owner A", phone_hash=None),
            Practitioner(id="prac-lead-a", active=True, display_name="Lead A", phone_hash=None),
        ):
            await uow.people.save_practitioner(practitioner)
        await uow.people.save_role(
            PractitionerRole(
                id=A_OWNER_ROLE,
                practitioner_id="prac-owner-a",
                service_id=A_SERVICE,
                code=PractitionerRoleCode.CRITERIA_OWNER,
                active=True,
                channel=Channel.TEXT,
                period_start=TODAY,
            )
        )
        await uow.commit()
    async with factory() as uow:
        await uow.criteria.add(_version(1, CriteriaStatus.SUPERSEDED))
        await uow.criteria.add(_version(2, CriteriaStatus.SUPERSEDED))
        await uow.criteria.add(_version(3, CriteriaStatus.CURRENT))
        pending = replace(
            _version(4, CriteriaStatus.PENDING_APPROVAL, id_=A_PENDING),
            change_reason="lower youngest age",
            review_by=date(2026, 9, 23),
        )
        await uow.criteria.add(pending)
        await uow.commit()


async def _seed_b(factory: UnitOfWorkFactory) -> None:
    async with factory() as uow:
        await uow.services.save(_profile(B_SERVICE))
        await uow.people.save_practitioner(
            Practitioner(id="prac-lead-b", active=True, display_name="Lead B", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id=B_LEAD_ROLE,
                practitioner_id="prac-lead-b",
                service_id=None,
                code=PractitionerRoleCode.CLINICAL_LEAD,
                active=True,
                channel=None,
                period_start=TODAY,
            )
        )
        await uow.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    return two_tenant_driver


@pytest_asyncio.fixture(loop_scope="session")
async def tenants(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    two_tenant_driver: AsyncDriver,
) -> AsyncIterator[None]:
    await wipe_all(two_tenant_driver)
    await _seed_a(uow_factory_a)
    await _seed_b(uow_factory_b)
    yield
    await wipe_all(two_tenant_driver)


async def test_tenant_b_cannot_change_a_service_it_does_not_hold(
    uow_factory_b: UnitOfWorkFactory, tenants: None
) -> None:
    change = ChangeCriteria(uow_factory_b, SequentialIds(), FixedClock(TODAY))
    with pytest.raises(NotFound):
        await change.execute(
            ChangeCriteriaCommand(
                idempotency_key="b-steal",
                actor=B_LEAD,
                service_id=A_SERVICE,
                values=CriteriaValues(
                    age_min=16,
                    age_max=None,
                    accepts=frozenset({NeedCategory.FRAILTY}),
                    excludes=frozenset(),
                    districts=frozenset({"DT4"}),
                ),
                change_reason="not mine",
                review_months=3,
            )
        )


async def test_tenant_b_cannot_approve_a_pending_version_of_tenant_a_by_its_id(
    uow_factory_b: UnitOfWorkFactory, tenants: None
) -> None:
    approve = ApproveCriteria(uow_factory_b, SequentialIds(), FixedClock(TODAY))
    with pytest.raises(NotFound):
        await approve.execute(
            ApproveCriteriaCommand(
                idempotency_key="b-approve-a",
                actor=B_LEAD,
                criteria_id=A_PENDING,
                decision="approve",
            )
        )
    async with uow_factory_b() as uow:
        assert (await uow.criteria.get(A_PENDING)) is None


async def test_tenant_b_reads_no_history_of_tenant_a(
    uow_factory_b: UnitOfWorkFactory, tenants: None
) -> None:
    views = await CriteriaHistory(uow_factory_b).execute(
        CriteriaHistoryQuery(actor=replace(B_LEAD, role=Role.LEAD), service_id=A_SERVICE)
    )
    assert views == []
