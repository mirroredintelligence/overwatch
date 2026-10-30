"""The privacy scan of the network scope and of every network route (TEN-062, DEC-132 items 4 and
7, DEC-134 items 6 and 8, DEC-136 item 14).

Each of the three members holds private data of every category the projection never copies
(`NEVER_SHARED`): a sentinel in a node of that kind, written in the member's own tenant, and patient
shaped text in the fields a producer does read (the service comment, a full postcode). The
projector runs, the network board is built and read, and then:

- every node of the network scope is looked at: its labels are on the allowlist, its properties are
  on the allowlist of its label (or are the stamped system properties), its relationships are the
  two the allowlist names, and no sentinel, patient-shaped value, member id or grant id is in any of
  them;
- every network route is called with a viewer who may read it, and no response holds a sentinel, a
  patient-shaped value, a tenant id, a grant id or a forbidden key (the table of
  `tests/support/network_routes.py` is held equal to the routes the app serves).

The strongest check is the plain one: the sentinel of each category is in the member's tenant, and
the scan reads the whole of the network scope.
"""

import json
import re
from collections.abc import Mapping
from typing import Any

import pytest
from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.scope_labels import (
    NETWORK_ONLY_LABELS,
    SCOPE_GENERIC_LABELS,
)
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_uow_factory
from diucs.application.tenancy import bind_tenant
from diucs.domain.codes import Role
from diucs.domain.messages.privacy_guard import find_patient_data, scan_value
from diucs.domain.rules import projection as allowlist
from diucs.domain.rules.projection import NETWORK_RELATIONSHIPS, NEVER_SHARED
from tests.support import network_fixtures
from tests.support.neo4j import read_tx, write_tx
from tests.support.network_fixtures import NetApp, bearer, client_of, wall_bearer
from tests.support.network_routes import ROUTES, discovered, url
from tests.support.network_world import NetworkWorld
from tests.support.projection_samples import sample_profile

pytestmark = pytest.mark.asyncio(loop_scope="session")

# the shared fixtures of the network tests, under their own names
bare_world = network_fixtures.bare_world
connection = network_fixtures.connection
world = network_fixtures.world
net_app = network_fixtures.net_app

PATIENT_COMMENT = "Mrs Smith 943 476 5919 lives at DT4 8XX"
WEEK = {"weekStart": "2026-10-26"}
AUDIT_RELATIONSHIPS = frozenset(
    {
        "NEXT",
        "HEAD",
        "CHAIN",
        "PREVIOUS",
        "HAS_SNAPSHOT",
        "HAS_REF",
        "ENTITY",
        "SNAPSHOT",
        "ACTIVITY",
        "AGENT",
        "TARGET",
    }
)

# One private node per category, written in the member's own tenant. A category that the producers
# read from a real source record is planted there instead (below), and one that is a shape and not
# a text is covered by the property allowlist check.
RAW: dict[str, str] = {
    "reporter-name": (
        "CREATE (n:Practitioner {tenantId: $tenant, key: $key, displayName: $value})"
    ),
    "reporter-phone": ("CREATE (n:Practitioner {tenantId: $tenant, key: $key, phoneHash: $value})"),
    "device": "CREATE (n:Device {tenantId: $tenant, id: $key, deviceName: $value})",
    "pin": "CREATE (n:Credential {tenantId: $tenant, deviceId: $key, pinHash: $value})",
    "token": "CREATE (n:LinkToken {tenantId: $tenant, tokenHash: $key, aboutId: $value})",
    "communication": "CREATE (n:Communication {tenantId: $tenant, id: $key, text: $value})",
    "booking": "CREATE (n:Task {tenantId: $tenant, id: $key, description: $value})",
    "case": "CREATE (n:ServiceRequest {tenantId: $tenant, id: $key, reference: $value})",
    "audit-entry": "CREATE (n:AuditEvent {tenantId: $tenant, id: $key, entryJson: $value})",
    "flag-reason": "CREATE (n:ReportFlag {tenantId: $tenant, id: $key, reason: $value})",
    "role-contact": "CREATE (n:ProtectedContact {tenantId: $tenant, key: $key, value: $value})",
}
PLANTED_IN_SOURCES = {"service-comment", "criteria-change-reason", "role-reference"}
SHAPES_ONLY = {"report-channel", "report-range", "next-due", "pending-bookings"}


