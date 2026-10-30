"""An executive's notifications through the reporter app's routes, on two tenants (W9H, DEC-1040 to
DEC-1044, H-710 to H-712).

An executive signs in through the organisation's directory (a staff subject, no device, no
post). They may save a push subscription for their phone, ask for a test notification and take the
subscription off; nothing of the reporter's posts is theirs. The person record the subscription
needs is made on the first save, in the executive's own tenant only. A refused role is the one 404,
for all thirteen roles, and the platform operator is a 401 at the edge. Samples only; the push
provider is a recording fake.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.message_senders import PushMessageSender
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.recording_senders import RecordingPushSender
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.tenancy import bind_tenant
from diucs.bootstrap.container import Container
from diucs.domain.codes import Role
from diucs.domain.model.people import Practitioner
from tests.integration.adapters.inbound.fhir_rest.reporter_rig import (
    NOW,
    OTHER_DEVICE,
    bearer,
    build_app,
    client_for,
    open_container,
    seed_world,
)
from tests.integration.adapters.inbound.link_pages.conftest import seed_tenant_host
from tests.support.link_rig import HOST_A, HOST_B
from tests.support.neo4j import ThrowawayNeo4j, read_tx
from tests.support.uow import ensure_audit_heads

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.no_tenant]

# The same subject in both tenants: a derived staff subject is per tenant in production, but the
# isolation proof is the harder one, so the ids are shared and the answers must still differ.
STAFF = "stf-0123456789abcdef0123456789abcdef"
KEY = "exec-key-0001"
SUBSCRIPTION = {
    "endpoint": "https://push.example/sample-exec-endpoint",
    "keys": {"p256dh": "sample-p256dh", "auth": "sample-auth"},
}
BODY = {"subscription": SUBSCRIPTION, "wordingVersion": "v1", "deviceId": OTHER_DEVICE}


def exec_headers(tenant: str, key: str | None = KEY, role: Role = Role.EXEC) -> dict[str, str]:
    return bearer(STAFF, role=role, services=(), device=None, tenant=tenant, key=key)


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
    await seed_world(two_container, tenant_id)
    await seed_world(two_container, other_tenant_id, mobile="07700 900456")
    return await build_app(two_container)


@pytest_asyncio.fixture(loop_scope="session")
async def api(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with client_for(app, HOST_A) as client:
        yield client


async def _count(driver: AsyncDriver, query: str, **params: Any) -> int:
    async def work(tx: Any) -> int:
        result = await tx.run(query, **params)
        return int((await result.single())["n"])

    return await read_tx(driver, work)


PERSONS = "MATCH (p:Practitioner {id: $id, tenantId: $tenant}) RETURN count(p) AS n"


async def _save(api: AsyncClient, tenant: str, key: str = KEY) -> Any:
    return await api.post(
        "/identity/push-subscription", json=BODY, headers=exec_headers(tenant, key)
    )


async def test_the_first_save_makes_the_executives_person_in_their_tenant_only(
    api: AsyncClient,
    harness_driver: AsyncDriver,
    two_container: Container,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    saved = await _save(api, tenant_id)

    assert saved.status_code == 200
    assert await _count(harness_driver, PERSONS, id=STAFF, tenant=tenant_id) == 1
    assert await _count(harness_driver, PERSONS, id=STAFF, tenant=other_tenant_id) == 0
    with bind_tenant(tenant_id):
        async with two_container.uow_factory() as uow:
            person = await uow.people.get_practitioner(STAFF)
            held = await uow.push_subscriptions.for_practitioner(STAFF)
    assert person is not None and (person.active, person.phone_hash) == (True, None)
    assert [item.device_id for item in held] == ["app-" + OTHER_DEVICE]
    with bind_tenant(other_tenant_id):
        async with two_container.uow_factory() as uow:
            assert await uow.push_subscriptions.for_practitioner(STAFF) == []


async def test_a_second_save_keeps_the_one_person_and_the_same_subscription(
    api: AsyncClient, harness_driver: AsyncDriver, tenant_id: str
) -> None:
    first = await _save(api, tenant_id, "exec-key-one")
    second = await _save(api, tenant_id, "exec-key-two")

    assert (first.status_code, second.status_code) == (200, 200)
    assert await _count(harness_driver, PERSONS, id=STAFF, tenant=tenant_id) == 1


async def test_the_same_executive_id_in_two_tenants_is_two_people_with_two_subscriptions(
    api: AsyncClient,
    app: FastAPI,
    harness_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _save(api, tenant_id)
    async with client_for(app, HOST_B) as on_b:
        await _save(on_b, other_tenant_id, "exec-key-b")

    assert await _count(harness_driver, PERSONS, id=STAFF, tenant=tenant_id) == 1
    assert await _count(harness_driver, PERSONS, id=STAFF, tenant=other_tenant_id) == 1
    devices = (
        "MATCH (d:Device {tenantId: $tenant}) WHERE d.pushSubscriptionJson IS NOT NULL "
        "RETURN count(d) AS n"
    )
    assert await _count(harness_driver, devices, tenant=tenant_id) == 1
    assert await _count(harness_driver, devices, tenant=other_tenant_id) == 1


async def test_a_test_notification_needs_a_saved_subscription(
    api: AsyncClient, tenant_id: str, two_container: Container
) -> None:
    # No person record yet: the test is refused as any unknown person is, and makes none.
    before = await api.post("/reporter/push-test", json={}, headers=exec_headers(tenant_id, None))
    assert before.status_code == 401

    await _save(api, tenant_id)
    with bind_tenant(tenant_id):
        async with two_container.uow_factory() as uow:
            await uow.push_subscriptions.delete("app-" + OTHER_DEVICE)
            await uow.commit()
    none = await api.post("/reporter/push-test", json={}, headers=exec_headers(tenant_id, None))
    assert (none.status_code, none.json()) == (409, {"code": "no-subscription"})


async def test_a_test_notification_is_one_person_push_queued_in_the_executives_tenant(
    api: AsyncClient, two_container: Container, tenant_id: str, other_tenant_id: str
) -> None:
    await _save(api, tenant_id)

    sent = await api.post("/reporter/push-test", json={}, headers=exec_headers(tenant_id, None))

    assert (sent.status_code, sent.json()) == (200, {"queued": True})
    with bind_tenant(tenant_id):
        async with two_container.uow_factory() as uow:
            pending = [
                m for m in await uow.outbox.pending(20) if m.payload.get("channel") == "push"
            ]
    assert len(pending) == 1
    assert pending[0].payload["recipient_practitioner_id"] == STAFF
    assert pending[0].payload["message_id"] == "K3"
    assert "sealed_content" not in pending[0].payload
    with bind_tenant(other_tenant_id):
        async with two_container.uow_factory() as uow:
            assert [
                m for m in await uow.outbox.pending(20) if m.payload.get("channel") == "push"
            ] == []


async def test_the_queued_test_reaches_the_executives_phone_through_the_push_sender(
    api: AsyncClient, two_container: Container, tenant_id: str
) -> None:
    await _save(api, tenant_id)
    await api.post("/reporter/push-test", json={}, headers=exec_headers(tenant_id, None))
    with bind_tenant(tenant_id):
        async with two_container.uow_factory() as uow:
            [queued] = [
                m for m in await uow.outbox.pending(20) if m.payload.get("channel") == "push"
            ]
    sender = RecordingPushSender()
    handler = PushMessageSender(sender, _Sealer(), "https://diucs.example/app", FixedClock(NOW))  # type: ignore[arg-type]

    with bind_tenant(tenant_id):
        async with two_container.uow_factory() as uow:
            await handler(
                BusMessage(
                    id=queued.id,
                    topic=queued.topic,
                    event_type=queued.event_type,
                    payload=queued.payload,
                    tenant_id=tenant_id,
                ),
                uow,
            )
            await uow.commit()

    assert [(p.title, p.urgency) for p in sender.sent] == [("Test notification", "high")]
    assert sender.sent[0].subscription["endpoint"] == SUBSCRIPTION["endpoint"]


class _Sealer:
    def unseal(self, *args: Any, **kwargs: Any) -> str:
        raise AssertionError("a person push has no sealed content")


async def test_a_removed_executive_cannot_save_or_ask_for_a_test(
    api: AsyncClient, two_container: Container, tenant_id: str
) -> None:
    with bind_tenant(tenant_id):
        async with two_container.uow_factory() as uow:
            await uow.people.save_practitioner(
                Practitioner(id=STAFF, active=False, display_name="Executive", phone_hash=None)
            )
            await uow.commit()

    saved = await _save(api, tenant_id)
    tested = await api.post("/reporter/push-test", json={}, headers=exec_headers(tenant_id, None))

    assert (saved.status_code, tested.status_code) == (401, 401)
    with bind_tenant(tenant_id):
        async with two_container.uow_factory() as uow:
            person = await uow.people.get_practitioner(STAFF)
    assert person is not None and person.active is False


async def test_the_subscription_comes_off_and_a_second_removal_is_still_200(
    api: AsyncClient, two_container: Container, tenant_id: str
) -> None:
    await _save(api, tenant_id)

    off = await api.delete(
        "/identity/push-subscription",
        headers={**exec_headers(tenant_id, "exec-key-off"), "X-Device-Id": OTHER_DEVICE},
    )

    assert off.status_code == 200
    with bind_tenant(tenant_id):
        async with two_container.uow_factory() as uow:
            assert await uow.push_subscriptions.for_practitioner(STAFF) == []


# ----------------------------------------------------------------------------- the role matrix

PUSH_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", "/identity/push-subscription", BODY),
    ("DELETE", "/identity/push-subscription", None),
    ("POST", "/reporter/push-test", {}),
]
EDGE_REFUSED = {Role.PLATFORM_OPERATOR}


@pytest.mark.parametrize(("method", "path", "body"), PUSH_ROUTES)
async def test_every_role_but_a_reporter_and_an_executive_is_the_one_404(
    api: AsyncClient,
    harness_driver: AsyncDriver,
    tenant_id: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    refused: dict[Role, bytes] = {}
    admitted = (Role.REPORTER, Role.EXEC)
    # The refused roles first: they must leave no person behind, so the count is still nothing when
    # the admitted roles come after.
    for role in (r for r in Role if r not in admitted):
        response = await api.request(
            method, path, json=body, headers=exec_headers(tenant_id, f"matrix-{role.value}", role)
        )
        if role in EDGE_REFUSED:
            assert response.status_code == 401, role
        else:
            assert response.status_code == 404, (role, response.status_code)
            refused[role] = response.content
    assert len(set(refused.values())) == 1
    assert len(refused) == len(Role) - len(admitted) - len(EDGE_REFUSED) == 10
    assert await _count(harness_driver, PERSONS, id=STAFF, tenant=tenant_id) == 0
    for role in admitted:
        response = await api.request(
            method, path, json=body, headers=exec_headers(tenant_id, f"matrix-{role.value}", role)
        )
        assert response.status_code != 404, role
