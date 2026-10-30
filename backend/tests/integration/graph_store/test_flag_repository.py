"""Integration tests for the report and service flag repository (P14).

They run against the throwaway Neo4j that the F10 harness starts for the pytest session (DEC-008).
Every write is one committed transaction and every read is a fresh session, so the tests assert on
what was really stored. Race tests hold one transaction open and start a second writer while it is
held (lesson L94), and the 16-racer tests assert outcomes, not only errors (lesson L102). Values are
synthetic; there is no patient data.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.capacity_repository import Neo4jCapacityRepository
from diucs.adapters.outbound.graph_store.flag_repository import (
    Neo4jFlagRepository,
    service_flag_id,
    service_flag_to_fhir,
)
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import Neo4jServiceRepository
from diucs.application.tenancy import current_tenant
from diucs.domain.codes import ReportFlagReason
from diucs.domain.errors import Conflict, InvalidTransition, NotFound, ValidationFailed
from diucs.domain.model.flags import (
    REPORT_FLAG_ACCEPTED,
    REPORT_FLAG_CHECKED,
    REPORT_FLAG_OPEN,
    SERVICE_FLAG_CRITERIA_OVERDUE,
    SERVICE_FLAG_SUSPENDED,
    ReportFlag,
    ServiceFlag,
)
from tests.integration.graph_store.test_service_repository import UCR_EAST
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip
from tests.support.scoped import scoped
from tests.unit.adapters.outbound.graph_store.test_capacity_repository import NUMBER_REPORT
from tests.unit.adapters.outbound.graph_store.test_service_repository import UCR_WEST

pytestmark = pytest.mark.asyncio(loop_scope="session")

WEST = "svc-ucr-west"
EAST = "svc-ucr-east"
WEST_REPORT = NUMBER_REPORT.id
EAST_REPORT = "obs-ucr-east-0912"
EAST_NUMBER_REPORT = replace(NUMBER_REPORT, id=EAST_REPORT, service_id=EAST)

RESOLVED = datetime(2026, 10, 25, 9, 40, tzinfo=UTC)

RANGE_FLAG_WEST = ReportFlag(
    id="rf-west-0912-range",
    report_id=WEST_REPORT,
    service_id=WEST,
    reason=ReportFlagReason.OUT_OF_RANGE_TWICE,
    status=REPORT_FLAG_OPEN,
    created_at=datetime(2026, 10, 25, 9, 13, tzinfo=UTC),
)
CHANGES_FLAG_WEST = replace(
    RANGE_FLAG_WEST,
    id="rf-west-0912-changes",
    reason=ReportFlagReason.MANY_CHANGES,
    created_at=datetime(2026, 10, 25, 9, 20, tzinfo=UTC),
)
EARLIER_CHECKED_WEST = replace(
    RANGE_FLAG_WEST,
    id="rf-west-0905-earlier",
    created_at=datetime(2026, 10, 25, 9, 5, tzinfo=UTC),
)
RANGE_FLAG_EAST = replace(
    RANGE_FLAG_WEST,
    id="rf-east-0912-range",
    report_id=EAST_REPORT,
    service_id=EAST,
    created_at=datetime(2026, 10, 25, 9, 15, tzinfo=UTC),
)

SUSPENDED_WEST = ServiceFlag(
    service_id=WEST,
    code=SERVICE_FLAG_SUSPENDED,
    active=True,
    reason="Staffing shortfall",
    actor_id="role-ucr-west-lead",
    at=datetime(2026, 10, 25, 9, 14, tzinfo=UTC),
)
SUSPENDED_WEST_AGAIN = replace(
    SUSPENDED_WEST,
    reason="Rota filled",
    at=datetime(2026, 10, 25, 10, 0, tzinfo=UTC),
)

Step = Callable[[Neo4jFlagRepository], Awaitable[Any]]


def _repo(tx: AsyncManagedTransaction) -> Neo4jFlagRepository:
    return Neo4jFlagRepository(tx, ResourceStore(tx))


async def _seed(driver: AsyncDriver) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        services = Neo4jServiceRepository(tx, ResourceStore(tx))
        reports = Neo4jCapacityRepository(tx, ResourceStore(tx))
        await services.save(UCR_WEST)
        await services.save(UCR_EAST)
        await reports.add(NUMBER_REPORT)
        await reports.add(EAST_NUMBER_REPORT)

    await write_tx(driver, work)


async def _run(driver: AsyncDriver, *steps: Step) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = _repo(tx)
        for step in steps:
            await step(repo)

    await write_tx(driver, work)


async def _read(driver: AsyncDriver, step: Step) -> Any:
    return await read_tx(driver, lambda tx: step(_repo(tx)))


async def _rows(driver: AsyncDriver, cypher: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(cypher, **params)
        return await result.data()

    return await read_tx(driver, work)


async def _stored_basic(driver: AsyncDriver, flag_id: str) -> dict[str, Any] | None:
    return await read_tx(driver, lambda tx: ResourceStore(tx).get("Basic", flag_id))


async def _stored_observation(driver: AsyncDriver, report_id: str) -> dict[str, Any] | None:
    return await read_tx(driver, lambda tx: ResourceStore(tx).get("Observation", report_id))


# --- The seven behaviours the prompt asks for ----------------------------------------------------


async def test_a_report_flag_round_trips_and_sits_on_its_observation(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    await assert_round_trip(
        neo4j_driver,
        lambda tx: _repo(tx).add_report_flag(RANGE_FLAG_WEST),
        lambda tx: _repo(tx).open_report_flags(WEST),
        [RANGE_FLAG_WEST],
    )
    on = await _rows(
        neo4j_driver,
        "MATCH (f:ReportFlag {id: $id, tenantId: $tenant})-[:ON]->(o:Observation {tenantId: "
        "$tenant}) RETURN o.id AS report",
        id=RANGE_FLAG_WEST.id,
    )
    assert on == [{"report": WEST_REPORT}]


async def test_open_flags_are_listed_oldest_first_and_checked_ones_are_not(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    await _run(
        neo4j_driver,
        lambda repo: repo.add_report_flag(CHANGES_FLAG_WEST),
        lambda repo: repo.add_report_flag(RANGE_FLAG_WEST),
        lambda repo: repo.add_report_flag(RANGE_FLAG_EAST),
        lambda repo: repo.add_report_flag(EARLIER_CHECKED_WEST),
        lambda repo: repo.save_report_flag(
            replace(EARLIER_CHECKED_WEST, status=REPORT_FLAG_CHECKED, resolved_at=RESOLVED)
        ),
    )
    assert await _read(neo4j_driver, lambda repo: repo.open_report_flags(WEST)) == [
        RANGE_FLAG_WEST,
        CHANGES_FLAG_WEST,
    ]
    assert await _read(neo4j_driver, lambda repo: repo.open_report_flags()) == [
        RANGE_FLAG_WEST,
        RANGE_FLAG_EAST,
        CHANGES_FLAG_WEST,
    ]


async def test_saving_a_checked_flag_sets_its_resolution_and_removes_it_from_open(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add_report_flag(RANGE_FLAG_WEST))
    checked = replace(
        RANGE_FLAG_WEST,
        status=REPORT_FLAG_CHECKED,
        resolved_at=RESOLVED,
        outcome="phoned, figure right",
    )
    await _run(neo4j_driver, lambda repo: repo.save_report_flag(checked))
    assert await _read(neo4j_driver, lambda repo: repo.open_report_flags(WEST)) == []
    props = await node_props(neo4j_driver, "ReportFlag", id=RANGE_FLAG_WEST.id)
    assert props["status"] == REPORT_FLAG_CHECKED
    assert props["resolvedAt"] is not None
    assert props["outcome"] == "phoned, figure right"


async def test_flagging_a_report_leaves_the_observation_unchanged(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    props_before = await node_props(neo4j_driver, "Observation", id=WEST_REPORT)
    stored_before = await _stored_observation(neo4j_driver, WEST_REPORT)
    await _run(neo4j_driver, lambda repo: repo.add_report_flag(RANGE_FLAG_WEST))
    assert await node_props(neo4j_driver, "Observation", id=WEST_REPORT) == props_before
    assert await _stored_observation(neo4j_driver, WEST_REPORT) == stored_before
    assert await count_nodes(neo4j_driver, "Observation") == 2


async def test_setting_a_service_flag_twice_keeps_one_node_and_inactive_hides_it(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.set_service_flag(SUSPENDED_WEST))
    await _run(neo4j_driver, lambda repo: repo.set_service_flag(SUSPENDED_WEST_AGAIN))
    assert await count_nodes(neo4j_driver, "ServiceFlag") == 1
    assert await _read(neo4j_driver, lambda repo: repo.service_flags(WEST)) == [
        SUSPENDED_WEST_AGAIN
    ]
    await _run(
        neo4j_driver,
        lambda repo: repo.set_service_flag(replace(SUSPENDED_WEST_AGAIN, active=False)),
    )
    assert await _read(neo4j_driver, lambda repo: repo.service_flags(WEST)) == []
    assert await count_nodes(neo4j_driver, "ServiceFlag") == 1


async def test_services_with_a_flag_lists_only_the_active_ones(neo4j_driver: AsyncDriver) -> None:
    await _seed(neo4j_driver)
    overdue_west = ServiceFlag(
        service_id=WEST,
        code=SERVICE_FLAG_CRITERIA_OVERDUE,
        active=True,
        reason="Review date passed",
        actor_id="role-ucr-west-lead",
        at=datetime(2026, 10, 25, 8, 0, tzinfo=UTC),
    )
    await _run(
        neo4j_driver,
        lambda repo: repo.set_service_flag(SUSPENDED_WEST),
        lambda repo: repo.set_service_flag(replace(SUSPENDED_WEST, service_id=EAST)),
        lambda repo: repo.set_service_flag(overdue_west),
        lambda repo: repo.set_service_flag(replace(SUSPENDED_WEST, service_id=EAST, active=False)),
    )
    assert await _read(neo4j_driver, lambda repo: repo.services_with_flag("suspended")) == {WEST}
    assert await _read(neo4j_driver, lambda repo: repo.services_with_flag("criteria-overdue")) == {
        WEST
    }
    assert await _read(neo4j_driver, lambda repo: repo.services_with_flag("not-a-code")) == set()


async def test_a_service_flag_is_stored_as_its_basic_resource_with_no_json(
    neo4j_driver: AsyncDriver,
) -> None:
    # DEC-001 replaces the prompt's json check: the stored resource, rebuilt from the graph alone,
    # equals the canonical Basic apart from meta. The same test also pins one node per service.
    await _seed(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.set_service_flag(SUSPENDED_WEST_AGAIN))
    stored = await _stored_basic(neo4j_driver, service_flag_id(WEST, SERVICE_FLAG_SUSPENDED))
    assert stored is not None
    assert "meta" in stored
    assert {key: value for key, value in stored.items() if key != "meta"} == (
        service_flag_to_fhir(SUSPENDED_WEST_AGAIN)
    )


# --- Guards, each with its own test ---------------------------------------------------------------


async def test_a_report_flag_for_an_unknown_report_is_not_found_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    orphan = replace(RANGE_FLAG_WEST, report_id="obs-not-stored")
    with pytest.raises(NotFound):
        await _run(neo4j_driver, lambda repo: repo.add_report_flag(orphan))
    assert await count_nodes(neo4j_driver, "ReportFlag") == 0


async def test_a_report_flag_naming_another_service_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    wrong_service = replace(RANGE_FLAG_WEST, service_id=EAST)
    with pytest.raises(ValidationFailed):
        await _run(neo4j_driver, lambda repo: repo.add_report_flag(wrong_service))
    assert await count_nodes(neo4j_driver, "ReportFlag") == 0


async def test_a_repeated_report_flag_id_is_a_conflict_and_leaves_one(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add_report_flag(RANGE_FLAG_WEST))
    with pytest.raises(Conflict):
        await _run(neo4j_driver, lambda repo: repo.add_report_flag(RANGE_FLAG_WEST))
    assert await count_nodes(neo4j_driver, "ReportFlag") == 1


async def test_a_second_add_of_one_flag_waits_for_a_held_add_and_is_refused(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    session = neo4j_driver.session()
    held = scoped(await session.begin_transaction())
    try:
        await _repo(held).add_report_flag(RANGE_FLAG_WEST)
        racer = asyncio.create_task(
            write_tx(neo4j_driver, lambda tx: _repo(tx).add_report_flag(RANGE_FLAG_WEST))
        )
        done, _ = await asyncio.wait({racer}, timeout=1.0)
        assert not done, "the second add must wait for the held add on the report"
    finally:
        await held.commit()
        await session.close()
    with pytest.raises(Conflict):
        await racer
    assert await count_nodes(neo4j_driver, "ReportFlag") == 1


async def test_sixteen_racing_adds_of_one_flag_leave_one_flag_and_fifteen_conflicts(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)

    async def attempt() -> str:
        try:
            await write_tx(neo4j_driver, lambda tx: _repo(tx).add_report_flag(RANGE_FLAG_WEST))
        except Conflict:
            return "conflict"
        return "stored"

    outcomes = await asyncio.gather(*(attempt() for _ in range(16)))
    assert outcomes.count("stored") == 1
    assert outcomes.count("conflict") == 15
    assert await count_nodes(neo4j_driver, "ReportFlag") == 1


async def test_a_resolved_flag_cannot_be_resolved_again(neo4j_driver: AsyncDriver) -> None:
    await _seed(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add_report_flag(RANGE_FLAG_WEST))
    checked = replace(RANGE_FLAG_WEST, status=REPORT_FLAG_CHECKED, resolved_at=RESOLVED)
    await _run(neo4j_driver, lambda repo: repo.save_report_flag(checked))
    accepted = replace(checked, status=REPORT_FLAG_ACCEPTED, outcome="accepted on the second look")
    with pytest.raises(InvalidTransition):
        await _run(neo4j_driver, lambda repo: repo.save_report_flag(accepted))
    props = await node_props(neo4j_driver, "ReportFlag", id=RANGE_FLAG_WEST.id)
    assert props["status"] == REPORT_FLAG_CHECKED
    assert "outcome" not in props


async def test_saving_a_flag_cannot_change_its_report_or_its_reason(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add_report_flag(RANGE_FLAG_WEST))
    moved = replace(
        RANGE_FLAG_WEST,
        reason=ReportFlagReason.MANY_CHANGES,
        status=REPORT_FLAG_CHECKED,
        resolved_at=RESOLVED,
    )
    with pytest.raises(ValidationFailed):
        await _run(neo4j_driver, lambda repo: repo.save_report_flag(moved))
    props = await node_props(neo4j_driver, "ReportFlag", id=RANGE_FLAG_WEST.id)
    assert props["reason"] == ReportFlagReason.OUT_OF_RANGE_TWICE.value
    assert props["status"] == REPORT_FLAG_OPEN


async def test_saving_an_unknown_flag_is_not_found(neo4j_driver: AsyncDriver) -> None:
    await _seed(neo4j_driver)
    with pytest.raises(NotFound):
        await _run(neo4j_driver, lambda repo: repo.save_report_flag(RANGE_FLAG_WEST))


async def test_a_second_resolution_waits_for_a_held_resolution_and_is_refused(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    await _run(neo4j_driver, lambda repo: repo.add_report_flag(RANGE_FLAG_WEST))
    session = neo4j_driver.session()
    held = scoped(await session.begin_transaction())
    first = replace(RANGE_FLAG_WEST, status=REPORT_FLAG_CHECKED, resolved_at=RESOLVED)
    second = replace(
        RANGE_FLAG_WEST,
        status=REPORT_FLAG_ACCEPTED,
        resolved_at=datetime(2026, 10, 25, 9, 41, tzinfo=UTC),
    )
    try:
        await _repo(held).save_report_flag(first)
        racer = asyncio.create_task(
            write_tx(neo4j_driver, lambda tx: _repo(tx).save_report_flag(second))
        )
        done, _ = await asyncio.wait({racer}, timeout=1.0)
        assert not done, "the second resolution must wait for the held resolution"
    finally:
        await held.commit()
        await session.close()
    with pytest.raises(InvalidTransition):
        await racer
    props = await node_props(neo4j_driver, "ReportFlag", id=RANGE_FLAG_WEST.id)
    assert props["status"] == REPORT_FLAG_CHECKED


async def test_a_service_flag_for_an_unknown_service_is_not_found_and_makes_no_placeholder(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    stray = replace(SUSPENDED_WEST, service_id="svc-not-stored")
    with pytest.raises(NotFound):
        await _run(neo4j_driver, lambda repo: repo.set_service_flag(stray))
    assert await count_nodes(neo4j_driver, "ServiceFlag") == 0
    assert await count_nodes(neo4j_driver, "Basic") == 0
    assert await count_nodes(neo4j_driver, "HealthcareService") == 2


async def test_an_existing_basic_that_is_not_a_service_flag_is_a_conflict(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    intruder = {
        "resourceType": "Basic",
        "id": service_flag_id(WEST, SERVICE_FLAG_SUSPENDED),
        "subject": {"reference": f"HealthcareService/{WEST}"},
    }

    async def plant(tx: AsyncManagedTransaction) -> None:
        await ResourceStore(tx).put(intruder, None)

    await write_tx(neo4j_driver, plant)
    with pytest.raises(Conflict):
        await _run(neo4j_driver, lambda repo: repo.set_service_flag(SUSPENDED_WEST))
    assert await count_nodes(neo4j_driver, "ServiceFlag") == 0


async def test_a_second_set_for_a_service_that_a_held_set_is_creating_waits_and_succeeds(
    neo4j_driver: AsyncDriver,
) -> None:
    # Lesson L103: the first create is what discriminates. A second set that would only update an
    # existing node is serialised by Neo4j anyway, so it cannot show the lock is there.
    await _seed(neo4j_driver)
    session = neo4j_driver.session()
    held = scoped(await session.begin_transaction())
    try:
        await _repo(held).set_service_flag(SUSPENDED_WEST)
        racer = asyncio.create_task(
            write_tx(neo4j_driver, lambda tx: _repo(tx).set_service_flag(SUSPENDED_WEST_AGAIN))
        )
        done, _ = await asyncio.wait({racer}, timeout=1.0)
        assert not done, "the second set must wait for the held set on the service"
    finally:
        await held.commit()
        await session.close()
    await racer
    assert await count_nodes(neo4j_driver, "ServiceFlag") == 1
    assert await _read(neo4j_driver, lambda repo: repo.service_flags(WEST)) == [
        SUSPENDED_WEST_AGAIN
    ]


async def test_sixteen_racing_sets_for_one_service_and_code_all_succeed_and_leave_one_flag(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)

    async def attempt(index: int) -> None:
        flag = replace(SUSPENDED_WEST, reason=f"reason {index}")
        await write_tx(neo4j_driver, lambda tx: _repo(tx).set_service_flag(flag))

    # Every racer must succeed: a refusal here would hide a missing lock (lesson L102).
    await asyncio.gather(*(attempt(index) for index in range(16)))
    assert await count_nodes(neo4j_driver, "ServiceFlag") == 1
    flags = await _read(neo4j_driver, lambda repo: repo.service_flags(WEST))
    assert len(flags) == 1
    assert flags[0].code == SERVICE_FLAG_SUSPENDED


async def test_the_database_refuses_a_second_report_flag_node_with_one_id(
    neo4j_driver: AsyncDriver,
) -> None:
    # Not the repository: a raw CREATE, so the unique key on (tenantId, ReportFlag.id) is tested.
    await _seed(neo4j_driver)

    async def create(tx: AsyncManagedTransaction) -> None:
        result = await tx.run(
            "MATCH (o:Observation {key: $key, tenantId: $tenant}) "
            "CREATE (f:ReportFlag {id: $id, serviceId: $service, tenantId: $tenant})-[:ON]->(o)",
            key=f"Observation/{WEST_REPORT}",
            id="rf-raw-duplicate",
            service=WEST,
            tenant=current_tenant(),
        )
        await result.consume()

    await write_tx(neo4j_driver, create)
    with pytest.raises(ConstraintError):
        await write_tx(neo4j_driver, create)
    assert await count_nodes(neo4j_driver, "ReportFlag") == 1


async def test_two_racing_adds_of_one_flag_id_on_different_reports_leave_one_flag(
    neo4j_driver: AsyncDriver,
) -> None:
    # The report-add lock is per report, so two reports never serialise here: the unique key on
    # the flag id must hold the second writer (lesson L94: a held transaction, not timing).
    await _seed(neo4j_driver)
    same_id_on_east = replace(RANGE_FLAG_EAST, id=RANGE_FLAG_WEST.id)
    session = neo4j_driver.session()
    held = scoped(await session.begin_transaction())
    try:
        await _repo(held).add_report_flag(RANGE_FLAG_WEST)
        racer = asyncio.create_task(
            write_tx(neo4j_driver, lambda tx: _repo(tx).add_report_flag(same_id_on_east))
        )
        done, _ = await asyncio.wait({racer}, timeout=1.0)
        assert not done, "the second add must wait for the held add on the flag id"
    finally:
        await held.commit()
        await session.close()
    with pytest.raises(Conflict):
        await racer
    assert await count_nodes(neo4j_driver, "ReportFlag") == 1
