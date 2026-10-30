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

import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.queries import (
    PLATFORM_QUERY_IDS,
    PLATFORM_STATEMENTS,
    REGISTRY,
    NamedQuery,
    QueryRegistry,
)
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
from tests.support.neo4j import ThrowawayNeo4j, read_tx, write_tx
from tests.support.tenant_seed import invariant_breaks

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.schema]

A, B = "reg-alpha", "reg-bravo"
SID = "AC" + "a" * 32
NUMBER_A, NUMBER_B = "+447700900301", "+447700900302"
GUID = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
GUID_B = "1a6b8d2f-4c3e-4d7b-8f9a-2b3c4d5e6f70"
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


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def harness_driver(own_neo4j: tuple[ThrowawayNeo4j, AsyncDriver]) -> AsyncDriver:
    """The registry holds the whole database's tenants, and a host, a number or a directory is
    unique across it, so this module runs on a container of its own, whatever the session's mode
    (`schema`)."""
    return own_neo4j[1]


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def neo4j_driver(harness_driver: AsyncDriver) -> AsyncDriver:
    return harness_driver


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
            "MATCH (r:Resource) WHERE r.tenantId IN $ids OR r.id IN $ids DETACH DELETE r",
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


# -- the seven platform statements: each is proved to reach one tenant's registry nodes only -----
#
# The generated two-tenant test (test_tenant_isolation.py) runs the tenant statements. The seven
# statements of the `platform` scope write the registry, whose nodes carry no tenant, so they are
# proved here, in the same shape: a world of two tenants (each with a record, a host, a directory,
# a number and a data node of its own), one statement run for A, and what is not A's must be what
# it was. Each statement is run twice, with A's own values and with values that belong to B, and a
# mutant of each (the key taken out) is run to show that the check would notice.

A_HOST, B_HOST = "alpha.example.org", "bravo.example.org"
NUMBER_A2 = "+447700900303"
OTHERS = (
    "MATCH (n) WHERE NOT (n:Tenant AND n.id = $a) "
    "AND NOT (n:TenantNumber AND EXISTS {(:Tenant {id: $a})-[:HAS_NUMBER]->(n)}) "
    "RETURN labels(n) AS labels, properties(n) AS props"
)
OTHER_LINKS = (
    "MATCH (x)-[r]->(y) WHERE NOT (x:Tenant AND x.id = $a) "
    "RETURN labels(x) AS x, properties(x) AS xp, type(r) AS type, labels(y) AS y, "
    "properties(y) AS yp"
)
OWN = (
    "MATCH (n) WHERE (n:Tenant AND n.id = $a) "
    "OR (n:TenantNumber AND EXISTS {(:Tenant {id: $a})-[:HAS_NUMBER]->(n)}) "
    "RETURN labels(n) AS labels, properties(n) AS props"
)


async def _seed_world(registry: Neo4jTenantRegistry, driver: AsyncDriver, *, with_a: bool) -> None:
    """B, and unless `with_a` is False A, each with a host, a directory and a number, and a data
    node of its own with the very words the registry keys use (a host, a number)."""
    people = [(B, NUMBER_B, B_HOST, GUID_B)]
    if with_a:
        people.insert(0, (A, NUMBER_A, A_HOST, GUID))
    for tenant, number, host, directory in people:
        await registry.create(_tenant(tenant))
        await registry.set_host(tenant, host)
        await registry.set_entra_directory(tenant, directory)
        await registry.put_number(tenant, _number(tenant, number))

    async def data(tx: AsyncManagedTransaction) -> None:
        for tenant, number, host in ((A, NUMBER_A, A_HOST), (B, NUMBER_B, B_HOST)):
            await tx.run(
                "CREATE (a:Resource {id: 'res-1', tenantId: $t, host: $host, e164: $number}) "
                "CREATE (b:Resource {id: 'res-2', tenantId: $t}) CREATE (a)-[:NEXT]->(b)",
                t=tenant,
                host=host,
                number=number,
            )

    await write_tx(driver, data)


def _canonical(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)


