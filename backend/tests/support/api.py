"""API test support (R01): the test container and the HTTP client every route test uses.

The app runs on the composition root's test profile, on the Docker Neo4j of the F10 harness, with
fakes only for external providers. Route tests add their own test-only routes to api_app.

Stub for the red commit (DEC-010): the fixtures exist, their bodies raise NotImplementedError.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.bootstrap.container import Container
from tests.support.neo4j import ThrowawayNeo4j


@pytest_asyncio.fixture(loop_scope="session")
async def test_container(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Container]:
    raise NotImplementedError("R01: test_container is not built yet")
    yield  # pragma: no cover


@pytest_asyncio.fixture(loop_scope="session")
async def api_app(test_container: Container) -> FastAPI:
    raise NotImplementedError("R01: api_app is not built yet")


@pytest_asyncio.fixture(loop_scope="session")
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    raise NotImplementedError("R01: api_client is not built yet")
    yield  # pragma: no cover
