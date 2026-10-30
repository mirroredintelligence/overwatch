"""The contract step of the tenant schema on a real Neo4j (TEN-032, DEC-134 items 10 and 13).

Two halves. The first runs on private containers: an expanded database (every migration but the
contract one, as production is today) is contracted and must end identical to a fresh one; the
contract migration is idempotent, safe to run again, and refuses to drop a key whose composite
replacement is missing. The second runs on the SHARED harness schema, which after the contract is
the contracted schema: a second tenant holds the same Concept, Communication and AuditHead ids as
the first, and every composite key lets two tenants share and refuses a repeat in one. Every value
is synthetic.
"""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.communication_repository import (
    Neo4jCommunicationRepository,
)
from diucs.adapters.outbound.graph_store.migration_types import Migration, MigrationFailed
from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS, apply_migrations
from diucs.adapters.outbound.graph_store.migrations_contract import CONTRACT_MIGRATION_ID
from diucs.adapters.outbound.graph_store.migrations_tenant import (
    COMPOSITE_CONSTRAINTS,
    COMPOSITE_INDEXES,
    SUPERSEDED_CONSTRAINTS,
    SUPERSEDED_INDEXES,
)
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.tenancy import bind_tenant
from diucs.domain.codes import Channel
from tests.support.neo4j import read_tx, throwaway_driver, write_tx
from tests.support.tenant_seed import schema_names
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

EXPANDED = [m for m in MIGRATIONS if m.id != CONTRACT_MIGRATION_ID]
CONTRACT = next(m for m in MIGRATIONS if m.id == CONTRACT_MIGRATION_ID)
SENT = datetime(2026, 10, 25, 9, 0, 0, tzinfo=UTC)
REPLACED = [c for c in COMPOSITE_CONSTRAINTS if c.replaces is not None]


async def _rows(driver: AsyncDriver, cypher: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(cypher, **params)).data()

    return await read_tx(driver, work)


async def _run(driver: AsyncDriver, cypher: str, **params: Any) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await (await tx.run(cypher, **params)).consume()

    await write_tx(driver, work)


async def _schema(driver: AsyncDriver) -> list[dict[str, Any]]:
    """Every constraint and index of the database, by name, with what it is made of."""
    constraints = await _rows(
        driver,
        "SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties "
        "RETURN 'constraint' AS kind, name, type, entityType, labelsOrTypes, properties",
    )
    indexes = await _rows(
        driver,
        "SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties, owningConstraint "
        "RETURN 'index' AS kind, name, type, entityType, labelsOrTypes, properties, "
        "owningConstraint",
    )
    return sorted([*constraints, *indexes], key=lambda row: (row["kind"], row["name"]))


# The private half


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def expanded() -> AsyncIterator[AsyncDriver]:
    """A private container with every migration but the contract one: the production schema as it
    is before TEN-032 (the old single-property keys and the composite keys side by side)."""
    async with throwaway_driver() as (_container, driver):
        await apply_migrations(driver, EXPANDED)
        yield driver


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def fresh() -> AsyncIterator[AsyncDriver]:
    """A private container with every migration applied at once, as a new installation."""
    async with throwaway_driver() as (_container, driver):
        await apply_migrations(driver)
        yield driver


async def test_the_expanded_database_holds_the_old_keys_and_the_composite_ones(
    expanded: AsyncDriver,
) -> None:
    constraints, _ = await schema_names(expanded)
    assert constraints >= SUPERSEDED_CONSTRAINTS
    assert constraints >= {c.name for c in COMPOSITE_CONSTRAINTS}


async def test_a_refused_contract_drops_nothing_when_a_replacement_is_missing(
    expanded: AsyncDriver,
) -> None:
    before = await schema_names(expanded)
    await _run(expanded, "DROP CONSTRAINT tenant_device_id")
    try:
        with pytest.raises(MigrationFailed) as caught:
            await apply_migrations(expanded)
        assert str(caught.value) == (
            f"migration {CONTRACT_MIGRATION_ID} failed at precondition: "
            "constraint tenant_device_id is missing"
        )
        constraints, _ = await schema_names(expanded)
        assert constraints >= SUPERSEDED_CONSTRAINTS
        records = await _rows(expanded, "MATCH (m:Migration) RETURN m.id AS id")
        assert CONTRACT_MIGRATION_ID not in {r["id"] for r in records}
    finally:
        await _run(
            expanded,
            "CREATE CONSTRAINT tenant_device_id IF NOT EXISTS FOR (n:Device) "
            "REQUIRE (n.tenantId, n.id) IS UNIQUE",
        )
    assert await schema_names(expanded) == before


