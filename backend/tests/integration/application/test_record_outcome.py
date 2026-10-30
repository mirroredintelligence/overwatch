"""Integration tests for RecordOutcome (U14), against the real Neo4j the harness starts. Written in
the build wave and NOT RUN there: the batch run happens later.

Each assertion reads back through a fresh unit of work or a harness helper (DEC-004). The case is
4821: an 80+ patient, fall and frailty, two scores, within 2 hrs, booked to UCR West. Its postcode
is held as the district only (DEC-067). The full postcode DT4 8XX must never reach the graph.
"""

import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.record_outcome import (
    RecordOutcome,
    RecordOutcomeCommand,
)
from diucs.domain.codes import (
    AgeBand,
    Cadence,
    Channel,
    Measure,
    NeedCategory,
    Outcome,
    ReferrerType,
    Role,
    ServiceCategory,
    Urgency,
)
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.scores import ClinicalFrailty, News2
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, node_props, read_tx, wipe_all
from tests.support.tenant_seed import contracted_container

Seed = Callable[..., Awaitable[None]]

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    """A private Neo4j with every migration applied and the superseded single-property keys dropped
    (DEC-159). The cross-tenant test saves a service in tenant B with the same category Concept
    that tenant A holds, which the shared schema refuses until TEN-032."""
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    """Overrides the session driver for this module."""
    return two_tenant_driver


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def fresh_graph(neo4j_driver: AsyncDriver) -> None:
    """Wipes the module's own container before each test (clean_graph wipes only the harness)."""
    await wipe_all(neo4j_driver)


OPENED = datetime(2026, 10, 23, 13, 10, tzinfo=UTC)
NOW = datetime(2026, 10, 23, 13, 19, tzinfo=UTC)  # 14:19 BST
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
REPORTER = dataclasses.replace(ADVISOR, role=Role.REPORTER, practitioner_id=None)
WEST = "svc-ucr-west"
CASE_ID = "case-4821"
FULL_POSTCODE = "DT4 8XX"


