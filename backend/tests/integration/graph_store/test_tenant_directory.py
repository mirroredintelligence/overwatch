"""The tenant directory on a real Neo4j (TEN-007, DEC-130 to DEC-134).

The directory is the one code that runs before a tenant is bound, so the tests show what it reads
and what it cannot: it answers from the registry nodes (`Tenant`, `TenantNumber`) and from nothing
else, whatever the graph also holds and whatever tenant is bound; a number and its account must
match together; an ambiguous or damaged record is a fault, never a guess; and a secret is a
reference in the graph, never a value.

The registry nodes are seeded with raw Cypher here (test code): provisioning is TEN-028, and the
directory has no write statement, which is the point.
"""

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

from diucs.adapters.inbound.workers.outbox_relay import OutboxRelay, RelayResult
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import run_global_query
from diucs.adapters.outbound.graph_store.migrations import apply_migrations
from diucs.adapters.outbound.graph_store.migrations_tenant import TENANT_MIGRATIONS
from diucs.adapters.outbound.graph_store.queries import GLOBAL_QUERY_IDS, REGISTRY
from diucs.adapters.outbound.graph_store.tenant_directory import (
    Neo4jTenantDirectory,
    tenant_properties,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.tenants import TenantRecordInvalid, twilio_token_ref
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import bind_tenant
from diucs.bootstrap.container import build
from diucs.bootstrap.settings import Settings
from diucs.domain.model.tenant import Tenant, TenantStatus
from tests.support.neo4j import read_tx, write_tx
from tests.support.relay_rig import NOW, SpyBus, add_messages, outbox_message
from tests.support.tenant_samples import make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

A, B = "alpha-icb", "bravo-trust"
SID_A, SID_B = "AC" + "a" * 32, "AC" + "b" * 32
NUMBER_A, NUMBER_A2, NUMBER_B = "+447700900101", "+447700900102", "+447700900201"
TOKEN_A = b"test-only-token-for-alpha"
TOKEN_B = b"test-only-token-for-bravo"
GUID_A = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
GUID_B = "1f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
DATA_MARKER = "DATA-MARKER-must-never-leave-the-graph"


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


@pytest.fixture
def directory(connection: Neo4jConnection) -> Neo4jTenantDirectory:
    return Neo4jTenantDirectory(connection)


async def _run(driver: AsyncDriver, cypher: str, **params: Any) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(cypher, params)

    await write_tx(driver, work)


async def _rows(driver: AsyncDriver, cypher: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(cypher, params)).data()

    return await read_tx(driver, work)


async def seed_tenant(
    driver: AsyncDriver,
    tenant: Tenant,
    *,
    host: str | None = None,
    entra: str | None = None,
    **damage: Any,
) -> None:
    props = tenant_properties(tenant)
    if host is not None:
        props["host"] = host
    if entra is not None:
        props["entraDirectoryId"] = entra
    props.update(damage)
    await _run(driver, "CREATE (t:Tenant) SET t = $props", props=props)


async def seed_number(
    driver: AsyncDriver,
    tenant_id: str,
    e164: str,
    sid: str,
    *,
    ref: str | None = None,
    status: str = "active",
) -> None:
    await _run(
        driver,
        "MATCH (t:Tenant {id: $id}) "
        "CREATE (t)-[:HAS_NUMBER]->(:TenantNumber {e164: $e164, accountSid: $sid, "
        "secretRef: $ref, status: $status})",
        id=tenant_id,
        e164=e164,
        sid=sid,
        ref=twilio_token_ref(tenant_id) if ref is None else ref,
        status=status,
    )


async def seed_two_tenants(driver: AsyncDriver) -> None:
    await seed_tenant(driver, make_tenant(id=A), host="alpha.example.org", entra=GUID_A)
    await seed_tenant(driver, make_tenant(id=B), host="bravo.example.org", entra=GUID_B)
    await seed_number(driver, A, NUMBER_A, SID_A)
    await seed_number(driver, A, NUMBER_A2, SID_A)
    await seed_number(driver, B, NUMBER_B, SID_B)


# A tenant and its keys


@pytest.mark.parametrize("status", list(TenantStatus))
async def test_a_tenant_in_any_status_is_read_back_equal_from_its_node(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory, status: TenantStatus
) -> None:
    tenant = make_tenant(status, id=A, ods_code="R1A", dsa_ref="DSA-1 v2")
    await seed_tenant(neo4j_driver, tenant)
    assert await directory.get(A) == tenant


async def test_a_tenant_that_is_not_there_or_not_an_id_is_none(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_two_tenants(neo4j_driver)
    for key in ("charlie-trust", "platform", "net-abcd1234", "ALPHA-ICB", "alpha-icb ", ""):
        assert await directory.get(key) is None, key


async def test_each_tenant_is_found_by_its_own_host_and_directory_and_no_other(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_two_tenants(neo4j_driver)
    tenant_a, tenant_b = make_tenant(id=A), make_tenant(id=B)
    assert await directory.by_host("alpha.example.org") == tenant_a
    assert await directory.by_host("BRAVO.Example.org.") == tenant_b
    assert await directory.by_host("charlie.example.org") is None
    assert await directory.by_entra_directory(GUID_A) == tenant_a
    assert await directory.by_entra_directory(GUID_B.upper()) == tenant_b
    assert await directory.by_entra_directory("2f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f") is None


async def test_one_host_and_one_directory_belong_to_one_tenant(
    neo4j_driver: AsyncDriver,
) -> None:
    await seed_tenant(neo4j_driver, make_tenant(id=A), host="alpha.example.org", entra=GUID_A)
    with pytest.raises(ConstraintError):
        await seed_tenant(neo4j_driver, make_tenant(id=B), host="alpha.example.org")
    with pytest.raises(ConstraintError):
        await seed_tenant(neo4j_driver, make_tenant(id=B), entra=GUID_A)
    with pytest.raises(ConstraintError):
        await seed_tenant(neo4j_driver, make_tenant(id=A))


# The number called and the account that carried it


async def test_a_number_resolves_to_its_tenant_only_with_its_own_account(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_two_tenants(neo4j_driver)

    line = await directory.by_inbound_number(NUMBER_A, SID_A)
    assert line is not None
    assert line.tenant == make_tenant(id=A)
    assert (line.number, line.account_sid) == (NUMBER_A, SID_A)
    assert line.secret_ref == twilio_token_ref(A)

    other = await directory.by_inbound_number(NUMBER_B, SID_B)
    assert other is not None and other.tenant.id == B and other.secret_ref == twilio_token_ref(B)

    # B's number under A's account, A's number under B's account, and an account nobody holds.
    assert await directory.by_inbound_number(NUMBER_B, SID_A) is None
    assert await directory.by_inbound_number(NUMBER_A, SID_B) is None
    assert await directory.by_inbound_number(NUMBER_A, "AC" + "c" * 32) is None
    assert await directory.by_inbound_number("+447700900999", SID_A) is None


async def test_a_retired_or_quarantined_number_resolves_to_nobody(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_tenant(neo4j_driver, make_tenant(id=A))
    await seed_number(neo4j_driver, A, NUMBER_A, SID_A, status="retired")
    await seed_number(neo4j_driver, A, NUMBER_A2, SID_A, status="quarantined")
    assert await directory.by_inbound_number(NUMBER_A, SID_A) is None
    assert await directory.by_inbound_number(NUMBER_A2, SID_A) is None
    assert await directory.by_account_sid(SID_A) is None


async def test_a_number_belongs_to_one_tenant(neo4j_driver: AsyncDriver) -> None:
    await seed_two_tenants(neo4j_driver)
    with pytest.raises(ConstraintError):
        await seed_number(neo4j_driver, B, NUMBER_A, SID_B)


async def test_a_suspended_tenant_still_resolves_so_the_caller_can_refuse_it(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_tenant(neo4j_driver, make_tenant(TenantStatus.SUSPENDED, id=A))
    await seed_number(neo4j_driver, A, NUMBER_A, SID_A)
    line = await directory.by_inbound_number(NUMBER_A, SID_A)
    assert line is not None and line.tenant.status is TenantStatus.SUSPENDED


async def test_an_account_resolves_to_its_tenant_for_receipts(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_two_tenants(neo4j_driver)
    line = await directory.by_account_sid(SID_A)
    assert line is not None and line.tenant.id == A and line.account_sid == SID_A
    assert line.number == NUMBER_A  # the first number in order, both are this tenant's
    other = await directory.by_account_sid(SID_B)
    assert other is not None and other.tenant.id == B
    assert await directory.by_account_sid("AC" + "c" * 32) is None


async def test_an_account_two_tenants_hold_is_a_fault_not_a_guess(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_two_tenants(neo4j_driver)
    await seed_number(neo4j_driver, B, "+447700900202", SID_A)  # B holds a number of A's account
    with pytest.raises(TenantRecordInvalid):
        await directory.by_account_sid(SID_A)
    # The number and the account together still name one tenant each.
    first = await directory.by_inbound_number(NUMBER_A, SID_A)
    second = await directory.by_inbound_number("+447700900202", SID_A)
    assert first is not None and first.tenant.id == A
    assert second is not None and second.tenant.id == B


async def test_a_number_that_points_at_another_tenants_secret_is_a_fault(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_tenant(neo4j_driver, make_tenant(id=A))
    await seed_number(neo4j_driver, A, NUMBER_A, SID_A, ref=twilio_token_ref(B))
    with pytest.raises(TenantRecordInvalid) as raised:
        await directory.by_inbound_number(NUMBER_A, SID_A)
    assert B not in str(raised.value)


# Which tenants are active


async def test_only_active_tenants_are_listed_in_id_order(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    for tenant_id, status in (
        ("charlie-gp", TenantStatus.ACTIVE),
        ("delta-lab", TenantStatus.SUSPENDED),
        ("echo-trust", TenantStatus.PROVISIONING),
        ("foxtrot-ics", TenantStatus.OFFBOARDING),
        ("golf-trust", TenantStatus.OFFBOARDED),
        ("hotel-trust", TenantStatus.PURGED),
        (A, TenantStatus.ACTIVE),
    ):
        await seed_tenant(neo4j_driver, make_tenant(status, id=tenant_id))
    assert [t.id for t in await directory.list_active()] == [A, "charlie-gp"]
    assert list(await directory.active_tenant_ids()) == [A, "charlie-gp"]


async def test_the_directory_is_the_same_with_no_tenant_bound_or_any_tenant_bound(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_two_tenants(neo4j_driver)

    async def ask() -> tuple[object, ...]:
        return (
            await directory.get(B),
            await directory.by_inbound_number(NUMBER_B, SID_B),
            await directory.by_account_sid(SID_B),
            await directory.by_host("bravo.example.org"),
            await directory.by_entra_directory(GUID_B),
            tuple(await directory.list_active()),
            tuple(await directory.active_tenant_ids()),
        )

    with bind_tenant(A):
        as_a = await ask()
    with bind_tenant(B):
        as_b = await ask()
    assert as_a == as_b
    assert as_a[0] == make_tenant(id=B)


@pytest.mark.no_tenant
async def test_the_directory_works_before_any_tenant_is_bound(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_two_tenants(neo4j_driver)
    assert (await directory.get(A)) == make_tenant(id=A)
    assert list(await directory.active_tenant_ids()) == [A, B]


async def test_a_damaged_record_is_a_fault_and_does_not_hide_the_other_tenants_ids(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_tenant(neo4j_driver, make_tenant(id=A))
    await seed_tenant(neo4j_driver, make_tenant(id=B), createdAt="2026-01-05T09:00:00Z")
    with pytest.raises(TenantRecordInvalid):
        await directory.get(B)
    with pytest.raises(TenantRecordInvalid):
        await directory.list_active()
    # The relay needs ids only: one tenant's record cannot stop another's outbox.
    assert list(await directory.active_tenant_ids()) == [A, B]
    assert await directory.get(A) == make_tenant(id=A)


# What a global statement can reach


async def test_no_global_statement_returns_anything_from_a_graph_that_also_holds_data(
    neo4j_driver: AsyncDriver, connection: Neo4jConnection, tenant_id: str, other_tenant_id: str
) -> None:
    """The graph holds data of two tenants that carry the same words as the registry's keys. A
    global statement may return registry rows and nothing that came from a data node."""
    await seed_two_tenants(neo4j_driver)
    for scope in (tenant_id, other_tenant_id):
        await _run(
            neo4j_driver,
            "CREATE (:Observation {id: $id, tenantId: $scope, note: $marker, status: 'active', "
            "host: 'alpha.example.org', e164: $number, accountSid: $sid, "
            "entraDirectoryId: $guid}) "
            "CREATE (:Person {id: $id, tenantId: $scope, note: $marker, status: 'active', "
            "host: 'alpha.example.org', e164: $number, accountSid: $sid})",
            id=f"data-{scope}",
            scope=scope,
            marker=DATA_MARKER,
            number=NUMBER_A,
            sid=SID_A,
            guid=GUID_A,
        )
    answers = {
        "Q-TENANT-GET": {"id": A},
        "Q-TENANT-LIST-ACTIVE": {},
        "Q-TENANT-ACTIVE-IDS": {},
        "Q-TENANT-BY-NUMBER": {"number": NUMBER_A, "accountSid": SID_A},
        "Q-TENANT-BY-ACCOUNT": {"accountSid": SID_A},
        "Q-TENANT-BY-HOST": {"host": "alpha.example.org"},
        "Q-TENANT-BY-ENTRA": {"directoryId": GUID_A},
    }
    assert set(answers) | {"Q-NEO4J-PING"} == set(GLOBAL_QUERY_IDS)

    for query_id in answers:

        async def work(tx: AsyncManagedTransaction, query_id: str = query_id) -> Any:
            return await run_global_query(tx, REGISTRY.get(query_id), **answers[query_id])

        rows = await connection.run_read(work)
        assert rows, query_id
        assert DATA_MARKER not in repr(rows), query_id
        assert f"data-{tenant_id}" not in repr(rows), query_id
        assert f"data-{other_tenant_id}" not in repr(rows), query_id


async def test_the_directory_holds_references_to_secrets_and_never_a_secret(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await seed_two_tenants(neo4j_driver)
    secrets = FixedSecretStore({twilio_token_ref(A): TOKEN_A, twilio_token_ref(B): TOKEN_B})
    line_a = await directory.by_inbound_number(NUMBER_A, SID_A)
    line_b = await directory.by_inbound_number(NUMBER_B, SID_B)
    assert line_a is not None and line_b is not None

    assert secrets.get(line_a.secret_ref) == TOKEN_A
    assert secrets.get(line_b.secret_ref) == TOKEN_B
    assert secrets.requested == (twilio_token_ref(A), twilio_token_ref(B))

    everything = await _rows(
        neo4j_driver,
        "MATCH (n) RETURN properties(n) AS props UNION ALL "
        "MATCH ()-[r]->() RETURN properties(r) AS props",
    )
    text = repr(everything)
    for token in (TOKEN_A, TOKEN_B):
        assert token.decode() not in text
    assert twilio_token_ref(A) in text  # the reference is there
    assert repr(line_a).count(TOKEN_A.decode()) == 0


# The relay reads its tenants from the directory (DEC-157 item 2)


async def test_the_relay_serves_the_active_tenants_of_the_directory_and_no_other(
    neo4j_driver: AsyncDriver,
    directory: Neo4jTenantDirectory,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await seed_tenant(neo4j_driver, make_tenant(id=tenant_id))
    await seed_tenant(neo4j_driver, make_tenant(TenantStatus.SUSPENDED, id=other_tenant_id))
    await add_messages(uow_factory_a, outbox_message("a-1", 0))
    await add_messages(uow_factory_b, outbox_message("b-1", 0))
    clock = FixedClock(NOW)
    bus = SpyBus(ManualEventBus(clock))
    relay = OutboxRelay(uow_factory_a, bus, InMemoryCache(clock), clock, directory)

    result = await relay.run_once()

    assert result == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert [(m.id, m.tenant_id) for m in bus.published] == [("a-1", tenant_id)]
    pending = await _rows(
        neo4j_driver, "MATCH (m:OutboxMessage {id: 'b-1'}) RETURN m.status AS status"
    )
    assert pending == [{"status": "pending"}]


# Start-up


async def test_start_up_applies_the_migrations_and_leaves_the_registry_readable(
    neo4j_driver: AsyncDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_URI", os.environ["NEO4J_URI"])
    monkeypatch.setenv("DIUCS_NEO4J_USER", os.environ["NEO4J_USER"])
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", os.environ["NEO4J_PASSWORD"])
    await seed_two_tenants(neo4j_driver)
    await _run(neo4j_driver, "MATCH (m:Migration {id: '0035_default_tenant_record'}) DELETE m")
    container = build(Settings())

    await container.startup()
    try:
        recorded = await _rows(
            neo4j_driver, "MATCH (m:Migration {id: '0035_default_tenant_record'}) RETURN m.id AS id"
        )
        assert recorded == [{"id": "0035_default_tenant_record"}]
        heads = await _rows(neo4j_driver, "MATCH (h:AuditHead) RETURN count(h) AS n")
        assert heads == [{"n": 1}]
        assert list(await container.tenants.active_tenant_ids()) == [A, B]
    finally:
        await container.shutdown()


async def test_a_second_start_up_changes_nothing(
    neo4j_driver: AsyncDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_URI", os.environ["NEO4J_URI"])
    monkeypatch.setenv("DIUCS_NEO4J_USER", os.environ["NEO4J_USER"])
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", os.environ["NEO4J_PASSWORD"])
    for _ in range(2):
        container = build(Settings())
        await container.startup()
        await container.shutdown()
    heads = await _rows(neo4j_driver, "MATCH (h:AuditHead) RETURN count(h) AS n")
    assert heads == [{"n": 1}]
    assert await apply_migrations(neo4j_driver) == []


# The default tenant record (migration 0035)


async def _run_0035(driver: AsyncDriver) -> None:
    migration = next(m for m in TENANT_MIGRATIONS if m.id == "0035_default_tenant_record")

    async def work(tx: AsyncManagedTransaction) -> None:
        for statement in migration.statements:
            await tx.run(statement, dict(migration.params))

    await write_tx(driver, work)


async def test_the_default_tenant_record_is_made_only_when_data_is_stamped_with_it(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await _run_0035(neo4j_driver)
    assert await directory.get("default") is None

    await _run(neo4j_driver, "CREATE (:Observation {id: 'legacy-1', tenantId: 'default'})")
    await _run_0035(neo4j_driver)
    record = await directory.get("default")
    assert record is not None
    assert record.status is TenantStatus.ACTIVE
    assert record.hash_key_version == 0  # the legacy global keys
    assert record.display_name == "Default tenant" and record.legal_name == "Default tenant"
    assert list(await directory.active_tenant_ids()) == ["default"]


async def test_running_0035_again_never_rewrites_a_record_that_was_edited(
    neo4j_driver: AsyncDriver, directory: Neo4jTenantDirectory
) -> None:
    await _run(neo4j_driver, "CREATE (:Observation {id: 'legacy-1', tenantId: 'default'})")
    await _run_0035(neo4j_driver)
    await _run(neo4j_driver, "MATCH (t:Tenant {id: 'default'}) SET t.displayName = 'Renamed'")
    await _run_0035(neo4j_driver)
    await _run_0035(neo4j_driver)
    record = await directory.get("default")
    assert record is not None and record.display_name == "Renamed"
    assert await _rows(neo4j_driver, "MATCH (t:Tenant) RETURN count(t) AS n") == [{"n": 1}]