def sentinel(category: str, member: str) -> str:
    return f"sentinel-{category}-{member.rsplit('-', 1)[-1]}"


async def _plant(world: NetworkWorld) -> list[str]:
    planted: list[str] = []
    for member in world.ids.members:
        for category, statement in RAW.items():
            value = sentinel(category, member)

            async def create(
                tx: AsyncManagedTransaction,
                text: str = statement,
                tenant: str = member,
                value: str = value,
            ) -> None:
                await tx.run(text, tenant=tenant, key=f"key-{value}", value=value)

            await write_tx(world.driver, create)
            planted.append(value)
        with bind_tenant(member):
            async with neo4j_uow_factory(world.driver)() as uow:
                await uow.services.save(
                    sample_profile(name=world.service_name(member), comment=PATIENT_COMMENT)
                )
                await uow.commit()
    return planted


async def _scan_network_scope(world: NetworkWorld) -> tuple[list[dict[str, Any]], list[str]]:
    async def nodes(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (n {tenantId: $net}) RETURN labels(n) AS labels, properties(n) AS props",
            net=world.ids.network,
        )
        return await result.data()

    async def relationships(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (a {tenantId: $net})-[r]-(b {tenantId: $net}) "
            "RETURN DISTINCT type(r) AS type, keys(r) AS keys, labels(a) AS ends",
            net=world.ids.network,
        )
        return await result.data()

    rows = await read_tx(world.driver, nodes)
    rels = await read_tx(world.driver, relationships)
    # a relationship between projected nodes holds no property (the audit chain's own links do)
    for rel in rels:
        if rel["type"] in NETWORK_RELATIONSHIPS:
            assert rel["keys"] == [], "a projection relationship holds a property"
    return rows, sorted({r["type"] for r in rels})


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list | tuple | set | frozenset):
        return [text for item in value for text in _strings(item)]
    return [str(value)] if value is not None else []


async def test_every_never_shared_category_is_planted_or_covered_by_a_shape_check() -> None:
    assert set(NEVER_SHARED) == set(RAW) | PLANTED_IN_SOURCES | SHAPES_ONLY
    assert not set(RAW) & PLANTED_IN_SOURCES and not set(RAW) & SHAPES_ONLY


async def test_no_sentinel_and_nothing_patient_shaped_is_anywhere_in_the_network_scope(
    world: NetworkWorld,
) -> None:
    planted = await _plant(world)
    await world.run_projector()
    rows, _ = await _scan_network_scope(world)
    assert rows, "the network scope holds the projection"
    text = json.dumps(rows, default=str)
    for value in (*planted, *(p for marks in world.poison.values() for p in marks)):
        assert value not in text, "a private value reached the network scope"
    for part in ("Mrs Smith", "943 476 5919", "DT4 8XX", "lives at"):
        assert part not in text
    # a district is the most of a postcode a projection holds
    assert "DT4" in text
    # a member's tenant id is in the scope only where the allowlist puts it: the row's source
    # (the scope's own audit chain names the source of a write by id: it is the chain, not a row)
    for row in rows:
        if set(row["labels"]) & SCOPE_GENERIC_LABELS:
            continue
        for key, value in row["props"].items():
            if any(member in str(value) for member in world.ids.members):
                assert key in {"sourceTenantId", "grantId"}, key
    # no value of a projected row looks like patient data (a hash in the audit chain can look like
    # a ten-digit number: the chain is the scope's own and holds ids and hashes only)
    for row in rows:
        if set(row["labels"]) & SCOPE_GENERIC_LABELS:
            continue
        leaked = [text for text in _strings(row["props"]) if find_patient_data(text)]
        assert leaked == [], row["labels"]