async def test_contracting_an_expanded_database_applies_only_the_contract_migration(
    expanded: AsyncDriver,
) -> None:
    assert await apply_migrations(expanded) == [CONTRACT_MIGRATION_ID]

    constraints, indexes = await schema_names(expanded)
    assert constraints.isdisjoint(SUPERSEDED_CONSTRAINTS)
    assert "link_token_hash" in constraints
    assert {c.name for c in COMPOSITE_CONSTRAINTS} <= constraints
    assert {i.name for i in COMPOSITE_INDEXES} <= indexes


async def test_a_fresh_database_and_an_expanded_then_contracted_one_end_identical(
    expanded: AsyncDriver, fresh: AsyncDriver
) -> None:
    await apply_migrations(expanded)  # already contracted by the previous test or now

    assert await _schema(expanded) == await _schema(fresh)
    migrations_a = await _rows(expanded, "MATCH (m:Migration) RETURN m.id AS id ORDER BY id")
    migrations_b = await _rows(fresh, "MATCH (m:Migration) RETURN m.id AS id ORDER BY id")
    assert migrations_a == migrations_b
    assert [r["id"] for r in migrations_a] == [m.id for m in MIGRATIONS]


async def test_the_single_property_indexes_are_left_alone_and_no_old_key_remains(
    fresh: AsyncDriver,
) -> None:
    constraints, indexes = await schema_names(fresh)
    assert constraints.isdisjoint(SUPERSEDED_CONSTRAINTS)
    # The six superseded single-property range indexes are not constraints and are not dropped here
    # (the contract is DROP CONSTRAINT only); the point index stays too.
    assert indexes >= SUPERSEDED_INDEXES | {"location_position"}
    # No unique key of a tenant label is single-property but the link token hash.
    rows = await _rows(
        fresh,
        "SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties "
        "WHERE type = 'UNIQUENESS' RETURN name, labelsOrTypes[0] AS label, properties",
    )
    registry = {"Migration", "Tenant", "TenantNumber", "Network", "NetworkMembership", "Grant"}
    single = {
        r["name"] for r in rows if r["label"] not in registry and r["properties"][0] != "tenantId"
    }
    assert single == {"link_token_hash"}


async def test_the_contract_is_safe_to_run_again(fresh: AsyncDriver) -> None:
    before = await _schema(fresh)
    for _ in range(2):
        await _run(fresh, "MATCH (m:Migration {id: $id}) DETACH DELETE m", id=CONTRACT_MIGRATION_ID)
        assert await apply_migrations(fresh) == [CONTRACT_MIGRATION_ID]
        assert await _schema(fresh) == before
    assert await apply_migrations(fresh) == []


async def test_the_contract_migration_is_the_only_thing_the_second_run_does(
    fresh: AsyncDriver,
) -> None:
    await _run(fresh, "MATCH (m:Migration) DETACH DELETE m")
    again = await apply_migrations(fresh)
    assert again == [m.id for m in MIGRATIONS]
    assert again[-1] == CONTRACT_MIGRATION_ID


async def test_a_bare_migration_that_requires_a_present_constraint_runs(
    fresh: AsyncDriver,
) -> None:
    probe = Migration(
        "0999_probe", ("RETURN 1",), requires=("tenant_resource_id", "link_token_hash")
    )
    assert await apply_migrations(fresh, [probe]) == ["0999_probe"]
    await _run(fresh, "MATCH (m:Migration {id: '0999_probe'}) DETACH DELETE m")


# The shared half: the harness container, with every migration applied, is the contracted schema


async def test_the_shared_schema_is_the_contracted_schema(neo4j_driver: AsyncDriver) -> None:
    constraints, indexes = await schema_names(neo4j_driver)
    assert constraints.isdisjoint(SUPERSEDED_CONSTRAINTS)
    assert {c.name for c in COMPOSITE_CONSTRAINTS} <= constraints
    assert "link_token_hash" in constraints
    assert "location_position" in indexes


def _props(label: str, properties: tuple[str, ...]) -> dict[str, Any]:
    return {p: 1 if p == "seq" else f"{label}-{p}-value" for p in properties if p != "tenantId"}


