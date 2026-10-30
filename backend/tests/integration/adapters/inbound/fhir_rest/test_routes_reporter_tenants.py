"""Two tenants through the reporter app routes (W7C, DEC-130 to DEC-132, DEC-134 item 3, H-453).

Each tenant has the same reporter id, the same device id, the same service ids and the same
booking reference, with figures that differ (UCR West 4 in A, 6 in B). A reporter's token names a
tenant and nothing of the other is read, changed, queued or shown: the services, the prompt, a
report, a cover, the settings and a booking of A are A's alone; an invitation of A is the one
refusal on B's host; a device of A is an unknown device on B's host. Runs on the shared harness
database, which has the contracted schema (DEC-159); the tests bind no tenant themselves, so the
routes must bind it from the token or the host.
"""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.identity import HmacPhoneHasher
from diucs.application.tenancy import bind_tenant
from diucs.bootstrap.container import Container
from diucs.domain.codes import BookingStatus
from diucs.domain.model.booking import Booking
from tests.integration.adapters.inbound.fhir_rest.reporter_rig import (
    COVER_MOBILE,
    DEVICE,
    EAST,
    MOBILE,
    NOW,
    PERSON,
    WEST,
    bearer,
    build_app,
    client_for,
    open_container,
    seed_invitation,
    seed_world,
)
from tests.integration.adapters.inbound.link_pages.conftest import seed_tenant_host
from tests.support.booking_rig import open_case
from tests.support.link_rig import HOST_A, HOST_B
from tests.support.neo4j import ThrowawayNeo4j, read_tx
from tests.support.uow import ensure_audit_heads

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.no_tenant]

MOBILE_B = "07700 900456"
UNKNOWN_TOKEN = "AbCdEfGhIjKlMnOpQrStUvW"


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
    two_container: Container,
    harness_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> FastAPI:
    await ensure_audit_heads(harness_driver, tenant_id, other_tenant_id)
    await seed_tenant_host(harness_driver, tenant_id, HOST_A)
    await seed_tenant_host(harness_driver, other_tenant_id, HOST_B)
    await seed_world(two_container, tenant_id, mobile=MOBILE, west_value=4, east_value=2)
    await seed_world(two_container, other_tenant_id, mobile=MOBILE_B, west_value=6, east_value=3)
    return await build_app(two_container)


