"""A tenant's whole way out on a real Neo4j: offboarding, export, completion and purge (TEN-074,
DEC-136 item 10, DEC-132 item 6, audit F section 2.4, hazards H-T18 and H-N08).

Two members of one network share capacity. The operator offboards the first: it leaves the network
(its sharing stops, its history stays), its record moves through offboarding to offboarded, its
data is exported to a package whose manifest hashes are checked, its number is quarantined, and it
is purged by two operators. What is proved on the real graph: the second member and the network's
own scope are exactly as they were, the registry keeps the tenant's record (purged) and the
membership that ended, the tombstone holds the head of the chain that was deleted, and nothing
carrying the purged tenant's id is left.
"""

import json
import os
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_directory import Neo4jTenantDirectory
from diucs.adapters.outbound.graph_store.tenant_purge import Neo4jTenantData
from diucs.adapters.outbound.graph_store.tenant_registry import Neo4jTenantRegistry
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_export_storage import MemoryExportStorage
from diucs.adapters.testing.recording_platform_audit import RecordingPlatformAudit
from diucs.application.ports.outbound.tenant_registry import TenantNumberRecord
from diucs.application.tenancy import ScopeId, bind_scope, bind_tenant
from diucs.application.use_cases.membership import LeaveAllNetworks
from diucs.application.use_cases.tenant_offboard import (
    CompleteOffboarding,
    CompleteOffboardingCommand,
    ExportTenant,
    ExportTenantCommand,
    StartOffboarding,
    StartOffboardingCommand,
)
from diucs.application.use_cases.tenant_purge import PurgeTenant, PurgeTenantCommand
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed
from diucs.domain.model.network import GrantScope, MembershipStatus
from diucs.domain.model.tenant import NumberStatus, OrganisationType, Tenant, TenantStatus
from tests.support.neo4j import read_tx, tx_run
from tests.support.network_admin_fakes import person
from tests.support.network_admin_rig import START, AdminRig
from tests.support.network_world import world_ids
from tests.support.tenancy import RunIdentity

pytestmark = pytest.mark.asyncio(loop_scope="session")

ALL = tuple(GrantScope)
SID = "AC" + "1" * 32


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
async def rig(
    harness_driver: AsyncDriver,
    connection: Neo4jConnection,
    run_identity: RunIdentity,
    clean_graph: None,
) -> AsyncIterator[AdminRig]:
    built = await AdminRig.build(harness_driver, connection, world_ids(run_identity))
    await built.make_network()
    for member, admin in zip(built.ids.members[:2], built.people.admins[:2], strict=True):
        await built.join(member, admin)
        await built.share(member, admin, *ALL)
        await built.list_service(member, admin)
    await built.deliver_events()
    await built.apply_pending()
    yield built
    await built.cleanup()


async def _every_node(driver: AsyncDriver, tenant: str) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        with bind_scope(ScopeId.parse(tenant)):
            result = await tx_run(tx, "MATCH (n {tenantId: $tenant}) RETURN count(n) AS n")
            return int((await result.data())[0]["n"])

    return await read_tx(driver, work)


