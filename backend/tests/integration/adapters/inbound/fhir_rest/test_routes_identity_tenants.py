"""Two tenants through the reporter identity routes (R11, DEC-130 to DEC-132, DEC-134 item 3).

The host picks the tenant. Each tenant has a reporter `prac-1` and the same device id; a number is
known only in its own tenant; a code held in A is not found on B's host; A's device is an unknown
device on B's host and answers as any unknown device does, and nothing of B is read, changed or
queued by a request for A. The same device id and the same person id in both tenants do not collide.
A budget spent by one address in A is not spent in B.

These run on a private contracted container (DEC-159), because the shared harness schema refuses a
second tenant's Concept; each tenant has an audit head. The tests run with no tenant bound, so the
routes must bind it from the host.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.migrations import apply_migrations
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.application.ports.outbound.identity import HmacPhoneHasher
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.text_code import CODE_HMAC_SECRET, code_hash
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import Cadence, Channel, Measure, PractitionerRoleCode, ServiceCategory
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.identity_policy import CodeState
from tests.integration.adapters.inbound.fhir_rest.test_routes_identity import (
    CODE,
    DEVICE,
    MOBILE,
    PERSON,
    PIN,
    SECRETS,
)
from tests.integration.adapters.inbound.link_pages.conftest import seed_tenant_host
from tests.support.link_rig import HOST_A, HOST_B
from tests.support.neo4j import ThrowawayNeo4j, read_tx, throwaway_driver, wipe
from tests.support.redis import flush_prefix
from tests.support.tenant_seed import contract_schema
from tests.support.uow import ensure_audit_heads

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.no_tenant]

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
MOBILE_B = "07700 900456"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant() -> AsyncIterator[tuple[ThrowawayNeo4j, AsyncDriver]]:
    async with throwaway_driver() as (container, driver):
        await apply_migrations(driver)
        await contract_schema(driver)
        yield container, driver


@pytest_asyncio.fixture(loop_scope="session")
async def two_container(
    two_tenant: tuple[ThrowawayNeo4j, AsyncDriver], tenant_id: str, other_tenant_id: str
) -> AsyncIterator[Container]:
    server, driver = two_tenant
    await wipe(driver)
    connection = Neo4jConnection(server.uri, server.user, server.password)
    await connection.open()
    container = build_for_tests(
        clock=FixedClock(NOW),
        ids=SequentialIds(),
        neo4j=connection,
        secrets=FixedSecretStore(SECRETS),
    )
    for tenant in (tenant_id, other_tenant_id):
        await flush_prefix(container.redis, f"diucs:{tenant}:")
    try:
        yield container
    finally:
        for tenant in (tenant_id, other_tenant_id):
            await flush_prefix(container.redis, f"diucs:{tenant}:")
        await container.redis.aclose()
        await connection.close()
        await wipe(driver)


async def _seed_tenant(container: Container, tenant: str, mobile: str) -> None:
    hasher = HmacPhoneHasher(container.secrets)
    with bind_tenant(tenant):
        async with container.uow_factory() as uow:
            await uow.services.save(
                ServiceProfile(
                    id="ucr-west",
                    name="UCR West",
                    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                    measure=Measure.REFERRALS_ACCEPTABLE,
                    unit_label="referrals",
                    established_capacity=8,
                    can_exceed_established=False,
                    usual_range=(0, 8),
                    cadence=Cadence.EVERY_2_HRS,
                    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
                    channel=Channel.TEXT,
                    limited_level_percent=80,
                )
            )
            await uow.people.save_practitioner(
                Practitioner(
                    id=PERSON,
                    active=True,
                    display_name="Sample Reporter",
                    phone_hash=hasher.hash(mobile),
                )
            )
            await uow.people.save_role(
                PractitionerRole(
                    id="role-1",
                    practitioner_id=PERSON,
                    service_id="ucr-west",
                    code=PractitionerRoleCode.DUTY_MANAGER,
                    active=True,
                    channel=Channel.TEXT,
                    period_start=NOW - timedelta(days=30),
                )
            )
            await uow.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def app(
    two_container: Container,
    two_tenant: tuple[ThrowawayNeo4j, AsyncDriver],
    tenant_id: str,
    other_tenant_id: str,
) -> FastAPI:
    _, driver = two_tenant
    await ensure_audit_heads(driver, tenant_id, other_tenant_id)
    await seed_tenant_host(driver, tenant_id, HOST_A)
    await seed_tenant_host(driver, other_tenant_id, HOST_B)
    await _seed_tenant(two_container, tenant_id, MOBILE)
    await _seed_tenant(two_container, other_tenant_id, MOBILE_B)
    app = create_app(two_container)
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    app.state.cache = two_container.cache
    return app


def _client(app: FastAPI, host: str, address: str = "203.0.113.9") -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False, client=(address, 1)),
        base_url=f"https://{host}",
    )


async def _hold(container: Container, tenant: str, mobile: str) -> None:
    phone_hash = HmacPhoneHasher(container.secrets).hash(mobile)
    stored = code_hash(SECRETS[CODE_HMAC_SECRET], phone_hash, "setup", CODE)
    with bind_tenant(tenant):
        await container.codes.save("setup", phone_hash, stored, CodeState(NOW))


async def _count(driver: AsyncDriver, query: str, **params: Any) -> int:
    async def work(tx: Any) -> int:
        result = await tx.run(query, **params)
        return int((await result.single())["n"])

    return await read_tx(driver, work)


async def test_a_number_known_in_a_is_unknown_on_bs_host_and_queues_nothing_to_send(
    app: FastAPI,
    two_tenant: tuple[ThrowawayNeo4j, AsyncDriver],
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    _, driver = two_tenant
    async with _client(app, HOST_A) as on_a, _client(app, HOST_B) as on_b:
        known_in_a = await on_a.post("/identity/code", json={"mobile": MOBILE})
        crossed = await on_b.post("/identity/code", json={"mobile": MOBILE})
    assert known_in_a.status_code == crossed.status_code == 202
    assert known_in_a.content == crossed.content
    query = "MATCH (m:OutboxMessage {eventType: $type, tenantId: $tenant}) RETURN count(m) AS n"
    assert await _count(driver, query, type="SendCode", tenant=tenant_id) == 1
    assert await _count(driver, query, type="SendCode", tenant=other_tenant_id) == 0
    assert await _count(driver, query, type="DiscardCode", tenant=other_tenant_id) == 1


async def test_a_code_held_in_a_is_not_found_on_bs_host_and_records_nothing_in_b(
    app: FastAPI,
    two_container: Container,
    two_tenant: tuple[ThrowawayNeo4j, AsyncDriver],
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    _, driver = two_tenant
    await _hold(two_container, tenant_id, MOBILE)
    async with _client(app, HOST_B) as on_b:
        crossed = await on_b.post(
            "/identity/code/verify", json={"mobile": MOBILE, "code": CODE, "deviceId": DEVICE}
        )
    assert crossed.status_code == 400
    assert crossed.json()["issue"][0]["diagnostics"] == "Ask for a new code"
    devices = "MATCH (d:Device {id: $id, tenantId: $tenant}) RETURN count(d) AS n"
    assert await _count(driver, devices, id=DEVICE, tenant=other_tenant_id) == 0
    assert await _count(driver, devices, id=DEVICE, tenant=tenant_id) == 0


async def test_the_same_device_id_and_person_id_in_both_tenants_do_not_collide(
    app: FastAPI,
    two_container: Container,
    two_tenant: tuple[ThrowawayNeo4j, AsyncDriver],
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    _, driver = two_tenant
    await _hold(two_container, tenant_id, MOBILE)
    await _hold(two_container, other_tenant_id, MOBILE_B)
    async with _client(app, HOST_A) as on_a, _client(app, HOST_B) as on_b:
        for client, mobile in ((on_a, MOBILE), (on_b, MOBILE_B)):
            verified = await client.post(
                "/identity/code/verify", json={"mobile": mobile, "code": CODE, "deviceId": DEVICE}
            )
            assert verified.status_code == 200
            assert (
                await client.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN})
            ).status_code == 200
        signed_a = await on_a.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
        wrong_b = await on_b.post(
            "/identity/pin/verify", json={"deviceId": DEVICE, "pin": "000000"}
        )
    assert signed_a.status_code == 200
    assert wrong_b.status_code == 403
    devices = "MATCH (d:Device {id: $id, tenantId: $tenant}) RETURN count(d) AS n"
    assert await _count(driver, devices, id=DEVICE, tenant=tenant_id) == 1
    assert await _count(driver, devices, id=DEVICE, tenant=other_tenant_id) == 1
    failed = "MATCH (c:Credential {deviceId: $id, tenantId: $tenant}) RETURN c.failed AS n"
    assert await _count(driver, failed, id=DEVICE, tenant=tenant_id) == 0
    assert await _count(driver, failed, id=DEVICE, tenant=other_tenant_id) == 1


async def test_a_device_of_a_is_an_unknown_device_on_bs_host(
    app: FastAPI, two_container: Container, tenant_id: str
) -> None:
    await _hold(two_container, tenant_id, MOBILE)
    async with _client(app, HOST_A) as on_a:
        await on_a.post(
            "/identity/code/verify", json={"mobile": MOBILE, "code": CODE, "deviceId": DEVICE}
        )
        await on_a.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN})
    async with _client(app, HOST_B) as on_b:
        status = await on_b.get("/identity/status", headers={"X-Device-Id": DEVICE})
        unknown = await on_b.get(
            "/identity/status", headers={"X-Device-Id": "device-zzzzzzzzzzzzzzzzzzzzzz"}
        )
        signed = await on_b.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
    assert status.content == unknown.content
    assert status.json() == {"reverifyDue": True, "daysLeft": 0}
    assert signed.status_code == 403
    assert signed.json()["needsTextCode"] is True


async def test_a_budget_spent_in_a_is_not_spent_in_b(app: FastAPI) -> None:
    async with _client(app, HOST_A) as on_a, _client(app, HOST_B) as on_b:
        for n in range(10):
            await on_a.post("/identity/code", json={"mobile": f"0770090{n:04d}"})
        blocked = await on_a.post("/identity/code", json={"mobile": MOBILE})
        free = await on_b.post("/identity/code", json={"mobile": MOBILE})
    assert (blocked.status_code, free.status_code) == (429, 202)
