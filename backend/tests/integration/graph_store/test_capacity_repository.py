"""Integration tests for the capacity repository (P01).

Written through the resource store in one committed transaction, read back in a fresh session.
Reports are never updated: a second add with the same id is a Conflict and the graph keeps one.
All values are synthetic.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.capacity_repository import Neo4jCapacityRepository
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import Neo4jServiceRepository
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.domain.codes import Measure, ReportSource, ReportType
from diucs.domain.errors import Conflict, NotFound
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile
from tests.integration.graph_store.test_service_repository import (
    REABLEMENT,
    UCR_EAST,
)
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip
from tests.unit.adapters.outbound.graph_store.test_capacity_repository import (
    CONFIRMED_REPORT,
    NUMBER_REPORT,
)
from tests.unit.adapters.outbound.graph_store.test_service_repository import UCR_WEST

pytestmark = pytest.mark.asyncio(loop_scope="session")

REPORT_0715 = CapacityReport(
    id="obs-ucr-west-0715",
    service_id="svc-ucr-west",
    value=2,
    measure=Measure.REFERRALS_ACCEPTABLE,
    effective_at=datetime(2026, 10, 25, 7, 15, tzinfo=UTC),
    source=ReportSource.TEXT,
    report_type=ReportType.NUMBER,
)
REPORT_0912 = NUMBER_REPORT


def _repo(tx: AsyncManagedTransaction) -> Neo4jCapacityRepository:
    return Neo4jCapacityRepository(tx, ResourceStore(tx))


async def _seed(driver: AsyncDriver, *profiles: ServiceProfile) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        services = Neo4jServiceRepository(tx, ResourceStore(tx))
        for profile in profiles:
            await services.save(profile)

    await write_tx(driver, work)


async def _add(driver: AsyncDriver, *reports: CapacityReport) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = _repo(tx)
        for report in reports:
            await repo.add(report)

    await write_tx(driver, work)


async def _read(driver: AsyncDriver, fn: Any) -> Any:
    return await read_tx(driver, lambda tx: fn(_repo(tx)))


async def test_a_number_report_round_trips_through_a_fresh_session(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, UCR_WEST)

    async def save(tx: AsyncManagedTransaction) -> None:
        await _repo(tx).add(NUMBER_REPORT)

    async def load(tx: AsyncManagedTransaction) -> CapacityReport | None:
        return await _repo(tx).latest("svc-ucr-west")

    await assert_round_trip(neo4j_driver, save, load, NUMBER_REPORT)


async def test_a_confirmed_report_round_trips_with_its_performer_and_derived_from(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, UCR_WEST)
    await _add(neo4j_driver, NUMBER_REPORT)

    async def save(tx: AsyncManagedTransaction) -> None:
        await _repo(tx).add(CONFIRMED_REPORT)

    async def load(tx: AsyncManagedTransaction) -> CapacityReport | None:
        return await _repo(tx).latest("svc-ucr-west")

    await assert_round_trip(neo4j_driver, save, load, CONFIRMED_REPORT)


async def test_the_stored_observation_has_its_label_and_properties(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, UCR_WEST)
    await _add(neo4j_driver, NUMBER_REPORT)

    props = await node_props(neo4j_driver, "Observation", id=NUMBER_REPORT.id)

    assert props["key"] == f"Observation/{NUMBER_REPORT.id}"
    assert props["status"] == "final"
    assert props["valueQuantity_value"] == 5
    assert props["measureCode"] == "referrals-acceptable"
    assert props["ext_reportType"] == "number"
    assert "json" not in props


async def test_a_report_for_a_service_that_is_not_stored_is_refused(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, UCR_WEST)
    orphan = replace(NUMBER_REPORT, id="obs-orphan", service_id="svc-missing")

    with pytest.raises(NotFound):
        await _add(neo4j_driver, orphan)

    assert await count_nodes(neo4j_driver, "Observation") == 0


async def test_latest_is_the_greatest_effective_time_even_when_added_last(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, UCR_WEST)
    await _add(neo4j_driver, REPORT_0912, REPORT_0715)

    assert await _read(neo4j_driver, lambda repo: repo.latest("svc-ucr-west")) == REPORT_0912


async def test_latest_for_services_has_one_key_for_a_service_with_reports(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, UCR_WEST, REABLEMENT)
    await _add(neo4j_driver, REPORT_0715, REPORT_0912)

    latest = await _read(
        neo4j_driver,
        lambda repo: repo.latest_for_services(["svc-ucr-west", "svc-none"]),
    )

    assert latest == {"svc-ucr-west": REPORT_0912}


async def test_reports_since_returns_only_reports_at_or_after_the_time_oldest_first(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, UCR_WEST)
    await _add(neo4j_driver, REPORT_0912, REPORT_0715)
    since = datetime(2026, 10, 25, 8, 0, tzinfo=UTC)

    reports = await _read(neo4j_driver, lambda repo: repo.reports_since("svc-ucr-west", since))

    assert reports == [REPORT_0912]


async def test_a_report_read_back_carries_the_whole_second_the_store_wrote_it(
    neo4j_driver: AsyncDriver,
) -> None:
    """The record order behind hazard H-32 (U05): the write time is the store's, not the report's
    effective time, and it is whole seconds (lesson L65)."""
    await _seed(neo4j_driver, UCR_WEST)
    clock = FixedClock(datetime(2026, 10, 25, 10, 3, 7, 987_654, tzinfo=UTC))

    async def save(tx: AsyncManagedTransaction) -> None:
        await Neo4jCapacityRepository(tx, ResourceStore(tx, clock)).add(REPORT_0715)

    await write_tx(neo4j_driver, save)

    for read in (
        lambda repo: repo.latest("svc-ucr-west"),
        lambda repo: repo.get(REPORT_0715.id),
        lambda repo: repo.reports_since("svc-ucr-west", datetime(2026, 1, 1, tzinfo=UTC)),
        lambda repo: repo.latest_for_services(["svc-ucr-west"]),
    ):
        found = await _read(neo4j_driver, read)
        report = (
            found["svc-ucr-west"]
            if isinstance(found, dict)
            else found[0]
            if isinstance(found, list)
            else found
        )
        assert report.effective_at == REPORT_0715.effective_at  # the report's own time is kept
        assert report.written_at == datetime(2026, 10, 25, 10, 3, 7, tzinfo=UTC)


async def test_last_report_times_gives_the_latest_time_or_none_for_every_active_service(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, UCR_WEST, REABLEMENT, UCR_EAST)
    await _add(neo4j_driver, REPORT_0715, REPORT_0912)

    times = await _read(neo4j_driver, lambda repo: repo.last_report_times())

    assert times == {
        "svc-reablement": None,
        "svc-ucr-east": None,
        "svc-ucr-west": datetime(2026, 10, 25, 9, 12, tzinfo=UTC),
    }


async def test_adding_the_same_report_id_twice_is_a_conflict_and_keeps_one_node(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, UCR_WEST)
    await _add(neo4j_driver, NUMBER_REPORT)

    with pytest.raises(Conflict):
        await _add(neo4j_driver, NUMBER_REPORT)

    assert await count_nodes(neo4j_driver, "Observation") == 1


def _report(report_id: str, hour: int, report_type: ReportType) -> CapacityReport:
    return CapacityReport(
        id=report_id,
        service_id="svc-ucr-west",
        value=5,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=datetime(2026, 10, 25, hour, 0, tzinfo=UTC),
        source=ReportSource.TEXT,
        report_type=report_type,
        derived_from=None if report_type is ReportType.NUMBER else "obs-n",
    )


@pytest.mark.parametrize(
    ("types", "expected"),
    [
        ((), 0),
        (("number",), 0),
        (("number", "confirmed"), 1),
        (("number", "confirmed", "confirmed"), 2),
        (("number", "confirmed", "confirmed", "confirmed"), 3),
        (("number", "confirmed", "confirmed", "number"), 0),
        (("number", "confirmed", "confirmed", "number", "confirmed"), 1),
        (("confirmed",), 1),
    ],
)
async def test_trailing_confirmations_counts_confirmed_reports_after_the_last_number(
    neo4j_driver: AsyncDriver, types: tuple[str, ...], expected: int
) -> None:
    await _seed(neo4j_driver, UCR_WEST, UCR_EAST)
    other = replace(_report("obs-other", 20, ReportType.NUMBER), service_id="svc-ucr-east")
    await _add(neo4j_driver, other)
    reports = [_report(f"obs-{i}", 6 + i, ReportType(t)) for i, t in enumerate(types)]
    await _add(neo4j_driver, *reports)

    count = await _read(neo4j_driver, lambda repo: repo.trailing_confirmations("svc-ucr-west"))

    assert count == expected


async def test_trailing_confirmations_follows_effective_time_not_insert_order(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, UCR_WEST)
    await _add(
        neo4j_driver,
        _report("obs-late-confirm", 10, ReportType.CONFIRMED),
        _report("obs-early-number", 6, ReportType.NUMBER),
    )

    count = await _read(neo4j_driver, lambda repo: repo.trailing_confirmations("svc-ucr-west"))

    assert count == 1


async def test_trailing_confirmations_of_an_unknown_service_is_zero(
    neo4j_driver: AsyncDriver,
) -> None:
    assert await _read(neo4j_driver, lambda repo: repo.trailing_confirmations("nope")) == 0


async def test_latest_confirmation_at_is_the_newest_confirmed_effective_time(
    neo4j_driver: AsyncDriver,
) -> None:
    """DEC-140: the effective time of the newest confirmed report of one service. Numbers are not
    confirmations, another service's confirmation is not this service's, and a service with no
    confirmation has None."""
    await _seed(neo4j_driver, UCR_WEST, UCR_EAST)
    repo_none = await _read(neo4j_driver, lambda repo: repo.latest_confirmation_at("svc-ucr-west"))
    assert repo_none is None
    await _add(
        neo4j_driver,
        _report("obs-n1", 6, ReportType.NUMBER),
        _report("obs-c1", 8, ReportType.CONFIRMED),
        _report("obs-n2", 10, ReportType.NUMBER),
    )
    other = replace(_report("obs-other-c", 20, ReportType.CONFIRMED), service_id="svc-ucr-east")
    await _add(neo4j_driver, other)

    at = await _read(neo4j_driver, lambda repo: repo.latest_confirmation_at("svc-ucr-west"))

    assert at == datetime(2026, 10, 25, 8, 0, tzinfo=UTC)


async def test_get_returns_the_report_with_this_id_and_none_for_another(
    neo4j_driver: AsyncDriver,
) -> None:
    """R05: the confirm operation reads back the report it just wrote, by the report's own id."""
    await _seed(neo4j_driver, UCR_WEST, UCR_EAST)
    number = _report("obs-n", 6, ReportType.NUMBER)
    confirmed = _report("obs-c", 8, ReportType.CONFIRMED)
    await _add(neo4j_driver, number, confirmed)

    got_confirmed = await _read(neo4j_driver, lambda repo: repo.get("obs-c"))
    got_number = await _read(neo4j_driver, lambda repo: repo.get("obs-n"))
    missing = await _read(neo4j_driver, lambda repo: repo.get("obs-nope"))

    assert got_confirmed == confirmed
    assert got_number == number
    assert missing is None


async def test_get_does_not_return_a_resource_of_another_type_with_the_same_id(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver, UCR_WEST)

    # The service's own id is not a report id.
    assert await _read(neo4j_driver, lambda repo: repo.get("svc-ucr-west")) is None
