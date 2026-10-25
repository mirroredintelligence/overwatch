"""Integration tests for the service repository (P01).

They run against the throwaway Neo4j that the F10 harness starts for the pytest session (DEC-008).
Every write is one committed transaction, and every read happens in a fresh session, so what the
tests assert is what was really stored. All values are synthetic.
"""

from dataclasses import replace
from datetime import time
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import (
    Neo4jServiceRepository,
    profile_to_fhir,
)
from diucs.domain.codes import BASE_URL, Cadence, Channel, Measure, ServiceCategory
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip
from tests.unit.adapters.outbound.graph_store.test_service_repository import UCR_WEST

pytestmark = pytest.mark.asyncio(loop_scope="session")

REABLEMENT = ServiceProfile(
    id="svc-reablement",
    name="Reablement",
    category=ServiceCategory.REABLEMENT,
    measure=Measure.FREE_SLOTS,
    unit_label="visits",
    established_capacity=20,
    can_exceed_established=True,
    usual_range=(5, 20),
    cadence=Cadence.ONCE_A_DAY,
    available_times=(AvailableTime.every_day_all_day(),),
    channel=Channel.EMAIL,
)
UCR_EAST = replace(UCR_WEST, id="svc-ucr-east", name="UCR East")
CLOSED_WARD = replace(UCR_WEST, id="svc-closed-ward", name="Closed ward", active=False)


def _repo(tx: AsyncManagedTransaction) -> Neo4jServiceRepository:
    return Neo4jServiceRepository(tx, ResourceStore(tx))


async def _save(driver: AsyncDriver, *profiles: ServiceProfile) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = _repo(tx)
        for profile in profiles:
            await repo.save(profile)

    await write_tx(driver, work)


async def _get(driver: AsyncDriver, service_id: str) -> ServiceProfile | None:
    return await read_tx(driver, lambda tx: _repo(tx).get(service_id))


async def test_ucr_west_round_trips_through_a_fresh_session(neo4j_driver: AsyncDriver) -> None:
    async def save(tx: AsyncManagedTransaction) -> None:
        await _repo(tx).save(UCR_WEST)

    async def load(tx: AsyncManagedTransaction) -> ServiceProfile | None:
        return await _repo(tx).get("svc-ucr-west")

    await assert_round_trip(neo4j_driver, save, load, UCR_WEST)


async def test_the_stored_node_has_the_fhir_label_and_its_extension_properties(
    neo4j_driver: AsyncDriver,
) -> None:
    await _save(neo4j_driver, UCR_WEST)

    props = await node_props(neo4j_driver, "HealthcareService", id="svc-ucr-west")

    assert props["key"] == "HealthcareService/svc-ucr-west"
    assert props["ext_establishedCapacity"] == 8
    assert props["ext_usualRangeMax"] == 8
    assert props["ext_measure"] == "referrals-acceptable"
    assert "json" not in props
    assert await count_nodes(neo4j_driver, "HealthcareService") == 1


async def test_the_stored_resource_rebuilds_to_the_mapped_fhir_apart_from_meta(
    neo4j_driver: AsyncDriver,
) -> None:
    await _save(neo4j_driver, UCR_WEST)

    async def load(tx: AsyncManagedTransaction) -> dict[str, Any] | None:
        return await ResourceStore(tx).get("HealthcareService", "svc-ucr-west")

    rebuilt = await read_tx(neo4j_driver, load)
    assert rebuilt is not None
    rebuilt.pop("meta")
    assert rebuilt == profile_to_fhir(UCR_WEST)


async def test_a_missing_service_is_none(neo4j_driver: AsyncDriver) -> None:
    assert await _get(neo4j_driver, "svc-missing") is None


async def test_list_active_returns_active_services_by_name_and_skips_inactive(
    neo4j_driver: AsyncDriver,
) -> None:
    await _save(neo4j_driver, UCR_WEST, UCR_EAST, REABLEMENT, CLOSED_WARD)

    async def load(tx: AsyncManagedTransaction) -> list[ServiceProfile]:
        return await _repo(tx).list_active()

    active = await read_tx(neo4j_driver, load)

    assert [profile.name for profile in active] == ["Reablement", "UCR East", "UCR West"]
    assert active == [REABLEMENT, UCR_EAST, UCR_WEST]


async def test_saving_again_replaces_the_profile_and_keeps_the_old_version(
    neo4j_driver: AsyncDriver,
) -> None:
    await _save(neo4j_driver, UCR_WEST)
    changed = replace(UCR_WEST, established_capacity=9)

    await _save(neo4j_driver, changed)

    assert await _get(neo4j_driver, "svc-ucr-west") == changed
    assert await count_nodes(neo4j_driver, "HealthcareService") == 1
    assert await count_nodes(neo4j_driver, "ResourceVersion") == 1


async def test_suspended_is_not_stored_so_it_reads_back_false(neo4j_driver: AsyncDriver) -> None:
    await _save(neo4j_driver, replace(UCR_WEST, suspended=True))

    loaded = await _get(neo4j_driver, "svc-ucr-west")

    assert loaded is not None
    assert loaded.suspended is False


async def test_an_overnight_window_is_stored_and_read_back_unchanged(
    neo4j_driver: AsyncDriver,
) -> None:
    overnight = replace(
        UCR_WEST,
        available_times=(AvailableTime.every_day(time(20, 0), time(8, 0)),),
    )
    await _save(neo4j_driver, overnight)

    assert await _get(neo4j_driver, "svc-ucr-west") == overnight