async def _create(
    driver: AsyncDriver, label: str, tenant: str | None, props: dict[str, Any]
) -> None:
    values = dict(props) if tenant is None else {**props, "tenantId": tenant}
    await _run(driver, f"CREATE (n:{label}) SET n = $props", props=values)


@pytest.mark.parametrize("row", REPLACED, ids=lambda row: row.name)
async def test_two_tenants_share_a_key_on_the_shared_schema_and_one_tenant_cannot_repeat_it(
    neo4j_driver: AsyncDriver, clean_graph: None, row: Any
) -> None:
    props = _props(row.label, row.properties)
    await _create(neo4j_driver, row.label, "a", props)
    await _create(neo4j_driver, row.label, "b", props)
    with pytest.raises(ConstraintError):
        await _create(neo4j_driver, row.label, "a", props)
    count = await _rows(neo4j_driver, f"MATCH (n:{row.label}) RETURN count(n) AS n")
    assert count == [{"n": 2}]


async def test_a_second_tenant_gets_its_own_audit_head_on_the_shared_schema(
    neo4j_driver: AsyncDriver, clean_graph: None, tenant_id: str, other_tenant_id: str
) -> None:
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)  # idempotent for both

    heads = await _rows(
        neo4j_driver, "MATCH (h:AuditHead) RETURN h.id AS id, h.tenantId AS tenant ORDER BY tenant"
    )
    assert heads == sorted(
        [{"id": "audit", "tenant": tenant_id}, {"id": "audit", "tenant": other_tenant_id}],
        key=lambda r: r["tenant"],
    )


def _comm() -> Communication:
    return Communication(
        id="comm-1",
        message_id="C1",
        channel=Channel.TEXT,
        recipient_role_id="role-1",
        about_id="svc-1",
        payload_text="UCR West: how many referrals can you take? Reply by 12:30.",
        sent_at=SENT,
        delivery_status="sent",
        provider_message_id="sms-1",
        in_response_to=None,
    )


async def test_a_second_tenant_holds_the_same_communication_and_concept_ids_on_the_shared_schema(
    neo4j_driver: AsyncDriver, clean_graph: None, tenant_id: str, other_tenant_id: str
) -> None:
    async def add(tx: AsyncManagedTransaction) -> None:
        await Neo4jCommunicationRepository(tx).add(_comm())

    for tenant in (tenant_id, other_tenant_id):
        with bind_tenant(tenant):
            await write_tx(neo4j_driver, add)

    comms = await _rows(
        neo4j_driver,
        "MATCH (c:Communication {id: 'comm-1'}) RETURN c.tenantId AS tenant ORDER BY tenant",
    )
    assert [r["tenant"] for r in comms] == sorted([tenant_id, other_tenant_id])
    concepts = await _rows(
        neo4j_driver,
        "MATCH (c:Concept) RETURN c.tenantId AS tenant, c.system AS system, c.code AS code, "
        "count(*) AS n ORDER BY tenant, system, code",
    )
    assert concepts
    assert all(r["n"] == 1 for r in concepts)
    assert {r["tenant"] for r in concepts} == {tenant_id, other_tenant_id}
    by_tenant = {
        t: {(r["system"], r["code"]) for r in concepts if r["tenant"] == t}
        for t in (tenant_id, other_tenant_id)
    }
    assert by_tenant[tenant_id] == by_tenant[other_tenant_id]


@pytest.mark.parametrize("row", REPLACED, ids=lambda row: row.name)
async def test_the_planner_seeks_each_composite_key_by_its_unique_index(
    neo4j_driver: AsyncDriver, row: Any
) -> None:
    """The old key's index went with it; a lookup by the tenant and the key still seeks."""
    conditions = ", ".join(f"{p}: $p{i}" for i, p in enumerate(row.properties))
    params = {f"p{i}": "x" for i in range(len(row.properties))}

    async def explain(tx: AsyncManagedTransaction) -> str:
        result = await tx.run(f"EXPLAIN MATCH (n:{row.label} {{{conditions}}}) RETURN n", **params)
        return repr((await result.consume()).plan)

    plan = await read_tx(neo4j_driver, explain)
    assert "NodeUniqueIndexSeek" in plan
    assert re.search(rf"n:{row.label}\({', '.join(row.properties)}\)", plan), plan
