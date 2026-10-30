"""The REST edge on the real tenant directory, with two tenants (TEN-018, H-T23).

The harness seeds an active record for the run tenant and for the second tenant (`edge_tenants`).
A request is bound to the tenant its token names and to no other; a tenant with no record, a
suspended one and a token from before a suspend are all the one 401. The unit tests of the same
behaviour (`tests/unit/adapters/inbound/fhir_rest/test_edge_binding.py`) use a fake directory; this
file proves the same through `Neo4jTenantDirectory` and the container's clock.
"""

from datetime import timedelta
from typing import Annotated, Any

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import AsyncClient
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME, current_actor
from diucs.adapters.outbound.graph_store.tenant_directory import tenant_properties
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.application.actor import Actor
from diucs.application.tenancy import current_scope_or_none
from diucs.bootstrap.container import Container
from diucs.domain.codes import Role
from diucs.domain.model.tenant import SuspendMode, SuspendReason, TenantStatus
from tests.support.api import token_headers
from tests.support.neo4j import write_tx
from tests.support.tenant_samples import make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

WHOAMI = "/fhir/test/edge-whoami"


@pytest_asyncio.fixture(loop_scope="session")
async def edge_app(api_app: FastAPI) -> FastAPI:
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})

    @api_app.get(WHOAMI)
    async def edge_whoami(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, Any]:
        scope = current_scope_or_none()
        return {"actor": actor.tenant_id, "scope": None if scope is None else str(scope)}

    return api_app


async def test_each_tenants_token_is_bound_to_its_own_tenant(
    edge_app: FastAPI, api_client: AsyncClient, tenant_id: str, other_tenant_id: str
) -> None:
    mine = await api_client.get(WHOAMI, headers=token_headers(tenant_id))
    theirs = await api_client.get(WHOAMI, headers=token_headers(other_tenant_id))

    assert mine.json() == {"actor": tenant_id, "scope": tenant_id}
    assert theirs.json() == {"actor": other_tenant_id, "scope": other_tenant_id}


async def test_a_request_cannot_choose_a_tenant_other_than_its_tokens(
    edge_app: FastAPI, api_client: AsyncClient, tenant_id: str, other_tenant_id: str
) -> None:
    response = await api_client.get(
        WHOAMI,
        headers={**token_headers(tenant_id), "X-Tenant": other_tenant_id},
        params={"tenant": other_tenant_id},
    )

    assert response.json() == {"actor": tenant_id, "scope": tenant_id}


async def test_a_token_for_a_tenant_with_no_record_is_refused(
    edge_app: FastAPI, api_client: AsyncClient
) -> None:
    response = await api_client.get(WHOAMI, headers=token_headers("tenant-nobody"))

    assert response.status_code == 401


async def test_a_suspend_refuses_the_tenants_token_within_a_minute(
    edge_app: FastAPI,
    api_client: AsyncClient,
    neo4j_driver: AsyncDriver,
    test_container: Container,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    before = await api_client.get(WHOAMI, headers=token_headers(tenant_id))
    suspended = make_tenant(
        TenantStatus.SUSPENDED,
        id=tenant_id,
        epoch=2,
        suspend_mode=SuspendMode.BLOCKED,
        suspend_reason=SuspendReason.SECURITY_INCIDENT,
        suspended_at=test_container.clock.now(),
    )

    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "MATCH (t:Tenant {id: $id}) SET t += $props",
            id=tenant_id,
            props=tenant_properties(suspended),
        )

    await write_tx(neo4j_driver, work)
    test_container.clock.advance(timedelta(seconds=60))  # type: ignore[attr-defined]
    after = await api_client.get(WHOAMI, headers=token_headers(tenant_id))
    other = await api_client.get(WHOAMI, headers=token_headers(other_tenant_id))

    assert before.status_code == 200
    assert after.status_code == 401
    assert other.status_code == 200  # the other tenant is untouched


async def test_the_platform_operator_never_reaches_a_data_route(
    edge_app: FastAPI, api_client: AsyncClient, tenant_id: str
) -> None:
    response = await api_client.get(
        WHOAMI, headers=token_headers(tenant_id, Role.PLATFORM_OPERATOR)
    )

    assert response.status_code == 401
