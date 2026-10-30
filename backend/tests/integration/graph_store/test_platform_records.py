"""The platform's own records on a real Neo4j (TEN-075): the platform audit chain, the
support-access tickets and the registry's list and detail.

These nodes carry no tenant (DEC-132), so the module runs on a private container, whatever the
session's mode (`schema`), emptied for each test. What is proved that the unit tests cannot:

- the chain is one chain: appends made at once get a place each (no two share a sequence), every
  link hashes from the one before, an edited, removed or reordered link or a head that moved breaks
  `verify`, and the constraints refuse a second link in a place;
- a ticket is read and moved only by the tenant it names and only by the person who asked: another
  tenant's ticket and another person's read as not found, a move that names the wrong tenant writes
  nothing, and of two decisions made at once on one ticket exactly one stands;
- no platform node carries a tenant, and the start-up invariant check does not count one as a node
  that lost its tenant;
- the registry lists every tenant whatever its status with its host and directory.

Written in build wave 9 (bundle W9C) and run there. Synthetic values only.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.invariants import Neo4jTenantInvariants
from diucs.adapters.outbound.graph_store.platform_audit import (
    GENESIS_SCOPE,
    Neo4jPlatformAudit,
    entry_json,
)
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.support_ticket_store import (
    Neo4jSupportTickets,
    ticket_properties,
)
from diucs.adapters.outbound.graph_store.tenant_registry import Neo4jTenantRegistry
from diucs.application.ports.outbound.audit import chain_hash_over, genesis_hash_for
from diucs.application.ports.outbound.platform_audit import PlatformAuditEntry
from diucs.domain.errors import Conflict
from diucs.domain.model.tenant import OrganisationType, Tenant, TenantStatus
from diucs.domain.rules.support_ticket import (
    EndedBy,
    ReasonCode,
    SupportTicket,
    TicketState,
    approve,
    end_access,
    new_ticket,
    open_access,
    refuse,
    revoke,
)
from tests.support.neo4j import ThrowawayNeo4j, read_tx, wipe_all, write_tx

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.schema]

A, B = "plat-alpha", "plat-bravo"
SUPPORT = "ref-support-person-0123456789"
OTHER_SUPPORT = "ref-another-support-9876543210"
ADMIN = "admin-ref-0001"
HASH = "c" * 64
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
GUID = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
REASON = "A reporter cannot sign in on the tenant host."


@dataclass
class World:
    driver: AsyncDriver
    connection: Neo4jConnection
    audit: Neo4jPlatformAudit
    tickets: Neo4jSupportTickets
    registry: Neo4jTenantRegistry


@pytest_asyncio.fixture(loop_scope="session")
async def world(own_neo4j: tuple[ThrowawayNeo4j, AsyncDriver]) -> AsyncIterator[World]:
    container, driver = own_neo4j
    await wipe_all(driver)
    connection = Neo4jConnection(container.uri, container.user, container.password)
    await connection.open()
    try:
        yield World(
            driver,
            connection,
            Neo4jPlatformAudit(connection),
            Neo4jSupportTickets(connection),
            Neo4jTenantRegistry(connection),
        )
    finally:
        await connection.close()
        await wipe_all(driver)


def _entry(n: int, **changes: Any) -> PlatformAuditEntry:
    base: dict[str, Any] = {
        "action": f"support-access-step-{n}",
        "principal_ref": SUPPORT,
        "tenant_id": A,
        "access_id": f"access-{n}",
        "snapshot": {"n": n, "expires_at": NOW + timedelta(hours=1)},
        "at": NOW + timedelta(minutes=n),
    }
    return PlatformAuditEntry(**{**base, **changes})


async def _run(world: World, cypher: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(cypher, **params)).data()

    return await write_tx(world.driver, work)


async def _read(world: World, cypher: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(cypher, **params)).data()

    return await read_tx(world.driver, work)


# -- the platform audit chain --------------------------------------------------------------------


async def test_an_empty_chain_verifies_and_the_first_link_starts_from_the_platforms_genesis(
    world: World,
) -> None:
    assert await world.audit.verify() is True
    assert await world.audit.entries(0, 10) == []

    await world.audit.append(_entry(1))

    (record,) = await world.audit.entries(0, 10)
    assert record.seq == 1
    assert record.previous_hash == genesis_hash_for(GENESIS_SCOPE)
    assert record.chain_hash == chain_hash_over(record.previous_hash, entry_json(_entry(1)))
    assert await world.audit.verify() is True


async def test_each_link_hashes_from_the_one_before_and_reads_back_as_written(world: World) -> None:
    entries = [_entry(n) for n in range(1, 5)]
    for entry in entries:
        await world.audit.append(entry)

    records = await world.audit.entries(0, 10)

    assert [r.seq for r in records] == [1, 2, 3, 4]
    for before, after in zip(records, records[1:], strict=False):
        assert after.previous_hash == before.chain_hash
    assert [(r.action, r.principal_ref, r.tenant_id, r.access_id) for r in records] == [
        (e.action, e.principal_ref, e.tenant_id, e.access_id) for e in entries
    ]
    assert records[0].at == NOW + timedelta(minutes=1)
    assert records[0].snapshot == {"n": 1, "expires_at": "2026-10-30T10:00:00.000000Z"}
    assert [r.seq for r in await world.audit.entries(2, 10)] == [3, 4]
    assert [r.seq for r in await world.audit.entries(0, 2)] == [1, 2]
    assert await world.audit.verify() is True


async def test_an_entry_about_the_platform_itself_names_no_tenant(world: World) -> None:
    await world.audit.append(
        _entry(1, action="operator-signed-in", tenant_id=None, access_id=None, snapshot=None)
    )

    (record,) = await world.audit.entries(0, 10)
    rows = await _read(world, "MATCH (e:PlatformAuditEntry) RETURN properties(e) AS p")
    assert record.tenant_id is None and record.access_id is None
    assert "forTenant" not in rows[0]["p"] and "accessId" not in rows[0]["p"]


async def test_appends_made_at_once_each_get_a_place_and_the_chain_still_verifies(
    world: World,
) -> None:
    await asyncio.gather(*(world.audit.append(_entry(n)) for n in range(1, 13)))

    records = await world.audit.entries(0, 50)

    assert [r.seq for r in records] == list(range(1, 13))
    assert {r.action for r in records} == {f"support-access-step-{n}" for n in range(1, 13)}
    assert await world.audit.verify() is True


async def test_a_failed_append_leaves_the_chain_as_it_was(world: World) -> None:
    await world.audit.append(_entry(1))

    with pytest.raises(Exception, match="timezone-aware"):
        await world.audit.append(_entry(2, at=datetime(2026, 10, 30, 9, 0)))

    assert [r.seq for r in await world.audit.entries(0, 10)] == [1]
    assert await world.audit.verify() is True


async def test_an_edited_removed_or_moved_link_breaks_the_chain(world: World) -> None:
    for n in range(1, 5):
        await world.audit.append(_entry(n))
    assert await world.audit.verify() is True

    await _run(
        world,
        "MATCH (e:PlatformAuditEntry {seq: 2}) "
        "SET e.entryJson = replace(e.entryJson, 'access-2', 'ZZZZZZZZ')",
    )
    assert await world.audit.verify() is False
    await _run(
        world,
        "MATCH (e:PlatformAuditEntry {seq: 2}) "
        "SET e.entryJson = replace(e.entryJson, 'ZZZZZZZZ', 'access-2')",
    )
    assert await world.audit.verify() is True

    await _run(world, "MATCH (e:PlatformAuditEntry {seq: 3}) SET e.forTenant = 'someone-else'")
    assert await world.audit.verify() is False
    await _run(world, f"MATCH (e:PlatformAuditEntry {{seq: 3}}) SET e.forTenant = '{A}'")
    assert await world.audit.verify() is True

    await _run(world, "MATCH (e:PlatformAuditEntry {seq: 4}) DETACH DELETE e")
    assert await world.audit.verify() is False  # the head names a link that is gone


async def test_a_removed_middle_link_and_a_moved_head_break_the_chain(world: World) -> None:
    for n in range(1, 5):
        await world.audit.append(_entry(n))

    await _run(world, "MATCH (e:PlatformAuditEntry {seq: 2}) DETACH DELETE e")
    assert await world.audit.verify() is False

    other = world
    await _run(other, "MATCH (e:PlatformAuditEntry) DETACH DELETE e")
    await other.audit.append(_entry(1))
    await _run(other, "MATCH (h:PlatformAuditHead) SET h.lastSeq = 7")
    assert await other.audit.verify() is False


async def test_two_links_cannot_share_a_place_and_the_head_is_one(world: World) -> None:
    await world.audit.append(_entry(1))

    with pytest.raises(ConstraintError):
        await _run(world, "CREATE (e:PlatformAuditEntry {seq: 1})")
    with pytest.raises(ConstraintError):
        await _run(world, "CREATE (h:PlatformAuditHead {id: 'platform'})")


# -- the tickets ---------------------------------------------------------------------------------


def _ticket(
    ticket_id: str = "st-1", tenant: str = A, principal: str = SUPPORT, at: datetime = NOW
) -> SupportTicket:
    return new_ticket(
        ticket_id=ticket_id,
        tenant_id=tenant,
        requested_by_ref=principal,
        reason_code=ReasonCode.SERVICE_FAULT,
        reason=REASON,
        reference="HD-1042",
        now=at,
    )


def _approved(ticket: SupportTicket) -> SupportTicket:
    return approve(
        ticket,
        decided_by_ref=ADMIN,
        grant_hash=HASH,
        grant_expires_at=ticket.requested_at + timedelta(hours=4),
        now=ticket.requested_at + timedelta(minutes=5),
    )


async def test_a_ticket_reads_back_equal_in_every_state(world: World) -> None:
    pending = _ticket("st-1")
    approved = _approved(_ticket("st-2"))
    opened = open_access(
        _approved(_ticket("st-3")),
        access_id="access-3",
        grant_hash=HASH,
        opened_at=NOW + timedelta(minutes=9),
        expires_at=NOW + timedelta(minutes=69),
    )
    ended = end_access(
        open_access(
            _approved(_ticket("st-6")),
            access_id="access-6",
            grant_hash=HASH,
            opened_at=NOW + timedelta(minutes=9),
            expires_at=NOW + timedelta(minutes=69),
        ),
        by=EndedBy.SUPPORT,
        now=NOW + timedelta(minutes=30),
    )
    revoked = revoke(_approved(_ticket("st-4")), now=NOW + timedelta(minutes=20))
    refused = refuse(_ticket("st-5"), decided_by_ref=ADMIN, now=NOW + timedelta(minutes=2))
    every = [pending, approved, opened, ended, revoked, refused]

    for ticket in every:
        await world.tickets.add(ticket)

    for ticket in every:
        assert await world.tickets.for_tenant(A, ticket.id) == ticket
        assert await world.tickets.for_principal(SUPPORT, ticket.id) == ticket


async def test_the_node_carries_no_tenant_no_code_and_no_name(world: World) -> None:
    await world.tickets.add(_approved(_ticket()))

    (row,) = await _read(world, "MATCH (t:SupportAccessTicket) RETURN properties(t) AS p")

    props = row["p"]
    assert "tenantId" not in props and props["forTenant"] == A and props["requestedBy"] == SUPPORT
    assert props["grantHash"] == HASH
    assert not any(key in props for key in ("code", "supportCode", "name", "phone"))


async def test_a_second_ticket_with_the_same_id_is_a_conflict(world: World) -> None:
    await world.tickets.add(_ticket())

    with pytest.raises(Conflict):
        await world.tickets.add(replace(_ticket(), reason="Another sentence for the same id."))

    assert (await world.tickets.for_tenant(A, "st-1")) == _ticket()


async def test_a_tenant_and_a_person_see_only_their_own_tickets(world: World) -> None:
    await world.tickets.add(_ticket("st-a1", A, SUPPORT, NOW))
    await world.tickets.add(_ticket("st-a2", A, OTHER_SUPPORT, NOW + timedelta(minutes=1)))
    await world.tickets.add(_ticket("st-b1", B, SUPPORT, NOW + timedelta(minutes=2)))

    assert [t.id for t in await world.tickets.of_tenant(A, 10)] == ["st-a2", "st-a1"]
    assert [t.id for t in await world.tickets.of_tenant(B, 10)] == ["st-b1"]
    assert [t.id for t in await world.tickets.of_principal(SUPPORT, 10)] == ["st-b1", "st-a1"]
    assert [t.id for t in await world.tickets.of_principal(OTHER_SUPPORT, 10)] == ["st-a2"]
    assert [t.id for t in await world.tickets.of_tenant(A, 1)] == ["st-a2"]
    assert await world.tickets.for_tenant(B, "st-a1") is None
    assert await world.tickets.for_tenant(A, "st-b1") is None
    assert await world.tickets.for_principal(OTHER_SUPPORT, "st-a1") is None
    assert await world.tickets.of_tenant("plat-nobody", 10) == []


async def test_a_move_is_a_compare_and_set_on_the_tenant_and_the_state_read(world: World) -> None:
    pending = _ticket()
    await world.tickets.add(pending)
    approved = _approved(pending)

    stale = await world.tickets.move(approved, TicketState.APPROVED)  # it is not approved yet
    wrong_tenant = await world.tickets.move(replace(approved, tenant_id=B), TicketState.PENDING)
    won = await world.tickets.move(approved, TicketState.PENDING)
    again = await world.tickets.move(approved, TicketState.PENDING)

    assert (stale, wrong_tenant, won, again) == (False, False, True, False)
    assert await world.tickets.for_tenant(A, "st-1") == approved


async def test_of_two_decisions_made_at_once_exactly_one_stands(world: World) -> None:
    pending = _ticket()
    await world.tickets.add(pending)
    approved = _approved(pending)
    refused = refuse(pending, decided_by_ref="admin-ref-0002", now=NOW + timedelta(minutes=5))

    outcomes = await asyncio.gather(
        world.tickets.move(approved, TicketState.PENDING),
        world.tickets.move(refused, TicketState.PENDING),
    )

    assert sorted(outcomes) == [False, True]
    stored = await world.tickets.for_tenant(A, "st-1")
    assert stored in (approved, refused)


async def test_a_move_that_clears_a_field_removes_the_property(world: World) -> None:
    ticket = _approved(_ticket())
    await world.tickets.add(ticket)
    revoked = revoke(ticket, now=NOW + timedelta(minutes=30))

    assert await world.tickets.move(revoked, TicketState.APPROVED)

    (row,) = await _read(world, "MATCH (t:SupportAccessTicket) RETURN properties(t) AS p")
    assert row["p"]["state"] == "revoked" and row["p"]["endedBy"] == "tenant-admin"
    assert await world.tickets.for_tenant(A, "st-1") == revoked


# -- no tenant on a platform node, and the invariant check ---------------------------------------


async def test_no_platform_node_carries_a_tenant_and_the_invariant_check_does_not_count_one(
    world: World,
) -> None:
    await world.audit.append(_entry(1))
    await world.tickets.add(_ticket())

    rows = await _read(
        world,
        "MATCH (n) WHERE n:PlatformAuditHead OR n:PlatformAuditEntry OR n:SupportAccessTicket "
        "RETURN labels(n) AS labels, n.tenantId AS tenant",
    )
    report = await Neo4jTenantInvariants(world.connection).check()

    assert len(rows) == 3 and all(row["tenant"] is None for row in rows)
    assert report.ok, report


# -- the registry's list and detail --------------------------------------------------------------


def _tenant(
    tenant_id: str, status: TenantStatus = TenantStatus.PROVISIONING, **fields: Any
) -> Tenant:
    base: dict[str, Any] = {
        "id": tenant_id,
        "display_name": f"Org {tenant_id}",
        "legal_name": f"Org {tenant_id} Ltd",
        "organisation_type": OrganisationType.OTHER,
        "status": TenantStatus.PROVISIONING,
        "created_at": NOW,
    }
    return Tenant(**{**base, **fields})


async def test_the_list_is_every_tenant_whatever_its_status_with_its_host_and_directory(
    world: World,
) -> None:
    await world.registry.create(_tenant(B))
    await world.registry.create(_tenant(A))
    await world.registry.set_host(A, "alpha.example.org")
    await world.registry.set_entra_directory(A, GUID)
    created = _tenant(A)
    assert await world.registry.save(
        replace(created, status=TenantStatus.ACTIVE, activated_at=NOW),
        expected_epoch=1,
        expected_status=TenantStatus.PROVISIONING,
    )

    listed = await world.registry.list_all()

    assert [item.tenant.id for item in listed] == [A, B]
    assert [item.tenant.status for item in listed] == [
        TenantStatus.ACTIVE,
        TenantStatus.PROVISIONING,
    ]
    assert (listed[0].host, listed[0].directory_id) == ("alpha.example.org", GUID)
    assert (listed[1].host, listed[1].directory_id) == (None, None)
    detail = await world.registry.detail(A)
    assert detail == listed[0]
    assert await world.registry.detail("plat-nobody") is None


# -- the mutants: the checks above are not vacuous -----------------------------------------------
#
# Each platform statement is run as it is, and again with the part that scopes it taken out, on the
# same world (two tenants' tickets, two support persons, a chain of two links). The two must not
# behave alike, so a test that cannot tell a leaking statement from the real one fails here. The
# digest pin (`test_platform_statements.py`) is what keeps a mutant out of the production registry.


@dataclass(frozen=True)
class Mutant:
    name: str
    statement: str
    old: str
    new: str
    params: dict[str, Any]
    foreign: str | None = None
    """What a read must never answer (the other tenant's or person's row), when the statement is a
    read: the real statement leaves it out and the mutant gives it."""


def _mutants() -> list[Mutant]:
    other = _ticket("st-b", B, OTHER_SUPPORT)
    props = ticket_properties(replace(other, reason="Hijacked by a statement that leaks."))
    return [
        Mutant(
            "a ticket read that does not name the tenant",
            "Q-SUPPORT-TICKET-OF-TENANT",
            ", forTenant: $forTenant",
            "",
            {"id": "st-b", "forTenant": A},
            foreign="st-b",
        ),
        Mutant(
            "a ticket read that does not name the person",
            "Q-SUPPORT-TICKET-OF-PRINCIPAL",
            ", requestedBy: $requestedBy",
            "",
            {"id": "st-b", "requestedBy": SUPPORT},
            foreign="st-b",
        ),
        Mutant(
            "a list of a tenant's tickets that does not name the tenant",
            "Q-SUPPORT-TICKETS-OF-TENANT",
            "{forTenant: $forTenant}",
            "",
            {"forTenant": A, "limit": 10},
            foreign="st-b",
        ),
        Mutant(
            "a list of a person's tickets that does not name the person",
            "Q-SUPPORT-TICKETS-OF-PRINCIPAL",
            "{requestedBy: $requestedBy}",
            "",
            {"requestedBy": SUPPORT, "limit": 10},
            foreign="st-b",
        ),
        Mutant(
            "a move that does not name the tenant",
            "Q-SUPPORT-TICKET-MOVE",
            ", forTenant: $forTenant",
            "",
            {"id": "st-b", "forTenant": A, "expectedState": "pending", "props": props},
        ),
        Mutant(
            "a move that does not compare the state",
            "Q-SUPPORT-TICKET-MOVE",
            ", state: $expectedState",
            "",
            {"id": "st-a", "forTenant": A, "expectedState": "approved", "props": props},
        ),
        Mutant(
            "an add that merges: it would overwrite a ticket that exists",
            "Q-SUPPORT-TICKET-ADD",
            "CREATE (t:",
            "MERGE (t:",
            {"id": "st-a", "props": props},
        ),
        Mutant(
            "a tenant read that does not name the tenant",
            "Q-TENANT-REG-GET",
            "(t:Tenant {id: $id})",
            "(t:Tenant)",
            {"id": A},
            foreign="plat-bravo",
        ),
        Mutant(
            "an append that does not compare the head",
            "Q-PLATFORM-AUDIT-APPEND",
            ", lastSeq: $expectedSeq",
            "",
            {
                "id": "platform",
                "expectedSeq": 0,
                "seq": 3,
                "hash": "d" * 64,
                "props": {"action": "x", "chainHash": "d" * 64, "previousHash": "e" * 64},
            },
        ),
    ]


async def _seed_mutant_world(world: World) -> None:
    await _run(
        world,
        "MATCH (n) WHERE n:SupportAccessTicket OR n:PlatformAuditEntry "
        "OR n:PlatformAuditHead OR n:Tenant DETACH DELETE n",
    )
    await world.registry.create(_tenant(A))
    await world.registry.create(_tenant(B))
    await world.tickets.add(_ticket("st-a", A, SUPPORT))
    await world.tickets.add(_ticket("st-b", B, OTHER_SUPPORT, NOW + timedelta(minutes=1)))
    await world.audit.append(_entry(1))
    await world.audit.append(_entry(2))


async def _world_outcome(world: World, cypher: str, mutant: Mutant) -> tuple[Any, ...]:
    await _seed_mutant_world(world)
    try:
        rows: Any = sorted(
            repr(sorted(row.items(), key=lambda item: item[0]))
            for row in await _run(world, cypher, **mutant.params)
        )
    except Exception as error:  # noqa: BLE001  the kind of failure is part of the outcome
        rows = type(error).__name__
    tickets = await _read(
        world,
        "MATCH (t:SupportAccessTicket) "
        "RETURN t.id AS id, t.state AS s, t.reason AS r ORDER BY t.id",
    )
    chain = await _read(world, "MATCH (e:PlatformAuditEntry) RETURN e.seq AS seq ORDER BY e.seq")
    head = await _read(world, "MATCH (h:PlatformAuditHead) RETURN h.lastSeq AS seq")
    return rows, tickets, chain, head


@pytest.mark.parametrize("mutant", _mutants(), ids=lambda m: m.name)
async def test_a_platform_statement_with_its_scoping_taken_out_is_told_apart(
    mutant: Mutant, world: World
) -> None:
    original = REGISTRY.get(mutant.statement)
    assert mutant.old in original.cypher, "the statement changed: update the mutant"
    mutated = original.cypher.replace(mutant.old, mutant.new, 1)
    assert mutated != original.cypher

    real = await _world_outcome(world, original.cypher, mutant)
    leaky = await _world_outcome(world, mutated, mutant)

    assert leaky != real, f"the check cannot tell {mutant.name} from the statement"
    if mutant.foreign is not None:
        # A read: the real statement never answers the other tenant's or person's row.
        assert mutant.foreign not in repr(real[0]) and mutant.foreign in repr(leaky[0])
    else:
        # A write: given another tenant's or person's value, the real statement found nothing to
        # change, or was refused by a key.
        assert real[0] in ([], "ConstraintError"), real[0]
