"""The platform's own records without a database (TEN-075): the platform audit chain, the
support-access tickets and the registry's list and detail.

The connection is a recording stand-in (`tests/support/registry_connection.py`): it answers each
platform statement by id and records what was sent. The behaviour on a real Neo4j is
`tests/integration/graph_store/test_platform_records.py`.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.platform_audit import (
    GENESIS_SCOPE,
    Neo4jPlatformAudit,
    entry_json,
    record_from_properties,
)
from diucs.adapters.outbound.graph_store.support_ticket_store import (
    Neo4jSupportTickets,
    ticket_from_properties,
    ticket_properties,
)
from diucs.adapters.outbound.graph_store.tenant_registry import Neo4jTenantRegistry
from diucs.application.ports.outbound.audit import chain_hash_over, genesis_hash_for
from diucs.application.ports.outbound.platform_audit import PlatformAuditEntry
from diucs.application.ports.outbound.tenants import TenantRecordInvalid
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.model.tenant import TenantStatus
from diucs.domain.rules.support_ticket import (
    ReasonCode,
    SupportTicket,
    TicketState,
    approve,
    new_ticket,
    open_access,
)
from tests.support.registry_connection import RecordingWriteConnection
from tests.support.tenant_samples import SAMPLE_ID, make_tenant

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SUPPORT = "ref-support-person-0123456789"
HASH = "c" * 64
GENESIS = genesis_hash_for(GENESIS_SCOPE)


def _audit(connection: RecordingWriteConnection) -> Neo4jPlatformAudit:
    return Neo4jPlatformAudit(cast(Neo4jConnection, connection))


def _entry(action: str = "support-access-opened", **changes: Any) -> PlatformAuditEntry:
    base: dict[str, Any] = {
        "action": action,
        "principal_ref": SUPPORT,
        "tenant_id": "tenant-a",
        "access_id": "access-1",
        "snapshot": {"expires_at": NOW + timedelta(hours=1)},
        "at": NOW,
    }
    return PlatformAuditEntry(**{**base, **changes})


# -- the chain: what one append sends ------------------------------------------------------------


async def test_the_chain_starts_from_a_genesis_of_its_own_that_is_no_tenants() -> None:
    assert genesis_hash_for("platform") == GENESIS
    assert genesis_hash_for("default") != GENESIS and genesis_hash_for("tenant-a") != GENESIS
    assert len(GENESIS) == 64


async def test_an_append_takes_the_head_then_adds_the_link_in_one_write_transaction() -> None:
    connection = RecordingWriteConnection(
        {
            "Q-PLATFORM-AUDIT-LOCK": [{"lastSeq": 4, "lastHash": "e" * 64}],
            "Q-PLATFORM-AUDIT-APPEND": [{"seq": 5}],
        }
    )
    entry = _entry()

    await _audit(connection).append(entry)

    assert connection.ids_called() == ["Q-PLATFORM-AUDIT-LOCK", "Q-PLATFORM-AUDIT-APPEND"]
    assert {kind for _, kind, _ in connection.calls} == {"write"}
    _, _, lock = connection.calls[0]
    assert lock["id"] == "platform" and lock["genesis"] == GENESIS and lock["stamp"]
    _, _, append = connection.calls[1]
    text = entry_json(entry)
    assert append["expectedSeq"] == 4 and append["seq"] == 5
    assert append["hash"] == chain_hash_over("e" * 64, text)
    props = append["props"]
    assert props["previousHash"] == "e" * 64
    assert props["chainHash"] == append["hash"]
    assert props["entryJson"] == text
    assert (props["action"], props["principalRef"], props["forTenant"]) == (
        "support-access-opened",
        SUPPORT,
        "tenant-a",
    )


async def test_the_first_append_links_to_the_genesis() -> None:
    connection = RecordingWriteConnection(
        {
            "Q-PLATFORM-AUDIT-LOCK": [{"lastSeq": 0, "lastHash": GENESIS}],
            "Q-PLATFORM-AUDIT-APPEND": [{"seq": 1}],
        }
    )

    await _audit(connection).append(_entry())

    assert connection.calls[1][2]["props"]["previousHash"] == GENESIS
    assert connection.calls[1][2]["seq"] == 1


async def test_two_appends_use_two_lock_stamps() -> None:
    connection = RecordingWriteConnection(
        {
            "Q-PLATFORM-AUDIT-LOCK": [{"lastSeq": 0, "lastHash": GENESIS}],
            "Q-PLATFORM-AUDIT-APPEND": [{"seq": 1}],
        }
    )
    audit = _audit(connection)

    await audit.append(_entry())
    await audit.append(_entry())

    stamps = [p["stamp"] for i, _, p in connection.calls if i == "Q-PLATFORM-AUDIT-LOCK"]
    assert len(set(stamps)) == 2


async def test_an_append_that_finds_the_head_moved_raises_and_writes_nothing_more() -> None:
    connection = RecordingWriteConnection(
        {
            "Q-PLATFORM-AUDIT-LOCK": [{"lastSeq": 4, "lastHash": "e" * 64}],
            "Q-PLATFORM-AUDIT-APPEND": [],
        }
    )

    with pytest.raises(RuntimeError, match="could not be appended"):
        await _audit(connection).append(_entry())


async def test_an_entry_about_the_platform_itself_names_no_tenant() -> None:
    connection = RecordingWriteConnection(
        {
            "Q-PLATFORM-AUDIT-LOCK": [{"lastSeq": 0, "lastHash": GENESIS}],
            "Q-PLATFORM-AUDIT-APPEND": [{"seq": 1}],
        }
    )

    await _audit(connection).append(
        _entry("operator-signed-in", tenant_id=None, access_id=None, snapshot=None)
    )

    props = connection.calls[1][2]["props"]
    assert props["forTenant"] is None and props["accessId"] is None
    assert '"tenant_id":null' in props["entryJson"]


async def test_the_chain_never_sends_a_tenant_parameter() -> None:
    connection = RecordingWriteConnection(
        {
            "Q-PLATFORM-AUDIT-LOCK": [{"lastSeq": 0, "lastHash": GENESIS}],
            "Q-PLATFORM-AUDIT-APPEND": [{"seq": 1}],
            "Q-PLATFORM-AUDIT-ENTRIES": [],
        }
    )
    audit = _audit(connection)
    await audit.append(_entry())
    await audit.entries(0, 10)

    for _, _, parameters in connection.calls:
        assert "tenant" not in parameters


def test_a_naive_time_is_refused_and_an_entry_hashes_the_same_text_every_time() -> None:
    with pytest.raises(ValidationFailed):
        entry_json(_entry(at=datetime(2026, 10, 30, 9, 0)))
    assert entry_json(_entry()) == entry_json(_entry())
    assert entry_json(_entry()) != entry_json(_entry(access_id="access-2"))


# -- the chain: reading it back ------------------------------------------------------------------


def _links(entries: list[PlatformAuditEntry]) -> list[dict[str, Any]]:
    """The properties of a well-formed chain of these entries, as the graph would hold them."""
    previous, links = GENESIS, []
    for seq, entry in enumerate(entries, start=1):
        text = entry_json(entry)
        chain = chain_hash_over(previous, text)
        links.append(
            {
                "seq": seq,
                "action": entry.action,
                "principalRef": entry.principal_ref,
                "forTenant": entry.tenant_id,
                "accessId": entry.access_id,
                "previousHash": previous,
                "chainHash": chain,
                "entryJson": text,
            }
        )
        previous = chain
    return links


ENTRIES = [
    _entry("support-ticket-requested", access_id=None, snapshot={"ticket": "st-1"}),
    _entry("support-access-opened"),
    _entry("operator-signed-in", tenant_id=None, access_id=None, snapshot=None),
]


def _head(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"lastSeq": len(links), "lastHash": links[-1]["chainHash"]}]


def _read_connection(
    links: list[dict[str, Any]], head: list[dict[str, Any]] | None = None
) -> RecordingWriteConnection:
    return RecordingWriteConnection(
        {
            "Q-PLATFORM-AUDIT-HEAD": _head(links) if head is None else head,
            "Q-PLATFORM-AUDIT-ENTRIES": [{"entry": link} for link in links],
        }
    )


async def test_a_link_reads_back_as_the_entry_the_chain_hashed() -> None:
    links = _links(ENTRIES)

    record = record_from_properties(links[1])

    assert (record.seq, record.action, record.principal_ref) == (
        2,
        "support-access-opened",
        SUPPORT,
    )
    assert (record.tenant_id, record.access_id, record.at) == ("tenant-a", "access-1", NOW)
    assert record.snapshot == {"expires_at": "2026-10-30T10:00:00.000000Z"}
    assert record.previous_hash == links[0]["chainHash"]


async def test_entries_ask_for_the_page_after_a_sequence() -> None:
    links = _links(ENTRIES)
    connection = _read_connection(links)

    records = await _audit(connection).entries(1, 50)

    assert [r.seq for r in records] == [1, 2, 3]
    _, kind, parameters = connection.calls[0]
    assert kind == "read" and parameters == {"afterSeq": 1, "limit": 50}


@pytest.mark.parametrize(("after", "limit"), [(-1, 10), (0, 0), (0, 201), ("0", 10), (0, None)])
async def test_a_page_that_is_not_a_page_is_refused_before_anything_is_sent(
    after: Any, limit: Any
) -> None:
    connection = RecordingWriteConnection()

    with pytest.raises(ValidationFailed):
        await _audit(connection).entries(after, limit)

    assert connection.calls == []


async def test_a_whole_chain_verifies() -> None:
    assert await _audit(_read_connection(_links(ENTRIES))).verify() is True


async def test_an_empty_chain_verifies_and_a_head_with_no_links_does_not() -> None:
    empty = RecordingWriteConnection({"Q-PLATFORM-AUDIT-HEAD": [], "Q-PLATFORM-AUDIT-ENTRIES": []})
    assert await _audit(empty).verify() is True
    headed = RecordingWriteConnection(
        {
            "Q-PLATFORM-AUDIT-HEAD": [{"lastSeq": 2, "lastHash": "f" * 64}],
            "Q-PLATFORM-AUDIT-ENTRIES": [],
        }
    )
    assert await _audit(headed).verify() is False


async def test_an_edited_removed_reordered_or_inserted_link_breaks_the_chain() -> None:
    links = _links(ENTRIES)
    edited = [dict(link) for link in links]
    edited[1]["entryJson"] = edited[1]["entryJson"].replace("access-1", "access-9")
    property_changed = [dict(link) for link in links]
    property_changed[1]["forTenant"] = "tenant-b"
    removed_middle = [links[0], links[2]]
    removed_tail = links[:2]
    reordered = [links[1], links[0], links[2]]
    inserted = [links[0], _links([ENTRIES[0], _entry("x-inserted"), ENTRIES[1]])[1], *links[1:]]

    for broken in (edited, property_changed, removed_middle, reordered, inserted):
        assert await _audit(_read_connection(broken, _head(links))).verify() is False
    assert await _audit(_read_connection(removed_tail, _head(links))).verify() is False


async def test_a_chain_hashed_from_another_genesis_does_not_verify() -> None:
    other_start = genesis_hash_for("tenant-a")
    text = entry_json(ENTRIES[0])
    link = {
        "seq": 1,
        "action": ENTRIES[0].action,
        "principalRef": SUPPORT,
        "forTenant": "tenant-a",
        "accessId": None,
        "previousHash": other_start,
        "chainHash": chain_hash_over(other_start, text),
        "entryJson": text,
    }

    connection = _read_connection([link], [{"lastSeq": 1, "lastHash": link["chainHash"]}])

    assert await _audit(connection).verify() is False


# -- the tickets ---------------------------------------------------------------------------------


def _ticket(**changes: Any) -> SupportTicket:
    base = new_ticket(
        ticket_id="st-1",
        tenant_id="tenant-a",
        requested_by_ref=SUPPORT,
        reason_code=ReasonCode.CONFIGURATION,
        reason="The tenant cannot see its own wording page.",
        reference="HD-7",
        now=NOW,
    )
    return replace(base, **changes) if changes else base


def _tickets(connection: RecordingWriteConnection) -> Neo4jSupportTickets:
    return Neo4jSupportTickets(cast(Neo4jConnection, connection))


def _node(ticket: SupportTicket) -> dict[str, Any]:
    return {"id": ticket.id, **ticket_properties(ticket)}


def test_a_ticket_node_holds_the_platform_facts_and_nothing_secret_or_personal() -> None:
    ticket = approve(
        _ticket(),
        decided_by_ref="admin-ref-0001",
        grant_hash=HASH,
        grant_expires_at=NOW + timedelta(hours=4),
        now=NOW + timedelta(minutes=5),
    )

    props = ticket_properties(ticket)

    assert "id" not in props and "tenantId" not in props
    assert props["forTenant"] == "tenant-a" and props["requestedBy"] == SUPPORT
    assert props["state"] == "approved" and props["grantHash"] == HASH
    assert props["accessId"] is None and props["endedAt"] is None
    assert not any("code" in key.lower().replace("reasoncode", "") for key in props)


def test_every_state_of_a_ticket_reads_back_equal() -> None:
    approved = approve(
        _ticket(),
        decided_by_ref="admin-ref-0001",
        grant_hash=HASH,
        grant_expires_at=NOW + timedelta(hours=4),
        now=NOW + timedelta(minutes=5),
    )
    opened = open_access(
        approved,
        access_id="access-1",
        grant_hash=HASH,
        opened_at=NOW + timedelta(minutes=9),
        expires_at=NOW + timedelta(minutes=69),
    )

    for ticket in (_ticket(), approved, opened):
        assert ticket_from_properties(_node(ticket)) == ticket


def test_a_node_the_domain_refuses_is_a_registry_fault_with_a_fixed_message() -> None:
    good = _node(_ticket())
    for bad in (
        {**good, "state": "approved"},  # approved with no code
        {**good, "forTenant": "Not A Tenant"},
        {**good, "reasonCode": "something-else"},
        {**good, "requestedAt": "yesterday"},
        {key: value for key, value in good.items() if key != "reason"},
    ):
        with pytest.raises(TenantRecordInvalid) as refused:
            ticket_from_properties(bad)
        assert "tenant-a" not in str(refused.value) and SUPPORT not in str(refused.value)


async def test_adding_a_ticket_sends_the_id_and_the_properties() -> None:
    connection = RecordingWriteConnection({"Q-SUPPORT-TICKET-ADD": [{"id": "st-1"}]})

    await _tickets(connection).add(_ticket())

    [(query_id, kind, parameters)] = connection.calls
    assert (query_id, kind) == ("Q-SUPPORT-TICKET-ADD", "write")
    assert parameters["id"] == "st-1" and parameters["props"]["forTenant"] == "tenant-a"


async def test_an_id_that_exists_is_a_conflict_with_a_fixed_message() -> None:
    connection = RecordingWriteConnection({"Q-SUPPORT-TICKET-ADD": ConstraintError("x")})

    with pytest.raises(Conflict) as refused:
        await _tickets(connection).add(_ticket())

    assert "st-1" not in str(refused.value)


async def test_the_tenants_side_reads_by_the_tenant_it_is_given_and_the_other_by_the_person() -> (
    None
):
    node = _node(_ticket())
    connection = RecordingWriteConnection(
        {
            "Q-SUPPORT-TICKET-OF-TENANT": [{"ticket": node}],
            "Q-SUPPORT-TICKET-OF-PRINCIPAL": [{"ticket": node}],
            "Q-SUPPORT-TICKETS-OF-TENANT": [{"ticket": node}],
            "Q-SUPPORT-TICKETS-OF-PRINCIPAL": [{"ticket": node}],
        }
    )
    tickets = _tickets(connection)

    assert await tickets.for_tenant("tenant-a", "st-1") == _ticket()
    assert await tickets.for_principal(SUPPORT, "st-1") == _ticket()
    assert await tickets.of_tenant("tenant-a", 20) == [_ticket()]
    assert await tickets.of_principal(SUPPORT, 20) == [_ticket()]

    sent = {query_id: parameters for query_id, _, parameters in connection.calls}
    assert sent["Q-SUPPORT-TICKET-OF-TENANT"] == {"id": "st-1", "forTenant": "tenant-a"}
    assert sent["Q-SUPPORT-TICKET-OF-PRINCIPAL"] == {"id": "st-1", "requestedBy": SUPPORT}
    assert sent["Q-SUPPORT-TICKETS-OF-TENANT"] == {"forTenant": "tenant-a", "limit": 20}
    assert sent["Q-SUPPORT-TICKETS-OF-PRINCIPAL"] == {"requestedBy": SUPPORT, "limit": 20}
    assert {kind for _, kind, _ in connection.calls} == {"read"}


async def test_no_row_is_no_ticket_and_two_rows_are_a_registry_fault() -> None:
    node = _node(_ticket())
    none = RecordingWriteConnection({"Q-SUPPORT-TICKET-OF-TENANT": []})
    two = RecordingWriteConnection(
        {"Q-SUPPORT-TICKET-OF-TENANT": [{"ticket": node}, {"ticket": node}]}
    )

    assert await _tickets(none).for_tenant("tenant-a", "st-1") is None
    with pytest.raises(TenantRecordInvalid):
        await _tickets(two).for_tenant("tenant-a", "st-1")


async def test_a_tenant_id_that_is_not_one_is_refused_before_anything_is_sent() -> None:
    connection = RecordingWriteConnection()

    for call in (
        _tickets(connection).for_tenant("net-alliance", "st-1"),
        _tickets(connection).of_tenant("Not A Tenant", 5),
    ):
        with pytest.raises(ValidationFailed):
            await call
    assert connection.calls == []


@pytest.mark.parametrize("limit", [0, 201, -1, "5", None])
async def test_a_list_has_a_bound(limit: Any) -> None:
    connection = RecordingWriteConnection()

    with pytest.raises(ValidationFailed):
        await _tickets(connection).of_tenant("tenant-a", limit)
    with pytest.raises(ValidationFailed):
        await _tickets(connection).of_principal(SUPPORT, limit)

    assert connection.calls == []


async def test_a_move_is_a_compare_and_set_on_the_tenant_and_the_state_read() -> None:
    approved = approve(
        _ticket(),
        decided_by_ref="admin-ref-0001",
        grant_hash=HASH,
        grant_expires_at=NOW + timedelta(hours=4),
        now=NOW + timedelta(minutes=5),
    )
    won = RecordingWriteConnection({"Q-SUPPORT-TICKET-MOVE": [{"id": "st-1"}]})
    lost = RecordingWriteConnection({"Q-SUPPORT-TICKET-MOVE": []})

    assert await _tickets(won).move(approved, TicketState.PENDING) is True
    assert await _tickets(lost).move(approved, TicketState.PENDING) is False

    [(_, kind, parameters)] = won.calls
    assert kind == "write"
    assert parameters["id"] == "st-1" and parameters["forTenant"] == "tenant-a"
    assert parameters["expectedState"] == "pending"
    assert parameters["props"]["state"] == "approved"


# -- the registry's list and detail --------------------------------------------------------------


def _registry(connection: RecordingWriteConnection) -> Neo4jTenantRegistry:
    return Neo4jTenantRegistry(cast(Neo4jConnection, connection))


def _node_of(tenant_id: str, **extra: Any) -> dict[str, Any]:
    from diucs.adapters.outbound.graph_store.tenant_registry import tenant_write_properties

    return {
        "id": tenant_id,
        **tenant_write_properties(make_tenant(TenantStatus.ACTIVE, id=tenant_id)),
        **extra,
    }


async def test_the_list_reads_every_tenant_with_its_host_and_directory() -> None:
    guid = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
    connection = RecordingWriteConnection(
        {
            "Q-TENANT-REG-LIST": [
                {"tenant": _node_of("tenant-a", host="a.example.org", entraDirectoryId=guid)},
                {"tenant": _node_of("tenant-b")},
            ]
        }
    )

    listed = await _registry(connection).list_all()

    assert [item.tenant.id for item in listed] == ["tenant-a", "tenant-b"]
    assert (listed[0].host, listed[0].directory_id) == ("a.example.org", guid)
    assert (listed[1].host, listed[1].directory_id) == (None, None)
    assert connection.calls[0][:2] == ("Q-TENANT-REG-LIST", "read")
    assert connection.calls[0][2] == {}


async def test_the_detail_reads_one_tenant_and_none_is_none() -> None:
    connection = RecordingWriteConnection({"Q-TENANT-REG-GET": [{"tenant": _node_of(SAMPLE_ID)}]})
    empty = RecordingWriteConnection({"Q-TENANT-REG-GET": []})

    found = await _registry(connection).detail(SAMPLE_ID)

    assert found is not None and found.tenant.id == SAMPLE_ID
    assert connection.calls[0][2] == {"id": SAMPLE_ID}
    assert await _registry(empty).detail(SAMPLE_ID) is None


async def test_a_detail_for_an_id_that_is_not_a_tenant_id_sends_nothing() -> None:
    connection = RecordingWriteConnection()

    with pytest.raises(ValidationFailed):
        await _registry(connection).detail("net-alliance")

    assert connection.calls == []
