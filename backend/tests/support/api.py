"""API test support (R01): the test container and the HTTP client every route test uses.

The app runs on the composition root's test profile, on the Docker Neo4j of the F10 harness, with
fakes only for external providers. Route tests add their own test-only routes to api_app.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.bootstrap.container import Container, build_for_tests
from tests.support.neo4j import ThrowawayNeo4j

# The clock of the R01 route tests (DEC-070 item 4): 14:12 London, passed explicitly. F08's
# TEST_NOW (13:00Z) is left unchanged.
R01_TEST_NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)


@pytest_asyncio.fixture(loop_scope="session")
async def test_container(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Container]:
    """The composition root's test profile on the harness Neo4j. Each test owns one connection,
    which it closes; the graph was wiped by clean_graph."""
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(clock=FixedClock(R01_TEST_NOW), neo4j=connection)
    finally:
        await connection.close()


@pytest_asyncio.fixture(loop_scope="session")
async def api_app(test_container: Container) -> FastAPI:
    return create_app(test_container)


@pytest_asyncio.fixture(loop_scope="session")
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=api_app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client