async def _look(driver: AsyncDriver, query: str, subject: str) -> list[str]:
    async def work(tx: AsyncManagedTransaction) -> list[str]:
        return _canonical(await (await tx.run(query, a=subject)).data())

    return await read_tx(driver, work)


@dataclass(frozen=True)
class Seen:
    """What the graph holds that is not A's registry nodes, the links of those, and A's own."""

    others: list[str]
    links: list[str]
    own: list[str]


async def _seen(driver: AsyncDriver) -> Seen:
    return Seen(
        await _look(driver, OTHERS, A),
        await _look(driver, OTHER_LINKS, A),
        await _look(driver, OWN, A),
    )


@pytest_asyncio.fixture(loop_scope="session")
async def world(registry: Neo4jTenantRegistry, neo4j_driver: AsyncDriver) -> Neo4jTenantRegistry:
    await _seed_world(registry, neo4j_driver, with_a=True)
    return registry


@pytest_asyncio.fixture(loop_scope="session")
async def world_without_a(
    registry: Neo4jTenantRegistry, neo4j_driver: AsyncDriver
) -> Neo4jTenantRegistry:
    await _seed_world(registry, neo4j_driver, with_a=False)
    return registry


Act = Callable[[Neo4jTenantRegistry], Awaitable[object]]


@dataclass(frozen=True)
class Case:
    """One platform statement, run for A with A's own values (`own`) and with a value that is B's
    (`foreign`, which must be refused with `refused`, or answer empty for a read)."""

    statement: str
    own: Act
    foreign: Act
    refused: type[BaseException] | None
    creates_a: bool = False


async def _create_a(registry: Neo4jTenantRegistry) -> object:
    return await registry.create(_tenant(A))


async def _create_b(registry: Neo4jTenantRegistry) -> object:
    return await registry.create(_tenant(B, display_name="Hijack"))


async def _save_a(registry: Neo4jTenantRegistry) -> object:
    return await registry.save(
        _tenant(A, status=TenantStatus.ACTIVE, activated_at=NOW, display_name="A renamed"),
        expected_epoch=1,
        expected_status=TenantStatus.PROVISIONING,
    )


async def _save_a_stale(registry: Neo4jTenantRegistry) -> object:
    return await registry.save(
        _tenant(A, status=TenantStatus.ACTIVE, activated_at=NOW),
        expected_epoch=9,
        expected_status=TenantStatus.PROVISIONING,
    )


CASES = (
    Case("Q-TENANT-REG-CREATE", _create_a, _create_b, Conflict, creates_a=True),
    Case("Q-TENANT-REG-SAVE", _save_a, _save_a_stale, None),
    Case(
        "Q-TENANT-REG-SET-HOST",
        lambda r: r.set_host(A, "alpha-two.example.org"),
        lambda r: r.set_host(A, B_HOST),
        Conflict,
    ),
    Case(
        "Q-TENANT-REG-SET-DIRECTORY",
        lambda r: r.set_entra_directory(A, "2b7c9e3a-5d4f-4e8c-9a0b-3c4d5e6f7081"),
        lambda r: r.set_entra_directory(A, GUID_B),
        Conflict,
    ),
    Case(
        "Q-TENANT-REG-PUT-NUMBER",
        lambda r: r.put_number(A, _number(A, NUMBER_A2)),
        lambda r: r.put_number(A, _number(A, NUMBER_B)),
        Conflict,
    ),
    Case(
        "Q-TENANT-REG-MARK-TESTED",
        lambda r: r.mark_number_tested(A, NUMBER_A, NOW),
        lambda r: r.mark_number_tested(A, NUMBER_B, NOW),  # B's number, A's id
        NotFound,
    ),
    Case("Q-TENANT-REG-NUMBERS", lambda r: r.numbers(A), lambda r: r.numbers("reg-nobody"), None),
)


