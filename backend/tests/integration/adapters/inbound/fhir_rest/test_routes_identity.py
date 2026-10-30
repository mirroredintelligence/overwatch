"""The reporter identity routes (R11) on the harness Neo4j and the compose Redis, with the real
U25, U32, U37 and I14 use cases and the real session, code and rate stores.

The clock is Thursday 29 October 2026, 14:00Z. The run tenant is the one the host `HOST_A` names.
What a test asserts is what the route answered and what was really stored, read back through the
graph and Redis (DEC-004). The number, code, PIN and device id are samples: no real number, no
patient data. Each test flushes the run tenant's Redis keys first, so the per-address throttle and
the code state of one test never reach the next.
"""

import logging
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
from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.pin import PIN_HMAC_SECRET
from diucs.application.use_cases.remove_person import SignOutEverywhere, SignOutEverywhereCommand
from diucs.application.use_cases.text_code import CODE_HMAC_SECRET, code_hash
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    Role,
    ServiceCategory,
)
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.identity_policy import CodeState
from tests.integration.adapters.inbound.link_pages.conftest import seed_tenant_host
from tests.support.actors import ACTOR_TENANT
from tests.support.link_rig import HOST_A
from tests.support.neo4j import ThrowawayNeo4j, count_nodes, node_props
from tests.support.redis import flush_prefix
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
MOBILE = "07700 900123"
UNKNOWN_MOBILE = "07700 900789"
CODE = "482913"
PIN = "135790"
PERSON = "prac-1"
DEVICE = "device-aaaaaaaaaaaaaaaaaaaaaa"
OTHER_DEVICE = "device-bbbbbbbbbbbbbbbbbbbbbb"
SECRETS = {
    BFF_SECRET_NAME: TEST_BFF_SECRET,
    PHONE_HASH_SECRET: b"phone-hash-route-test-secret-0123456789ab",
    CODE_HMAC_SECRET: b"code-hmac-route-test-secret-0123456789abc",
    PIN_HMAC_SECRET: b"pin-hmac-route-test-secret-0123456789abcd",
    LINK_TOKEN_SECRET: b"link-token-route-test-secret-0123456789a",
}
SUBSCRIPTION = {
    "endpoint": "https://push.example/sample-endpoint",
    "keys": {"p256dh": "sample-p256dh", "auth": "sample-auth"},
}


@pytest_asyncio.fixture(loop_scope="session")
async def identity_container(
    harness_container: ThrowawayNeo4j, clean_graph: None, tenant_id: str
) -> AsyncIterator[Container]:
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    container = build_for_tests(
        clock=FixedClock(NOW),
        ids=SequentialIds(),
        neo4j=connection,
        secrets=FixedSecretStore(SECRETS),
    )
    await flush_prefix(container.redis, f"diucs:{tenant_id}:")
    try:
        yield container
    finally:
        await flush_prefix(container.redis, f"diucs:{tenant_id}:")
        await container.redis.aclose()
        await connection.close()


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(
    identity_container: Container, neo4j_driver: AsyncDriver, tenant_id: str
) -> Container:
    """The audit head, the tenant with its host, and a reporter on UCR West with a known number."""
    with as_tenant(tenant_id):
        await ensure_audit_head(neo4j_driver)
    await seed_tenant_host(neo4j_driver, tenant_id, HOST_A)
    hasher = HmacPhoneHasher(identity_container.secrets)
    async with identity_container.uow_factory() as uow:
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
                phone_hash=hasher.hash(MOBILE),
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
    return identity_container


@pytest_asyncio.fixture(loop_scope="session")
async def app(seeded: Container) -> FastAPI:
    app = create_app(seeded)
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    app.state.cache = seeded.cache
    return app


@pytest_asyncio.fixture(loop_scope="session")
async def api(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False, client=("203.0.113.9", 1)),
        base_url=f"https://{HOST_A}",
    ) as client:
        yield client


async def hold_code(
    container: Container, tenant: str, mobile: str = MOBILE, purpose: str = "setup"
) -> None:
    """Put the code a person was texted into the code store, as a request would have."""
    phone_hash = HmacPhoneHasher(container.secrets).hash(mobile)
    stored = code_hash(SECRETS[CODE_HMAC_SECRET], phone_hash, purpose, CODE)
    with bind_tenant(tenant):
        await container.codes.save(purpose, phone_hash, stored, CodeState(NOW))


def bearer(device: str | None = DEVICE, role: Role = Role.REPORTER) -> dict[str, str]:
    token = issue_test_token(
        role, ("ucr-west",), PERSON, device=device, expires_at=NOW + timedelta(hours=8)
    )
    return {"Authorization": f"Bearer {token}"}


