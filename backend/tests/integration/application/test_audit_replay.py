"""Integration tests for the audit replay (U42), against the real Neo4j the harness starts.

The audit trail is written through the real audit log with the same entries and snapshot shapes the
use cases write (FilterOptions, OpenCase, RequestBooking, RespondToBooking, RecordOutcome): the full
booking path needs sealing, messaging and the reply processor, which these tests do not run. Each
test seeds committed units of work and reads back through a fresh one (DEC-004). Clock: Friday
23 October 2026, 14:30 London. Synthetic values only; the postcode DT4 8XX never reaches storage.
"""

import dataclasses
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.audit_replay import (
    ExportAuditReplay,
    GetAuditReplay,
    GetAuditReplayCommand,
)
from diucs.domain.codes import (
    AgeBand,
    BookingStatus,
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    ReferrerType,
    Role,
    ServiceCategory,
    Status,
    Urgency,
)
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.booking import Booking
from diucs.domain.model.case import Case
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, read_tx, wipe, write_tx
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 23, 13, 30, tzinfo=UTC)  # 14:30 BST
OPENED = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)  # 14:12 BST
SHOWN = datetime(2026, 10, 23, 13, 13, tzinfo=UTC)  # 14:13 BST
REQUESTED = datetime(2026, 10, 23, 13, 16, tzinfo=UTC)  # 14:16 BST
CONFIRMED = datetime(2026, 10, 23, 13, 19, tzinfo=UTC)  # 14:19 BST
OUTCOME = datetime(2026, 10, 23, 13, 24, tzinfo=UTC)  # 14:24 BST
CASE_ID = "case-4821"
REFERENCE = "4821"
BOOKING_ID = "bk-4821"
UCR_WEST = "svc-ucr-west"
HOME = "svc-hospital-at-home"
WARD_B = "svc-ward-b"
ACTOR = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
ADVISOR = dataclasses.replace(ACTOR, role=Role.ADVISOR, practitioner_id="prac-advisor-1")

Seed = Callable[..., Awaitable[None]]


def _profile(service_id: str, name: str) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=name,
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.every_day_all_day(),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


def _criteria(service_id: str) -> ServiceCriteria:
    return ServiceCriteria(
        id=f"crit-{service_id}-v3",
        service_id=service_id,
        version=3,
        status=CriteriaStatus.CURRENT,
        age_min=18,
        age_max=None,
        districts=frozenset({"DT1", "DT2", "DT3", "DT4"}),
        accepts=frozenset({NeedCategory.FRAILTY}),
        excludes=frozenset(),
        review_by=datetime(2026, 12, 31).date(),
        owner_role_id="role-lead-west",
    )


def _row(service_id: str, status: Status, number: int | None, age: int | None) -> dict[str, object]:
    return {
        "id": service_id,
        "status": status.value,
        "number": number,
        "data_age_seconds": age,
        "criteria_version": 3,
        "shown_as": "option",
    }


SHOWN_ROWS: dict[str, object] = {
    "reference": REFERENCE,
    "services": [
        _row(UCR_WEST, Status.ACCEPTING, 4, 9 * 60),
        # The snapshot holds the used count for an occupied-patients service (DEC-033), not the
        # over-capacity figure: see DEC-391.
        _row(HOME, Status.OVER_CAPACITY, 14, 14 * 60),
        _row(WARD_B, Status.ACCEPTING, 5, 2 * 3600 + 10 * 60),
    ],
}


