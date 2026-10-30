"""The token exchange on real Neo4j with two tenants (TEN-043, DEC-522 to DEC-527).

Each tenant owns one host, binds its own Entra directory (verified) and maps one group to a role.
The identity verifier is the fake (Entra is an external provider); everything else is the real
composition: the tenant directory, the configuration records, the unit of work and the audit chain.
What is proved:

- a member signed in through a tenant's directory gets a token for the tenant of the HOST, with the
  role the tenant's mapping gives, and the real REST edge accepts it and binds that tenant;
- the same member on the other tenant's host gets the one refusal and no audit entry is written
  there; a directory bound to nobody gets nothing anywhere;
- the token carries the tenant's epoch: after a suspend and resume the old token is refused at the
  edge and a new exchange gets a token for the new epoch;
- a suspended tenant's host answers as an unknown host;
- the exchange writes one audit entry in the tenant's own chain, holding the role and epoch only;
- a paired wall screen exchanges its device token for a wall token for its own tenant, and another
  tenant's host does not know it.

Written in build wave 5 and not run there: the orchestrator runs the full integration suite once on
the merged tip. Synthetic values only.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import current_actor
from diucs.adapters.inbound.fhir_rest.routes_auth import (
    DEVICE_PATH,
    FORBIDDEN_TEXT,
    STAFF_PATH,
    ExchangeDeps,
)
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_config_repository import (
    Neo4jTenantConfigRepository,
)
from diucs.adapters.testing.fake_identity_verifier import FakeIdentityVerifier
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET, PHONE_HASH_SECRET
from diucs.application.ports.outbound.identity_verifier import Audience, VerifiedIdentity
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.tenancy import current_scope_or_none
from diucs.application.use_cases.exchange_token import ACCOUNT_REF_SECRET, SIGNING_SECRET
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import Role
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from diucs.domain.model.tenant_records import (
    BindingStatus,
    EntraBinding,
    MappingStatus,
    RoleMapping,
)
from diucs.domain.rules.bff_token import decode_bff_token
from diucs.domain.rules.tokens import hash_token
from tests.support.api import seed_edge_tenants
from tests.support.neo4j import ThrowawayNeo4j, write_tx
from tests.support.tenancy import as_tenant
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SIGNING = b"synthetic-bff-signing-secret-for-the-exchange-it-01"
ACCOUNT_KEY = b"synthetic-account-ref-key-for-the-exchange-it-0002"
PLATFORM_KEY = b"synthetic-platform-key-for-the-exchange-integration"
D_A = "11111111-1111-4111-8111-111111111111"
D_B = "22222222-2222-4222-8222-222222222222"
D_NOBODY = "55555555-5555-4555-8555-555555555555"
OID = "33333333-3333-4333-8333-333333333333"
G_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
G_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CREDENTIAL = "synthetic-entra-id-token-0001"
DEVICE_TOKEN = "AbCdEfGhIjKlMnOpQrStUvW"


def _secrets() -> FixedSecretStore:
    return FixedSecretStore(
        {
            SIGNING_SECRET: SIGNING,
            ACCOUNT_REF_SECRET: ACCOUNT_KEY,
            DEVICE_TOKEN_SECRET: PLATFORM_KEY,
            LINK_TOKEN_SECRET: PLATFORM_KEY,
            PHONE_HASH_SECRET: PLATFORM_KEY,
        }
    )


@pytest_asyncio.fixture(loop_scope="session")
async def container(
    harness_container: ThrowawayNeo4j, clean_graph: None
) -> AsyncIterator[Container]:
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=FixedClock(NOW),
            ids=SequentialIds(),
            neo4j=connection,
            secrets=_secrets(),
        )
    finally:
        await connection.close()


async def _host(driver: AsyncDriver, tenant: str, host: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run("MATCH (t:Tenant {id: $id}) SET t.host = $host", id=tenant, host=host)

    await write_tx(driver, work)


async def _configure(driver: AsyncDriver, tenant: str, directory: str, group: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = Neo4jTenantConfigRepository(tx)  # type: ignore[arg-type]
        await repo.put_binding(
            EntraBinding(
                directory_id=directory,
                status=BindingStatus.VERIFIED,
                verified_at=NOW,
                verified_by_ref="operator-ref-1",
            )
        )
        await repo.put_role_mapping(RoleMapping(group, Role.LEAD, MappingStatus.ACTIVE))

    with as_tenant(tenant):
        await write_tx(driver, work)


@pytest_asyncio.fixture(loop_scope="session")
async def hosts(
    container: Container,
    neo4j_driver: AsyncDriver,
    edge_tenants: None,
    tenant_id: str,
    other_tenant_id: str,
) -> dict[str, str]:
    """Two active tenants with a host each, an audit chain head each, a verified directory each and
    one group mapped to `lead`."""
    host_a, host_b = f"{tenant_id}.example.test", f"{other_tenant_id}.example.test"
    await _host(neo4j_driver, tenant_id, host_a)
    await _host(neo4j_driver, other_tenant_id, host_b)
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    await _configure(neo4j_driver, tenant_id, D_A, G_A)
    await _configure(neo4j_driver, other_tenant_id, D_B, G_B)
    return {"a": host_a, "b": host_b}


def _identity(directory: str, group: str) -> VerifiedIdentity:
    return VerifiedIdentity(
        directory_id=directory,
        object_id=OID,
        group_ids=frozenset({group}),
        app_roles=frozenset(),
    )


@pytest_asyncio.fixture(loop_scope="session")
async def app(container: Container, hosts: dict[str, str]) -> FastAPI:
    verifier = FakeIdentityVerifier()
    verifier.accepts(CREDENTIAL, _identity(D_A, G_A), Audience.STAFF)
    verifier.accepts("credential-of-b", _identity(D_B, G_B), Audience.STAFF)
    verifier.accepts("credential-of-nobody", _identity(D_NOBODY, G_A), Audience.STAFF)
    built = create_app(container)
    built.state.secrets = _secrets()
    built.state.token_exchange = ExchangeDeps(verifier=verifier, operator_directory_id=None)

    @built.get("/probe")
    async def probe(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, Any]:
        scope = current_scope_or_none()
        return {"scope": None if scope is None else str(scope), "role": actor.role.value}

    return built


def _client(app: FastAPI, host: str) -> AsyncClient:
    transport = ASGITransport(app=app, client=("203.0.113.9", 4321), raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url=f"http://{host}")


async def _exchange(c: AsyncClient, credential: str = CREDENTIAL) -> Any:
    return await c.post(STAFF_PATH, json={"idToken": credential})


async def test_a_member_gets_a_token_for_the_tenant_of_the_host_and_the_edge_accepts_it(
    app: FastAPI, hosts: dict[str, str], tenant_id: str
) -> None:
    async with _client(app, hosts["a"]) as c:
        response = await _exchange(c)
        token = response.json()["token"]
        probe = await c.get("/probe", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["role"] == "lead"
    claims = decode_bff_token(token, SIGNING, NOW)
    assert (claims.tenant, claims.role) == (tenant_id, Role.LEAD)
    assert probe.json() == {"scope": tenant_id, "role": "lead"}


async def test_each_member_gets_a_token_for_their_own_tenants_host_only(
    app: FastAPI, hosts: dict[str, str], tenant_id: str, other_tenant_id: str
) -> None:
    async with _client(app, hosts["b"]) as c:
        own = await _exchange(c, "credential-of-b")
        foreign = await _exchange(c, CREDENTIAL)  # tenant A's member, tenant B's host
    async with _client(app, hosts["a"]) as c:
        foreign_the_other_way = await _exchange(c, "credential-of-b")

    assert decode_bff_token(own.json()["token"], SIGNING, NOW).tenant == other_tenant_id
    assert foreign.status_code == foreign_the_other_way.status_code == 403
    assert foreign.content == foreign_the_other_way.content
    assert FORBIDDEN_TEXT in foreign.text


async def test_a_directory_bound_to_nobody_gets_nothing_on_any_host(
    app: FastAPI, hosts: dict[str, str]
) -> None:
    async with _client(app, hosts["a"]) as a, _client(app, hosts["b"]) as b:
        first = await _exchange(a, "credential-of-nobody")
        second = await _exchange(b, "credential-of-nobody")

    assert first.status_code == second.status_code == 403
    assert first.content == second.content


async def test_a_refused_exchange_writes_nothing_in_either_tenants_chain(
    app: FastAPI,
    container: Container,
    hosts: dict[str, str],
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    async def chain_length(tenant: str) -> int:
        with as_tenant(tenant):
            async with container.uow_factory() as uow:
                return len(await uow.audit.records())

    before = (await chain_length(tenant_id), await chain_length(other_tenant_id))
    async with _client(app, hosts["b"]) as c:
        await _exchange(c, CREDENTIAL)
    after = (await chain_length(tenant_id), await chain_length(other_tenant_id))

    assert after == before


async def test_a_granted_exchange_writes_one_entry_in_the_tenants_own_chain(
    app: FastAPI, container: Container, hosts: dict[str, str], tenant_id: str, other_tenant_id: str
) -> None:
    async def records(tenant: str) -> list[Any]:
        with as_tenant(tenant):
            async with container.uow_factory() as uow:
                found = await uow.audit.records()
                assert await uow.audit.verify_chain()
                return list(found)

    other_before = len(await records(other_tenant_id))
    before = len(await records(tenant_id))
    async with _client(app, hosts["a"]) as c:
        await _exchange(c)
    after = await records(tenant_id)

    assert len(after) == before + 1
    entry = after[-1].entry
    assert (entry.use_case, entry.action) == ("ExchangeStaffToken", "token-issued")
    assert entry.snapshot == {"role": "lead", "epoch": 1}
    assert len(await records(other_tenant_id)) == other_before
    assert OID not in repr(entry)


async def test_the_token_carries_the_epoch_so_a_suspend_and_resume_ends_the_old_token(
    app: FastAPI, neo4j_driver: AsyncDriver, hosts: dict[str, str], tenant_id: str
) -> None:
    async def set_epoch(epoch: int) -> None:
        await seed_edge_tenants(neo4j_driver, tenant_id, epoch=epoch)

    async with _client(app, hosts["a"]) as c:
        old = (await _exchange(c)).json()["token"]
        await set_epoch(2)  # a resume bumps the epoch (DEC-250)
        try:
            refused = await c.get("/probe", headers={"Authorization": f"Bearer {old}"})
            new = (await _exchange(c)).json()["token"]
            accepted = await c.get("/probe", headers={"Authorization": f"Bearer {new}"})
        finally:
            await set_epoch(1)

    assert refused.status_code == 401
    assert decode_bff_token(new, SIGNING, NOW).epoch == 2
    assert accepted.status_code == 200


async def test_a_suspended_tenants_host_answers_as_an_unknown_host(
    app: FastAPI, neo4j_driver: AsyncDriver, hosts: dict[str, str], tenant_id: str
) -> None:
    async def status(value: str) -> None:
        async def work(tx: AsyncManagedTransaction) -> None:
            await tx.run(
                "MATCH (t:Tenant {id: $id}) SET t.status = $status, t.suspendMode = $mode, "
                "t.suspendedAt = $at, t.suspendReason = $reason",
                id=tenant_id,
                status=value,
                mode="blocked" if value == "suspended" else None,
                at=NOW if value == "suspended" else None,
                reason="contract" if value == "suspended" else None,
            )

        await write_tx(neo4j_driver, work)

    async with _client(app, "no-such-host.example.test") as unknown_client:
        unknown = await _exchange(unknown_client)
    await status("suspended")
    try:
        async with _client(app, hosts["a"]) as c:
            suspended = await _exchange(c)
    finally:
        await status("active")

    assert suspended.status_code == unknown.status_code == 404
    assert suspended.content == unknown.content


async def test_a_paired_screen_gets_a_wall_token_for_its_own_tenant_and_no_other_host_knows_it(
    app: FastAPI,
    container: Container,
    hosts: dict[str, str],
    tenant_id: str,
) -> None:
    with as_tenant(tenant_id):
        async with container.uow_factory() as uow:
            await uow.devices.save(
                Device(
                    id="screen-ten043-a",
                    status=DeviceStatus.ACTIVE,
                    name="Ward screen",
                    location=None,
                    device_type=DeviceType.WALL_DISPLAY,
                    token_hash=hash_token(DEVICE_TOKEN, container.secrets.get(DEVICE_TOKEN_SECRET)),
                    board_scope=BoardScope.TENANT,
                )
            )
            await uow.commit()
    headers = {"Authorization": f"Bearer {DEVICE_TOKEN}"}

    async with _client(app, hosts["a"]) as a:
        granted = await a.post(DEVICE_PATH, json={}, headers=headers)
        probe = await a.get(
            "/probe", headers={"Authorization": f"Bearer {granted.json()['token']}"}
        )
    async with _client(app, hosts["b"]) as b:
        elsewhere = await b.post(DEVICE_PATH, json={}, headers=headers)

    assert granted.status_code == 200
    assert probe.json() == {"scope": tenant_id, "role": "wall"}
    assert elsewhere.status_code == 404
