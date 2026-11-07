"""The shared postcode points on a real Neo4j (DEC-1329): the platform's download write, and the
read by district.

What is proved:

- a download stores one point per postcode, and a retried download refreshes them, not adds;
- a district's read returns its own postcodes in postcode order, and no other district's;
- a narrowed or unknown district reads nothing.

Synthetic values only (the points are public data, and these are sample postcodes). The fixtures
are the registry test's: a private Neo4j for the run.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio

from overwatch.adapters.outbound.graph_store.connection import Neo4jConnection
from overwatch.adapters.outbound.graph_store.postcode_points import Neo4jPostcodePointStore
from overwatch.adapters.outbound.graph_store.tenant_registry import Neo4jPostcodePoints
from overwatch.application.ports.outbound.postcode_directory import DirectoryPostcode

# The fixtures of the tenant registry's integration test: one private Neo4j for this module's run.
from tests.integration.graph_store.test_tenant_registry import (  # noqa: F401
    connection,
    harness_driver,
)

pytestmark = [pytest.mark.schema]

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
POINTS = [
    DirectoryPostcode("DT4 0AX", 50.609, -2.462),
    DirectoryPostcode("DT4 0AW", 50.611, -2.461),
    DirectoryPostcode("SO16 0AA", 50.906, -1.404),
]


@pytest_asyncio.fixture(loop_scope="session")
async def store(connection: Neo4jConnection) -> Neo4jPostcodePointStore:  # noqa: F811
    return Neo4jPostcodePointStore(connection, Neo4jPostcodePoints(connection))


async def test_a_download_stores_one_point_per_postcode_and_a_retry_adds_none(
    store: Neo4jPostcodePointStore,
) -> None:
    await store.upsert(POINTS)
    await store.upsert(POINTS)
    dt4 = await store.of_district("DT4")
    assert [postcode for postcode, _, _ in dt4] == ["DT4 0AW", "DT4 0AX"]


async def test_a_district_reads_its_own_postcodes_only(store: Neo4jPostcodePointStore) -> None:
    await store.upsert(POINTS)
    so16 = await store.of_district("SO16")
    assert [postcode for postcode, _, _ in so16] == ["SO16 0AA"]
    assert await store.of_district("ZZ99") == []
