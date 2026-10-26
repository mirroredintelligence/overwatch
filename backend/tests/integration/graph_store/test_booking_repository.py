"""Integration tests for the booking repository (P02).

Run against the throwaway Neo4j that the F10 harness starts for the pytest session (DEC-008). Each
write is one committed transaction and each read is a fresh session, so the tests assert on what
was really stored. All values are synthetic; there is no patient data.
"""

import asyncio
import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.booking_repository import (
    Neo4jBookingRepository,
    booking_to_fhir,
    read_task_fhir,
)
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.codes import BookingStatus
from diucs.domain.errors import Conflict, NotFound
from diucs.domain.model.booking import Booking
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

REQUESTED_AT = datetime(2026, 10, 25, 13, 16, tzinfo=UTC)
REPLY_BY = datetime(2026, 10, 25, 13, 26, tzinfo=UTC)
CONFIRMED_AT = datetime(2026, 10, 25, 13, 19, tzinfo=UTC)

BOOKING_4821 = Booking(
    id="bk-4821",
    reference="4821",
    service_id="svc-ucr-west",
    case_id="case-1",
    requester_id="prac-advisor-1",
    status=BookingStatus.REQUESTED,
    requested_at=REQUESTED_AT,
    reply_by=REPLY_BY,
)
BOOKING_4822_EAST = Booking(
    id="bk-4822",
    reference="4822",
    service_id="svc-ucr-east",
    case_id="case-2",
    requester_id="prac-advisor-1",
    status=BookingStatus.REQUESTED,
    requested_at=REQUESTED_AT,
    reply_by=REPLY_BY,
)


def _repo(tx: AsyncManagedTransaction) -> Neo4jBookingRepository:
    return Neo4jBookingRepository(tx, ResourceStore(tx))


async def _write(driver: AsyncDriver, *bookings: Booking, save: bool = False) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = _repo(tx)
        for booking in bookings:
            if save:
                await repo.save(booking)
            else:
                await repo.add(booking)

    await write_tx(driver, work)


async def test_booking_4821_round_trips_through_a_fresh_session(neo4j_driver: AsyncDriver) -> None:
    async def save(tx: AsyncManagedTransaction) -> None:
        await _repo(tx).add(BOOKING_4821)

    async def load(tx: AsyncManagedTransaction) -> Booking | None:
        return await _repo(tx).get("bk-4821")

    await assert_round_trip(neo4j_driver, save, load, BOOKING_4821)


async def test_the_stored_task_reads_back_as_the_fhir_form_apart_from_meta(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, BOOKING_4821)

    async def load(tx: AsyncManagedTransaction) -> dict[str, Any] | None:
        return await read_task_fhir(ResourceStore(tx), "bk-4821")

    resource = await read_tx(neo4j_driver, load)

    assert resource is not None
    assert "meta" in resource
    del resource["meta"]
    assert resource == booking_to_fhir(BOOKING_4821)


async def test_the_task_node_has_reference_and_business_status_properties(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, BOOKING_4821)

    props = await node_props(neo4j_driver, "Task", id="bk-4821")

    assert props["reference"] == "4821"
    assert props["businessStatus"] == "requested"


async def test_open_bookings_for_a_service_are_the_requested_ones(
    neo4j_driver: AsyncDriver,
) -> None:
    confirmed = BOOKING_4822_EAST.with_status(BookingStatus.CONFIRMED, CONFIRMED_AT)
    await _write(neo4j_driver, BOOKING_4821, BOOKING_4822_EAST)
    await _write(neo4j_driver, confirmed, save=True)

    open_ucr_west = await read_tx(
        neo4j_driver, lambda tx: _repo(tx).open_for_service("svc-ucr-west")
    )
    assert [b.id for b in open_ucr_west] == ["bk-4821"]

    pending = await read_tx(neo4j_driver, lambda tx: _repo(tx).pending_count("svc-ucr-west"))
    assert pending == len(open_ucr_west) == 1

    by_service = await read_tx(
        neo4j_driver,
        lambda tx: _repo(tx).open_for_services(["svc-ucr-west", "svc-ucr-east"]),
    )
    assert [b.id for b in by_service["svc-ucr-west"]] == ["bk-4821"]
    assert by_service["svc-ucr-east"] == []


