"""The hourly samples of a network board on a real Neo4j (TEN-082, DEC-132 item 4).

A network scope holds one sample per hour: counts per status, the organisations shown and the
highest pressure of the hour. The tests show: a sample is read back equal; a later sample of an
hour replaces the counts and keeps the highest pressure; an older one changes only the peak; the
key is unique per scope and hour, so two samples of an hour are one node; two networks with the
same hours see only their own; a tenant scope and a read-only unit cannot write; and the node holds
exactly the properties of a sample, no null, and nothing that names a member or a service.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.unit_of_work import Neo4jUnitOfWork
from diucs.application.tenancy import (
    ReadOnlyUnitWrite,
    ScopeKindMismatch,
    bind_network,
    bind_tenant,
)
from diucs.domain.codes import Status
from diucs.domain.rules.network_sample import READINGS, NetworkSample
from diucs.domain.rules.pressure import Pressure
from tests.support.neo4j import read_tx, write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

HOUR = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
FROM = HOUR - timedelta(hours=2)
TO = HOUR + timedelta(hours=2)
SAMPLE_PROPERTIES = {
    "tenantId",
    "hour",
    "lastAt",
    "accepting",
    "limited",
    "notAccepting",
    "overCapacity",
    "notUpdated",
    "outOfHours",
    "unavailable",
    "organisations",
    "peak",
}


@pytest.fixture
def net_a(network_id: str) -> str:
    return network_id


@pytest.fixture
def net_b(network_id: str) -> str:
    return f"{network_id}-b"


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _clean_networks(
    harness_driver: AsyncDriver, net_a: str, net_b: str
) -> AsyncIterator[None]:
    async def wipe(tx: AsyncManagedTransaction) -> None:
        await tx.run("MATCH (n) WHERE n.tenantId IN $nets DETACH DELETE n", nets=[net_a, net_b])

    await write_tx(harness_driver, wipe)
    yield
    await write_tx(harness_driver, wipe)


def sample(
    hour: datetime = HOUR,
    minute: int = 30,
    pressure: Pressure = Pressure.NORMAL,
    organisations: int = 3,
    **counts: int,
) -> NetworkSample:
    tally = {status: 0 for status in READINGS}
    tally.update({Status(k.replace("_", "-")): v for k, v in counts.items()})
    return NetworkSample(
        hour=hour,
        at=hour + timedelta(minutes=minute),
        counts=tuple(tally.items()),
        unavailable=1,
        organisations=organisations,
        pressure=pressure,
    )


@asynccontextmanager
async def unit(driver: AsyncDriver, scope: str, *, read_only: bool = False) -> AsyncIterator[Any]:
    with bind_network(scope):
        async with Neo4jUnitOfWork(driver, read_only=read_only) as uow:
            yield uow


async def put(driver: AsyncDriver, scope: str, *samples: NetworkSample) -> list[bool]:
    async with unit(driver, scope) as uow:
        written = [await uow.network_samples.record(s) for s in samples]
        await uow.commit()
    return written


async def get(
    driver: AsyncDriver, scope: str, start: datetime = FROM, end: datetime = TO
) -> list[NetworkSample]:
    async with unit(driver, scope, read_only=True) as uow:
        return list(await uow.network_samples.between(start, end))


async def test_a_sample_is_read_back_equal(harness_driver: AsyncDriver, net_a: str) -> None:
    one = sample(accepting=4, limited=2, not_updated=1, pressure=Pressure.WATCH)
    assert await put(harness_driver, net_a, one) == [True]
    assert await get(harness_driver, net_a) == [one]


async def test_a_later_sample_of_the_hour_replaces_the_counts_and_keeps_the_highest_pressure(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await put(harness_driver, net_a, sample(accepting=4, pressure=Pressure.HIGH))
    later = sample(minute=50, accepting=2, limited=3, pressure=Pressure.NORMAL)
    assert await put(harness_driver, net_a, later) == [True]
    (stored,) = await get(harness_driver, net_a)
    assert stored == replace(later, pressure=Pressure.HIGH)


async def test_a_later_sample_with_a_higher_pressure_raises_the_peak(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await put(harness_driver, net_a, sample(accepting=4, pressure=Pressure.WATCH))
    await put(harness_driver, net_a, sample(minute=40, accepting=4, pressure=Pressure.HIGH))
    (stored,) = await get(harness_driver, net_a)
    assert stored.pressure is Pressure.HIGH


async def test_an_older_sample_than_the_hour_holds_changes_only_the_peak(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    newest = sample(minute=50, accepting=2, pressure=Pressure.NORMAL)
    await put(harness_driver, net_a, newest)
    stale = sample(minute=10, accepting=9, pressure=Pressure.HIGH)
    assert await put(harness_driver, net_a, stale) == [False]
    (stored,) = await get(harness_driver, net_a)
    assert stored.at == newest.at
    assert stored.count(Status.ACCEPTING) == 2
    assert stored.pressure is Pressure.HIGH


async def test_a_replay_of_the_same_sample_changes_nothing(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    one = sample(accepting=4, limited=1)
    await put(harness_driver, net_a, one)
    assert await put(harness_driver, net_a, one) == [True]
    assert await get(harness_driver, net_a) == [one]


async def test_two_samples_of_an_hour_are_one_node(harness_driver: AsyncDriver, net_a: str) -> None:
    await put(harness_driver, net_a, sample(minute=5, accepting=1), sample(minute=6, accepting=2))

    async def count(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (s:NetworkSample {tenantId: $tenant}) RETURN count(s) AS n", tenant=net_a
        )
        return await result.data()

    assert (await read_tx(harness_driver, count))[0]["n"] == 1


async def test_concurrent_samples_of_one_hour_make_one_node_and_keep_the_highest_pressure(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await asyncio.gather(
        *(
            put(harness_driver, net_a, sample(minute=m, accepting=m, pressure=p))
            for m, p in ((10, Pressure.NORMAL), (20, Pressure.HIGH), (30, Pressure.WATCH))
        ),
        return_exceptions=True,
    )
    stored = await get(harness_driver, net_a)
    assert len(stored) == 1
    assert stored[0].pressure is Pressure.HIGH


async def test_the_range_is_half_open_and_ordered(harness_driver: AsyncDriver, net_a: str) -> None:
    hours = [HOUR + timedelta(hours=h) for h in (-3, -2, 0, 1, 2)]
    await put(harness_driver, net_a, *(sample(h, accepting=i) for i, h in enumerate(hours)))
    found = await get(harness_driver, net_a, FROM, TO)
    assert [s.hour for s in found] == [HOUR - timedelta(hours=2), HOUR, HOUR + timedelta(hours=1)]


async def test_two_networks_with_the_same_hours_see_only_their_own(
    harness_driver: AsyncDriver, net_a: str, net_b: str
) -> None:
    await put(harness_driver, net_a, sample(accepting=1, organisations=3))
    await put(harness_driver, net_b, sample(accepting=7, organisations=9))
    (mine,) = await get(harness_driver, net_a)
    (theirs,) = await get(harness_driver, net_b)
    assert (mine.count(Status.ACCEPTING), mine.organisations) == (1, 3)
    assert (theirs.count(Status.ACCEPTING), theirs.organisations) == (7, 9)


async def test_a_write_in_one_network_changes_nothing_in_another(
    harness_driver: AsyncDriver, net_a: str, net_b: str
) -> None:
    await put(harness_driver, net_b, sample(accepting=7))
    await put(harness_driver, net_a, sample(minute=50, accepting=1, pressure=Pressure.HIGH))
    (theirs,) = await get(harness_driver, net_b)
    assert (theirs.count(Status.ACCEPTING), theirs.pressure) == (7, Pressure.NORMAL)


async def test_a_tenant_scope_cannot_run_either_statement(
    harness_driver: AsyncDriver, tenant_id: str
) -> None:
    with bind_tenant(tenant_id):
        async with Neo4jUnitOfWork(harness_driver) as uow:
            with pytest.raises(ScopeKindMismatch):
                await uow.network_samples.record(sample())
            with pytest.raises(ScopeKindMismatch):
                await uow.network_samples.between(FROM, TO)


async def test_a_read_only_unit_cannot_write_but_reads(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await put(harness_driver, net_a, sample(accepting=1))
    async with unit(harness_driver, net_a, read_only=True) as uow:
        assert len(await uow.network_samples.between(FROM, TO)) == 1
        with pytest.raises(ReadOnlyUnitWrite):
            await uow.network_samples.record(sample(accepting=2))


async def test_the_node_holds_exactly_the_sample_properties_and_no_null(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await put(harness_driver, net_a, sample(accepting=4, limited=1))

    async def props(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (s:NetworkSample {tenantId: $tenant}) RETURN properties(s) AS p", tenant=net_a
        )
        return await result.data()

    (row,) = await read_tx(harness_driver, props)
    stored = row["p"]
    assert set(stored) == SAMPLE_PROPERTIES
    assert all(value is not None for value in stored.values())
    assert stored["tenantId"] == net_a and stored["peak"] == "normal"


async def test_the_samples_hold_nothing_of_a_member_or_a_service(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await put(harness_driver, net_a, sample(accepting=4))

    async def relationships(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (s:NetworkSample {tenantId: $tenant}) OPTIONAL MATCH (s)-[r]-() "
            "WHERE s.tenantId = $tenant "
            "RETURN count(r) AS n, [k IN keys(s) WHERE k CONTAINS 'ource' OR k CONTAINS 'ervice' "
            "OR k CONTAINS 'rant'] AS keys",
            tenant=net_a,
        )
        return await result.data()

    (row,) = await read_tx(harness_driver, relationships)
    assert row == {"n": 0, "keys": []}
