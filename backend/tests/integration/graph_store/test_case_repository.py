"""Integration tests for the case repository (P21).

Run against the throwaway Neo4j that the F10 harness starts for the pytest session (DEC-008). Each
write is one committed transaction and each read is a fresh session, so the tests assert on what
was really stored. Values are synthetic; there is no patient data.
"""

import asyncio
import contextlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.case_repository import Neo4jCaseRepository
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.codes import AgeBand, NeedCategory, Outcome, ReferrerType, Urgency
from diucs.domain.errors import Conflict, InvalidTransition, NotFound, ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.scores import ClinicalFrailty, ManchesterTriage, News2, PathwaysDx
from tests.support.neo4j import count_nodes, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

OPENED = datetime(2026, 10, 25, 13, 16, tzinfo=UTC)
CLOSED = datetime(2026, 10, 25, 13, 40, tzinfo=UTC)

OPEN_CASE = Case(
    id="case-1",
    reference="4821",
    referrer_type=ReferrerType.AMBULANCE_CREW,
    age_band=AgeBand.A80_PLUS,
    postcode="DT4 8XX",
    needs=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
    urgency=Urgency.WITHIN_2_HRS,
    scores=(News2(2), ClinicalFrailty(6)),
    opened_at=OPENED,
)

MANCHESTER_CASE = Case(
    id="case-2",
    reference="4822",
    referrer_type=ReferrerType.GP,
    age_band=AgeBand.A65_79,
    postcode="DT4 8XX",
    needs=(NeedCategory.WOUND_CARE,),
    urgency=Urgency.TODAY,
    scores=(ManchesterTriage("urgent"), PathwaysDx("PD12")),
    opened_at=OPENED,
)


def _repo(tx: AsyncManagedTransaction) -> Neo4jCaseRepository:
    return Neo4jCaseRepository(tx, ResourceStore(tx))


async def _write(driver: AsyncDriver, *cases: Case, save: bool = False) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = _repo(tx)
        for case in cases:
            if save:
                await repo.save(case)
            else:
                await repo.add(case)

    await write_tx(driver, work)


async def _load(driver: AsyncDriver, case_id: str) -> Case | None:
    async def work(tx: AsyncManagedTransaction) -> Case | None:
        return await _repo(tx).get(case_id)

    return await read_tx(driver, work)


async def _rows(driver: AsyncDriver, query: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(query, **params)).data()

    return await read_tx(driver, work)


async def test_the_open_case_round_trips_and_keeps_its_postcode_on_the_stub(
    neo4j_driver: AsyncDriver,
) -> None:
    async def save(tx: AsyncManagedTransaction) -> None:
        await _repo(tx).add(OPEN_CASE)

    async def load(tx: AsyncManagedTransaction) -> Case | None:
        return await _repo(tx).get("case-1")

    await assert_round_trip(neo4j_driver, save, load, OPEN_CASE)
    stub = await _rows(
        neo4j_driver, "MATCH (p:Patient {id: 'pt-case-1'}) RETURN p.postalCode AS postalCode"
    )
    assert stub == [{"postalCode": "DT4 8XX"}]


async def test_get_by_reference_finds_the_case_and_an_unknown_reference_finds_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)

    async def find(tx: AsyncManagedTransaction) -> tuple[Case | None, Case | None]:
        repo = _repo(tx)
        return await repo.get_by_reference("4821"), await repo.get_by_reference("0000")

    found, missing = await read_tx(neo4j_driver, find)

    assert found == OPEN_CASE
    assert missing is None


async def test_closing_the_case_removes_its_postcode_and_needs_and_writes_no_history(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)
    versions_before = await count_nodes(neo4j_driver, "ResourceVersion")

    closed = OPEN_CASE.close(
        Outcome.ACCEPTED_AND_BOOKED, CLOSED, destination_service_id="svc-ucr-west"
    )
    await _write(neo4j_driver, closed, save=True)

    postcode_left = await _rows(
        neo4j_driver,
        "MATCH (n) WHERE n.postalCode IS NOT NULL OR n.json CONTAINS 'DT4 8XX' "
        "RETURN count(n) AS total",
    )
    reason_links = await _rows(
        neo4j_driver, "MATCH ()-[r:REASON_CODE]->() RETURN count(r) AS total"
    )
    assert postcode_left == [{"total": 0}]
    assert reason_links == [{"total": 0}]
    assert await count_nodes(neo4j_driver, "ResourceVersion") == versions_before


