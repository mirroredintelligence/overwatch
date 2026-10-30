"""The tenant registry's writes on a real Neo4j (TEN-028, DEC-503): the platform statements, and
what the directory then reads.

What is proved, on a graph that holds two tenants (and, in one test, a tenant's data):

- a tenant created through the registry is read back equal by the directory, a second creation of
  the id is a `Conflict`, and nothing in the node is a secret;
- a save is a compare and set: a stale epoch or status writes nothing and answers False, a fresh
  one changes the record, and a resumed tenant keeps none of its suspend properties (a record that
  kept them would not read back at all);
- a host, a directory and a number belong to one tenant: a second claim is a `Conflict`, and the
  first tenant's value is unchanged;
- a write to one tenant never touches the other's node (its properties are compared before and
  after), and none of the statements reads or writes a node that is not a registry node;
- a number put through the registry resolves through the directory's own lookups, and a test text
  marked on it is read back.

Written in build wave 5 and not run there: the full integration run follows on the merged tip.
Synthetic values only.
"""

import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_directory import Neo4jTenantDirectory
from diucs.adapters.outbound.graph_store.tenant_registry import Neo4jTenantRegistry
from diucs.application.ports.outbound.tenant_registry import TenantNumberRecord
from diucs.application.ports.outbound.tenants import twilio_token_ref
from diucs.domain.errors import Conflict, NotFound
from diucs.domain.model.tenant import (
    NumberStatus,
    OrganisationType,
    SuspendMode,
    SuspendReason,
    Tenant,
    TenantStatus,
)
from diucs.domain.rules.tenant_lifecycle import resume_tenant, suspend_tenant
from tests.support.neo4j import read_tx, write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

A, B = "reg-alpha", "reg-bravo"
SID = "AC" + "a" * 32
NUMBER_A, NUMBER_B = "+447700900301", "+447700900302"
GUID = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)


def _tenant(tenant_id: str, **fields: Any) -> Tenant:
    base: dict[str, Any] = {
        "id": tenant_id,
        "display_name": f"Org {tenant_id}",
        "legal_name": f"Org {tenant_id} Ltd",
        "organisation_type": OrganisationType.OTHER,
        "status": TenantStatus.PROVISIONING,
        "created_at": NOW,
    }
    return Tenant(**{**base, **fields})


def _number(tenant_id: str, e164: str, **fields: Any) -> TenantNumberRecord:
    base: dict[str, Any] = {
        "e164": e164,
        "account_sid": SID,
        "secret_ref": twilio_token_ref(tenant_id),
    }
    return TenantNumberRecord(**{**base, **fields})


@pytest_asyncio.fixture(loop_scope="session")
async def connection(harness_driver: AsyncDriver) -> AsyncIterator[Neo4jConnection]:
    conn = Neo4jConnection(
        os.environ["NEO4J_URI"], os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
    )
    await conn.open()
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture(loop_scope="session")
async def registry(
    neo4j_driver: AsyncDriver, connection: Neo4jConnection
) -> AsyncIterator[Neo4jTenantRegistry]:
    """The registry on a graph whose test registry nodes (the two ids here) are removed before and
    after: registry nodes carry no tenant, so the tenant-scoped wipe does not remove them."""
    await _forget(neo4j_driver)
    yield Neo4jTenantRegistry(connection)
    await _forget(neo4j_driver)


@pytest.fixture
def directory(connection: Neo4jConnection) -> Neo4jTenantDirectory:
    return Neo4jTenantDirectory(connection)


async def _forget(driver: AsyncDriver) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "MATCH (t:Tenant) WHERE t.id IN $ids "
            "OPTIONAL MATCH (t)-[:HAS_NUMBER]->(n:TenantNumber) DETACH DELETE n, t",
            ids=[A, B],
        )
        await tx.run(
            "MATCH (r:Resource) WHERE r.id IN $ids AND r.tenantId = r.id DETACH DELETE r",
            ids=[A, B],
        )

    await write_tx(driver, work)


async def _node(driver: AsyncDriver, tenant_id: str) -> dict[str, Any]:
    async def work(tx: AsyncManagedTransaction) -> dict[str, Any]:
        rows = await (
            await tx.run("MATCH (t:Tenant {id: $id}) RETURN properties(t) AS p", id=tenant_id)
        ).data()
        return dict(rows[0]["p"]) if rows else {}

    return await read_tx(driver, work)


# -- create and read back ------------------------------------------------------------------------


