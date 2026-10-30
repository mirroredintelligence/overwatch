"""The harness on a Neo4j that other runs share (TEN-034), against a real Neo4j.

Whatever mode the session runs in (a private container, the machine's shared container, or an
instance named by `DIUCS_TEST_NEO4J_URI`), the tests see the same thing: a migrated database, a run
tenant that is theirs alone, and a refusal to empty a database they do not own. The tests here
attach explicitly to the session's own database, to prove the attached path, and look the shared
container up for real.
"""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS, apply_migrations
from tests.support.harness_mode import (
    Mode,
    Selection,
    ensure_shared_neo4j,
    open_harness_database,
    select_mode,
)
from tests.support.neo4j import (
    ThrowawayNeo4j,
    WipeRefused,
    count_nodes,
    count_nodes_all,
    is_owned,
    throwaway_driver,
    tx_run,
    wipe_all,
    write_tx,
)
from tests.support.neo4j_locks import apply_migrations_once
from tests.support.sweeper import sweep_orphan_tenants
from tests.support.tenancy import RunIdentity, as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

DEAD_OWNER = RunIdentity(pid=4_194_302, started=1_800_000_000, nonce="5eed")


def _attach_selection(container: ThrowawayNeo4j) -> Selection:
    return select_mode(
        {
            "DIUCS_TEST_NEO4J_URI": container.uri,
            "DIUCS_TEST_NEO4J_USER": container.user,
            "DIUCS_TEST_NEO4J_PASSWORD": container.password,
        }
    )


async def _probe(driver: AsyncDriver, tenant: str) -> None:
    async def work(tx: object) -> None:
        await tx_run(tx, "CREATE (:SharedProbe {id: 'p', tenantId: $tenant})")

    with as_tenant(tenant):
        await write_tx(driver, work)


@pytest_asyncio.fixture(loop_scope="session")
async def attached(harness_container: ThrowawayNeo4j, tenant_id: str) -> AsyncIterator[AsyncDriver]:
    """The session's own database, opened the way an attached run opens one."""
    async with open_harness_database(_attach_selection(harness_container), exclusive=False) as db:
        yield db.driver


async def test_the_session_database_is_owned_only_when_the_session_started_it(
    neo4j_driver: AsyncDriver, harness_mode: Mode
) -> None:
    assert is_owned(neo4j_driver) is (harness_mode is Mode.OWNED)


async def test_a_database_the_session_did_not_start_cannot_be_emptied(
    neo4j_driver: AsyncDriver, harness_mode: Mode, tenant_id: str
) -> None:
    await _probe(neo4j_driver, tenant_id)
    if harness_mode is Mode.OWNED:
        assert is_owned(neo4j_driver)
        return
    with pytest.raises(WipeRefused):
        await wipe_all(neo4j_driver)
    assert await count_nodes(neo4j_driver, "SharedProbe") == 1


async def test_the_harness_environment_names_the_database_the_tests_use(
    harness_container: ThrowawayNeo4j,
) -> None:
    assert os.environ["NEO4J_URI"] == harness_container.uri
    assert os.environ["NEO4J_USER"] == harness_container.user


# attached


async def test_an_attached_run_reaches_the_same_database_as_a_direct_one(
    attached: AsyncDriver, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _probe(attached, tenant_id)

    assert await count_nodes(neo4j_driver, "SharedProbe") == 1
    assert not is_owned(attached)


async def test_an_attached_run_cannot_empty_the_database(
    attached: AsyncDriver, tenant_id: str
) -> None:
    await _probe(attached, tenant_id)

    with pytest.raises(WipeRefused):
        await wipe_all(attached)
    assert await count_nodes(attached, "SharedProbe") == 1


async def test_opening_an_attached_database_that_is_already_migrated_applies_nothing(
    attached: AsyncDriver,
) -> None:
    assert await count_nodes_all(attached, "Migration") == len(MIGRATIONS)


async def test_opening_the_database_sweeps_the_leftovers_of_a_dead_run(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _probe(neo4j_driver, DEAD_OWNER.tenant_id)
    await _probe(neo4j_driver, tenant_id)

    async with open_harness_database(
        _attach_selection(harness_container), exclusive=False, own=RunIdentity(1, 1, "0000")
    ) as db:
        assert DEAD_OWNER in db.swept

    assert await count_nodes(neo4j_driver, "SharedProbe", tenant=DEAD_OWNER.tenant_id) == 0
    assert await count_nodes(neo4j_driver, "SharedProbe") == 1


async def test_the_sweeper_run_by_hand_finds_nothing_after_that(neo4j_driver: AsyncDriver) -> None:
    assert await sweep_orphan_tenants(neo4j_driver) == []


# the shared container


async def test_the_shared_container_is_found_again_by_a_second_call() -> None:
    first = await asyncio.to_thread(ensure_shared_neo4j)
    second = await asyncio.to_thread(ensure_shared_neo4j)

    assert first == second
    assert first.name == "diucs-test-shared-neo4j"


# the migration lock, against a real schema


@pytest.mark.schema
async def test_two_sessions_migrating_one_new_database_leave_one_record_per_migration() -> None:
    async with throwaway_driver() as (container, driver):
        results = await asyncio.gather(
            apply_migrations_once(driver, container.uri),
            apply_migrations_once(driver, container.uri),
        )

        assert sorted(results) == [False, True]
        assert await count_nodes_all(driver, "Migration") == len(MIGRATIONS)
        await apply_migrations(driver)  # and the plain runner agrees there is nothing left to do
        assert await count_nodes_all(driver, "Migration") == len(MIGRATIONS)