async def test_a_closed_case_reads_back_with_its_outcome_destination_and_both_scores(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)
    closed = OPEN_CASE.close(
        Outcome.ACCEPTED_AND_BOOKED, CLOSED, destination_service_id="svc-ucr-west"
    )
    await _write(neo4j_driver, closed, save=True)

    assert await _load(neo4j_driver, "case-1") == closed
    performers = await _rows(
        neo4j_driver,
        "MATCH (r:ServiceRequest {id: 'case-1'})-[:PERFORMER]->(s) RETURN s.id AS id",
    )
    assert performers == [{"id": "svc-ucr-west"}]
    scores = await _rows(
        neo4j_driver,
        "MATCH (o:Observation)-[:SUBJECT]->(:Patient {id: 'pt-case-1'}) RETURN count(o) AS total",
    )
    assert scores == [{"total": 2}]


async def test_adding_the_same_case_twice_is_a_conflict_and_the_first_is_kept(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)

    with pytest.raises(Conflict):
        await _write(neo4j_driver, OPEN_CASE)

    assert await _load(neo4j_driver, "case-1") == OPEN_CASE
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 1


async def test_saving_an_unknown_case_is_not_found_and_creates_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    with pytest.raises(NotFound):
        await _write(neo4j_driver, OPEN_CASE, save=True)

    assert await count_nodes(neo4j_driver, "Patient") == 0
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 0


async def test_sixteen_racing_adds_of_one_case_let_exactly_one_win(
    neo4j_driver: AsyncDriver,
) -> None:
    async def add_once() -> bool:
        try:
            await _write(neo4j_driver, OPEN_CASE)
        except Conflict:
            return False
        return True

    outcomes = await asyncio.gather(*(add_once() for _ in range(16)))

    assert outcomes.count(True) == 1
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 1
    assert await count_nodes(neo4j_driver, "Observation") == 2


async def test_a_refused_second_add_that_is_committed_leaves_the_stored_case_unchanged(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)

    async def swallow_and_commit(tx: AsyncManagedTransaction) -> None:
        with contextlib.suppress(Conflict):
            await _repo(tx).add(replace(OPEN_CASE, scores=(News2(9),)))

    await write_tx(neo4j_driver, swallow_and_commit)

    assert await _load(neo4j_driver, "case-1") == OPEN_CASE
    assert await count_nodes(neo4j_driver, "Observation") == 2


async def test_saving_an_open_case_writes_its_change_without_rewriting_the_scores(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)
    changed = replace(OPEN_CASE, needs=(NeedCategory.WOUND_CARE,), urgency=Urgency.TODAY)

    await _write(neo4j_driver, changed, save=True)

    assert await _load(neo4j_driver, "case-1") == changed


async def test_a_save_that_changes_the_scores_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)
    changed = replace(OPEN_CASE, scores=(News2(3), ClinicalFrailty(6)))

    with pytest.raises(ValidationFailed):
        await _write(neo4j_driver, changed, save=True)

    assert await _load(neo4j_driver, "case-1") == OPEN_CASE


async def test_a_save_that_changes_the_reference_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)
    changed = replace(OPEN_CASE, reference="9999")

    with pytest.raises(ValidationFailed):
        await _write(neo4j_driver, changed, save=True)

    assert await _load(neo4j_driver, "case-1") == OPEN_CASE
    assert await _rows(
        neo4j_driver, "MATCH (r:ServiceRequest {reference: '9999'}) RETURN count(r) AS total"
    ) == [{"total": 0}]


async def test_a_closed_case_cannot_be_reopened_and_stays_closed(
    neo4j_driver: AsyncDriver,
) -> None:
    closed = OPEN_CASE.close(
        Outcome.ACCEPTED_AND_BOOKED, CLOSED, destination_service_id="svc-ucr-west"
    )
    await _write(neo4j_driver, OPEN_CASE)
    await _write(neo4j_driver, closed, save=True)
    reopened = replace(closed, closed_at=None, outcome=None, destination_service_id=None)

    with pytest.raises(InvalidTransition):
        await _write(neo4j_driver, reopened, save=True)

    assert await _load(neo4j_driver, "case-1") == closed


async def test_a_manchester_and_pathways_case_round_trips(neo4j_driver: AsyncDriver) -> None:
    async def save(tx: AsyncManagedTransaction) -> None:
        await _repo(tx).add(MANCHESTER_CASE)

    async def load(tx: AsyncManagedTransaction) -> Case | None:
        return await _repo(tx).get("case-2")

    await assert_round_trip(neo4j_driver, save, load, MANCHESTER_CASE)
