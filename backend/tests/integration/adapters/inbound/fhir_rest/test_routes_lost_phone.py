"""The lost-phone wait shows the SPOA's number (W7C, DEC-825, H-459).

While the new phone waits for the shift lead's call-back, the screen tells the reporter to phone
the SPOA. The number is the tenant's coordination phone, read in the tenant the host names: never
another tenant's, never a default, and none when the tenant has set none. A refused code carries
no number. Samples only.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.tenancy import bind_tenant
from diucs.bootstrap.container import Container
from diucs.domain.model.tenant import ContactKind, TenantContact
from tests.integration.adapters.inbound.fhir_rest.reporter_rig import (
    CODE,
    MOBILE,
    NOW,
    OTHER_DEVICE,
    build_app,
    client_for,
    hold_code,
    open_container,
    seed_world,
)
from tests.integration.adapters.inbound.link_pages.conftest import seed_tenant_host
from tests.support.link_rig import HOST_A, HOST_B
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.uow import ensure_audit_heads

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.no_tenant]

MOBILE_B = "07700 900456"
SPOA_A = "01305 000111"
SPOA_B = "01202 000222"


@pytest_asyncio.fixture(loop_scope="session")
async def two_container(
    harness_container: ThrowawayNeo4j, clean_graph: None, tenant_id: str, other_tenant_id: str
) -> AsyncIterator[Container]:
    async for opened in open_container(
        harness_container, FixedClock(NOW), tenant_id, other_tenant_id
    ):
        yield opened


@pytest_asyncio.fixture(loop_scope="session")
async def app(
    two_container: Container, harness_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> FastAPI:
    await ensure_audit_heads(harness_driver, tenant_id, other_tenant_id)
    await seed_tenant_host(harness_driver, tenant_id, HOST_A)
    await seed_tenant_host(harness_driver, other_tenant_id, HOST_B)
    await seed_world(two_container, tenant_id, mobile=MOBILE)
    await seed_world(two_container, other_tenant_id, mobile=MOBILE_B)
    return await build_app(two_container)


async def _set_spoa(container: Container, tenant: str, number: str) -> None:
    with bind_tenant(tenant):
        async with container.uow_factory() as uow:
            await uow.tenant_config.put_contact(
                TenantContact(ContactKind.COORDINATION_PHONE, "SPOA", number)
            )
            await uow.commit()


async def _verify(
    client: AsyncClient, container: Container, tenant: str, mobile: str
) -> tuple[int, dict[str, object]]:
    await hold_code(container, tenant, mobile, purpose="new-device")
    response = await client.post(
        "/identity/new-phone/verify",
        json={"phone": mobile, "code": CODE, "deviceId": OTHER_DEVICE},
    )
    return response.status_code, response.json()


async def test_the_wait_names_the_spoa_number_the_tenant_has_set(
    app: FastAPI, two_container: Container, tenant_id: str
) -> None:
    await _set_spoa(two_container, tenant_id, SPOA_A)

    async with client_for(app, HOST_A) as on_a:
        status, body = await _verify(on_a, two_container, tenant_id, MOBILE)

    assert status == 200
    assert body == {"status": "pending-callback", "spoaPhone": SPOA_A}


async def test_a_tenant_with_no_coordination_phone_shows_none_and_never_a_default(
    app: FastAPI, two_container: Container, tenant_id: str
) -> None:
    async with client_for(app, HOST_A) as on_a:
        status, body = await _verify(on_a, two_container, tenant_id, MOBILE)

    assert status == 200
    assert body == {"status": "pending-callback", "spoaPhone": None}


async def test_each_tenant_shows_its_own_number_and_not_the_others(
    app: FastAPI, two_container: Container, tenant_id: str, other_tenant_id: str
) -> None:
    await _set_spoa(two_container, tenant_id, SPOA_A)
    await _set_spoa(two_container, other_tenant_id, SPOA_B)

    async with client_for(app, HOST_A) as on_a, client_for(app, HOST_B) as on_b:
        _, in_a = await _verify(on_a, two_container, tenant_id, MOBILE)
        _, in_b = await _verify(on_b, two_container, other_tenant_id, MOBILE_B)

    assert in_a["spoaPhone"] == SPOA_A
    assert in_b["spoaPhone"] == SPOA_B


async def test_a_code_that_is_not_right_carries_no_number(
    app: FastAPI, two_container: Container, tenant_id: str
) -> None:
    await _set_spoa(two_container, tenant_id, SPOA_A)
    await hold_code(two_container, tenant_id, MOBILE, purpose="new-device")

    async with client_for(app, HOST_A) as on_a:
        response: object = await on_a.post(
            "/identity/new-phone/verify",
            json={"phone": MOBILE, "code": "000000", "deviceId": OTHER_DEVICE},
        )

    assert isinstance(response, object)
    assert response.status_code == 400  # type: ignore[attr-defined]
    assert SPOA_A not in response.text  # type: ignore[attr-defined]
