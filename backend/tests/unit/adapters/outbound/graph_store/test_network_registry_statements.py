"""The network registry's statements and mapping (TEN-051, DEC-541, DEC-134 item 9).

The registry is global: `Network`, `NetworkMembership`, `Grant` and `Listing` nodes carry no
`tenantId`. Eleven reads and eight writes, all on the global allowlist and pinned by digest. A read
names registry labels and no tenant. A write is a `CREATE` or a `SET` on a registry label, guarded
(a lock on the network, a check of the status expected), never a delete, a procedure, a map
assignment or a label assignment. The adapter is tried against a recording connection: what it
sends, that it sends no tenant, and what it does with the rows. The behaviour on a real Neo4j, with
data of two tenants in the same graph, is `tests/integration/graph_store/test_network_registry.py`.
"""

import re
from dataclasses import replace
from datetime import datetime
from typing import Any, cast

import pytest
from neo4j.exceptions import ConstraintError
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store import network_registry as module
from diucs.adapters.outbound.graph_store import queries as queries_module
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.network_registry import (
    Neo4jNetworkRegistry,
    grant_from_properties,
    grant_properties,
    listing_from_properties,
    listing_properties,
    membership_from_properties,
    membership_properties,
    network_from_properties,
    network_properties,
)
from diucs.adapters.outbound.graph_store.queries import (
    GLOBAL_QUERY_IDS,
    GLOBAL_STATEMENTS,
    GLOBAL_WRITE_IDS,
    REGISTRY,
    NamedQuery,
    QueryRegistry,
    statement_digest,
    statement_labels,
)
from diucs.application.ports.outbound.network import (
    NetworkRecordInvalid,
    RegisteredNetwork,
)
from diucs.domain.errors import Conflict
from diucs.domain.model.network import (
    GrantScope,
    GrantStatus,
    ListingStatus,
    MembershipStatus,
    NetworkStatus,
)
from tests.support.network_connection import NetworkConnection
from tests.support.network_samples import (
    MEMBER_B,
    MEMBER_C,
    NETWORK_ID,
    NOW,
    OWNER,
    SETTINGS,
    T0,
    make_grant,
    make_listing,
    make_member,
    make_network,
    make_owner_membership,
)

READ_IDS = {
    "Q-NETWORK-GET": {"id"},
    "Q-NETWORK-MEMBERSHIPS": {"networkId"},
    "Q-NETWORK-MEMBERSHIPS-OF": {"memberTenantId"},
    "Q-NETWORK-MEMBERSHIP-ACTIVE": {"networkId", "memberTenantId"},
    "Q-NETWORK-GRANT-GET": {"id"},
    "Q-NETWORK-GRANTS": {"networkId"},
    "Q-NETWORK-GRANTS-OF": {"grantorTenantId"},
    "Q-NETWORK-GRANT-ACTIVE-FOR": {"grantorTenantId", "scope"},
    "Q-NETWORK-LISTING-GET": {"id"},
    "Q-NETWORK-LISTINGS": {"networkId"},
    "Q-NETWORK-LISTINGS-OF": {"networkId", "sourceTenantId"},
}
NETWORK_PARAMS = {
    "id", "name", "ownerTenantId", "status", "agreementReference", "agreementVersion",
    "createdAt", "closedAt", "systemName", "pathwayName", "timeZone",
}  # fmt: skip
MEMBER_PARAMS = {
    "id", "networkId", "memberTenantId", "role", "status", "invitedAt", "joinedAt", "leftAt",
    "endReason", "acceptedAgreementReference", "acceptedAgreementVersion",
}  # fmt: skip
GRANT_PARAMS = {
    "id", "networkId", "grantorTenantId", "scope", "purpose", "version", "status", "effectiveFrom",
    "effectiveTo", "agreementReference", "agreementVersion", "allowlistVersion",
    "proposedByAccountRef", "proposedAt", "grantorApprovalAccountRef", "grantorApprovalTenantId",
    "grantorApprovalAt", "ownerApprovalAccountRef", "ownerApprovalTenantId", "ownerApprovalAt",
    "endedAt", "endedByAccountRef", "supersedesId",
}  # fmt: skip
LISTING_PARAMS = {
    "id", "networkId", "sourceTenantId", "sourceServiceId", "status", "requestedAt", "decidedAt",
    "decidedByAccountRef", "reason",
}  # fmt: skip
WRITE_IDS = {
    "Q-NETWORK-CREATE": NETWORK_PARAMS,
    "Q-NETWORK-SAVE": NETWORK_PARAMS | {"expectedStatus"},
    "Q-NETWORK-MEMBER-CREATE": MEMBER_PARAMS,
    "Q-NETWORK-MEMBER-SAVE": MEMBER_PARAMS | {"expectedStatus"},
    "Q-NETWORK-GRANT-CREATE": GRANT_PARAMS,
    "Q-NETWORK-GRANT-SAVE": GRANT_PARAMS | {"expectedStatus"},
    "Q-NETWORK-LISTING-CREATE": LISTING_PARAMS,
    "Q-NETWORK-LISTING-SAVE": LISTING_PARAMS | {"expectedStatus"},
}
REGISTRY_LABELS = {"Network", "NetworkMembership", "Grant", "Listing"}