def _west() -> ServiceProfile:
    return ServiceProfile(
        id=WEST,
        name="UCR West",
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


def _case(case_id: str = CASE_ID) -> Case:
    return Case(
        id=case_id,
        reference="4821",
        referrer_type=ReferrerType.AMBULANCE_CREW,
        age_band=AgeBand.A80_PLUS,
        postcode="DT4",
        needs=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
        urgency=Urgency.WITHIN_2_HRS,
        scores=(News2(2), ClinicalFrailty(6)),
        opened_at=OPENED,
    )


def _closer(factory: UnitOfWorkFactory, driver: AsyncDriver) -> RecordOutcome:
    return RecordOutcome(factory, FixedClock(NOW), DriverIdempotencyStore(driver))


async def _seed(factory: UnitOfWorkFactory, seed_service: Seed) -> None:
    await seed_service(_west())
    async with factory() as uow:
        await uow.cases.add(_case())
        await uow.commit()


async def _read(factory: UnitOfWorkFactory, case_id: str = CASE_ID) -> Case | None:
    async with factory() as uow:
        return await uow.cases.get(case_id)


async def _last_audit(factory: UnitOfWorkFactory) -> Any:
    async with factory() as uow:
        return (await uow.audit.records())[-1].entry


async def _reason_code_count(driver: AsyncDriver, request_id: str) -> int:
    async def work(tx: Any) -> int:
        record = await (
            await tx.run(
                "MATCH (r:ServiceRequest {id: $id})-[rel:REASON_CODE]->() "
                "RETURN count(rel) AS total",
                id=request_id,
            )
        ).single()
        return int(record["total"])

    return await read_tx(driver, work)


async def test_closing_as_booked_to_ucr_west_clears_the_postcode_and_the_needs(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)

    result = await _closer(uow_factory, neo4j_driver).execute(
        RecordOutcomeCommand("close-1", ADVISOR, CASE_ID, Outcome.ACCEPTED_AND_BOOKED, WEST)
    )

    closed = await _read(uow_factory)
    assert closed is not None
    assert closed.postcode is None
    assert closed.needs == ()
    assert closed.outcome is Outcome.ACCEPTED_AND_BOOKED
    assert closed.destination_service_id == WEST
    assert closed.closed_at == NOW
    assert result.closed_at == NOW
    assert result.reference == "4821"


async def test_the_closed_stub_has_no_postcode_property_and_the_request_no_reason_code(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)
    assert await _reason_code_count(neo4j_driver, CASE_ID) == 2

    await _closer(uow_factory, neo4j_driver).execute(
        RecordOutcomeCommand("close-2", ADVISOR, CASE_ID, Outcome.ACCEPTED_AND_BOOKED, WEST)
    )

    stub = await node_props(neo4j_driver, "Patient", id=f"pt-{CASE_ID}")
    assert "postalCode" not in stub
    assert await _reason_code_count(neo4j_driver, CASE_ID) == 0


async def test_the_audit_snapshot_keeps_the_needs_and_scores_and_never_the_postcode(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)

    await _closer(uow_factory, neo4j_driver).execute(
        RecordOutcomeCommand("close-3", ADVISOR, CASE_ID, Outcome.ACCEPTED_AND_BOOKED, WEST)
    )

    entry = await _last_audit(uow_factory)
    assert entry.use_case == "RecordOutcome"
    assert entry.snapshot["needs"] == ["fall-no-injury", "frailty"]
    assert entry.snapshot["age_band"] == "80+"
    assert entry.snapshot["scores"] == [
        {"method": "news2", "value": 2},
        {"method": "cfs", "value": 6},
    ]
    assert FULL_POSTCODE not in repr(entry.snapshot)
    assert "DT4" not in repr(entry.snapshot)


@pytest.mark.parametrize(
    ("outcome", "destination"),
    [(Outcome.ACCEPTED_AND_BOOKED, None), (Outcome.CALLER_CANCELLED, WEST)],
)
async def test_a_destination_the_outcome_does_not_take_is_refused_and_the_case_stays_open(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
    outcome: Outcome,
    destination: str | None,
) -> None:
    await _seed(uow_factory, seed_service)
    before = await _read(uow_factory)

    with pytest.raises(ValidationFailed) as refused:
        await _closer(uow_factory, neo4j_driver).execute(
            RecordOutcomeCommand("close-x", ADVISOR, CASE_ID, outcome, destination)
        )

    assert refused.value.field == "destination_service_id"
    assert await _read(uow_factory) == before
    assert before is not None and before.closed_at is None


async def test_closing_again_is_a_conflict_and_the_closed_case_is_unchanged(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)
    closer = _closer(uow_factory, neo4j_driver)
    await closer.execute(
        RecordOutcomeCommand("close-4", ADVISOR, CASE_ID, Outcome.ACCEPTED_AND_BOOKED, WEST)
    )
    closed = await _read(uow_factory)

    with pytest.raises(Conflict):
        await closer.execute(RecordOutcomeCommand("close-5", ADVISOR, CASE_ID, Outcome.DECLINED))

    assert await _read(uow_factory) == closed


async def test_a_reporter_may_not_close_and_a_replay_writes_one_audit_record(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)
    closer = _closer(uow_factory, neo4j_driver)

    with pytest.raises(NotAllowed):
        await closer.execute(RecordOutcomeCommand("close-r", REPORTER, CASE_ID, Outcome.DECLINED))

    command = RecordOutcomeCommand(
        "close-once", ADVISOR, CASE_ID, Outcome.ACCEPTED_AND_BOOKED, WEST
    )
    first = await closer.execute(command)
    before = await count_nodes(neo4j_driver, "AuditEvent")
    replay = await closer.execute(command)

    assert replay == first
    assert await count_nodes(neo4j_driver, "AuditEvent") == before


async def test_a_destination_of_another_tenant_is_not_found_and_the_case_stays_open(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
) -> None:
    await _seed(uow_factory, seed_service)
    async with uow_factory_b() as uow:
        await uow.services.save(dataclasses.replace(_west(), id="svc-b-only", name="Tenant B"))
        await uow.commit()

    with pytest.raises(NotFound):
        await _closer(uow_factory, neo4j_driver).execute(
            RecordOutcomeCommand("close-b", ADVISOR, CASE_ID, Outcome.REDIRECTED, "svc-b-only")
        )

    still = await _read(uow_factory)
    assert still is not None
    assert still.closed_at is None
    assert still.postcode == "DT4"
