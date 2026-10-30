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
from neo4j.exceptions import ClientError

from diucs.adapters.outbound.graph_store import case_repository
from diucs.adapters.outbound.graph_store.case_repository import Neo4jCaseRepository
from diucs.adapters.outbound.graph_store.queries import NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.application.tenancy import current_tenant
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
    postcode="DT4",
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
    postcode="DT4",
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
        neo4j_driver,
        "MATCH (p:Patient {id: 'pt-case-1', tenantId: $tenant}) RETURN p.postalCode AS postalCode",
    )
    assert stub == [{"postalCode": "DT4"}]


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
        "MATCH (n {tenantId: $tenant}) WHERE n.postalCode IS NOT NULL OR n.json CONTAINS 'DT4' "
        "RETURN count(n) AS total",
    )
    reason_links = await _rows(
        neo4j_driver,
        "MATCH ({tenantId: $tenant})-[r:REASON_CODE]->({tenantId: $tenant}) RETURN count(r) AS "
        "total",
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
        "MATCH (r:ServiceRequest {id: 'case-1', tenantId: $tenant})-[:PERFORMER]->(s) RETURN s.id "
        "AS id",
    )
    assert performers == [{"id": "svc-ucr-west"}]
    scores = await _rows(
        neo4j_driver,
        "MATCH (o:Observation {tenantId: $tenant})-[:SUBJECT]->(:Patient {id: 'pt-case-1', "
        "tenantId: $tenant}) RETURN count(o) AS total",
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
        neo4j_driver,
        "MATCH (r:ServiceRequest {reference: '9999', tenantId: $tenant}) RETURN count(r) AS total",
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


async def test_a_full_postcode_is_refused_and_writes_nothing(neo4j_driver: AsyncDriver) -> None:
    full = replace(OPEN_CASE, postcode="DT4 8XX")

    async def swallow_and_commit(tx: AsyncManagedTransaction) -> None:
        with contextlib.suppress(ValidationFailed):
            await _repo(tx).add(full)

    await write_tx(neo4j_driver, swallow_and_commit)

    assert await count_nodes(neo4j_driver, "Patient") == 0
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 0


async def test_a_reference_outside_the_four_digit_format_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    bad = replace(OPEN_CASE, reference="9434765919")

    async def swallow_and_commit(tx: AsyncManagedTransaction) -> None:
        with contextlib.suppress(ValidationFailed):
            await _repo(tx).add(bad)

    await write_tx(neo4j_driver, swallow_and_commit)

    assert await count_nodes(neo4j_driver, "Patient") == 0
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 0


async def test_a_second_case_with_the_same_reference_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)
    second = replace(OPEN_CASE, id="case-3")

    async def swallow_and_commit(tx: AsyncManagedTransaction) -> None:
        with contextlib.suppress(Conflict):
            await _repo(tx).add(second)

    await write_tx(neo4j_driver, swallow_and_commit)

    assert await count_nodes(neo4j_driver, "Patient") == 1
    assert await _load(neo4j_driver, "case-1") == OPEN_CASE


async def test_the_open_case_reference_is_unique_in_the_tenant(neo4j_driver: AsyncDriver) -> None:
    """The lifetime-unique key `case_reference_id` went with TEN-032: the composite constraint is on
    the open reference, which only an open case carries."""
    await _write(neo4j_driver, OPEN_CASE)

    async def duplicate(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "CREATE (:ServiceRequest {id: 'case-x', key: 'ServiceRequest/case-x', "
            "reference: '4821', openReference: '4821', tenantId: $tenant})",
            tenant=current_tenant(),
        )

    with pytest.raises(ClientError):
        await write_tx(neo4j_driver, duplicate)