def _stored(props: dict[str, Any]) -> dict[str, Any]:
    """What the driver hands back for a node's properties: a datetime is a Neo4j DateTime and an
    unset property is absent."""
    return {
        key: DateTime.from_native(value) if isinstance(value, datetime) else value
        for key, value in props.items()
        if value is not None
    }


def _registry(connection: NetworkConnection) -> Neo4jNetworkRegistry:
    return Neo4jNetworkRegistry(cast(Neo4jConnection, connection))


# The statements


def test_there_are_eleven_reads_and_eight_writes_on_the_global_allowlist() -> None:
    assert set(READ_IDS) | set(WRITE_IDS) <= set(GLOBAL_QUERY_IDS)
    assert set(WRITE_IDS) == set(GLOBAL_WRITE_IDS)
    assert len(READ_IDS) == 11
    assert len(WRITE_IDS) == 8
    for query_id in (*READ_IDS, *WRITE_IDS):
        assert "registry" in GLOBAL_QUERY_IDS[query_id]
        assert len(GLOBAL_QUERY_IDS[query_id]) > 30
    # No other statement may write: the write list is exactly these eight.
    assert not set(GLOBAL_WRITE_IDS) - set(WRITE_IDS)


@pytest.mark.parametrize("query_id", sorted({*READ_IDS, *WRITE_IDS}))
def test_each_statement_is_registered_global_pinned_and_free_of_the_tenant(query_id: str) -> None:
    query = REGISTRY.get(query_id)
    assert query.scope == "global"
    assert query.scenario is None
    assert query.mode == ("write" if query_id in WRITE_IDS else "read")
    assert GLOBAL_STATEMENTS[query_id] == statement_digest(query.cypher)
    assert re.search(r"\$tenant\b", query.cypher) is None
    assert re.search(r"\btenantId\b", query.cypher, re.IGNORECASE) is None
    expected = {**READ_IDS, **WRITE_IDS}[query_id]
    assert set(re.findall(r"\$(\w+)", query.cypher)) == expected
    assert set(statement_labels(query.cypher)) <= REGISTRY_LABELS


@pytest.mark.parametrize("query_id", sorted(READ_IDS))
def test_a_read_has_no_write_or_procedure_word(query_id: str) -> None:
    text = REGISTRY.get(query_id).cypher
    assert (
        re.search(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|CALL|LOAD|FOREACH|DROP)\b", text)
        is None
    )