async def test_the_cases_cover_every_platform_statement_and_only_those() -> None:
    registered = {i for i in REGISTRY.ids() if REGISTRY.get(i).scope == "platform"}
    assert {c.statement for c in CASES} == set(PLATFORM_QUERY_IDS) == registered
    assert set(PLATFORM_STATEMENTS) == set(PLATFORM_QUERY_IDS)
    assert len(CASES) == 7
    assert {m.statement for m in MUTANTS} == set(PLATFORM_QUERY_IDS)  # every statement has a mutant


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.statement)
async def test_a_platform_statement_run_for_one_tenant_changes_only_that_tenants_nodes(
    case: Case,
    registry: Neo4jTenantRegistry,
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed_world(registry, neo4j_driver, with_a=not case.creates_a)
    before = await _seen(neo4j_driver)

    await case.own(registry)

    after = await _seen(neo4j_driver)
    assert after.others == before.others, "a node that is not A's changed"
    assert after.links == before.links
    assert after.own != before.own or case.statement == "Q-TENANT-REG-NUMBERS"  # it did its work


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.statement)
async def test_a_platform_statement_given_a_value_of_another_tenant_changes_nothing(
    case: Case, registry: Neo4jTenantRegistry, neo4j_driver: AsyncDriver
) -> None:
    await _seed_world(registry, neo4j_driver, with_a=True)
    await registry.mark_number_tested(B, NUMBER_B, NOW)
    before = await _seen(neo4j_driver)

    if case.refused is None:
        answer = await case.foreign(registry)
        assert answer in (False, ())  # a stale save, or a read of a tenant nobody created
    else:
        with pytest.raises(case.refused):
            await case.foreign(registry)

    assert await _seen(neo4j_driver) == before  # not B's nodes, not A's, not a link


async def test_a_read_of_one_tenants_numbers_never_lists_the_others(
    world: Neo4jTenantRegistry,
) -> None:
    assert [n.e164 for n in await world.numbers(A)] == [NUMBER_A]
    assert [n.e164 for n in await world.numbers(B)] == [NUMBER_B]


async def test_the_registry_writes_leave_the_graphs_invariants_whole(
    world: Neo4jTenantRegistry, neo4j_driver: AsyncDriver
) -> None:
    """Every node still carries a tenant, except the registry labels, and no relationship joins two
    tenants: the `HAS_NUMBER` edges are between two registry nodes, which carry none."""
    await world.mark_number_tested(A, NUMBER_A, NOW)
    await world.put_number(B, _number(B, "+447700900304"))

    async def work(tx: AsyncManagedTransaction) -> tuple[list[str], list[str]]:
        return await invariant_breaks(tx)

    assert await read_tx(neo4j_driver, work) == ([], [])


# -- the mutants: the check above is not vacuous ---------------------------------------------------


@dataclass(frozen=True)
class Mutant:
    """A statement with the part that scopes it taken out, and the call it is run with. The
    original and the mutant are each run in a fresh world; they must not behave alike."""

    name: str
    statement: str
    old: str  # the text taken out of the statement (it must be in it)
    new: str  # what takes its place
    params: dict[str, Any]
    mode: str = "write"


def _props(**fields: Any) -> dict[str, Any]:
    return {"displayName": "Hijack", **fields}