async def sent_codes(driver: AsyncDriver, event_type: str) -> int:
    from tests.support.neo4j import read_tx

    async def work(tx: Any) -> int:
        result = await tx.run(
            "MATCH (m:OutboxMessage {eventType: $type, tenantId: $tenant}) RETURN count(m) AS n",
            type=event_type,
        )
        return int((await result.single())["n"])

    return await read_tx(driver, work)


# ------------------------------------------------------------------ code, verify, PIN, sign in


async def test_a_known_and_an_unknown_number_get_the_same_answer_and_only_the_known_is_queued(
    api: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    known = await api.post("/identity/code", json={"mobile": MOBILE})
    unknown = await api.post("/identity/code", json={"mobile": UNKNOWN_MOBILE})
    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content
    assert await sent_codes(neo4j_driver, "SendCode") == 1
    assert await sent_codes(neo4j_driver, "DiscardCode") == 1
    for body in (known.text, unknown.text):
        assert "7700" not in body


async def test_a_right_code_is_recorded_on_the_device_a_pin_is_set_and_the_pin_signs_in(
    api: AsyncClient, seeded: Container, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await hold_code(seeded, tenant_id)
    verified = await api.post(
        "/identity/code/verify", json={"mobile": MOBILE, "code": CODE, "deviceId": DEVICE}
    )
    assert verified.status_code == 200
    assert verified.json() == {"verified": True}
    device = await node_props(neo4j_driver, "Device", id=DEVICE)
    assert device["status"] == "active"
    assert device["lastVerifiedAt"] is not None

    set_pin = await api.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN})
    assert set_pin.status_code == 200
    credential = await node_props(neo4j_driver, "Credential", deviceId=DEVICE)
    assert credential["failed"] == 0
    assert PIN not in str(credential)

    signed_in = await api.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
    body = signed_in.json()
    assert signed_in.status_code == 200
    assert body["services"] == ["ucr-west"]
    with bind_tenant(tenant_id):
        session = await seeded.sessions.get(body["sessionId"])
    assert session is not None
    assert (session.practitioner_id, session.device_id) == (PERSON, DEVICE)


async def test_five_wrong_codes_end_with_ask_for_a_new_code(
    api: AsyncClient, seeded: Container, tenant_id: str
) -> None:
    await hold_code(seeded, tenant_id)
    answers = [
        await api.post(
            "/identity/code/verify",
            json={"mobile": MOBILE, "code": "000000", "deviceId": DEVICE},
        )
        for _ in range(5)
    ]
    texts = [a.json()["issue"][0]["diagnostics"] for a in answers]
    assert texts == ["That code is not right"] * 4 + ["Ask for a new code"]


async def test_a_pin_without_a_recent_verification_is_refused_and_stores_nothing(
    api: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    refused = await api.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN})
    assert refused.status_code == 403
    assert await count_nodes(neo4j_driver, "Credential") == 0


async def test_five_wrong_pins_lock_it_and_the_stored_credential_shows_the_lock(
    api: AsyncClient, seeded: Container, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await hold_code(seeded, tenant_id)
    await api.post(
        "/identity/code/verify", json={"mobile": MOBILE, "code": CODE, "deviceId": DEVICE}
    )
    await api.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN})
    answers = [
        await api.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": "000000"})
        for _ in range(5)
    ]
    assert [a.status_code for a in answers] == [403, 403, 403, 403, 423]
    locked = await api.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
    assert locked.status_code == 423
    assert locked.json()["issue"][0]["code"] == "lock-error"
    credential = await node_props(neo4j_driver, "Credential", deviceId=DEVICE)
    assert credential["locked"] is True
    assert credential["failed"] == 5


async def test_the_status_31_days_after_the_verification_is_due(
    api: AsyncClient, seeded: Container, tenant_id: str
) -> None:
    await hold_code(seeded, tenant_id)
    await api.post(
        "/identity/code/verify", json={"mobile": MOBILE, "code": CODE, "deviceId": DEVICE}
    )
    fresh = await api.get("/identity/status", headers={"X-Device-Id": DEVICE})
    assert fresh.json() == {"reverifyDue": False, "daysLeft": 30}
    seeded.clock.advance(timedelta(days=31))  # type: ignore[attr-defined]
    try:
        late = await api.get("/identity/status", headers={"X-Device-Id": DEVICE})
    finally:
        seeded.clock.advance(timedelta(days=-31))  # type: ignore[attr-defined]
    assert late.json() == {"reverifyDue": True, "daysLeft": 0}


# ------------------------------------------------------------------ sign out, lost phone


async def _signed_in(api: AsyncClient, seeded: Container, tenant_id: str, device: str) -> str:
    await hold_code(seeded, tenant_id)
    await api.post(
        "/identity/code/verify", json={"mobile": MOBILE, "code": CODE, "deviceId": device}
    )
    await api.post("/identity/pin", json={"deviceId": device, "pin": PIN})
    response = await api.post("/identity/pin/verify", json={"deviceId": device, "pin": PIN})
    session_id: str = response.json()["sessionId"]
    return session_id