@pytest.mark.parametrize("query_id", sorted(WRITE_IDS))
def test_a_write_creates_or_sets_and_never_deletes_calls_or_assigns_a_map_or_a_label(
    query_id: str,
) -> None:
    text = REGISTRY.get(query_id).cypher
    assert re.search(r"\b(DELETE|DETACH|REMOVE|CALL|LOAD|FOREACH|DROP|MERGE)\b", text) is None
    assert "+=" not in text
    assert re.search(r"\bSET\s+\w+\s*:", text) is None
    assert re.search(r"\b(CREATE|SET)\b", text) is not None


@pytest.mark.parametrize("query_id", sorted(WRITE_IDS))
def test_a_write_returns_the_id_it_wrote_so_that_no_row_means_nothing_was_written(
    query_id: str,
) -> None:
    assert re.search(r"RETURN \w+\.id AS id$", REGISTRY.get(query_id).cypher) is not None


@pytest.mark.parametrize(
    "query_id",
    ["Q-NETWORK-SAVE", "Q-NETWORK-MEMBER-SAVE", "Q-NETWORK-GRANT-SAVE", "Q-NETWORK-LISTING-SAVE"],
)
def test_a_save_matches_the_status_it_expects_so_a_lost_race_writes_nothing(query_id: str) -> None:
    assert re.search(r"status: \$expectedStatus", REGISTRY.get(query_id).cypher) is not None


@pytest.mark.parametrize("query_id", ["Q-NETWORK-MEMBER-CREATE", "Q-NETWORK-LISTING-CREATE"])
def test_a_create_that_must_be_the_only_live_row_takes_the_networks_lock_first(
    query_id: str,
) -> None:
    text = REGISTRY.get(query_id).cypher
    assert text.startswith("MATCH (n:Network {id: $networkId}) SET n.status = n.status")
    assert "count(" in text


def test_a_write_registers_only_when_its_id_is_on_the_write_list() -> None:
    """A write on the allowlist but not on the write list is refused, as it always was."""
    text = REGISTRY.get("Q-NETWORK-CREATE").cypher
    registry = QueryRegistry()
    registry.register(NamedQuery(id="Q-NETWORK-CREATE", cypher=text, mode="write", scope="global"))
    with pytest.raises(ValueError, match="read-only"):
        QueryRegistry().register(
            NamedQuery(id="Q-TENANT-GET", cypher=text, mode="write", scope="global")
        )
    assert frozenset(REGISTRY_LABELS) == queries_module.NETWORK_REGISTRY_LABELS


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n:Network {id: $id}) DELETE n RETURN 1 AS id",
        "MATCH (n:Network {id: $id}) DETACH DELETE n",
        "MATCH (n:Network {id: $id}) SET n += $map RETURN n.id AS id",
        "MATCH (n:Network {id: $id}) SET n:Tenant RETURN n.id AS id",
        "MATCH (n:Network {id: $id}) REMOVE n.name RETURN n.id AS id",
        "CREATE (t:Tenant {id: $id}) RETURN t.id AS id",
        "CREATE (t:Observation {id: $id}) RETURN t.id AS id",
        "MATCH (n:Network {id: $id}) CALL db.labels() YIELD label RETURN n.id AS id",
        "MATCH (n:Network {id: $id}) FOREACH (x IN [1] | SET n.a = x) RETURN n.id AS id",
    ],
)
def test_a_registry_write_that_goes_beyond_the_registry_is_refused_even_when_pinned(
    cypher: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        queries_module,
        "GLOBAL_STATEMENTS",
        {**GLOBAL_STATEMENTS, "Q-NETWORK-CREATE": statement_digest(cypher)},
    )
    with pytest.raises(ValueError):
        QueryRegistry().register(
            NamedQuery(id="Q-NETWORK-CREATE", cypher=cypher, mode="write", scope="global")
        )


# The mapping


def test_a_network_with_its_settings_comes_back_from_its_node_equal() -> None:
    for status in NetworkStatus:
        network = make_network(status)
        props = _stored(network_properties(network, SETTINGS))
        assert network_from_properties(props) == RegisteredNetwork(network, SETTINGS)