MUTANTS = (
    Mutant(
        "a create that merges: it would overwrite a tenant that exists",
        "Q-TENANT-REG-CREATE",
        "CREATE (t:Tenant",
        "MERGE (t:Tenant",
        {"id": B, "props": _props()},
    ),
    Mutant(
        "a save that does not name the tenant",
        "Q-TENANT-REG-SAVE",
        "id: $id, ",
        "",
        {"id": A, "expectedEpoch": 1, "expectedStatus": "provisioning", "props": _props()},
    ),
    Mutant(
        "a save that does not compare the epoch and the status",
        "Q-TENANT-REG-SAVE",
        ", epoch: $expectedEpoch, status: $expectedStatus",
        "",
        {"id": A, "expectedEpoch": 9, "expectedStatus": "suspended", "props": _props()},
    ),
    Mutant(
        "a host set on every tenant",
        "Q-TENANT-REG-SET-HOST",
        "(t:Tenant {id: $id})",
        "(t:Tenant)",
        {"id": A, "host": "everyone.example.org"},
    ),
    Mutant(
        "a directory set on every tenant",
        "Q-TENANT-REG-SET-DIRECTORY",
        "(t:Tenant {id: $id})",
        "(t:Tenant)",
        {"id": A, "directoryId": "3c8d0f4b-6e5a-4f9d-8b1c-4d5e6f708192"},
    ),
    Mutant(
        "a number put on every tenant",
        "Q-TENANT-REG-PUT-NUMBER",
        "(t:Tenant {id: $id})",
        "(t:Tenant)",
        {"id": A, "e164": NUMBER_A2, "props": {"accountSid": SID, "status": "active"}},
    ),
    Mutant(
        "a test mark that does not name the tenant",
        "Q-TENANT-REG-MARK-TESTED",
        "(:Tenant {id: $id})",
        "(:Tenant)",
        {"id": A, "e164": NUMBER_B, "at": NOW},
    ),
    Mutant(
        "a read of numbers that does not name the tenant",
        "Q-TENANT-REG-NUMBERS",
        "(:Tenant {id: $id})",
        "(:Tenant)",
        {"id": A},
        mode="read",
    ),
)


async def _outcome(
    driver: AsyncDriver, cypher: str, mutant: Mutant, registry: Neo4jTenantRegistry
) -> tuple[Any, ...]:
    """The rows (or the class of the error) and what the graph holds afterwards, from a fresh
    world, for one statement text."""
    await _forget(driver)
    await _seed_world(registry, driver, with_a=True)

    async def work(tx: AsyncManagedTransaction) -> list[str]:
        return _canonical(await (await tx.run(cypher, mutant.params)).data())

    try:
        rows: Any = await (read_tx if mutant.mode == "read" else write_tx)(driver, work)
    except Exception as error:  # noqa: BLE001  the kind of failure is part of the outcome
        rows = type(error).__name__
    return rows, await _seen(driver)


@pytest.mark.parametrize("mutant", MUTANTS, ids=lambda m: m.name)
async def test_a_platform_statement_with_its_scoping_taken_out_is_told_apart(
    mutant: Mutant, registry: Neo4jTenantRegistry, neo4j_driver: AsyncDriver
) -> None:
    original = REGISTRY.get(mutant.statement)
    assert mutant.old in original.cypher, "the statement changed: update the mutant"
    mutated = original.cypher.replace(mutant.old, mutant.new, 1)
    assert mutated != original.cypher

    real_rows, real_seen = await _outcome(neo4j_driver, original.cypher, mutant, registry)
    leaky_rows, leaky_seen = await _outcome(neo4j_driver, mutated, mutant, registry)

    # The real statement, given a value that is not A's, touches nothing that is not A's.
    fresh_others = await _seen_after_seed(registry, neo4j_driver)
    assert real_seen.others == fresh_others.others and real_seen.links == fresh_others.links
    # And the mutant does not behave like it: another tenant's node, a link, the rows or the
    # answer (an error) is different.
    assert (leaky_rows, leaky_seen.others, leaky_seen.links) != (
        real_rows,
        real_seen.others,
        real_seen.links,
    ), f"the check cannot tell {mutant.name} from the statement"


async def _seen_after_seed(registry: Neo4jTenantRegistry, driver: AsyncDriver) -> Seen:
    await _forget(driver)
    await _seed_world(registry, driver, with_a=True)
    return await _seen(driver)


@pytest.mark.parametrize("mutant", MUTANTS, ids=lambda m: m.name)
async def test_a_changed_platform_statement_is_refused_at_registration(mutant: Mutant) -> None:
    """The digest pin: the registry will not take a statement whose text is not the pinned one, so
    a mutant cannot get into the production registry by being called what the original is called."""
    original = REGISTRY.get(mutant.statement)
    scratch = QueryRegistry()
    with pytest.raises(ValueError, match="pinned"):
        scratch.register(
            NamedQuery(
                id=original.id,
                cypher=original.cypher.replace(mutant.old, mutant.new, 1),
                mode=original.mode,
                scope="platform",
            )
        )