async def test_every_label_property_and_relationship_is_on_the_allowlist(
    world: NetworkWorld,
) -> None:
    await _plant(world)
    await world.run_projector()
    rows, relationship_types = await _scan_network_scope(world)
    allowed_labels = NETWORK_ONLY_LABELS | SCOPE_GENERIC_LABELS
    for row in rows:
        labels = set(row["labels"])
        assert labels <= allowed_labels, row["labels"]
        if labels & SCOPE_GENERIC_LABELS:
            continue
        (label,) = row["labels"]
        permitted = {spec.prop for spec in allowlist.ALLOWLIST.get(label, ())}
        permitted |= allowlist.SYSTEM_PROPERTIES.get(label, frozenset())
        assert set(row["props"]) <= permitted, (label, set(row["props"]) - permitted)
    assert set(relationship_types) <= (NETWORK_RELATIONSHIPS | AUDIT_RELATIONSHIPS)


async def test_the_sentinels_are_in_the_members_own_tenant_and_still_there(
    world: NetworkWorld,
) -> None:
    """The scan proves something only if the private data exists: each member still holds every
    sentinel in its own tenant after the projector ran."""
    await _plant(world)
    await world.run_projector()

    async def held(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (n {tenantId: $tenant}) RETURN properties(n) AS props",
            tenant=world.ids.members[0],
        )
        return await result.data()

    rows = await read_tx(world.driver, held)
    holding = [r for r in rows if any(t.startswith("sentinel-") for t in _strings(r["props"]))]
    assert len(holding) == len(RAW)


async def test_the_network_scope_holds_no_member_data_after_a_leave_either(
    world: NetworkWorld,
) -> None:
    planted = await _plant(world)
    await world.run_projector()
    await world.leave(world.ids.members[2])
    rows, _ = await _scan_network_scope(world)
    text = json.dumps(rows, default=str)
    assert not any(value in text for value in planted)


# ------------------------------------------------------------------ every route


def _headers(route_roles: frozenset[Role], member: str, network: str) -> dict[str, str]:
    if Role.WALL in route_roles:
        return wall_bearer(member)
    return bearer(member, Role.EXEC if Role.EXEC in route_roles else Role.LEAD, (network,))


async def test_every_network_route_is_in_the_scan(net_app: NetApp) -> None:
    assert discovered(net_app.app) == {(r.method, r.template) for r in ROUTES}


async def test_no_network_route_answers_with_a_sentinel_a_patient_value_or_a_member(
    net_app: NetApp, world: NetworkWorld
) -> None:
    planted = await _plant(world)
    await world.run_projector()
    member = world.ids.members[0]
    network = world.ids.network
    # a screen set to the network, so the wall's own route has something to say
    from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType

    with bind_tenant(member):
        async with neo4j_uow_factory(world.driver)() as uow:
            await uow.devices.save(
                Device(
                    id="screen-1",
                    status=DeviceStatus.ACTIVE,
                    name="Ward 4 corridor",
                    location=None,
                    device_type=DeviceType.WALL_DISPLAY,
                    token_hash="e" * 64,
                    board_scope=BoardScope.NETWORK,
                    network_id=network,
                )
            )
            await uow.commit()
    scanned = 0
    async with client_of(net_app) as client:
        for route in ROUTES:
            if route.streams:
                continue  # content-free by construction: `changedAt` only (test_network_stream)
            response = await client.get(
                url(route, network),
                params={"weekStart": "2026-10-26"} if route.needs_week else {},
                headers=_headers(route.roles, member, network),
            )
            assert response.status_code == 200, route.template
            text = response.text
            body = response.json()
            for value in (*planted, *(p for marks in world.poison.values() for p in marks)):
                assert value not in text, route.template
            for part in ("Mrs Smith", "943 476 5919", "DT4 8XX"):
                assert part not in text, route.template
            for tenant in (*world.ids.members, world.ids.owner, world.ids.outsider):
                assert tenant not in text, route.template
            assert "grant-" not in text and re.search(r"sourceTenant|source_tenant", text) is None
            if route.template != "/networks":
                assert network not in text, route.template
            found = scan_value(body) if route.json_keys_are_scanned else _values_only(body)
            assert found == [], (route.template, found)
            scanned += 1
    assert scanned == len([r for r in ROUTES if not r.streams])


def _values_only(body: Any) -> list[str]:
    return [hit for text in _strings(body) for hit in find_patient_data(text)]