async def test_confirmed_since_lists_confirmed_at_until_the_booking_is_cancelled_after(
    neo4j_driver: AsyncDriver,
) -> None:
    since = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)
    confirmed = BOOKING_4821.with_status(BookingStatus.CONFIRMED, CONFIRMED_AT)
    await _write(neo4j_driver, confirmed)

    before = await read_tx(
        neo4j_driver, lambda tx: _repo(tx).confirmed_since("svc-ucr-west", since)
    )
    assert before == [CONFIRMED_AT]

    cancelled = confirmed.with_status(BookingStatus.CANCELLED_AFTER, CONFIRMED_AT)
    await _write(neo4j_driver, cancelled, save=True)

    after = await read_tx(neo4j_driver, lambda tx: _repo(tx).confirmed_since("svc-ucr-west", since))
    assert after == []


async def test_get_by_reference_finds_the_booking_and_unknown_is_none(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, BOOKING_4821)

    found = await read_tx(neo4j_driver, lambda tx: _repo(tx).get_by_reference("4821"))
    missing = await read_tx(neo4j_driver, lambda tx: _repo(tx).get_by_reference("9999"))

    assert found == BOOKING_4821
    assert missing is None


async def test_the_task_is_owned_by_the_service_and_focused_on_the_case_with_no_for(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, BOOKING_4821)

    async def rels(tx: AsyncManagedTransaction) -> list[tuple[str, str]]:
        result = await tx.run(
            "MATCH (:Task {id: 'bk-4821'})-[r]->(t) RETURN type(r) AS type, t.key AS key"
        )
        return [(row["type"], row["key"]) async for row in result]

    edges = await read_tx(neo4j_driver, rels)

    assert ("OWNER", "HealthcareService/svc-ucr-west") in edges
    assert ("FOCUS", "ServiceRequest/case-1") in edges
    assert all(edge_type != "FOR" for edge_type, _ in edges)


async def test_add_twice_is_a_conflict_and_save_of_an_unknown_booking_is_not_found(
    neo4j_driver: AsyncDriver,
) -> None:
    await _write(neo4j_driver, BOOKING_4821)

    with pytest.raises(Conflict):
        await _write(neo4j_driver, BOOKING_4821)

    with pytest.raises(NotFound):
        await _write(neo4j_driver, BOOKING_4822_EAST, save=True)

    assert await count_nodes(neo4j_driver, "Task") == 1


async def test_sixteen_racing_adds_of_one_booking_let_exactly_one_win(
    neo4j_driver: AsyncDriver,
) -> None:
    async def add_once() -> bool:
        try:
            await _write(neo4j_driver, BOOKING_4821)
        except Conflict:
            return False
        return True

    outcomes = await asyncio.gather(*(add_once() for _ in range(16)))

    assert outcomes.count(True) == 1
    assert await count_nodes(neo4j_driver, "Task") == 1


async def test_confirmed_since_for_services_gives_each_service_its_own_confirmations(
    neo4j_driver: AsyncDriver,
) -> None:
    since = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)
    west_after = BOOKING_4821.with_status(BookingStatus.CONFIRMED, CONFIRMED_AT)
    west_before = dataclasses.replace(BOOKING_4821, id="bk-4823", reference="4823").with_status(
        BookingStatus.CONFIRMED, datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    )
    east_at = datetime(2026, 10, 25, 13, 30, tzinfo=UTC)
    east_after = BOOKING_4822_EAST.with_status(BookingStatus.CONFIRMED, east_at)
    await _write(neo4j_driver, west_after, west_before, east_after)

    grouped = await read_tx(
        neo4j_driver,
        lambda tx: _repo(tx).confirmed_since_for_services(
            ["svc-ucr-west", "svc-ucr-east", "svc-none"], since
        ),
    )

    assert grouped == {
        "svc-ucr-west": [CONFIRMED_AT],
        "svc-ucr-east": [east_at],
        "svc-none": [],
    }