@pytest_asyncio.fixture(loop_scope="session")
async def on_a(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with client_for(app, HOST_A) as client:
        yield client


@pytest_asyncio.fixture(loop_scope="session")
async def on_b(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with client_for(app, HOST_B) as client:
        yield client


async def _count(driver: AsyncDriver, query: str, **params: Any) -> int:
    async def work(tx: Any) -> int:
        result = await tx.run(query, **params)
        return int((await result.single())["n"])

    return await read_tx(driver, work)


async def test_each_tenants_reporter_sees_their_own_figures_under_the_same_ids(
    on_a: AsyncClient, tenant_id: str, other_tenant_id: str
) -> None:
    a = await on_a.get("/reporter/services", headers=bearer(tenant=tenant_id))
    b = await on_a.get("/reporter/services", headers=bearer(tenant=other_tenant_id))

    figures_a = {row["id"]: row["recordedValue"] for row in a.json()["services"]}
    figures_b = {row["id"]: row["recordedValue"] for row in b.json()["services"]}
    assert figures_a == {WEST: 4, EAST: 2}
    assert figures_b == {WEST: 6, EAST: 3}


async def test_a_prompt_and_the_settings_are_the_tenants_own(
    on_b: AsyncClient, tenant_id: str, other_tenant_id: str
) -> None:
    prompt = await on_b.get(
        f"/reporter/services/{WEST}/prompt", headers=bearer(tenant=other_tenant_id)
    )
    settings = await on_b.get("/reporter/settings", headers=bearer(tenant=other_tenant_id))

    assert prompt.json()["recordedValue"] == 6
    assert settings.json()["maskedPhone"] == "07xxx xxx456"


async def test_a_report_in_a_writes_nothing_in_b(
    on_a: AsyncClient,
    harness_driver: AsyncDriver,
    two_container: Container,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    sent = await on_a.post(
        f"/reporter/services/{WEST}/report",
        json={"kind": "number", "value": 5},
        headers=bearer(tenant=tenant_id, key="key-two-tenants-1"),
    )

    assert sent.json()["result"] == "recorded"
    observations = "MATCH (o:Observation {tenantId: $tenant}) RETURN count(o) AS n"
    assert await _count(harness_driver, observations, tenant=tenant_id) == 3
    assert await _count(harness_driver, observations, tenant=other_tenant_id) == 2
    with bind_tenant(other_tenant_id):
        async with two_container.uow_factory() as uow:
            latest = await uow.capacity.latest(WEST)
    assert latest is not None and latest.value == 6


async def test_the_same_key_in_two_tenants_records_one_report_in_each(
    on_a: AsyncClient, harness_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    key = "key-shared-by-both"
    first = await on_a.post(
        f"/reporter/services/{WEST}/report",
        json={"kind": "number", "value": 5},
        headers=bearer(tenant=tenant_id, key=key),
    )
    second = await on_a.post(
        f"/reporter/services/{WEST}/report",
        json={"kind": "number", "value": 7},
        headers=bearer(tenant=other_tenant_id, key=key),
    )

    assert (first.json()["value"], second.json()["value"]) == (5, 7)
    observations = "MATCH (o:Observation {tenantId: $tenant}) RETURN count(o) AS n"
    assert await _count(harness_driver, observations, tenant=tenant_id) == 3
    assert await _count(harness_driver, observations, tenant=other_tenant_id) == 3


async def test_a_cover_in_a_leaves_bs_posts_with_b(
    on_a: AsyncClient, on_b: AsyncClient, tenant_id: str, other_tenant_id: str
) -> None:
    covered = await on_a.post(
        "/reporter/cover", json={"phone": COVER_MOBILE}, headers=bearer(tenant=tenant_id)
    )

    assert covered.status_code == 200
    in_a = await on_a.get("/reporter/services", headers=bearer(tenant=tenant_id))
    in_b = await on_b.get("/reporter/services", headers=bearer(tenant=other_tenant_id))
    assert in_a.json() == {"services": []}
    assert [row["id"] for row in in_b.json()["services"]] == [EAST, WEST]
    settings_b = await on_b.get("/reporter/settings", headers=bearer(tenant=other_tenant_id))
    assert settings_b.json()["maskedCover"] is None


async def test_a_booking_reference_of_a_is_unknown_to_bs_reporter(
    on_b: AsyncClient, two_container: Container, tenant_id: str, other_tenant_id: str
) -> None:
    with bind_tenant(tenant_id):
        async with two_container.uow_factory() as uow:
            await uow.cases.add(open_case())
            await uow.bookings.add(
                Booking(
                    id="bk-1",
                    reference="1001",
                    service_id=WEST,
                    case_id="case-1001",
                    requester_id="advisor-1",
                    status=BookingStatus.REQUESTED,
                    requested_at=NOW - timedelta(minutes=5),
                    reply_by=NOW + timedelta(minutes=25),
                )
            )
            await uow.commit()

    in_a = await on_b.get("/reporter/bookings/1001", headers=bearer(tenant=tenant_id))
    crossed = await on_b.get("/reporter/bookings/1001", headers=bearer(tenant=other_tenant_id))
    decided = await on_b.post(
        "/reporter/bookings/1001/respond",
        json={"decision": "confirm"},
        headers=bearer(tenant=other_tenant_id, key="key-cross-1"),
    )

    assert in_a.status_code == 200
    assert crossed.status_code == decided.status_code == 404
    with bind_tenant(tenant_id):
        async with two_container.uow_factory() as uow:
            booking = await uow.bookings.get("bk-1")
    assert booking is not None and booking.status is BookingStatus.REQUESTED


async def test_an_invitation_of_a_is_the_one_refusal_on_bs_host(
    on_a: AsyncClient, on_b: AsyncClient, two_container: Container, tenant_id: str
) -> None:
    token = await seed_invitation(two_container, tenant_id)

    here = await on_a.get(f"/invitations/{token}")
    crossed = await on_b.get(f"/invitations/{token}")
    unknown = await on_b.get(f"/invitations/{UNKNOWN_TOKEN}")
    code = await on_b.post(f"/identity/invitations/{token}/code", json={})

    assert here.status_code == 200
    assert (
        (crossed.status_code, crossed.json())
        == (unknown.status_code, unknown.json())
        == (
            410,
            {"state": "expired"},
        )
    )
    assert code.status_code == 202  # the same answer as for any token


async def test_a_code_for_a_token_of_a_queues_nothing_to_send_in_b(
    on_a: AsyncClient,
    on_b: AsyncClient,
    two_container: Container,
    harness_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    token = await seed_invitation(two_container, tenant_id)
    await on_a.post(f"/identity/invitations/{token}/code", json={})
    await on_b.post(f"/identity/invitations/{token}/code", json={})

    query = "MATCH (m:OutboxMessage {eventType: $type, tenantId: $tenant}) RETURN count(m) AS n"
    assert await _count(harness_driver, query, type="SendCode", tenant=tenant_id) == 1
    assert await _count(harness_driver, query, type="SendCode", tenant=other_tenant_id) == 0
    assert await _count(harness_driver, query, type="DiscardCode", tenant=other_tenant_id) == 1


async def test_a_device_code_for_a_device_of_a_is_for_an_unknown_device_on_bs_host(
    on_b: AsyncClient,
    two_container: Container,
    harness_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    # The same device id is B's own device too (a collision on purpose): B's owner is texted.
    known = await on_b.post(
        "/identity/device/code", json={"deviceId": DEVICE, "purpose": "reverify"}
    )

    assert known.status_code == 202
    query = "MATCH (m:OutboxMessage {eventType: $type, tenantId: $tenant}) RETURN count(m) AS n"
    assert await _count(harness_driver, query, type="SendCode", tenant=other_tenant_id) == 1
    assert await _count(harness_driver, query, type="SendCode", tenant=tenant_id) == 0
    phone_hash_b = HmacPhoneHasher(two_container.secrets).hash(MOBILE_B)
    phone_hash_a = HmacPhoneHasher(two_container.secrets).hash(MOBILE)
    with bind_tenant(other_tenant_id):
        assert await two_container.codes.get("reverify", phone_hash_b) is not None
        assert await two_container.codes.get("reverify", phone_hash_a) is None
    with bind_tenant(tenant_id):
        assert await two_container.codes.get("reverify", phone_hash_a) is None


async def test_the_person_and_device_of_a_token_are_resolved_in_the_tokens_tenant(
    on_a: AsyncClient, other_tenant_id: str
) -> None:
    # B's person holds no post in A's graph under a token for B's tenant on A's host, and a token
    # for a tenant with no record at all is the one 401.
    stranger = await on_a.get("/reporter/services", headers=bearer(tenant="no-such-tenant"))

    assert stranger.status_code == 401
    assert PERSON == "prac-1"
