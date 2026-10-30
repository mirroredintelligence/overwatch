"""The public tenant profile on real Neo4j with two tenants (TEN-040, DEC-134 item 3).

Each tenant owns one host in the tenant directory. A request is answered for the tenant its host
names and for no other: its display name, its wording and its coordination phone, never the other
tenant's. A host nobody owns and a tenant that is not active answer as a path that is not there.
Written in the build wave; run in the verification stage (one Neo4j at a time). Synthetic values.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.outbound.graph_store.tenant_config_repository import (
    Neo4jTenantConfigRepository,
)
from diucs.adapters.outbound.graph_store.tenant_directory import tenant_properties
from diucs.application.rate_limits import PUBLIC_REQUESTS_PER_ADDRESS
from diucs.bootstrap.container import Container
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    TenantConfig,
    TenantContact,
    TenantStatus,
)
from tests.support.neo4j import write_tx
from tests.support.tenancy import as_tenant
from tests.support.tenant_samples import make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
PATH = "/public/tenant-profile"


def _wording(name: str) -> dict[str, Any]:
    return {
        "systemName": f"{name} capacity",
        "referralSystemName": f"{name} referrals",
        "coordinationTeamName": f"{name} coordination team",
    }


async def _set_host_and_name(
    driver: AsyncDriver, tenant: str, host: str, name: str, status: TenantStatus
) -> None:
    props = tenant_properties(make_tenant(status, id=tenant, display_name=name))

    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "MATCH (t:Tenant {id: $id}) SET t += $props, t.host = $host",
            id=tenant,
            props=props,
            host=host,
        )

    await write_tx(driver, work)


async def _configure(driver: AsyncDriver, tenant: str, name: str, phone: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = Neo4jTenantConfigRepository(tx)

        def config(status: ConfigStatus, **fields: Any) -> TenantConfig:
            return TenantConfig(
                version=1,
                status=status,
                values=_wording(name),
                created_at=T0,
                created_by_ref="prac-lead-1",
                **fields,
            )

        await repo.add_version(config(ConfigStatus.DRAFT))
        await repo.move_version(
            config(ConfigStatus.PENDING_APPROVAL, approved_by_refs=("prac-owner-1",)),
            ConfigStatus.DRAFT,
        )
        await repo.move_version(
            config(
                ConfigStatus.CURRENT,
                effective_from=T0,
                approved_by_refs=("prac-owner-1", "prac-owner-2"),
            ),
            ConfigStatus.PENDING_APPROVAL,
        )
        await repo.put_contact(TenantContact(ContactKind.COORDINATION_PHONE, "Coordination", phone))
        await repo.put_contact(
            TenantContact(ContactKind.SUPPORT_EMAIL, "Support", f"support@{name}.example.test")
        )

    with as_tenant(tenant):
        await write_tx(driver, work)


@pytest_asyncio.fixture(loop_scope="session")
async def hosts(
    neo4j_driver: AsyncDriver, edge_tenants: None, tenant_id: str, other_tenant_id: str
) -> dict[str, str]:
    """A host for each run tenant (the tenant id is in it, so runs never share one), the tenants'
    own names, wording and phones."""
    host_a, host_b = f"{tenant_id}.example.test", f"{other_tenant_id}.example.test"
    await _set_host_and_name(neo4j_driver, tenant_id, host_a, "Alpha ICB", TenantStatus.ACTIVE)
    await _set_host_and_name(
        neo4j_driver, other_tenant_id, host_b, "Bravo ICB", TenantStatus.ACTIVE
    )
    await _configure(neo4j_driver, tenant_id, "alpha", "01234 567890")
    await _configure(neo4j_driver, other_tenant_id, "bravo", "01234 111222")
    return {"a": host_a, "b": host_b}


@pytest_asyncio.fixture(loop_scope="session")
async def client(test_container: Container, hosts: dict[str, str]) -> AsyncIterator[AsyncClient]:
    app: FastAPI = create_app(test_container)
    transport = ASGITransport(app=app, client=("203.0.113.9", 4321), raise_app_exceptions=False)
    async with AsyncClient(transport=transport) as http:
        yield http


async def test_each_host_is_answered_with_its_own_tenants_profile_only(
    client: AsyncClient, hosts: dict[str, str]
) -> None:
    first = await client.get(f"http://{hosts['a']}{PATH}")
    second = await client.get(f"http://{hosts['b']}{PATH}")

    assert first.status_code == second.status_code == 200
    assert first.json()["displayName"] == "Alpha ICB"
    assert first.json()["wording"]["systemName"] == "alpha capacity"
    assert first.json()["coordinationPhone"] == "01234 567890"
    assert second.json()["displayName"] == "Bravo ICB"
    assert second.json()["wording"]["coordinationTeamName"] == "bravo coordination team"
    assert second.json()["coordinationPhone"] == "01234 111222"
    for hidden in ("Bravo", "bravo", "01234 111222"):
        assert hidden not in first.text
    for hidden in ("Alpha", "alpha", "01234 567890"):
        assert hidden not in second.text


async def test_a_header_or_query_naming_the_other_tenant_changes_nothing(
    client: AsyncClient, hosts: dict[str, str], other_tenant_id: str
) -> None:
    response = await client.get(
        f"http://{hosts['a']}{PATH}?tenant={other_tenant_id}",
        headers={"X-Forwarded-Host": hosts["b"], "X-Tenant": other_tenant_id},
    )

    assert response.json()["displayName"] == "Alpha ICB"


async def test_an_unowned_host_and_a_suspended_tenant_answer_as_a_missing_path(
    client: AsyncClient, hosts: dict[str, str], neo4j_driver: AsyncDriver, other_tenant_id: str
) -> None:
    missing = await client.get(f"http://{hosts['a']}/public/nothing-here")
    unowned = await client.get(f"http://nobody-{hosts['a']}{PATH}")
    await _set_host_and_name(
        neo4j_driver, other_tenant_id, hosts["b"], "Bravo ICB", TenantStatus.SUSPENDED
    )
    suspended = await client.get(f"http://{hosts['b']}{PATH}")

    for response in (unowned, suspended):
        assert response.status_code == 404
        assert response.content == missing.content


async def test_the_limit_is_per_address_in_the_platform_namespace_across_both_tenants(
    client: AsyncClient, hosts: dict[str, str]
) -> None:
    for number in range(PUBLIC_REQUESTS_PER_ADDRESS):
        host = hosts["a"] if number % 2 == 0 else hosts["b"]
        assert (await client.get(f"http://{host}{PATH}")).status_code == 200

    response = await client.get(f"http://{hosts['a']}{PATH}")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