async def test_a_tenant_leaves_the_network_is_exported_completed_and_purged_and_nobody_else_moves(
    rig: AdminRig, connection: Neo4jConnection, harness_driver: AsyncDriver
) -> None:
    leaver, stayer = rig.ids.members[0], rig.ids.members[1]
    registry = Neo4jTenantRegistry(connection)
    directory = Neo4jTenantDirectory(connection)
    created = START - timedelta(days=200)
    tenant = Tenant(
        id=leaver,
        display_name="Leaving Org",
        legal_name="Leaving Org Ltd",
        organisation_type=OrganisationType.OTHER,
        status=TenantStatus.PROVISIONING,
        created_at=created,
    )
    await registry.create(tenant)
    from dataclasses import replace

    active = replace(tenant, status=TenantStatus.ACTIVE, activated_at=created + timedelta(days=1))
    assert await registry.save(active, expected_epoch=1, expected_status=TenantStatus.PROVISIONING)
    await registry.put_number(
        leaver,
        TenantNumberRecord(
            "+441234567890", SID, f"twilio/{leaver}/token", NumberStatus.ACTIVE, START
        ),
    )
    storage = MemoryExportStorage()
    reader = Neo4jTenantData(connection)
    platform_audit = RecordingPlatformAudit()
    cache = InMemoryCache(rig.clock)
    operator = person(leaver, Role.PLATFORM_OPERATOR, "op-one")
    second = person(leaver, Role.PLATFORM_OPERATOR, "op-two")
    stayer_before = await _every_node(harness_driver, stayer)

    # 1. start: the membership ends first, then the record moves
    leave = LeaveAllNetworks(rig.registry, rig.ends, rig.recorder, rig.clock)
    start = StartOffboarding(directory, registry, leave, rig.tenant_factory, rig.clock)
    with bind_tenant(leaver):
        started = await start.execute(StartOffboardingCommand(operator))
    assert started.memberships_ended == 1
    [row] = [m for m in await rig.registry.memberships_of(leaver)]
    assert row.status is MembershipStatus.LEFT
    live = await rig.view()
    assert all(rig.rows_of(leaver, rows) == [] for rows in live)  # sharing stopped
    assert any(rig.rows_of(stayer, rows) for rows in live)  # the other member carries on
    assert (await directory.get(leaver)).status is TenantStatus.OFFBOARDING  # type: ignore[union-attr]
    assert leaver not in await directory.active_tenant_ids()

    # the leave wrote its own records in the network scope; from here on it must not move
    network_before = await _every_node(harness_driver, rig.ids.network)

    # 2. export: a package whose manifest hashes are the storage's own
    export = ExportTenant(directory, reader, storage, rig.tenant_factory, rig.ids_gen, rig.clock)
    with bind_tenant(leaver):
        package = await export.execute(ExportTenantCommand(operator))
    manifest = json.loads(storage.files[(leaver, package.package_id, "manifest.json")])
    names = {f["name"] for f in manifest["files"]}
    assert "directory-and-criteria/HealthcareService+Resource.jsonl" in names
    assert "audit-chain/AuditEvent+ChainLink.jsonl" in names and "relationships.jsonl" in names
    assert manifest["audit_chain"]["last_seq"] >= 3
    assert not any("Credential" in n or "LinkToken" in n for n in names)
    exported = storage.files[
        (leaver, package.package_id, "directory-and-criteria/HealthcareService+Resource.jsonl")
    ]
    assert b'"tenantId"' not in exported  # the scope id is the package's key, not a property

    # 3. complete: the export delivered; the notice waived in writing; the number quarantined
    complete = CompleteOffboarding(directory, registry, storage, rig.tenant_factory, rig.clock)
    with bind_tenant(leaver):
        with pytest.raises(NotAllowed):  # before the notice has ended and with no waiver
            await complete.execute(
                CompleteOffboardingCommand(operator, manifest_hash=package.manifest_hash)
            )
        done = await complete.execute(
            CompleteOffboardingCommand(
                operator, manifest_hash=package.manifest_hash, notice_waived=True
            )
        )
    assert done.numbers_quarantined == 1
    [number] = await registry.numbers(leaver)
    assert number.status is NumberStatus.QUARANTINED
    assert number.quarantine_until == rig.clock.now() + timedelta(days=90)
    assert (await directory.get(leaver)).status is TenantStatus.OFFBOARDED  # type: ignore[union-attr]

    # 4. purge: a dry run first, then two operators and the typed id
    purge = PurgeTenant(directory, registry, reader, reader, cache, platform_audit, rig.clock)
    with bind_tenant(leaver):
        dry = await purge.execute(PurgeTenantCommand(operator, second, typed_slug="", dry_run=True))
        assert (
            dry.dry_run
            and sum(dry.counts.values()) > 8
            and await _every_node(harness_driver, leaver) > 8
        )
        with pytest.raises(NotAllowed):  # one person is not two operators
            await purge.execute(PurgeTenantCommand(operator, operator, typed_slug=leaver))
        with pytest.raises(NotAllowed):  # the id must be typed
            await purge.execute(PurgeTenantCommand(operator, second, typed_slug="leaving-org"))
        result = await purge.execute(
            PurgeTenantCommand(
                operator, second, typed_slug=leaver, export_manifest_hash=package.manifest_hash
            )
        )
    assert result.nodes_deleted == sum(dry.counts.values())
    assert await _every_node(harness_driver, leaver) == 0

    # what must not have moved
    assert await _every_node(harness_driver, stayer) == stayer_before
    assert await _every_node(harness_driver, rig.ids.network) == network_before
    after = await directory.get(leaver)
    assert (
        after is not None and after.status is TenantStatus.PURGED
    )  # the registry keeps the record
    assert [m.status for m in await rig.registry.memberships_of(leaver)] == [MembershipStatus.LEFT]
    history = await rig.view(live_only=False)
    assert all(
        len(rig.rows_of(leaver, rows)) == 1 for rows in history
    )  # the network's history stays

    # the tombstone proves the chain existed without keeping it
    start_entry, done_entry = platform_audit.entries
    snapshot = start_entry.snapshot or {}
    assert (
        snapshot["final_audit_seq"] == manifest["audit_chain"]["last_seq"] + 1
        or snapshot["final_audit_seq"] >= manifest["audit_chain"]["last_seq"]
    )
    assert snapshot["export_manifest_hash"] == package.manifest_hash
    assert done_entry.action == "PurgeTenantCompleted"