async def test_sign_out_everywhere_ends_the_session_and_the_token_of_that_device_stops_working(
    api: AsyncClient, seeded: Container, tenant_id: str
) -> None:
    session_id = await _signed_in(api, seeded, tenant_id, DEVICE)
    saved = await api.post(
        "/identity/push-subscription",
        json={"subscription": SUBSCRIPTION, "wordingVersion": "wording-v1", "deviceId": DEVICE},
        headers={**bearer(), "Idempotency-Key": "k1"},
    )
    assert saved.status_code == 200

    with bind_tenant(tenant_id):
        out = await SignOutEverywhere(seeded.uow_factory, seeded.clock, seeded.sessions).execute(
            SignOutEverywhereCommand(
                "so-1",
                _actor(PERSON),
            )
        )
        assert out.devices_signed_out == 1
        assert await seeded.sessions.get(session_id) is None

    again = await api.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
    assert again.status_code == 403
    assert again.json()["needsTextCode"] is True
    late = await api.post(
        "/identity/push-subscription",
        json={"subscription": SUBSCRIPTION, "wordingVersion": "wording-v1", "deviceId": DEVICE},
        headers={**bearer(), "Idempotency-Key": "k2"},
    )
    assert late.status_code == 401


def _actor(person: str) -> Any:
    from diucs.application.actor import Actor

    return Actor(
        role=Role.REPORTER,
        practitioner_id=person,
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


async def test_a_new_device_code_signs_out_the_old_phone_and_the_new_one_waits_for_the_callback(
    api: AsyncClient, seeded: Container, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _signed_in(api, seeded, tenant_id, DEVICE)
    await hold_code(seeded, tenant_id, purpose="new-device")
    started = await api.post(
        "/identity/code/verify",
        json={
            "mobile": MOBILE,
            "code": CODE,
            "deviceId": OTHER_DEVICE,
            "purpose": "new-device",
        },
    )
    assert started.json() == {"verified": True, "callbackRequired": True}
    assert (await node_props(neo4j_driver, "Device", id=DEVICE))["status"] == "revoked"
    assert (await node_props(neo4j_driver, "Device", id=OTHER_DEVICE))[
        "status"
    ] == "pending-callback"
    set_pin = await api.post("/identity/pin", json={"deviceId": OTHER_DEVICE, "pin": PIN})
    assert set_pin.status_code == 200
    refused = await api.post("/identity/pin/verify", json={"deviceId": OTHER_DEVICE, "pin": PIN})
    assert refused.status_code == 403
    assert refused.json()["needsTextCode"] is True


# ------------------------------------------------------------------ push


async def test_a_push_subscription_is_stored_with_its_consent(
    api: AsyncClient, seeded: Container, tenant_id: str
) -> None:
    await _signed_in(api, seeded, tenant_id, DEVICE)
    response = await api.post(
        "/identity/push-subscription",
        json={"subscription": SUBSCRIPTION, "wordingVersion": "wording-v1", "deviceId": DEVICE},
        headers={**bearer(), "Idempotency-Key": "k1"},
    )
    assert response.status_code == 200
    async with seeded.uow_factory() as uow:
        stored = await uow.push_subscriptions.for_practitioner(PERSON)
        consent = await uow.notification_consents.get("app-" + DEVICE)
    assert [item.device_id for item in stored] == ["app-" + DEVICE]
    assert stored[0].subscription["endpoint"] == SUBSCRIPTION["endpoint"]
    assert consent is not None
    assert (consent.wording_version, consent.status) == ("wording-v1", "active")

    removed = await api.request(
        "DELETE", "/identity/push-subscription", headers={**bearer(), "Idempotency-Key": "k2"}
    )
    assert removed.status_code == 200
    async with seeded.uow_factory() as uow:
        assert await uow.push_subscriptions.for_practitioner(PERSON) == []
        gone = await uow.notification_consents.get("app-" + DEVICE)
    assert gone is not None and gone.status == "inactive"


# ------------------------------------------------------------------ nothing leaks


async def test_no_body_or_log_line_holds_a_number_a_code_a_pin_or_a_device_id(
    api: AsyncClient, seeded: Container, tenant_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    await hold_code(seeded, tenant_id)
    bodies = [
        await api.post("/identity/code", json={"mobile": MOBILE}),
        await api.post(
            "/identity/code/verify", json={"mobile": MOBILE, "code": CODE, "deviceId": DEVICE}
        ),
        await api.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN}),
        await api.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN}),
        await api.get("/identity/status", headers={"X-Device-Id": DEVICE}),
    ]
    text = caplog.text
    for secret in (MOBILE, MOBILE.replace(" ", ""), CODE, PIN, DEVICE):
        assert secret not in text
    for response in bodies[:3] + bodies[4:]:
        for secret in (MOBILE, CODE, PIN, DEVICE):
            assert secret not in response.text
