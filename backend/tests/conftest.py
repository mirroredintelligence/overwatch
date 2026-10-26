"""Shared pytest fixtures and hooks.

The Neo4j harness (F10, DEC-008): an integration session starts its own throwaway Neo4j container,
on a free port with a unique name, and removes it when the session ends. The harness never reads
or uses a shared stack, so no test can wipe diucs-local (port 7687).
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.migrations import apply_migrations
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.bootstrap.container import TEST_NOW
from tests.support.neo4j import ThrowawayNeo4j, apply_session_env, throwaway_driver, wipe
from tests.support.uow import uow_factory_on

_INTEGRATION_ROOT = Path(__file__).resolve().parent / "integration"
# Drivers of the running harness session. Empty until a test needs Neo4j, so a run of tests that
# never touch Neo4j (and a Docker-less run) never starts a container.
_active: list[AsyncDriver] = []


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark everything under tests/integration/ and give it a wiped graph before each test."""
    for item in items:
        if Path(str(item.path)).resolve().is_relative_to(_INTEGRATION_ROOT):
            item.add_marker(pytest.mark.integration)
            # usefixtures markers are read at collection, before this hook runs, so the fixture
            # name is added to the item's closure directly (as pytest-asyncio does).
            if "clean_graph" not in item.fixturenames:
                item.fixturenames.append("clean_graph")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def harness_neo4j() -> AsyncIterator[tuple[ThrowawayNeo4j, AsyncDriver]]:
    """One throwaway Neo4j container and one driver for the whole pytest session; migrations
    applied once.

    The harness sets NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD for the session, so code that reads
    them (the G01 test module) reaches this container and nothing else. The container is restartable
    (F11): tests may stop and start it, and it is removed when the session ends, even if connecting
    failed.
    """
    async with throwaway_driver() as (container, driver):
        apply_session_env(container)
        await apply_migrations(driver)
        _active.append(driver)
        try:
            yield container, driver
        finally:
            _active.clear()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def harness_driver(harness_neo4j: tuple[ThrowawayNeo4j, AsyncDriver]) -> AsyncDriver:
    """The harness session's driver. Wiped by clean_graph before each integration test."""
    _, driver = harness_neo4j
    return driver


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def harness_container(harness_neo4j: tuple[ThrowawayNeo4j, AsyncDriver]) -> ThrowawayNeo4j:
    """The harness session's container, for tests that stop and start Neo4j (F11, G14)."""
    container, _ = harness_neo4j
    return container


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def neo4j_driver(harness_driver: AsyncDriver) -> AsyncDriver:
    """The session's driver. A test module may override this name (test_infra_up.py does, for the
    shared compose stack); clean_graph does not use the name, so it can never wipe another stack."""
    return harness_driver


@pytest_asyncio.fixture(loop_scope="session")
async def clean_graph() -> None:
    """Delete every node and relationship in the harness container before an integration test.
    Constraints, indexes and :Migration nodes stay. If no test has needed Neo4j yet, the container
    does not exist and there is nothing to clean, so this starts nothing."""
    for driver in _active:
        await wipe(driver)


@pytest.fixture
def uow_clock() -> Clock:
    """The clock the unit of work uses. A test that needs another instant overrides this fixture."""
    return FixedClock(TEST_NOW)


@pytest.fixture
def uow_factory(neo4j_driver: AsyncDriver, uow_clock: Clock) -> UnitOfWorkFactory:
    """The unit of work factory every use-case test takes (P06): real Neo4j, the default
    repositories, and the fixed clock."""
    return uow_factory_on(neo4j_driver, uow_clock)
