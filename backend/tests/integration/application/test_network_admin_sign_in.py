"""How the owner's network administrator signs in, on a real Neo4j (TEN-080, DEC-1260).

The real exchange (`ExchangeStaffToken` over the graph's tenant configuration and the network
registry), the real registry, and the real REST edge with the administration routes. The identity
verifier is the fake (Entra is external). What is proved:

- the owner's person, in a group of the owner's directory that the owner mapped to `network-admin`,
  gets the role once the owner owns an active network, and not before;
- a member of the network with the same mapping gets the one refusal, and so does a tenant that is
  in no network: the registry decides, never the token or the mapping;
- the issued token administers the owner's network over HTTP and no other: another owner's network
  reads as a missing one (the same 404 body), for a read and for a write;
- the operator's `MapNetworkAdminGroup` writes in the owner's scope only and a member is not found.
"""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.inbound.fhir_rest.routes_network_admin import NetworkAdminServices
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_config_repository import (
    Neo4jTenantConfigRepository,
)
from diucs.adapters.testing.fake_identity_verifier import FakeIdentityVerifier
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.application.ports.outbound.identity_verifier import Audience, VerifiedIdentity
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.exchange_token import (
    ACCOUNT_REF_SECRET,
    SIGNING_SECRET,
    ExchangeRefused,
    ExchangeStaffCommand,
    ExchangeStaffToken,
)
from diucs.application.use_cases.network_admin import (
    CreateNetworkCommand,
    MapNetworkAdminGroup,
    MapNetworkAdminGroupCommand,
    RegistryNetworkOwnership,
    owns_active_network,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotFound
from diucs.domain.model.tenant_records import (
    BindingStatus,
    EntraBinding,
    MappingStatus,
    RoleMapping,
)
from diucs.domain.rules.bff_token import decode_bff_token
from tests.support.edge import EdgeContainer, active_tenants
from tests.support.neo4j import read_tx, write_tx
from tests.support.network_admin_fakes import active_tenant, person
from tests.support.network_admin_rig import AdminRig
from tests.support.network_world import world_ids
from tests.support.tenancy import RunIdentity, as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

# The signing secret is the edge's own name for it (`bff-jwt`), so a token the exchange issues is one
# the edge accepts.
assert SIGNING_SECRET == BFF_SECRET_NAME
ACCOUNT_KEY = b"synthetic-account-ref-key-for-the-network-admin-it-01"
D_OWNER = "11111111-1111-4111-8111-111111111111"
D_MEMBER = "22222222-2222-4222-8222-222222222222"
G_ADMINS = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
G_ADMINS_OF_MEMBER = "ffffffff-ffff-4fff-8fff-ffffffffffff"
OID = "33333333-3333-4333-8333-333333333333"
OWNER_CREDENTIAL = "synthetic-credential-owner-admin"
MEMBER_CREDENTIAL = "synthetic-credential-member-admin"
OUTSIDER_CREDENTIAL = "synthetic-credential-outsider-admin"


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
    yield built
    await built.cleanup()


def _secrets() -> FixedSecretStore:
    return FixedSecretStore({SIGNING_SECRET: TEST_BFF_SECRET, ACCOUNT_REF_SECRET: ACCOUNT_KEY})


async def _configure(rig: AdminRig, tenant: str, directory: str, group: str, role: Role) -> None:
    """A verified directory for the tenant and one group mapped to `role`, as the tenant's own
    administrator (or the operator, for the first one) would leave it."""

    async def work(tx: AsyncManagedTransaction) -> None:
        repo = Neo4jTenantConfigRepository(tx)  # type: ignore[arg-type]
        await repo.put_binding(
            EntraBinding(
                directory_id=directory,
                status=BindingStatus.VERIFIED,
                verified_at=rig.clock.now(),
                verified_by_ref="operator-ref-1",
            )
        )
        await repo.put_role_mapping(RoleMapping(group, role, MappingStatus.ACTIVE))

    with as_tenant(tenant):
        await write_tx(rig.driver, work)


def _identity(directory: str, group: str) -> VerifiedIdentity:
    return VerifiedIdentity(
        directory_id=directory,
        object_id=OID,
        group_ids=frozenset({group}),
        app_roles=frozenset(),
    )


def _verifier() -> FakeIdentityVerifier:
    verifier = FakeIdentityVerifier()
    verifier.accepts(OWNER_CREDENTIAL, _identity(D_OWNER, G_ADMINS), Audience.STAFF)
    verifier.accepts(MEMBER_CREDENTIAL, _identity(D_MEMBER, G_ADMINS_OF_MEMBER), Audience.STAFF)
    verifier.accepts(OUTSIDER_CREDENTIAL, _identity(D_MEMBER, G_ADMINS_OF_MEMBER), Audience.STAFF)
    return verifier


def _exchange(rig: AdminRig) -> ExchangeStaffToken:
    return ExchangeStaffToken(
        rig.tenant_factory,
        rig.clock,
        _verifier(),
        _secrets(),
        RegistryNetworkOwnership(rig.registry),
    )


async def _sign_in(rig: AdminRig, tenant: str, credential: str) -> str:
    with bind_tenant(tenant):
        issued = await _exchange(rig).execute(
            ExchangeStaffCommand(tenant=active_tenant(tenant), credential=credential)
        )
    assert issued.role is Role.NETWORK_ADMIN
    return issued.token


def _app(rig: AdminRig, *tenants: str) -> FastAPI:
    services = NetworkAdminServices(
        query=rig.admin_query,
        invite=rig.invite,
        accept=rig.accept,
        leave=rig.leave,
        remove=rig.remove,
        agreement=rig.record_agreement,
        grants=rig.grant_query,
        propose=rig.propose,
        approve=rig.approve,
        decline=rig.decline,
        end=rig.end_grant,
        revise=rig.revise,
        listings=rig.listing_query,
        request_listing=rig.request_listing,
        decide_listing=rig.decide_listing,
    )
    container = EdgeContainer(tenants=active_tenants(*tenants), clock=rig.clock)
    app: FastAPI = create_app(container)  # type: ignore[arg-type]
    app.state.secrets = _secrets()
    app.state.network_admin = services
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def _mappings(rig: AdminRig, tenant: str) -> list[RoleMapping]:
    async def work(tx: AsyncManagedTransaction) -> list[RoleMapping]:
        return list(await Neo4jTenantConfigRepository(tx).role_mappings())  # type: ignore[arg-type]

    with as_tenant(tenant):
        return await read_tx(rig.driver, work)


async def test_the_role_is_given_once_the_owner_owns_an_active_network_and_not_before(
    rig: AdminRig,
) -> None:
    owner = rig.ids.owner
    await _configure(rig, owner, D_OWNER, G_ADMINS, Role.NETWORK_ADMIN)

    with pytest.raises(ExchangeRefused), bind_tenant(owner):
        await _exchange(rig).execute(
            ExchangeStaffCommand(tenant=active_tenant(owner), credential=OWNER_CREDENTIAL)
        )
    assert await owns_active_network(rig.registry, owner) is False

    await rig.make_network()

    assert await owns_active_network(rig.registry, owner) is True
    token = await _sign_in(rig, owner, OWNER_CREDENTIAL)
    claims = decode_bff_token(token, TEST_BFF_SECRET, rig.clock.now())
    assert (claims.tenant, claims.role) == (owner, Role.NETWORK_ADMIN)
    assert claims.networks == frozenset()  # the token names no network: the registry is asked


async def test_a_member_and_an_outsider_with_the_same_mapping_get_the_one_refusal(
    rig: AdminRig,
) -> None:
    await rig.make_network()
    member = rig.ids.members[0]
    await rig.join(member, rig.people.admins[0])
    await _configure(rig, member, D_MEMBER, G_ADMINS_OF_MEMBER, Role.NETWORK_ADMIN)

    with pytest.raises(ExchangeRefused) as member_refused, bind_tenant(member):
        await _exchange(rig).execute(
            ExchangeStaffCommand(tenant=active_tenant(member), credential=MEMBER_CREDENTIAL)
        )

    outsider = rig.ids.outsider
    await _configure(rig, outsider, D_MEMBER, G_ADMINS_OF_MEMBER, Role.NETWORK_ADMIN)
    with pytest.raises(ExchangeRefused) as outsider_refused, bind_tenant(outsider):
        await _exchange(rig).execute(
            ExchangeStaffCommand(tenant=active_tenant(outsider), credential=OUTSIDER_CREDENTIAL)
        )

    assert str(member_refused.value) == str(outsider_refused.value)
    assert str(member_refused.value) == "Your account does not have access."


async def test_the_owners_administrator_administers_its_network_and_not_another_owners(
    rig: AdminRig,
) -> None:
    owner, outsider = rig.ids.owner, rig.ids.outsider
    await rig.make_network()
    # The outsider owns another network (the operator creates it, in the outsider's own scope).
    with bind_tenant(outsider):
        await rig.create_network.execute(
            CreateNetworkCommand(
                actor=person(outsider, Role.PLATFORM_OPERATOR, "operator"),
                network_id=rig.ids.other_network,
                name="Another network",
                agreement_reference="DSA-2026-9",
                agreement_version=1,
                system_name="Another board",
                pathway_name="Another pathway",
            )
        )
    await _configure(rig, owner, D_OWNER, G_ADMINS, Role.NETWORK_ADMIN)
    token = await _sign_in(rig, owner, OWNER_CREDENTIAL)
    mine = f"/network-admin/network/{rig.ids.network}"
    theirs = f"/network-admin/network/{rig.ids.other_network}"
    unknown = "/network-admin/network/net-nothing-here"

    async with _client(_app(rig, owner, outsider)) as client:
        own_members = await client.get(f"{mine}/members", headers=_bearer(token))
        other_members = await client.get(f"{theirs}/members", headers=_bearer(token))
        none_members = await client.get(f"{unknown}/members", headers=_bearer(token))
        other_agreement = await client.post(
            f"{theirs}/agreement",
            json={"reference": "DSA-2026-10", "version": 2},
            headers=_bearer(token),
        )
        other_invite = await client.post(
            f"{theirs}/members", json={"tenant_id": rig.ids.members[0]}, headers=_bearer(token)
        )
        other_grants = await client.get(f"{theirs}/grants", headers=_bearer(token))
        other_listings = await client.get(f"{theirs}/listings", headers=_bearer(token))
        networks = await client.get("/network-admin/networks", headers=_bearer(token))

    assert own_members.status_code == 200
    assert [m["role"] for m in own_members.json()["members"]] == ["owner"]
    for refused in (other_members, other_agreement, other_invite, other_grants, other_listings):
        assert refused.status_code == 404
    # What is refused is not told apart from what does not exist.
    assert other_members.content == none_members.content
    assert [n["id"] for n in networks.json()["networks"]] == [rig.ids.network]
    # Nothing was changed in the other network.
    other = await rig.registry.get_network(rig.ids.other_network)
    assert other is not None and other.network.agreement is not None
    assert other.network.agreement.version == 1
    assert [m.member_tenant_id for m in await rig.registry.memberships(rig.ids.other_network)] == [
        outsider
    ]


async def test_the_operators_mapping_writes_in_the_owners_scope_only(rig: AdminRig) -> None:
    owner, member = rig.ids.owner, rig.ids.members[0]
    await rig.make_network()
    await rig.join(member, rig.people.admins[0])
    use_case = MapNetworkAdminGroup(rig.registry, rig.tenant_factory, rig.clock)
    operator = person(owner, Role.PLATFORM_OPERATOR, "operator")

    with bind_tenant(owner):
        first = await use_case.execute(MapNetworkAdminGroupCommand(operator, G_ADMINS))
        again = await use_case.execute(MapNetworkAdminGroupCommand(operator, G_ADMINS))
    with pytest.raises(NotFound), bind_tenant(member):
        await use_case.execute(
            MapNetworkAdminGroupCommand(person(member, Role.PLATFORM_OPERATOR, "op"), G_ADMINS)
        )

    assert (first.created, again.created) == (True, False)
    assert [(m.group_object_id, m.role) for m in await _mappings(rig, owner)] == [
        (G_ADMINS, Role.NETWORK_ADMIN)
    ]
    assert await _mappings(rig, member) == []
    chain = await rig.audit_use_cases(owner)
    assert chain.count("MapNetworkAdminGroup") == 1  # the repeat changed nothing and wrote nothing
    assert "MapNetworkAdminGroup" not in await rig.audit_use_cases(member)
