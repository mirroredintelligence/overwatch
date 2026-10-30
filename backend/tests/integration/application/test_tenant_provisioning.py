"""Tenant provisioning on a real Neo4j (TEN-028, DEC-503, DEC-130 to DEC-136).

A tenant is made from nothing, step by step, as the platform operator would: created in
provisioning (its registry record, its audit chain with its own genesis, its scope list), given a
host, a number and references, its configuration approved by the tenant's side, its directory
verified, its first administrator invited, and then activated. What is proved, on a private
contracted graph (DEC-159) that holds a second tenant that is never touched:

- a tenant that has just been created is in provisioning and cannot be activated: the blockers are
  listed in fixed words, and nothing changes;
- the new tenant's audit chain verifies, starts from its own genesis (not the default tenant's) and
  holds the operator's actions, named, in the tenant's own chain; the other tenant's chain is
  unchanged;
- a creation that stopped is finished by running it again, and creating an id that another
  tenant holds is refused;
- a number, a host and a directory that another tenant holds are refused and change nothing of the
  new tenant's;
- the invitation is a link token of the tenant's own purpose with no token, number or link at rest,
  and the text is sealed for the tenant;
- activation writes the registry once (compare and set), the tenant is then listed as active for
  the workers, and its daily jobs are scheduled; a second activation is refused;
- an operator of the other tenant, and a role that is not the platform operator, change nothing.

Written in build wave 5 and not run there: the full integration run follows on the merged tip.
Synthetic values only; the secret values are plainly fake.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_directory import Neo4jTenantDirectory
from diucs.adapters.outbound.graph_store.tenant_registry import Neo4jTenantRegistry
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import HmacPhoneHasher
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.provisioning import TENANT_ADMIN_INVITE
from diucs.application.tenancy import bind_tenant
from diucs.application.tenant_settings import DirectoryHostUrl
from diucs.application.use_cases.tenant_access import (
    InviteTenantAdmin,
    InviteTenantAdminCommand,
    invitation_key,
)
from diucs.application.use_cases.tenant_admin import (
    ActivateTenant,
    ActivateTenantCommand,
    CreateTenant,
    CreateTenantCommand,
    MarkNumberTested,
    MarkNumberTestedCommand,
    RecordNumberCommand,
    RecordReferencesCommand,
    RecordTenantNumber,
    RecordTenantReferences,
    SetHostCommand,
    SetTenantHost,
    VerifyDirectoryCommand,
    VerifyEntraBinding,
)
from diucs.application.use_cases.tenant_config import (
    ApproveConfigCommand,
    ApproveTenantConfig,
    BindDirectoryCommand,
    BindEntraDirectory,
    DraftConfigCommand,
    DraftTenantConfig,
    MapEntraGroup,
    MapGroupCommand,
    RecordContactCommand,
    RecordTenantContact,
    SetRetentionCommand,
    SetTenantRetention,
)
from diucs.application.work import SCHEDULED, WorkKind
from diucs.bootstrap.provisioning import AuditHeads
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed
from diucs.domain.model.tenant import ContactKind, OrganisationType, TenantStatus
from tests.support.neo4j import ThrowawayNeo4j, read_tx, wipe_all
from tests.support.tenancy import as_tenant
from tests.support.uow import tenant_uow_factory

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.schema]

NEW = "prov-new"
OTHER = "prov-other"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SID = "AC" + "c" * 32
NUMBER = "+447700900401"
OTHER_NUMBER = "+447700900402"
DIRECTORY_ID = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
GROUP_ID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
MOBILE = "07700 900123"
LINK_SECRET = b"test-only-link-token-secret-0123456789"
PHONE_SECRET = b"test-only-phone-hash-secret-0123456789"
WORDING = {
    "systemName": "Sample capacity view",
    "referralSystemName": "Sample referral system",
    "coordinationTeamName": "The sample coordination team",
}


@dataclass
class World:
    driver: AsyncDriver
    connection: Neo4jConnection
    directory: Neo4jTenantDirectory
    registry: Neo4jTenantRegistry
    clock: FixedClock
    ids: SequentialIds
    secrets: FixedSecretStore

    def factory(self, tenant: str) -> UnitOfWorkFactory:
        return tenant_uow_factory(self.driver, tenant)


@asynccontextmanager
async def _private_graph(
    own: tuple[ThrowawayNeo4j, AsyncDriver],
) -> AsyncIterator[tuple[AsyncDriver, Neo4jConnection]]:
    """The module's private container (`own_neo4j`: every migration applied, the registry is the
    whole database's, so it cannot share a Neo4j with other runs), emptied for each test, and a
    connection to it for the directory and the registry."""
    container, driver = own
    await wipe_all(driver)
    connection = Neo4jConnection(container.uri, container.user, container.password)
    await connection.open()
    try:
        yield driver, connection
    finally:
        await connection.close()
        await wipe_all(driver)


@pytest_asyncio.fixture(loop_scope="session")
async def world(own_neo4j: tuple[ThrowawayNeo4j, AsyncDriver]) -> AsyncIterator[World]:
    async with _private_graph(own_neo4j) as (driver, connection):
        # A second tenant, already made: it must never be touched by anything below.
        directory = Neo4jTenantDirectory(connection)
        registry = Neo4jTenantRegistry(connection)
        clock = FixedClock(NOW)
        ids = SequentialIds()
        secrets = FixedSecretStore({"link-token": LINK_SECRET, "phone-hash": PHONE_SECRET})
        built = World(driver, connection, directory, registry, clock, ids, secrets)
        await _create(built, OTHER)
        yield built


def _operator(tenant: str, *, ref: str | None = "operator-1", role: Role = Role.PLATFORM_OPERATOR):
    return Actor(
        role=role,
        practitioner_id=ref,
        device_id=None,
        channel="script",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def _create_use_case(world: World, tenant: str) -> CreateTenant:
    return CreateTenant(
        world.directory, world.registry, AuditHeads(world.connection), world.factory(tenant),
        world.clock,
    )  # fmt: skip


async def _create(world: World, tenant: str, **fields: Any) -> Any:
    base: dict[str, Any] = {
        "actor": _operator(tenant),
        "tenant_id": tenant,
        "display_name": f"Org {tenant}",
        "legal_name": f"Org {tenant} Ltd",
        "organisation_type": OrganisationType.OTHER,
    }
    with as_tenant(tenant):
        return await _create_use_case(world, tenant).execute(
            CreateTenantCommand(**{**base, **fields})
        )


async def _audit_rows(world: World, tenant: str) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (
            await tx.run(
                "MATCH (e:AuditEvent {tenantId: $tenant}) "
                "RETURN e.useCase AS useCase, e.entryJson AS entry ORDER BY e.seq",
                tenant=tenant,
            )
        ).data()

    return await read_tx(world.driver, work)


async def _count(world: World, tenant: str, label: str) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        row = await (
            await tx.run(f"MATCH (n:`{label}` {{tenantId: $t}}) RETURN count(n) AS c", t=tenant)
        ).single()
        assert row is not None
        return int(row["c"])

    return await read_tx(world.driver, work)


# -- the steps the tenant's own side takes (TEN-026) ----------------------------------------------


def _admin(tenant: str, ref: str) -> Actor:
    return Actor(
        role=Role.OWNER,
        practitioner_id=ref,
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


async def _configure(world: World, tenant: str) -> None:
    """What the tenant's side must do before activation: an approved configuration with its
    wording, two contacts, retention, a directory binding and a role mapping."""
    factory = world.factory(tenant)
    roles = frozenset({Role.OWNER})
    with as_tenant(tenant):
        drafted = await DraftTenantConfig(factory, world.clock, roles).execute(
            DraftConfigCommand(_admin(tenant, "admin-1"), 0, dict(WORDING))
        )
        # The wording keys are not clinical: one approver completes the version, and a further
        # approval of a version that is already current is refused (InvalidTransition).
        assert drafted.diff.approvals_required == 1
        for approver in ("admin-2", "admin-3")[: drafted.diff.approvals_required]:
            await ApproveTenantConfig(factory, world.clock, roles).execute(
                ApproveConfigCommand(_admin(tenant, approver), drafted.version)
            )
        contact = RecordTenantContact(factory, world.clock, roles)
        await contact.execute(
            RecordContactCommand(
                _admin(tenant, "admin-1"), ContactKind.COORDINATION_PHONE, "Coordination",
                "01234 567890",
            )
        )  # fmt: skip
        await contact.execute(
            RecordContactCommand(
                _admin(tenant, "admin-1"), ContactKind.CLINICAL_SAFETY_OFFICER, "Safety",
                "safety@example.org",
            )
        )  # fmt: skip
        await SetTenantRetention(factory, world.clock, roles).execute(
            SetRetentionCommand(_admin(tenant, "admin-1"), use_defaults=True)
        )
        await BindEntraDirectory(factory, world.clock, roles).execute(
            BindDirectoryCommand(_admin(tenant, "admin-1"), DIRECTORY_ID)
        )
        await MapEntraGroup(factory, world.clock, roles).execute(
            MapGroupCommand(_admin(tenant, "admin-1"), GROUP_ID, Role.LEAD)
        )


# -- the operator's steps -------------------------------------------------------------------------


async def _operator_steps(world: World, tenant: str) -> None:
    factory = world.factory(tenant)
    with as_tenant(tenant):
        await SetTenantHost(world.directory, world.registry, factory, world.clock).execute(
            SetHostCommand(_operator(tenant), f"{tenant}.example.org")
        )
        await RecordTenantNumber(world.directory, world.registry, factory, world.clock).execute(
            RecordNumberCommand(_operator(tenant), NUMBER, SID, "Sample sender")
        )
        await MarkNumberTested(world.directory, world.registry, factory, world.clock).execute(
            MarkNumberTestedCommand(_operator(tenant), NUMBER)
        )
        await RecordTenantReferences(world.directory, world.registry, factory, world.clock).execute(
            RecordReferencesCommand(
                _operator(tenant), dsa_ref="DSA-1", dpia_ref="DPIA-1", dcb0160_ref="CS-1"
            )
        )
        await VerifyEntraBinding(world.directory, world.registry, factory, world.clock).execute(
            VerifyDirectoryCommand(_operator(tenant), DIRECTORY_ID)
        )


def _invite_use_case(world: World, tenant: str) -> InviteTenantAdmin:
    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, world.secrets, world.clock)

    return InviteTenantAdmin(
        world.directory,
        world.factory(tenant),
        tokens,
        HmacPhoneHasher(world.secrets),
        AesGcmContentSealer(world.secrets),
        world.clock,
        world.ids,
        DirectoryHostUrl(world.directory),
    )


def _activate_use_case(world: World, tenant: str) -> ActivateTenant:
    return ActivateTenant(
        world.directory,
        world.registry,
        world.factory(tenant),
        world.ids,
        world.clock,
        lambda scope: frozenset({"DT1", "DT2"}),
    )


# -- tests ----------------------------------------------------------------------------------------


async def test_a_new_tenant_is_in_provisioning_with_its_own_chain_and_scope(world: World) -> None:
    result = await _create(world, NEW)

    assert result.created is True
    tenant = await world.directory.get(NEW)
    assert tenant is not None
    assert tenant.status is TenantStatus.PROVISIONING and tenant.epoch == 1
    assert tenant.hash_key_version == 1
    with bind_tenant(NEW):
        async with world.factory(NEW)() as uow:
            assert await uow.audit.verify_chain() is True
            entries = await uow.audit.records()
    assert [r.entry.use_case for r in entries] == ["CreateTenant"]
    assert entries[0].entry.actor.role is Role.PLATFORM_OPERATOR
    assert entries[0].entry.actor.practitioner_id == "operator-1"
    assert await _count(world, NEW, "List") == 1  # its scope list


async def test_each_new_chain_starts_from_its_own_genesis(
    world: World,
) -> None:
    await _create(world, NEW)
    from diucs.application.ports.outbound.audit import genesis_hash_for

    assert genesis_hash_for(NEW) != genesis_hash_for(OTHER)

    async def first_link(tenant: str) -> str:
        async def work(tx: AsyncManagedTransaction) -> str:
            row = await (
                await tx.run(
                    "MATCH (l:ChainLink {tenantId: $t}) RETURN l.previousHash AS p ORDER BY l.seq "
                    "LIMIT 1",
                    t=tenant,
                )
            ).single()
            assert row is not None
            return str(row["p"])

        return await read_tx(world.driver, work)

    assert await first_link(NEW) == genesis_hash_for(NEW)
    assert await first_link(OTHER) == genesis_hash_for(OTHER)


async def test_a_creation_that_stopped_is_finished_by_running_it_again(world: World) -> None:
    await _create(world, NEW)
    again = await _create(world, NEW)

    assert again.created is False
    rows = await _audit_rows(world, NEW)
    assert [r["useCase"] for r in rows] == ["CreateTenant", "CreateTenant"]
    assert json.loads(rows[1]["entry"])["snapshot"]["resumed"] is True
    with bind_tenant(NEW):
        async with world.factory(NEW)() as uow:
            assert await uow.audit.verify_chain() is True


async def test_an_id_another_tenant_holds_is_refused_and_nothing_is_written(world: World) -> None:
    before = await _audit_rows(world, OTHER)
    with pytest.raises(Conflict):
        await _create(world, OTHER, display_name="A different organisation")
    assert await _audit_rows(world, OTHER) == before


async def test_activation_of_a_fresh_tenant_lists_what_is_missing_and_changes_nothing(
    world: World,
) -> None:
    await _create(world, NEW)
    before = await _audit_rows(world, NEW)

    with as_tenant(NEW), pytest.raises(NotAllowed) as refused:
        await _activate_use_case(world, NEW).execute(ActivateTenantCommand(_operator(NEW)))

    for blocker in ("Configuration version approved", "Host set", "test text delivered"):
        assert blocker in str(refused.value)
    assert (await world.directory.get(NEW)).status is TenantStatus.PROVISIONING  # type: ignore[union-attr]
    assert await _audit_rows(world, NEW) == before
    assert NEW not in await world.directory.active_tenant_ids()


async def test_a_number_a_host_and_a_directory_another_tenant_holds_are_refused(
    world: World,
) -> None:
    await _create(world, NEW)
    factory_other = world.factory(OTHER)
    with as_tenant(OTHER):
        await SetTenantHost(world.directory, world.registry, factory_other, world.clock).execute(
            SetHostCommand(_operator(OTHER), "taken.example.org")
        )
        await RecordTenantNumber(
            world.directory, world.registry, factory_other, world.clock
        ).execute(RecordNumberCommand(_operator(OTHER), OTHER_NUMBER, SID, "Other sender"))
    factory = world.factory(NEW)
    before = await _count(world, NEW, "AuditEvent")

    with as_tenant(NEW):
        with pytest.raises(Conflict):
            await SetTenantHost(world.directory, world.registry, factory, world.clock).execute(
                SetHostCommand(_operator(NEW), "taken.example.org")
            )
        with pytest.raises(Conflict):
            await RecordTenantNumber(world.directory, world.registry, factory, world.clock).execute(
                RecordNumberCommand(_operator(NEW), OTHER_NUMBER, SID, "Sample sender")
            )

    assert await _count(world, NEW, "AuditEvent") == before
    assert await world.directory.host_of(NEW) is None
    assert await world.registry.numbers(NEW) == ()
    assert [n.e164 for n in await world.registry.numbers(OTHER)] == [OTHER_NUMBER]


async def test_another_role_and_an_operator_of_another_tenant_change_nothing(
    world: World,
) -> None:
    await _create(world, NEW)
    factory = world.factory(NEW)
    set_host = SetTenantHost(world.directory, world.registry, factory, world.clock)
    before = await _count(world, NEW, "AuditEvent")

    from diucs.application.tenancy import TenantMismatch

    with as_tenant(NEW):
        for role in (Role.OWNER, Role.LEAD, Role.TENANT_ADMIN, Role.SUPPORT):
            with pytest.raises(NotAllowed):
                await set_host.execute(SetHostCommand(_operator(NEW, role=role), "x.example.org"))
        with pytest.raises(TenantMismatch):
            await set_host.execute(SetHostCommand(_operator(OTHER), "x.example.org"))

    assert await world.directory.host_of(NEW) is None
    assert await _count(world, NEW, "AuditEvent") == before


async def test_the_whole_provisioning_ends_in_an_active_tenant_with_its_jobs_seeded(
    world: World,
) -> None:
    other_before = await _audit_rows(world, OTHER)
    await _create(world, NEW)
    await _configure(world, NEW)
    await _operator_steps(world, NEW)

    with as_tenant(NEW):
        invited = await _invite_use_case(world, NEW).execute(
            InviteTenantAdminCommand(_operator(NEW), MOBILE)
        )
    assert invited.expires_at > NOW

    with as_tenant(NEW):
        result = await _activate_use_case(world, NEW).execute(ActivateTenantCommand(_operator(NEW)))

    assert result.tenant_id == NEW and result.seeded == (True, True)
    tenant = await world.directory.get(NEW)
    assert tenant is not None and tenant.status is TenantStatus.ACTIVE
    assert tenant.activated_at == NOW and tenant.dsa_ref == "DSA-1"
    assert NEW in await world.directory.active_tenant_ids()
    with bind_tenant(NEW):
        async with world.factory(NEW)() as uow:
            for kind in (WorkKind.CRITERIA_REVIEW_REMINDER, WorkKind.INVARIANT_CHECK):
                works = await uow.scheduled_work.for_about(NEW, kind)
                assert [w.status for w in works] == [SCHEDULED]
            assert await uow.audit.verify_chain() is True
    used = [r["useCase"] for r in await _audit_rows(world, NEW)]
    assert used[0] == "CreateTenant" and used[-1] == "ActivateTenant"
    assert {"SetTenantHost", "RecordTenantNumber", "InviteTenantAdmin"} <= set(used)
    # The other tenant's chain did not move.
    assert await _audit_rows(world, OTHER) == other_before

    # A second activation is refused: the tenant is no longer in provisioning.
    with as_tenant(NEW), pytest.raises(NotAllowed):
        await _activate_use_case(world, NEW).execute(ActivateTenantCommand(_operator(NEW)))


async def test_the_invitation_holds_no_token_number_or_link_at_rest(world: World) -> None:
    await _create(world, NEW)
    await _configure(world, NEW)
    await _operator_steps(world, NEW)

    with as_tenant(NEW):
        await _invite_use_case(world, NEW).execute(InviteTenantAdminCommand(_operator(NEW), MOBILE))

    async def everything(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (
            await tx.run(
                "MATCH (n {tenantId: $t}) RETURN labels(n) AS labels, properties(n) AS p", t=NEW
            )
        ).data()

    rows = await read_tx(world.driver, everything)
    secrets = ("07700900123", "+447700900123", "07700 900123", "/i/")
    # The number lives in one place, the protected contact store; no other node holds it, and no
    # node of any kind holds the national form, the spaced form or a link path.
    holders = [
        r["labels"] for r in rows if any(x in json.dumps(r["p"], default=str) for x in secrets)
    ]
    assert holders == [["ProtectedContact"]]
    dump = json.dumps([r["p"] for r in rows if "ProtectedContact" not in r["labels"]], default=str)
    for secret in secrets:
        assert secret not in dump
    assert "07700900123" not in json.dumps(rows, default=str).replace("+447700900123", "")
    # The link token is the tenant's own purpose, by hash only; the contact is under its key.
    assert TENANT_ADMIN_INVITE in dump
    async with world.factory(NEW)() as uow:
        assert await uow.contacts.get_phone(invitation_key(_scope(NEW))) == "+447700900123"
    # Nothing of the other tenant holds an invitation.
    assert await _count(world, OTHER, "LinkToken") == 0


def _scope(tenant: str) -> Any:
    from diucs.application.tenancy import ScopeId

    return ScopeId.tenant(tenant)


async def test_the_registry_is_also_touched_only_for_the_tenant_acted_on(world: World) -> None:
    other_before = await world.directory.get(OTHER)
    await _create(world, NEW)
    await _configure(world, NEW)
    await _operator_steps(world, NEW)

    assert await world.directory.get(OTHER) == other_before
    assert [n.e164 for n in await world.registry.numbers(NEW)] == [NUMBER]
    assert await world.registry.numbers(OTHER) == ()
    assert await world.directory.by_entra_directory(DIRECTORY_ID) == await world.directory.get(NEW)