def test_a_membership_in_every_status_comes_back_equal() -> None:
    for status in MembershipStatus:
        row = make_member(MEMBER_B, status=status)
        assert membership_from_properties(_stored(membership_properties(row))) == row
    owner = make_owner_membership()
    assert membership_from_properties(_stored(membership_properties(owner))) == owner


def test_a_grant_in_every_state_comes_back_equal() -> None:
    proposed = make_grant(approved=False)
    approved = make_grant()
    from diucs.domain.rules.grant import end_grant

    ended = end_grant(approved, by_tenant_id=MEMBER_B, account_ref="acct-member-b-01", now=NOW)
    for grant in (proposed, approved, ended, replace(approved, effective_to=NOW + (NOW - T0))):
        assert grant_from_properties(_stored(grant_properties(grant))) == grant
    assert {g.status for g in (proposed, approved, ended)} == {
        GrantStatus.PROPOSED,
        GrantStatus.APPROVED,
        GrantStatus.ENDED,
    }


def test_a_listing_in_every_status_comes_back_equal() -> None:
    for listing in (make_listing(admitted=False), make_listing()):
        assert listing_from_properties(_stored(listing_properties(listing))) == listing
    assert ListingStatus.PENDING != ListingStatus.ADMITTED


def test_the_parameters_of_each_write_are_the_properties_of_its_record() -> None:
    assert set(network_properties(make_network(), SETTINGS)) == NETWORK_PARAMS
    assert set(membership_properties(make_member())) == MEMBER_PARAMS
    assert set(grant_properties(make_grant())) == GRANT_PARAMS
    assert set(listing_properties(make_listing())) == LISTING_PARAMS


def test_no_property_holds_a_name_a_phone_a_postcode_or_an_agreement_text() -> None:
    props = {
        **network_properties(make_network(), SETTINGS),
        **grant_properties(make_grant()),
        **membership_properties(make_member()),
        **listing_properties(make_listing()),
    }
    for key in props:
        assert key not in {"phone", "email", "postcode", "agreementText", "content", "contact"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("id"),
        lambda p: p.pop("status"),
        lambda p: p.update(status="unknown"),
        lambda p: p.update(status=7),
        lambda p: p.update(createdAt="2026-10-01T09:00:00Z"),
        lambda p: p.update(ownerTenantId="net-pilot"),
        lambda p: p.update(timeZone="Nowhere/Land"),
        lambda p: p.update(agreementVersion="1"),
        lambda p: p.update(id="tenant-a"),
    ],
)
def test_a_network_node_the_domain_refuses_is_a_fixed_message_error(mutate: Any) -> None:
    props = _stored(network_properties(make_network(), SETTINGS))
    mutate(props)
    with pytest.raises(NetworkRecordInvalid) as error:
        network_from_properties(props)
    assert str(error.value) == module.RECORD_MESSAGE
    assert "net-pilot" not in str(error.value)


def test_a_grant_whose_approvals_disagree_with_its_status_is_refused() -> None:
    props = _stored(grant_properties(make_grant()))
    del props["ownerApprovalAt"]
    with pytest.raises(NetworkRecordInvalid):
        grant_from_properties(props)
    props = _stored(grant_properties(make_grant(approved=False)))
    props["status"] = "approved"
    with pytest.raises(NetworkRecordInvalid):
        grant_from_properties(props)


def test_a_membership_or_a_listing_the_domain_refuses_is_refused() -> None:
    props = _stored(membership_properties(make_member()))
    props["status"] = "left"  # a left row needs its leave date and reason
    with pytest.raises(NetworkRecordInvalid):
        membership_from_properties(props)
    props = _stored(listing_properties(make_listing()))
    del props["decidedByAccountRef"]
    with pytest.raises(NetworkRecordInvalid):
        listing_from_properties(props)


# The adapter