async def test_a_created_tenant_reads_back_equal_and_a_second_creation_is_a_conflict(
    registry: Neo4jTenantRegistry, directory: Neo4jTenantDirectory
) -> None:
    tenant = _tenant(A, ods_code="R1A")

    await registry.create(tenant)

    assert await directory.get(A) == tenant
    with pytest.raises(Conflict):
        await registry.create(tenant)
    with pytest.raises(Conflict):
        await registry.create(replace(tenant, display_name="Another name"))
    assert await directory.get(A) == tenant


async def test_the_node_holds_no_secret_no_tenant_id_and_no_host_until_one_is_set(
    registry: Neo4jTenantRegistry, neo4j_driver: AsyncDriver
) -> None:
    await registry.create(_tenant(A))

    node = await _node(neo4j_driver, A)

    assert "tenantId" not in node and "host" not in node and "entraDirectoryId" not in node
    assert node["status"] == "provisioning" and node["epoch"] == 1
    assert not any("secret" in key.lower() or "token" in key.lower() for key in node)


# -- save: compare and set -----------------------------------------------------------------------


async def test_a_save_with_a_stale_epoch_or_status_writes_nothing(
    registry: Neo4jTenantRegistry, directory: Neo4jTenantDirectory
) -> None:
    created = _tenant(A)
    await registry.create(created)
    activated = replace(created, status=TenantStatus.ACTIVE, activated_at=NOW)

    stale_epoch = await registry.save(
        activated, expected_epoch=7, expected_status=TenantStatus.PROVISIONING
    )
    stale_status = await registry.save(
        activated, expected_epoch=1, expected_status=TenantStatus.SUSPENDED
    )

    assert (stale_epoch, stale_status) == (False, False)
    assert await directory.get(A) == created


async def test_a_save_with_the_record_as_read_changes_it_and_a_second_one_does_not(
    registry: Neo4jTenantRegistry, directory: Neo4jTenantDirectory
) -> None:
    created = _tenant(A)
    await registry.create(created)
    activated = replace(created, status=TenantStatus.ACTIVE, activated_at=NOW)

    first = await registry.save(
        activated, expected_epoch=1, expected_status=TenantStatus.PROVISIONING
    )
    again = await registry.save(
        activated, expected_epoch=1, expected_status=TenantStatus.PROVISIONING
    )

    assert (first, again) == (True, False)  # two operators that read the same record: one wins
    assert await directory.get(A) == activated


async def test_a_resumed_tenant_keeps_none_of_its_suspend_properties(
    registry: Neo4jTenantRegistry, directory: Neo4jTenantDirectory, neo4j_driver: AsyncDriver
) -> None:
    active = _tenant(A, status=TenantStatus.ACTIVE, activated_at=NOW)
    await registry.create(replace(active, status=TenantStatus.PROVISIONING, activated_at=None))
    assert await registry.save(active, expected_epoch=1, expected_status=TenantStatus.PROVISIONING)
    suspended = suspend_tenant(active, SuspendMode.BLOCKED, SuspendReason.SECURITY_INCIDENT, LATER)
    assert await registry.save(
        suspended, expected_epoch=active.epoch, expected_status=TenantStatus.ACTIVE
    )
    assert (await directory.get(A)) == suspended
    assert (await _node(neo4j_driver, A))["suspendMode"] == "blocked"

    resumed = resume_tenant(suspended, LATER.replace(day=1, month=11))
    assert await registry.save(
        resumed, expected_epoch=suspended.epoch, expected_status=TenantStatus.SUSPENDED
    )

    node = await _node(neo4j_driver, A)
    assert not {"suspendMode", "suspendReason", "suspendedAt"} & set(node)
    assert await directory.get(A) == resumed
    assert resumed.epoch == active.epoch + 2


async def test_a_save_for_a_tenant_that_does_not_exist_answers_false(
    registry: Neo4jTenantRegistry,
) -> None:
    assert (
        await registry.save(
            _tenant(A, status=TenantStatus.ACTIVE, activated_at=NOW),
            expected_epoch=1,
            expected_status=TenantStatus.PROVISIONING,
        )
        is False
    )


# -- host, directory, number: one tenant each ----------------------------------------------------


async def test_a_host_and_a_directory_belong_to_one_tenant(
    registry: Neo4jTenantRegistry, directory: Neo4jTenantDirectory
) -> None:
    await registry.create(_tenant(A))
    await registry.create(_tenant(B))
    await registry.set_host(A, "Alpha.Example.org")
    await registry.set_entra_directory(A, GUID)

    with pytest.raises(Conflict):
        await registry.set_host(B, "alpha.example.org")
    with pytest.raises(Conflict):
        await registry.set_entra_directory(B, GUID)

    found_by_host = await directory.by_host("alpha.example.org")
    found_by_directory = await directory.by_entra_directory(GUID)
    assert found_by_host is not None and found_by_host.id == A
    assert found_by_directory is not None and found_by_directory.id == A
    assert await directory.host_of(A) == "alpha.example.org"
    assert await directory.host_of(B) is None