async def _seed_trail(factory: UnitOfWorkFactory, driver: AsyncDriver, tenant: str) -> None:
    """The case, its services and criteria, its booking, and the audit trail of the case."""
    await ensure_audit_heads(driver, tenant)
    async with factory() as uow:
        for service_id, name in (
            (UCR_WEST, "UCR West"),
            (HOME, "Hospital at home"),
            (WARD_B, "Community hospital · Ward B"),
        ):
            await uow.services.save(_profile(service_id, name))
            await uow.criteria.add(_criteria(service_id))
        await uow.cases.add(
            Case(
                id=CASE_ID,
                reference=REFERENCE,
                referrer_type=ReferrerType.AMBULANCE_CREW,
                age_band=AgeBand.A80_PLUS,
                postcode="DT4",
                needs=(NeedCategory.FRAILTY,),
                urgency=Urgency.WITHIN_2_HRS,
                scores=(),
                opened_at=OPENED,
            )
        )
        await uow.bookings.add(
            Booking(
                id=BOOKING_ID,
                reference="4821B",
                service_id=UCR_WEST,
                case_id=CASE_ID,
                requester_id="role-requester",
                status=BookingStatus.CONFIRMED,
                requested_at=REQUESTED,
                reply_by=REQUESTED + timedelta(minutes=30),
                confirmed_at=CONFIRMED,
            )
        )
        await uow.commit()

    trail = (
        (ACTOR, "C", "OpenCase", (CASE_ID,), None, OPENED),
        (ACTOR, "R", "FilterOptions", (CASE_ID, UCR_WEST, HOME, WARD_B), SHOWN_ROWS, SHOWN),
        (
            ACTOR,
            "C",
            "RequestBooking",
            (BOOKING_ID, UCR_WEST, CASE_ID),
            {"service_id": UCR_WEST, "status": "accepting"},
            REQUESTED,
        ),
        (
            ACTOR,
            "U",
            "RespondToBooking",
            (BOOKING_ID, UCR_WEST),
            {"status": "confirmed", "channel": "text"},
            CONFIRMED,
        ),
        (
            ACTOR,
            "U",
            "RecordOutcome",
            (CASE_ID, UCR_WEST),
            {"outcome": "accepted-and-booked"},
            OUTCOME,
        ),
    )
    async with factory() as uow:
        for actor, action, use_case, entities, snapshot, at in trail:
            await uow.audit.append(
                AuditEntry(
                    action=action,
                    use_case=use_case,
                    actor=actor,
                    entity_ids=entities,
                    snapshot=snapshot,  # type: ignore[arg-type]
                    at=at,
                )
            )
        await uow.commit()


async def _rows(driver: AsyncDriver, query: str) -> list[dict[str, Any]]:
    """A raw read for the test's own checks (not a product statement, so not registered)."""

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(query)
        return [record.data() async for record in result]

    return await read_tx(driver, work)


async def _run(driver: AsyncDriver, query: str) -> None:
    """A raw write for the test's own tampering (not a product statement)."""

    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(query)

    await write_tx(driver, work)


@pytest.fixture
def replay(uow_factory: UnitOfWorkFactory) -> GetAuditReplay:
    return GetAuditReplay(uow_factory, FixedClock(NOW))