def _network_row() -> dict[str, Any]:
    return {"network": _stored(network_properties(make_network(), SETTINGS))}


async def test_a_network_is_read_by_its_id_and_nothing_is_sent_for_an_id_of_another_shape() -> None:
    connection = NetworkConnection({"Q-NETWORK-GET": [_network_row()]})
    registry = _registry(connection)
    found = await registry.get_network(NETWORK_ID)
    assert found == RegisteredNetwork(make_network(), SETTINGS)
    assert connection.calls[0][1] == {"id": NETWORK_ID}
    for bad in ("tenant-a", "net-", "NET-x", "", "net-pilot/x"):
        assert await registry.get_network(bad) is None
    assert len(connection.calls) == 1
    assert await _registry(NetworkConnection()).get_network(NETWORK_ID) is None


async def test_two_rows_for_one_key_are_a_registry_fault() -> None:
    connection = NetworkConnection({"Q-NETWORK-GET": [_network_row(), _network_row()]})
    with pytest.raises(NetworkRecordInvalid):
        await _registry(connection).get_network(NETWORK_ID)


async def test_the_active_membership_is_read_by_network_and_tenant() -> None:
    row = {"membership": _stored(membership_properties(make_member(MEMBER_B)))}
    connection = NetworkConnection({"Q-NETWORK-MEMBERSHIP-ACTIVE": [row]})
    registry = _registry(connection)
    assert await registry.active_membership(NETWORK_ID, MEMBER_B) == make_member(MEMBER_B)
    assert connection.calls[0][1] == {"networkId": NETWORK_ID, "memberTenantId": MEMBER_B}
    # An id of the wrong kind is refused before anything is sent: a network id in the tenant place
    # and a tenant id in the network place.
    assert await registry.active_membership(NETWORK_ID, NETWORK_ID) is None
    assert await registry.active_membership(MEMBER_B, MEMBER_B) is None
    assert len(connection.calls) == 1


async def test_memberships_come_back_in_the_order_the_statement_gave() -> None:
    rows = [
        {"membership": _stored(membership_properties(make_member(t)))} for t in (MEMBER_B, MEMBER_C)
    ]
    connection = NetworkConnection(
        {"Q-NETWORK-MEMBERSHIPS": rows, "Q-NETWORK-MEMBERSHIPS-OF": rows[:1]}
    )
    registry = _registry(connection)
    assert [m.member_tenant_id for m in await registry.memberships(NETWORK_ID)] == [
        MEMBER_B,
        MEMBER_C,
    ]
    assert [m.member_tenant_id for m in await registry.memberships_of(MEMBER_B)] == [MEMBER_B]


async def test_the_gate_returns_only_a_grant_that_may_project_now() -> None:
    def row(grant: Any, member: Any = None, network: Any = None) -> dict[str, Any]:
        return {
            "grant": _stored(grant_properties(grant)),
            "network": _stored(network_properties(network or make_network(), SETTINGS)),
            "membership": _stored(membership_properties(member or make_member(MEMBER_B))),
        }

    effective = make_grant(id="grant-ok")
    future = make_grant(id="grant-future", effective_from=NOW + (NOW - T0))
    ended_window = make_grant(id="grant-window", effective_to=NOW)
    left = make_member(MEMBER_B, status=MembershipStatus.LEFT)
    suspended = make_network(NetworkStatus.SUSPENDED)
    connection = NetworkConnection(
        {
            "Q-NETWORK-GRANT-ACTIVE-FOR": [
                row(effective),
                row(future),
                row(ended_window),
                row(make_grant(id="grant-left"), member=left),
                row(make_grant(id="grant-suspended"), network=suspended),
            ]
        }
    )
    active = await _registry(connection).active_grants_for(MEMBER_B, GrantScope.CAPACITY, NOW)
    assert [a.grant.id for a in active] == ["grant-ok"]
    assert active[0].network.settings == SETTINGS
    assert active[0].membership.member_tenant_id == MEMBER_B
    assert connection.calls[0][1] == {"grantorTenantId": MEMBER_B, "scope": "capacity"}


