"""Shared pytest fixtures and hooks.

The Neo4j harness (F10, DEC-008): an integration session starts its own throwaway Neo4j container,
on a free port with a unique name, and removes it when the session ends. The harness never reads
or uses a shared stack, so no test can wipe diucs-local (port 7687).

The tenant per run (TEN-003, DEC-147): each pytest session has one run identity, from which a run
tenant, a second tenant and a run network scope derive. Every integration test runs with the run
tenant bound (a test marked `no_tenant` runs with none), and a guard fails a test that leaves
another tenant bound. The wipe is still the whole database and the container still one per run
(TEN-033 to TEN-035).
"""

import os
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.migrations import apply_migrations
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, bind_tenant
from diucs.bootstrap.container import TEST_NOW
from tests.support.neo4j import (
    ThrowawayNeo4j,
    apply_session_env,
    reap_stale_test_containers,
    throwaway_driver,
    wipe,
)
from tests.support.tenancy import RunIdentity, guard_test, new_run_identity
from tests.support.uow import tenant_uow_factory, uow_factory_on
from tests.support.watchdog import configured_timeout_s, setup_timeout_s, time_limit

_INTEGRATION_ROOT = Path(__file__).resolve().parent / "integration"
# Drivers of the running harness session. Empty until a test needs Neo4j, so a run of tests that
# never touch Neo4j (and a Docker-less run) never starts a container.
_active: list[AsyncDriver] = []
_RUN_IDENTITY: pytest.StashKey[RunIdentity] = pytest.StashKey()


def pytest_configure(config: pytest.Config) -> None:
    """One run identity per pytest session (worker identities under xdist are TEN-035). The three
    ids are exported for child processes: the front end's end-to-end run reads them later."""
    identity = new_run_identity()
    config.stash[_RUN_IDENTITY] = identity
    os.environ["DIUCS_TEST_TENANT"] = identity.tenant_id
    os.environ["DIUCS_TEST_OTHER_TENANT"] = identity.other_tenant_id
    os.environ["DIUCS_TEST_NETWORK"] = identity.network_id


def pytest_sessionstart(session: pytest.Session) -> None:
    """Remove test containers left by killed runs (DEC-108). It never raises."""
    reap_stale_test_containers()


def _capture_release(item: pytest.Item) -> Callable[[], None] | None:
    """What the hard stage calls to give the real terminal back before it reports: pytest's output
    capture holds fd 2, and anything written there would be lost when the process is ended."""
    manager = item.config.pluginmanager.get_plugin("capturemanager")
    if manager is None:
        return None
    return lambda: manager.suspend_global_capture(in_=False)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item: pytest.Item) -> Iterator[None]:
    """Fail a test whose fixture set-up runs past DIUCS_TEST_SETUP_TIMEOUT seconds (default 900,
    0 turns it off). The harness pauses this clock for its lock wait and image pull (F10b)."""
    with time_limit(
        setup_timeout_s(), f"{item.nodeid} (set-up)", release_capture=_capture_release(item)
    ):
        return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    """Fail a test that runs past DIUCS_TEST_TIMEOUT seconds (default 300, 0 turns it off), so a
    hang ends in minutes with a stack, not never (F10b, lesson L67)."""
    with time_limit(configured_timeout_s(), item.nodeid, release_capture=_capture_release(item)):
        return (yield)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark everything under tests/integration/ and give it a wiped graph before each test, and run
    it with the run tenant bound."""
    tenant = config.stash[_RUN_IDENTITY].tenant_id
    for item in items:
        if Path(str(item.path)).resolve().is_relative_to(_INTEGRATION_ROOT):
            item.add_marker(pytest.mark.integration)
            # usefixtures markers are read at collection, before this hook runs, so the fixture
            # name is added to the item's closure directly (as pytest-asyncio does).
            if "clean_graph" not in item.fixturenames:
                item.fixturenames.append("clean_graph")
            _bind_run_tenant(item, tenant)


def _bind_run_tenant(item: pytest.Item, tenant: str) -> None:
    """Bind the run tenant around an integration test, and guard that it is still the one bound
    when the test ends. A test marked `no_tenant` runs with nothing bound, and is guarded to leave
    nothing bound.

    `bound_tenant` goes first in the closure, so that every other fixture, sync or async, is set up
    with the tenant bound. The guard wraps the test function itself, because it must run in the
    test's own task context: a teardown fixture runs outside it and would not see a binding the
    test body left behind (the reset trap, audit E 3.2). If the body raises, its own exception
    propagates and the guard does not run."""
    unbound = item.get_closest_marker("no_tenant") is not None
    if not unbound and "bound_tenant" not in item.fixturenames:
        item.fixturenames.insert(0, "bound_tenant")
    if isinstance(item, pytest.Function):
        item.obj = guard_test(item.obj, None if unbound else tenant)


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


@pytest.fixture(scope="session")
def run_identity(request: pytest.FixtureRequest) -> RunIdentity:
    """The identity of this pytest session: the tenant ids and the network id derive from it."""
    return request.config.stash[_RUN_IDENTITY]


@pytest.fixture(scope="session")
def tenant_id(run_identity: RunIdentity) -> str:
    return run_identity.tenant_id


@pytest.fixture(scope="session")
def other_tenant_id(run_identity: RunIdentity) -> str:
    return run_identity.other_tenant_id


@pytest.fixture(scope="session")
def network_id(run_identity: RunIdentity) -> str:
    return run_identity.network_id


@pytest.fixture
def bound_tenant(tenant_id: str) -> Iterator[ScopeId]:
    """The run tenant, bound for the test and restored after it. Synchronous on purpose: a context
    variable set by a sync yield fixture reaches async tests and the tasks they create, and is
    unset at teardown (lesson L151)."""
    with bind_tenant(tenant_id) as scope:
        yield scope


@pytest.fixture
def uow_clock() -> Clock:
    """The clock the unit of work uses. A test that needs another instant overrides this fixture."""
    return FixedClock(TEST_NOW)


@pytest.fixture
def uow_factory(neo4j_driver: AsyncDriver, uow_clock: Clock) -> UnitOfWorkFactory:
    """The unit of work factory every use-case test takes (P06): real Neo4j, the default
    repositories, and the fixed clock."""
    return uow_factory_on(neo4j_driver, uow_clock)


@pytest.fixture
def uow_factory_a(neo4j_driver: AsyncDriver, uow_clock: Clock, tenant_id: str) -> UnitOfWorkFactory:
    """Units of work bound to the run tenant, whatever is bound in the test."""
    return tenant_uow_factory(neo4j_driver, tenant_id, uow_clock)


@pytest.fixture
def uow_factory_b(
    neo4j_driver: AsyncDriver, uow_clock: Clock, other_tenant_id: str
) -> UnitOfWorkFactory:
    """Units of work bound to the run's second tenant, for the cross-tenant tests."""
    return tenant_uow_factory(neo4j_driver, other_tenant_id, uow_clock)
