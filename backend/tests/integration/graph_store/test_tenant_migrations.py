"""The tenant schema on a real Neo4j: the expand step (TEN-005, tests 12 to 19) and its contract
(TEN-032, which has its own file, `test_tenant_contract.py`).

The tests run on a private container with every migration applied (`throwaway_driver`), not on the
harness container: the first tests look at the schema as it is, and the schema belongs to this
module while it runs. After TEN-032 that schema has none of the superseded single-property keys.
The harness container is not started by this module. Every value is synthetic.
"""

import dataclasses
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.migration_types import MigrationFailed
from diucs.adapters.outbound.graph_store.migrations import (
    CORE_MIGRATIONS,
    MIGRATIONS,
    apply_migrations,
)
from diucs.adapters.outbound.graph_store.migrations_contract import CONTRACT_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_network import NETWORK_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_protected import PROTECTED_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_safety import SAFETY_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_support import SUPPORT_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_tenant import (
    COMPOSITE_CONSTRAINTS,
    COMPOSITE_INDEXES,
    OPEN_REFERENCE_BACKFILL,
    REGISTRY_LABELS,
    ROLLBACK_0031,
    SUPERSEDED_CONSTRAINTS,
    SUPERSEDED_INDEXES,
    TENANT_MIGRATIONS,
    backfill_default_tenant,
    invariant_violations,
)
from diucs.adapters.outbound.graph_store.migrations_tenant_config import TENANT_CONFIG_MIGRATIONS
from diucs.application.tenancy import DEFAULT_TENANT_ID
from tests.support.neo4j import read_tx, throwaway_driver, wipe_all, write_tx
from tests.support.tenant_seed import (
    SUPERSEDED_CONSTRAINT_NAMES,
    SUPERSEDED_INDEX_NAMES,
    schema_names,
)

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.schema]

_OLD_INDEXES = SUPERSEDED_INDEX_NAMES | {"location_position"}


class _Built:
    def __init__(self, driver: AsyncDriver, applied: list[str]) -> None:
        self.driver = driver
        self.applied = applied


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def built() -> AsyncIterator[_Built]:
    """A fresh container, every migration applied once, as a new installation would."""
    async with throwaway_driver() as (_container, driver):
        applied = await apply_migrations(driver)
        yield _Built(driver, applied)


@pytest_asyncio.fixture(loop_scope="session")
async def private(built: _Built) -> AsyncIterator[AsyncDriver]:
    """The private driver with no data in it (the migration records stay)."""
    await wipe_all(built.driver)
    yield built.driver
    await wipe_all(built.driver)


@pytest_asyncio.fixture(loop_scope="session")
async def contracted(built: _Built) -> AsyncIterator[AsyncDriver]:
    """The private driver with no data in it. Since TEN-032 the migrated schema is the contracted
    one, so nothing is dropped here and nothing is put back."""
    await wipe_all(built.driver)
    yield built.driver
    await wipe_all(built.driver)