async def test_the_gate_refuses_a_scope_that_is_not_a_scope_and_a_naive_time() -> None:
    registry = _registry(NetworkConnection())
    with pytest.raises(Exception):  # noqa: B017, PT011
        await registry.active_grants_for(MEMBER_B, "capacity", NOW)  # type: ignore[arg-type]
    with pytest.raises(Exception):  # noqa: B017, PT011
        await registry.active_grants_for(MEMBER_B, GrantScope.CAPACITY, NOW.replace(tzinfo=None))
    assert await registry.active_grants_for("net-pilot", GrantScope.CAPACITY, NOW) == []


async def test_a_write_sends_the_record_as_parameters_with_no_tenant() -> None:
    connection = NetworkConnection({"Q-NETWORK-GRANT-CREATE": [{"id": "grant-b-capacity"}]})
    grant = make_grant()
    await _registry(connection).create_grant(grant)
    [(text, params)] = connection.calls
    assert text == REGISTRY.get("Q-NETWORK-GRANT-CREATE").cypher
    assert params == grant_properties(grant)
    assert "tenant" not in params
    assert connection.writes == 1


async def test_a_save_that_matches_nothing_is_a_conflict_and_one_that_matches_is_not() -> None:
    grant = make_grant()
    refused = _registry(NetworkConnection({"Q-NETWORK-GRANT-SAVE": []}))
    with pytest.raises(Conflict):
        await refused.save_grant(grant, expected_status=GrantStatus.OWNER_APPROVED)
    connection = NetworkConnection({"Q-NETWORK-GRANT-SAVE": [{"id": grant.id}]})
    await _registry(connection).save_grant(grant, expected_status=GrantStatus.OWNER_APPROVED)
    assert connection.calls[0][1]["expectedStatus"] == "owner-approved"
    assert connection.calls[0][1]["status"] == "approved"


@pytest.mark.parametrize(
    ("method", "query_id", "args"),
    [
        ("create_network", "Q-NETWORK-CREATE", (make_network(), SETTINGS)),
        ("create_membership", "Q-NETWORK-MEMBER-CREATE", (make_member(),)),
        ("create_grant", "Q-NETWORK-GRANT-CREATE", (make_grant(),)),
        ("create_listing", "Q-NETWORK-LISTING-CREATE", (make_listing(),)),
    ],
)
async def test_a_create_that_finds_the_key_taken_or_a_live_row_is_a_conflict(
    method: str, query_id: str, args: tuple[Any, ...]
) -> None:
    taken = _registry(NetworkConnection(errors={query_id: ConstraintError("taken")}))
    with pytest.raises(Conflict):
        await getattr(taken, method)(*args)
    guarded = _registry(NetworkConnection({query_id: []}))
    with pytest.raises(Conflict):
        await getattr(guarded, method)(*args)


async def test_a_save_of_each_kind_names_the_expected_status() -> None:
    connection = NetworkConnection(
        {
            "Q-NETWORK-SAVE": [{"id": NETWORK_ID}],
            "Q-NETWORK-MEMBER-SAVE": [{"id": "x"}],
            "Q-NETWORK-LISTING-SAVE": [{"id": "x"}],
        }
    )
    registry = _registry(connection)
    await registry.save_network(make_network(), SETTINGS, expected_status=NetworkStatus.DRAFT)
    await registry.save_membership(make_member(), expected_status=MembershipStatus.INVITED)
    await registry.save_listing(make_listing(), expected_status=ListingStatus.PENDING)
    assert [params["expectedStatus"] for _, params in connection.calls] == [
        "draft",
        "invited",
        "pending",
    ]


async def test_the_owner_is_the_only_tenant_the_samples_make_an_owner() -> None:
    assert make_owner_membership().member_tenant_id == OWNER