async def test_a_host_for_a_tenant_nobody_created_is_not_found(
    registry: Neo4jTenantRegistry,
) -> None:
    with pytest.raises(NotFound):
        await registry.set_host(A, "alpha.example.org")
    with pytest.raises(NotFound):
        await registry.put_number(A, _number(A, NUMBER_A))


async def test_a_number_belongs_to_one_tenant_in_any_status(
    registry: Neo4jTenantRegistry,
) -> None:
    await registry.create(_tenant(A))
    await registry.create(_tenant(B))
    await registry.put_number(A, _number(A, NUMBER_A))

    with pytest.raises(Conflict):
        await registry.put_number(B, _number(B, NUMBER_A))

    # A retired number stays A's: it is not moved to B (it is quarantined, DEC-136 item 10).
    await registry.put_number(A, _number(A, NUMBER_A, status=NumberStatus.RETIRED))
    with pytest.raises(Conflict):
        await registry.put_number(B, _number(B, NUMBER_A))
    assert [n.e164 for n in await registry.numbers(A)] == [NUMBER_A]
    assert await registry.numbers(B) == ()


async def test_a_number_resolves_through_the_directory_and_its_test_text_is_read_back(
    registry: Neo4jTenantRegistry, directory: Neo4jTenantDirectory
) -> None:
    await registry.create(_tenant(A))
    await registry.put_number(A, _number(A, NUMBER_A))

    # The directory answers whatever the tenant's status is (the caller decides what a tenant in
    # provisioning may do): the number resolves to the tenant that holds it, with its own reference.
    line = await directory.by_inbound_number(NUMBER_A, SID)
    assert line is not None and line.tenant.id == A
    assert line.secret_ref == twilio_token_ref(A)
    [before] = await registry.numbers(A)
    assert before.tested_at is None

    await registry.mark_number_tested(A, NUMBER_A, NOW)

    [after] = await registry.numbers(A)
    assert after.tested_at == NOW
    assert after.secret_ref == twilio_token_ref(A)


async def test_a_test_text_is_marked_only_on_the_tenants_own_number(
    registry: Neo4jTenantRegistry,
) -> None:
    await registry.create(_tenant(A))
    await registry.create(_tenant(B))
    await registry.put_number(B, _number(B, NUMBER_B))

    with pytest.raises(NotFound):
        await registry.mark_number_tested(A, NUMBER_B, NOW)  # B's number, A's id

    assert (await registry.numbers(B))[0].tested_at is None


# -- nothing leaks between tenants ---------------------------------------------------------------


async def test_a_write_to_one_tenant_never_changes_the_others_node(
    registry: Neo4jTenantRegistry, neo4j_driver: AsyncDriver
) -> None:
    created_a = _tenant(A)
    await registry.create(created_a)
    await registry.create(_tenant(B))
    await registry.set_host(B, "bravo.example.org")
    await registry.put_number(B, _number(B, NUMBER_B))
    before = await _node(neo4j_driver, B)

    await registry.set_host(A, "alpha.example.org")
    await registry.put_number(A, _number(A, NUMBER_A))
    await registry.mark_number_tested(A, NUMBER_A, NOW)
    await registry.save(
        replace(created_a, status=TenantStatus.ACTIVE, activated_at=NOW),
        expected_epoch=1,
        expected_status=TenantStatus.PROVISIONING,
    )

    assert await _node(neo4j_driver, B) == before
    assert [n.e164 for n in await registry.numbers(B)] == [NUMBER_B]
    assert (await registry.numbers(B))[0].tested_at is None


async def test_the_registry_statements_touch_no_node_that_is_not_a_registry_node(
    registry: Neo4jTenantRegistry, neo4j_driver: AsyncDriver
) -> None:
    """A tenant's data node with the same words as the registry keys is never read or changed."""

    async def seed(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "CREATE (:Resource {id: $id, tenantId: $id, host: 'alpha.example.org', e164: $number})",
            id=A,
            number=NUMBER_A,
        )

    await write_tx(neo4j_driver, seed)
    await registry.create(_tenant(A))
    await registry.set_host(A, "alpha.example.org")
    await registry.put_number(A, _number(A, NUMBER_A))

    async def read(tx: AsyncManagedTransaction) -> dict[str, Any]:
        rows = await (
            await tx.run("MATCH (r:Resource {id: $id}) RETURN properties(r) AS p", id=A)
        ).data()
        return dict(rows[0]["p"])

    assert await read_tx(neo4j_driver, read) == {
        "id": A,
        "tenantId": A,
        "host": "alpha.example.org",
        "e164": NUMBER_A,
    }