async def _schema(driver: AsyncDriver, statement: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await (await tx.run(statement)).consume()

    await write_tx(driver, work)


async def _rows(driver: AsyncDriver, cypher: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(cypher, **params)).data()

    return await read_tx(driver, work)


async def _run(driver: AsyncDriver, cypher: str, **params: Any) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await (await tx.run(cypher, **params)).consume()

    await write_tx(driver, work)


# A driver that counts and breaks write transactions


class _CountingSession:
    def __init__(self, inner: Any, owner: _CountingDriver) -> None:
        self._inner = inner
        self._owner = owner

    async def __aenter__(self) -> _CountingSession:
        await self._inner.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._inner.__aexit__(exc_type, exc, tb)

    async def execute_read[T](self, work: Callable[..., Awaitable[T]], *a: Any, **k: Any) -> T:
        return await self._inner.execute_read(work, *a, **k)

    async def execute_write[T](self, work: Callable[..., Awaitable[T]], *a: Any, **k: Any) -> T:
        self._owner.writes += 1
        if self._owner.fail_on_write == self._owner.writes:
            raise ConnectionResetError("simulated failure of one write")
        return await self._inner.execute_write(work, *a, **k)


class _CountingDriver:
    def __init__(self, inner: AsyncDriver, fail_on_write: int | None = None) -> None:
        self._inner = inner
        self.writes = 0
        self.fail_on_write = fail_on_write

    def session(self, **kw: Any) -> _CountingSession:
        return _CountingSession(self._inner.session(**kw), self)


# Test 12: a fresh database

PINNED_MIGRATION_IDS = [
    "0001_resource_id",
    "0002_identifier_key",
    "0003_concept_key",
    "0004_obs_by_service",
    "0005_task_by_status",
    "0006_svc_active",
    "0007_phone_hash",
    "0008_location_position",
    "0009_scheduled_work_id",
    "0014_communication_id",
    "0015_communication_provider_id",
    "0016_audit_event_id",
    "0017_audit_head_id",
    "0018_audit_ref_id",
    "0019_provenance_id",
    "0020_chain_seq",
    "0021_link_token_hash",
    "0022_case_reference_id",
    "0023_device_id",
    "0024_protected_contact_role_id",
    "0025_protected_contact_key",
    "0026_credential_device_id",
    "0027_report_flag_id",
    "0028_outbox_message_id",
    "0029_idempotency_key",
    "0030_processed_key",
    "0031_tenant_composites",
    "0032_backfill_default_tenant",
    "0033_case_open_reference",
    "0034_tenant_registry",
    "0035_default_tenant_record",
    "0040_protected_text_handle",
    "0041_service_move_id",
    "0045_support_session_id",
    "0046_support_code_hash",
    "0055_tenant_config_records",
    "0070_safety_counter_id",
    "0105_drop_superseded_keys",
]


async def test_a_fresh_database_applies_every_migration_in_order(built: _Built) -> None:
    assert built.applied == [m.id for m in MIGRATIONS]
    # The count is the sum of the areas, so a new area or migration cannot leave a stale number...
    areas = (
        CORE_MIGRATIONS,
        TENANT_MIGRATIONS,
        NETWORK_MIGRATIONS,
        PROTECTED_MIGRATIONS,
        SUPPORT_MIGRATIONS,
        SAFETY_MIGRATIONS,
        TENANT_CONFIG_MIGRATIONS,
        CONTRACT_MIGRATIONS,
    )
    assert len(built.applied) == sum(len(area) for area in areas)
    # ...and the ids are pinned, so adding, removing or renaming one is a change to this list made
    # on purpose (an id applied in one place must never become a different migration elsewhere).
    assert built.applied == PINNED_MIGRATION_IDS


async def test_every_composite_constraint_has_the_label_the_properties_and_the_type_of_its_row(
    built: _Built,
) -> None:
    rows = await _rows(
        built.driver,
        "SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties "
        "RETURN name, type, entityType, labelsOrTypes, properties",
    )
    live = {r["name"]: r for r in rows}
    for row in COMPOSITE_CONSTRAINTS:
        found = live.get(row.name)
        assert found is not None, row.name
        assert found["type"] == "UNIQUENESS", row.name
        assert found["entityType"] == "NODE", row.name
        assert found["labelsOrTypes"] == [row.label], row.name
        assert tuple(found["properties"]) == row.properties, row.name
    migration = live.get("migration_id")
    assert migration is not None
    assert (migration["labelsOrTypes"], migration["properties"]) == (["Migration"], ["id"])
    assert migration["type"] == "UNIQUENESS"


async def test_the_six_composite_indexes_exist(built: _Built) -> None:
    rows = await _rows(
        built.driver,
        "SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties "
        "RETURN name, type, entityType, labelsOrTypes, properties",
    )
    live = {r["name"]: r for r in rows}
    for row in COMPOSITE_INDEXES:
        found = live.get(row.name)
        assert found is not None, row.name
        assert found["entityType"] == "NODE", row.name
        assert found["labelsOrTypes"] == [row.label], row.name
        assert tuple(found["properties"]) == row.properties, row.name


async def test_the_superseded_keys_are_gone_and_the_single_property_indexes_stay(
    built: _Built,
) -> None:
    constraints, indexes = await schema_names(built.driver)
    assert len(SUPERSEDED_CONSTRAINT_NAMES) == 18
    assert constraints.isdisjoint(SUPERSEDED_CONSTRAINT_NAMES)
    assert "link_token_hash" in constraints
    # TEN-032 drops constraints only: the six range indexes and the point index stay.
    assert len(_OLD_INDEXES) == 7
    assert indexes >= _OLD_INDEXES


async def test_the_link_token_hash_and_the_point_index_are_unchanged(built: _Built) -> None:
    constraints = await _rows(
        built.driver,
        "SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties "
        "WHERE name = 'link_token_hash' RETURN type, labelsOrTypes, properties",
    )
    assert constraints == [
        {"type": "UNIQUENESS", "labelsOrTypes": ["LinkToken"], "properties": ["tokenHash"]}
    ]
    indexes = await _rows(
        built.driver,
        "SHOW INDEXES YIELD name, type, labelsOrTypes, properties WHERE name = 'location_position' "
        "RETURN type, labelsOrTypes, properties",
    )
    assert indexes == [{"type": "POINT", "labelsOrTypes": ["Location"], "properties": ["position"]}]


async def test_the_superseded_lists_name_objects_the_contract_dropped_or_left(
    built: _Built,
) -> None:
    constraints, indexes = await schema_names(built.driver)
    assert constraints.isdisjoint(SUPERSEDED_CONSTRAINTS)
    assert indexes >= SUPERSEDED_INDEXES


# Test 13: applying again


async def test_applying_again_after_deleting_the_records_changes_no_schema_object(
    built: _Built,
) -> None:
    before = await schema_names(built.driver)
    for _ in range(2):
        await _run(built.driver, "MATCH (m:Migration) DETACH DELETE m")
        again = await apply_migrations(built.driver)
        assert again == [m.id for m in MIGRATIONS]
        assert await schema_names(built.driver) == before


# Test 14: the planner uses the new index


async def test_the_planner_uses_the_resource_key_index(built: _Built) -> None:
    async def explain(tx: AsyncManagedTransaction) -> str:
        result = await tx.run(
            "EXPLAIN MATCH (n:Resource {key: $key, tenantId: $tenant}) RETURN n",
            key="Practitioner/p-1",
            tenant="a",
        )
        summary = await result.consume()
        return repr(summary.plan)

    plan = await read_tx(built.driver, explain)
    # The plan names the label and the properties of the index, not its name:
    # "NodeUniqueIndexSeek UNIQUE n:Resource(tenantId, key) WHERE tenantId = $tenant AND ...".
    assert "NodeUniqueIndexSeek" in plan
    assert "n:Resource(tenantId, key)" in plan


# Test 15: the backfill

_LABELS = (
    ("Resource", "HealthcareService"),
    ("Concept",),
    ("CodeSystem",),
    ("AuditHead",),
    ("ChainLink",),
    ("OutboxMessage",),
    ("LinkToken",),
    ("ServiceRequest",),
    ("Device",),
    ("Practitioner",),
    ("Observation",),
    ("List",),
)


async def _seed_unstamped(driver: AsyncDriver) -> int:
    """Raw nodes with no tenant: two of each label group, a chain of relationships through them,
    one node already stamped `other` (with no relationship, so no scope is crossed), and the
    registry nodes. Returns the number of nodes a stamp must change."""

    async def work(tx: AsyncManagedTransaction) -> None:
        for position, labels in enumerate(_LABELS):
            for copy in range(2):
                await (
                    await tx.run(
                        f"CREATE (n:{':'.join(labels)} {{probe: $probe}})",
                        probe=f"{position}-{copy}",
                    )
                ).consume()
        await (
            await tx.run(
                "MATCH (a {probe: '0-0'}), (b {probe: '1-0'}), (c {probe: '2-1'}) "
                "CREATE (a)-[:REL_ONE]->(b), (b)-[:REL_TWO]->(c), (a)-[:REL_ONE]->(c)"
            )
        ).consume()
        await (await tx.run("CREATE (:Tenant {id: 'registry-probe'})")).consume()
        await (await tx.run("CREATE (:TenantNumber {e164: '+440000000000'})")).consume()
        await (await tx.run("CREATE (:Network {id: 'net-probe'})")).consume()
        await (
            await tx.run(
                "MATCH (t:Tenant {id: 'registry-probe'}), (x:TenantNumber) "
                "CREATE (t)-[:HAS_NUMBER]->(x)"
            )
        ).consume()
        await (await tx.run("CREATE (:Practitioner {probe: 'mine', tenantId: 'other'})")).consume()

    await write_tx(driver, work)
    return len(_LABELS) * 2


async def _shapes(driver: AsyncDriver) -> list[Any]:
    rows = await _rows(
        driver,
        "MATCH (a)-[r]->(b) RETURN labels(a) AS a, type(r) AS type, labels(b) AS b "
        "ORDER BY type, a, b",
    )
    return [(r["a"], r["type"], r["b"]) for r in rows]


async def test_the_backfill_stamps_every_node_but_the_registry_and_the_others_in_batches(
    built: _Built, private: AsyncDriver
) -> None:
    expected = await _seed_unstamped(private)
    shapes = await _shapes(private)
    counting = _CountingDriver(private)

    stamped = await backfill_default_tenant(counting, batch=3)  # type: ignore[arg-type]

    assert stamped == expected == 24
    assert counting.writes == math.ceil(expected / 3) + 1
    rows = await _rows(
        private,
        "MATCH (n) WHERE NOT any(l IN labels(n) WHERE l IN $registry) "
        "RETURN n.tenantId AS tenant, n.probe AS probe",
        registry=list(REGISTRY_LABELS),
    )
    stamps = {r["probe"]: r["tenant"] for r in rows}
    assert stamps.pop("mine") == "other"
    assert set(stamps.values()) == {DEFAULT_TENANT_ID}
    assert len(stamps) == expected
    registry_rows = await _rows(
        private,
        "MATCH (n) WHERE any(l IN labels(n) WHERE l IN $registry) RETURN n.tenantId AS tenant",
        registry=list(REGISTRY_LABELS),
    )
    assert registry_rows and all(r["tenant"] is None for r in registry_rows)
    assert await _shapes(private) == shapes
    assert shapes
    violations = await invariant_violations(private)
    assert all(rows == [] for rows in violations.values()), violations
    assert violations
    assert await backfill_default_tenant(private, batch=3) == 0


async def test_the_invariant_queries_find_an_unstamped_node_and_a_relationship_between_tenants(
    built: _Built, private: AsyncDriver
) -> None:
    await _run(
        private,
        "CREATE (:Device {probe: 'x'}), (:Device {probe: 'a', tenantId: 'a'})"
        "-[:BETWEEN]->(:Device {probe: 'b', tenantId: 'b'})",
    )

    violations = await invariant_violations(private)

    assert sorted(violations) == ["cross_scope_relationships", "unstamped_nodes"]
    assert violations["unstamped_nodes"] == [{"labels": ["Device"], "n": 1}]
    assert violations["cross_scope_relationships"] == [{"type": "BETWEEN", "n": 1}]


# Test 16: crash and resume


async def test_a_backfill_that_fails_part_way_is_unrecorded_and_a_rerun_finishes_it(
    built: _Built, private: AsyncDriver
) -> None:
    await _seed_unstamped(private)
    await _run(private, "MATCH (m:Migration {id: '0032_backfill_default_tenant'}) DETACH DELETE m")
    stamp = dataclasses.replace(TENANT_MIGRATIONS[1], batch=3)
    failing = _CountingDriver(private, fail_on_write=2)

    with pytest.raises(MigrationFailed) as caught:
        await apply_migrations(failing, [stamp])  # type: ignore[arg-type]

    assert (
        str(caught.value)
        == "migration 0032_backfill_default_tenant failed at loop 1: ConnectionResetError"
    )
    recorded = await _rows(private, "MATCH (m:Migration) RETURN m.id AS id")
    assert "0032_backfill_default_tenant" not in {r["id"] for r in recorded}
    stamped = await _rows(
        private, "MATCH (n {tenantId: $t}) RETURN count(n) AS n", t=DEFAULT_TENANT_ID
    )
    assert stamped == [{"n": 3}]

    assert await apply_migrations(private, [stamp]) == ["0032_backfill_default_tenant"]

    recorded = await _rows(private, "MATCH (m:Migration) RETURN m.id AS id")
    assert "0032_backfill_default_tenant" in {r["id"] for r in recorded}
    violations = await invariant_violations(private)
    assert all(rows == [] for rows in violations.values()), violations
    tenants = await _rows(
        private,
        "MATCH (n) WHERE n.tenantId IS NOT NULL "
        "RETURN DISTINCT n.tenantId AS tenant ORDER BY tenant",
    )
    assert [r["tenant"] for r in tenants] == [DEFAULT_TENANT_ID, "other"]


# Test 17: the open reference


async def test_an_active_case_gets_its_open_reference_and_a_completed_one_does_not(
    built: _Built, private: AsyncDriver
) -> None:
    await _run(
        private,
        "CREATE (:ServiceRequest {id: 'c-1', status: 'active', reference: '4821'}), "
        "(:ServiceRequest {id: 'c-2', status: 'completed', reference: '4822'})",
    )
    reference = TENANT_MIGRATIONS[2]
    assert reference.loops == (OPEN_REFERENCE_BACKFILL,)
    await _run(private, "MATCH (m:Migration {id: $id}) DETACH DELETE m", id=reference.id)

    assert await apply_migrations(private, [reference]) == ["0033_case_open_reference"]

    rows = await _rows(
        private,
        "MATCH (r:ServiceRequest) RETURN r.id AS id, r.reference AS reference, "
        "r.openReference AS open ORDER BY id",
    )
    assert rows == [
        {"id": "c-1", "reference": "4821", "open": "4821"},
        {"id": "c-2", "reference": "4822", "open": None},
    ]
    await _run(private, "MATCH (m:Migration {id: $id}) DETACH DELETE m", id=reference.id)
    assert await apply_migrations(private, [reference]) == ["0033_case_open_reference"]
    again = await _rows(
        private,
        "MATCH (r:ServiceRequest) RETURN r.id AS id, r.reference AS reference, "
        "r.openReference AS open ORDER BY id",
    )
    assert again == rows


# Test 18: composite semantics


def _value(label: str, prop: str) -> Any:
    return 1 if prop == "seq" else f"{label}-{prop}-value"


def _props(label: str, properties: tuple[str, ...]) -> dict[str, Any]:
    return {p: _value(label, p) for p in properties if p != "tenantId"}


async def _create(
    driver: AsyncDriver, label: str, tenant: str | None, props: dict[str, Any]
) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        values = dict(props) if tenant is None else {**props, "tenantId": tenant}
        await (await tx.run(f"CREATE (n:{label}) SET n = $props", props=values)).consume()

    await write_tx(driver, work)


async def test_each_composite_key_lets_two_tenants_share_and_refuses_a_repeat_in_one(
    built: _Built, contracted: AsyncDriver
) -> None:
    refused: list[str] = []
    for row in COMPOSITE_CONSTRAINTS:
        await wipe_all(contracted)
        props = _props(row.label, row.properties)
        await _create(contracted, row.label, "a", props)
        await _create(contracted, row.label, "b", props)
        try:
            await _create(contracted, row.label, "a", props)
        except ConstraintError:
            pass
        else:
            refused.append(f"{row.name}: a repeat in one tenant was accepted")
        await _create(contracted, row.label, None, props)
        await _create(contracted, row.label, None, props)
        count = await _rows(contracted, f"MATCH (n:{row.label}) RETURN count(n) AS n")
        if count != [{"n": 4}]:
            refused.append(f"{row.name}: expected four nodes, found {count}")
    assert refused == []


async def test_the_migrated_schema_has_no_superseded_constraint_whatever_ran_before(
    built: _Built,
) -> None:
    constraints, _ = await schema_names(built.driver)
    assert constraints.isdisjoint(SUPERSEDED_CONSTRAINT_NAMES)


async def test_the_migrated_schema_has_none_of_the_superseded_keys_and_keeps_two_objects(
    built: _Built, contracted: AsyncDriver
) -> None:
    constraints, indexes = await schema_names(contracted)
    assert constraints.isdisjoint(SUPERSEDED_CONSTRAINT_NAMES)
    assert "link_token_hash" in constraints
    assert "location_position" in indexes
    assert {c.name for c in COMPOSITE_CONSTRAINTS} <= constraints


# Test 19, the raw half: a reference per tenant among open cases


async def test_two_tenants_can_hold_one_open_reference_and_one_tenant_cannot_hold_it_twice(
    built: _Built, contracted: AsyncDriver
) -> None:
    await _run(contracted, "CREATE (:ServiceRequest {tenantId: 'a', openReference: '4821'})")
    await _run(contracted, "CREATE (:ServiceRequest {tenantId: 'b', openReference: '4821'})")
    with pytest.raises(ConstraintError):
        await _run(contracted, "CREATE (:ServiceRequest {tenantId: 'a', openReference: '4821'})")
    # A closed case has a reference and no open reference: it blocks nobody.
    await _run(contracted, "CREATE (:ServiceRequest {tenantId: 'a', reference: '4821'})")
    await _run(contracted, "CREATE (:ServiceRequest {tenantId: 'a', reference: '4821'})")


# The rollback


async def test_the_rollback_statements_undo_0031_and_nothing_the_old_schema_owns(
    built: _Built,
) -> None:
    before_constraints, before_indexes = await schema_names(built.driver)
    try:
        for statement in ROLLBACK_0031:
            await _schema(built.driver, statement)
        constraints, indexes = await schema_names(built.driver)
        assert constraints == before_constraints - {c.name for c in COMPOSITE_CONSTRAINTS} - {
            "migration_id"
        }
        # A unique constraint owns an index of its own name, so it goes with the constraint.
        owned = {i.name for i in COMPOSITE_INDEXES} | {c.name for c in COMPOSITE_CONSTRAINTS}
        assert indexes == before_indexes - owned - {"migration_id"}
        assert "link_token_hash" in constraints
        assert indexes >= _OLD_INDEXES
    finally:
        for statement in TENANT_MIGRATIONS[0].statements:
            await _schema(built.driver, statement)
    assert await schema_names(built.driver) == (before_constraints, before_indexes)