@pytest_asyncio.fixture(loop_scope="session")
async def seed_trail(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> Seed:
    async def seed() -> None:
        await _seed_trail(uow_factory, neo4j_driver, tenant_id)

    return seed  # type: ignore[return-value]


async def test_the_rows_are_what_the_advisor_saw(seed_trail: Seed, replay: GetAuditReplay) -> None:
    await seed_trail()
    result = await replay.execute(GetAuditReplayCommand(ACTOR, REFERENCE))
    assert [
        (r.service_name, r.status, r.value_text, r.data_age_text, r.criteria_version)
        for r in result.rows
    ] == [
        ("UCR West", "Accepting", "4", "9 min old", 3),
        ("Hospital at home", "Over capacity", "14", "14 min old", 3),
        ("Community hospital · Ward B", "Accepting", "5", "2 hrs 10 min old", 3),
    ]
    assert result.shown_at == SHOWN
    assert result.chain_ok is True


async def test_the_timeline_is_in_time_order_with_the_options_count(
    seed_trail: Seed, replay: GetAuditReplay
) -> None:
    await seed_trail()
    result = await replay.execute(GetAuditReplayCommand(ACTOR, REFERENCE))
    assert [(item.at, item.label) for item in result.timeline] == [
        (OPENED, "case opened"),
        (SHOWN, "3 options shown"),
        (REQUESTED, "booking request sent"),
        (CONFIRMED, "confirmed by text"),
        (OUTCOME, "outcome recorded"),
    ]


async def test_opening_the_replay_appends_exactly_one_replay_entry(
    seed_trail: Seed, replay: GetAuditReplay, neo4j_driver: AsyncDriver
) -> None:
    await seed_trail()
    await replay.execute(GetAuditReplayCommand(ACTOR, REFERENCE))
    assert await count_nodes(neo4j_driver, "AuditEvent") == 6
    rows = await _rows(
        neo4j_driver,
        "MATCH (e:AuditEvent {useCase: 'AuditReplay', action: 'R'}) RETURN e.id AS id",
    )
    assert len(rows) == 1


async def test_an_advisor_is_refused_and_nothing_is_appended(
    seed_trail: Seed, replay: GetAuditReplay, neo4j_driver: AsyncDriver
) -> None:
    await seed_trail()
    with pytest.raises(NotAllowed):
        await replay.execute(GetAuditReplayCommand(ADVISOR, REFERENCE))
    assert await count_nodes(neo4j_driver, "AuditEvent") == 5


async def test_a_tampered_snapshot_makes_the_chain_fail(
    seed_trail: Seed, replay: GetAuditReplay, neo4j_driver: AsyncDriver
) -> None:
    await seed_trail()
    first = await replay.execute(GetAuditReplayCommand(ACTOR, REFERENCE))
    assert first.chain_ok is True
    await _run(
        neo4j_driver,
        "MATCH (s:Snapshot) WHERE s.json CONTAINS 'svc-hospital-at-home' SET s.json = '{}'",
    )
    second = await replay.execute(GetAuditReplayCommand(ACTOR, REFERENCE))
    assert second.chain_ok is False


async def test_an_unknown_reference_is_not_found(seed_trail: Seed, replay: GetAuditReplay) -> None:
    await seed_trail()
    with pytest.raises(NotFound):
        await replay.execute(GetAuditReplayCommand(ACTOR, "9999"))


async def test_the_export_is_plain_data_with_no_postcode(
    seed_trail: Seed, uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await seed_trail()
    export = ExportAuditReplay(GetAuditReplay(uow_factory, FixedClock(NOW)))
    data = await export.execute(GetAuditReplayCommand(ACTOR, REFERENCE))
    text = json.dumps(data)
    assert "DT4" not in text
    assert data["chain_ok"] is True
    assert data["rows"][0]["service_name"] == "UCR West"
    assert len(data["timeline"]) == 5


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    """A private Neo4j with the superseded single-property keys dropped (DEC-159): both tenants
    hold a service with the same category and the same audit head shape."""
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    """Overrides the session driver for this module."""
    return two_tenant_driver


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def fresh_graph(neo4j_driver: AsyncDriver) -> None:
    await wipe(neo4j_driver)


async def test_another_tenants_case_reference_is_not_found(
    two_tenant_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """Tenant B holds the case with reference 4821; a replay run as tenant A answers not found and
    sees none of B's entries (DEC-130)."""
    await _seed_trail(
        tenant_uow_factory(two_tenant_driver, other_tenant_id), two_tenant_driver, other_tenant_id
    )
    replay_a = GetAuditReplay(tenant_uow_factory(two_tenant_driver, tenant_id), FixedClock(NOW))
    with pytest.raises(NotFound):
        await replay_a.execute(GetAuditReplayCommand(ACTOR, REFERENCE))
    assert await count_nodes(two_tenant_driver, "AuditEvent") == 5


async def test_tenant_a_replay_sees_only_tenant_a_entries(
    two_tenant_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _seed_trail(
        tenant_uow_factory(two_tenant_driver, tenant_id), two_tenant_driver, tenant_id
    )
    await _seed_trail(
        tenant_uow_factory(two_tenant_driver, other_tenant_id), two_tenant_driver, other_tenant_id
    )
    replay_a = GetAuditReplay(tenant_uow_factory(two_tenant_driver, tenant_id), FixedClock(NOW))
    result = await replay_a.execute(GetAuditReplayCommand(ACTOR, REFERENCE))
    assert len(result.timeline) == 5
    assert result.chain_ok is True
