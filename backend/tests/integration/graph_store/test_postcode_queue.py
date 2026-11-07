"""The postcode download queue on a real Neo4j (DEC-1329): a request is keyed by its prefix, a
worker claims the oldest queued request once, and a finished or failed request is recorded.

Synthetic prefixes only. The fixtures are the registry test's: a private Neo4j for the run.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from overwatch.adapters.outbound.graph_store.connection import Neo4jConnection
from overwatch.adapters.outbound.graph_store.tenant_registry import Neo4jPostcodeQueue

# The fixtures of the tenant registry's integration test: one private Neo4j for this module's run.
from tests.integration.graph_store.test_tenant_registry import (  # noqa: F401, F811
    connection,
    harness_driver,
)

pytestmark = [pytest.mark.schema]

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)


@pytest_asyncio.fixture(loop_scope="session")
async def queue(connection: Neo4jConnection) -> Neo4jPostcodeQueue:  # noqa: F811
    return Neo4jPostcodeQueue(connection)


@pytest.mark.asyncio(loop_scope="session")
async def test_a_prefix_asked_twice_is_one_request_and_the_oldest_is_claimed_first(
    queue: Neo4jPostcodeQueue,
) -> None:
    await queue.request("QA1", NOW)
    await queue.request("QA1", NOW)
    await queue.request("QA2", NOW + timedelta(minutes=1))
    assert await queue.claim_next(NOW + timedelta(minutes=2)) == "QA1"
    assert await queue.claim_next(NOW + timedelta(minutes=2)) == "QA2"
    assert await queue.claim_next(NOW + timedelta(minutes=2)) is None


@pytest.mark.asyncio(loop_scope="session")
async def test_a_finished_request_is_done_and_a_failed_one_is_failed(
    queue: Neo4jPostcodeQueue,
) -> None:
    await queue.request("QB1", NOW)
    assert await queue.claim_next(NOW) == "QB1"
    await queue.finish("QB1", 12, NOW)
    await queue.request("QB2", NOW)
    assert await queue.claim_next(NOW) == "QB2"
    await queue.fail("QB2", NOW)