async def test_a_reference_of_a_closed_case_can_be_held_again_in_the_tenant(
    neo4j_driver: AsyncDriver,
) -> None:
    """With the lifetime-unique key gone (TEN-032), a closed case's reference blocks nobody."""
    await _write(neo4j_driver, OPEN_CASE)
    closed = OPEN_CASE.close(
        Outcome.ACCEPTED_AND_BOOKED, CLOSED, destination_service_id="svc-ucr-west"
    )
    await _write(neo4j_driver, closed, save=True)

    async def reuse(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "CREATE (:ServiceRequest {id: 'case-y', key: 'ServiceRequest/case-y', "
            "reference: '4821', openReference: '4821', tenantId: $tenant})",
            tenant=current_tenant(),
        )

    await write_tx(neo4j_driver, reuse)

    rows = await _references(neo4j_driver)
    assert {(r["id"], r["open"]) for r in rows} == {("case-1", None), ("case-y", "4821")}


@pytest.mark.parametrize(
    ("postcode", "needs"),
    [("DT4", OPEN_CASE.needs), (None, (NeedCategory.FRAILTY,))],
)
async def test_a_closed_case_saved_with_postcode_or_needs_left_is_refused(
    neo4j_driver: AsyncDriver, postcode: str | None, needs: tuple[NeedCategory, ...]
) -> None:
    await _write(neo4j_driver, OPEN_CASE)
    residue = replace(
        OPEN_CASE,
        closed_at=CLOSED,
        outcome=Outcome.DECLINED,
        postcode=postcode,
        needs=needs,
    )

    with pytest.raises(ValidationFailed):
        await _write(neo4j_driver, residue, save=True)

    assert await _load(neo4j_driver, "case-1") == OPEN_CASE


async def test_a_duplicate_reference_that_passes_the_check_is_a_conflict(
    neo4j_driver: AsyncDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the pre-check is bypassed: the unique constraint on the reference must still refuse the
    # write at the reference step, and the store's error must come back as Conflict.
    await _write(neo4j_driver, OPEN_CASE)
    real_run_query = case_repository.run_query

    async def skip_the_reference_check(
        tx: AsyncManagedTransaction, query: NamedQuery, **params: Any
    ) -> Any:
        if query.id == "Q-CASE-BY-REF":
            return []
        return await real_run_query(tx, query, **params)

    monkeypatch.setattr(case_repository, "run_query", skip_the_reference_check)

    with pytest.raises(Conflict):
        await _write(neo4j_driver, replace(OPEN_CASE, id="case-3"))

    assert await count_nodes(neo4j_driver, "Patient") == 1
    assert await _load(neo4j_driver, "case-1") == OPEN_CASE


async def test_an_outcome_without_a_close_time_is_refused_on_add_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    # Round-2 finding: the write path accepted this and the next read raised. Refused on the way in.
    bad = replace(OPEN_CASE, outcome=Outcome.DECLINED)

    async def swallow_and_commit(tx: AsyncManagedTransaction) -> None:
        with contextlib.suppress(ValidationFailed):
            await _repo(tx).add(bad)

    await write_tx(neo4j_driver, swallow_and_commit)

    assert await count_nodes(neo4j_driver, "Patient") == 0
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 0


async def test_an_outcome_without_a_close_time_is_refused_on_save_and_the_stored_case_is_kept(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)
    bad = replace(OPEN_CASE, outcome=Outcome.DECLINED)

    with pytest.raises(ValidationFailed):
        await _write(neo4j_driver, bad, save=True)

    assert await _load(neo4j_driver, "case-1") == OPEN_CASE


async def test_a_full_postcode_is_refused_on_save_and_the_stored_case_is_kept(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)
    full = replace(OPEN_CASE, postcode="DT4 8XX")

    with pytest.raises(ValidationFailed):
        await _write(neo4j_driver, full, save=True)

    assert await _load(neo4j_driver, "case-1") == OPEN_CASE


async def test_a_closed_case_with_residue_is_refused_on_add_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    residue = replace(OPEN_CASE, closed_at=CLOSED, outcome=Outcome.DECLINED)

    async def swallow_and_commit(tx: AsyncManagedTransaction) -> None:
        with contextlib.suppress(ValidationFailed):
            await _repo(tx).add(residue)

    await write_tx(neo4j_driver, swallow_and_commit)

    assert await count_nodes(neo4j_driver, "Patient") == 0
    assert await count_nodes(neo4j_driver, "Observation") == 0


# TEN-005: the open reference, the property a composite constraint is unique on. It is set while a
# case is open and removed when the case closes, so a closed case's reference blocks nobody once
# the lifetime-unique constraint went (TEN-032).


async def _references(driver: AsyncDriver) -> list[dict[str, Any]]:
    return await _rows(
        driver,
        "MATCH (r:ServiceRequest {tenantId: $tenant}) RETURN r.id AS id, r.reference AS reference, "
        "r.openReference AS open ORDER BY id",
    )


async def test_an_open_case_carries_its_reference_as_the_open_reference(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)

    assert await _references(neo4j_driver) == [
        {"id": "case-1", "reference": "4821", "open": "4821"}
    ]


async def test_saving_an_open_case_keeps_its_open_reference(neo4j_driver: AsyncDriver) -> None:
    await _write(neo4j_driver, OPEN_CASE)
    await _write(neo4j_driver, replace(OPEN_CASE, urgency=Urgency.TODAY), save=True)

    assert await _references(neo4j_driver) == [
        {"id": "case-1", "reference": "4821", "open": "4821"}
    ]


async def test_closing_a_case_removes_the_open_reference_and_keeps_the_reference(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)
    closed = OPEN_CASE.close(
        Outcome.ACCEPTED_AND_BOOKED, CLOSED, destination_service_id="svc-ucr-west"
    )

    await _write(neo4j_driver, closed, save=True)

    assert await _references(neo4j_driver) == [{"id": "case-1", "reference": "4821", "open": None}]
    assert await _load(neo4j_driver, "case-1") == closed


async def test_two_open_cases_with_one_reference_are_still_refused_as_conflict(
    neo4j_driver: AsyncDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-tenant open-only constraint refuses it (the lifetime-unique one went with TEN-032).
    The statement sets both properties in one write, so the refusal is a Conflict and nothing of
    the second case stays."""
    await _write(neo4j_driver, OPEN_CASE)
    real_run_query = case_repository.run_query

    async def skip_the_reference_check(
        tx: AsyncManagedTransaction, query: NamedQuery, **params: Any
    ) -> Any:
        if query.id == "Q-CASE-BY-REF":
            return []
        return await real_run_query(tx, query, **params)

    monkeypatch.setattr(case_repository, "run_query", skip_the_reference_check)

    with pytest.raises(Conflict):
        await _write(neo4j_driver, replace(OPEN_CASE, id="case-3"))

    assert await _references(neo4j_driver) == [
        {"id": "case-1", "reference": "4821", "open": "4821"}
    ]


async def test_the_first_recording_of_scores_on_an_open_case_writes_them_and_reads_them_back(
    neo4j_driver: AsyncDriver,
) -> None:
    # UpdateCase records the referrer's scores once, after the case is opened without them (U11;
    # the CaseRepository port: scores never change once recorded). Each score is written once, here,
    # and nothing else about the case changes.
    await _write(neo4j_driver, replace(OPEN_CASE, scores=()))

    await _write(neo4j_driver, OPEN_CASE, save=True)

    assert await _load(neo4j_driver, "case-1") == OPEN_CASE
    assert await count_nodes(neo4j_driver, "Observation") == 2


async def test_a_save_that_clears_recorded_scores_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, OPEN_CASE)

    with pytest.raises(ValidationFailed):
        await _write(neo4j_driver, replace(OPEN_CASE, scores=()), save=True)

    assert await _load(neo4j_driver, "case-1") == OPEN_CASE
    assert await count_nodes(neo4j_driver, "Observation") == 2


async def test_a_case_opened_with_no_scores_round_trips_and_has_no_empty_score_list(
    neo4j_driver: AsyncDriver,
) -> None:
    # An advisor opens a case before any score is known (U11). The mapper refuses an empty list,
    # so a case with no scores leaves the supporting-information element out (the P21 mapping).
    empty = replace(OPEN_CASE, scores=())

    await assert_round_trip(
        neo4j_driver,
        lambda tx: _repo(tx).add(empty),
        lambda tx: _repo(tx).get("case-1"),
        empty,
    )
    assert await _rows(
        neo4j_driver,
        "MATCH (r:ServiceRequest {id: 'case-1', tenantId: $tenant}) RETURN r.supportingInfo AS "
        "info",
    ) == [{"info": None}]
