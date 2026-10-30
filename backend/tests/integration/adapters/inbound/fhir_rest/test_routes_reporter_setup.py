"""The reporter set-up routes behind a link or a device (W7C, DEC-810 to DEC-813, H-450, H-451).

The browser at set-up holds an invitation token and its own device id, never a number. These routes
look an invitation up, send and check a text code for an invitation or for a device (the 30-day
check and a PIN reset), record the channel of a device a text code verified, and serve the push
key. What a test asserts is what the route answered and what was really stored, read back through
the graph and Redis (DEC-004). Samples only: no real number, no patient data.
"""

import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.application.ports.outbound.identity import HmacPhoneHasher
from diucs.application.ports.outbound.tokens import LinkTokenService
from diucs.application.tenancy import bind_tenant
from diucs.bootstrap.container import Container
from diucs.domain.codes import Channel
from tests.integration.adapters.inbound.fhir_rest.reporter_rig import (
    CODE,
    DEVICE,
    MOBILE,
    NOW,
    OTHER_DEVICE,
    PERSON,
    PIN,
    VAPID_PUBLIC_KEY,
    build_app,
    client_for,
    hold_code,
    open_container,
    seed_host_and_head,
    seed_invitation,
    seed_world,
)
from tests.support.link_rig import HOST_A
from tests.support.neo4j import ThrowawayNeo4j, node_props, read_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

NEW_DEVICE = "device-cccccccccccccccccccccc"
UNKNOWN_DEVICE = "device-dddddddddddddddddddddd"
UNKNOWN_TOKEN = "AbCdEfGhIjKlMnOpQrStUvW"
GONE = {"state": "expired"}


@pytest_asyncio.fixture(loop_scope="session")
async def container(
    harness_container: ThrowawayNeo4j, clean_graph: None, tenant_id: str
) -> AsyncIterator[Container]:
    async for opened in open_container(harness_container, FixedClock(NOW), tenant_id):
        yield opened


@pytest_asyncio.fixture(loop_scope="session")
async def world(container: Container, neo4j_driver: AsyncDriver, tenant_id: str) -> Container:
    await seed_host_and_head(neo4j_driver, tenant_id, HOST_A)
    await seed_world(container, tenant_id)
    return container


@pytest_asyncio.fixture(loop_scope="session")
async def api(world: Container) -> AsyncIterator[AsyncClient]:
    async with client_for(await build_app(world), HOST_A) as client:
        yield client


async def outbox_count(driver: AsyncDriver, event_type: str) -> int:
    async def work(tx: Any) -> int:
        result = await tx.run(
            "MATCH (m:OutboxMessage {eventType: $type, tenantId: $tenant}) RETURN count(m) AS n",
            type=event_type,
        )
        return int((await result.single())["n"])

    return await read_tx(driver, work)


# ----------------------------------------------------------------------- invitation lookup


async def test_an_open_invitation_shows_the_service_the_post_the_expiry_and_the_masked_number(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    token = await seed_invitation(world, tenant_id)

    response = await api.get(f"/invitations/{token}")

    assert response.status_code == 200
    assert response.json() == {
        "state": "valid",
        "service": "UCR New",
        "role": "Duty manager",
        "maskedPhone": "07xxx xxx123",
        "expiresAt": "2026-10-31T06:00:00Z",
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    for secret in (MOBILE, MOBILE.replace(" ", ""), "7700900123", token):
        assert secret not in response.text


@pytest.mark.parametrize("case", ["unknown", "malformed", "expired", "used", "other-purpose"])
async def test_every_unusable_invitation_gets_the_one_refusal(
    api: AsyncClient, world: Container, tenant_id: str, case: str
) -> None:
    expected = await api.get(f"/invitations/{UNKNOWN_TOKEN}")
    assert (expected.status_code, expected.json()) == (410, GONE)

    if case == "unknown":
        token = UNKNOWN_TOKEN
    elif case == "malformed":
        token = "not-a-token!"
    elif case == "expired":
        token = await seed_invitation(world, tenant_id, expires_at=NOW - timedelta(minutes=1))
    elif case == "used":
        token = await seed_invitation(world, tenant_id, used=True)
    else:
        with bind_tenant(tenant_id):
            async with world.uow_factory() as uow:
                token = await LinkTokenService(uow.link_tokens, world.secrets, world.clock).issue(
                    "capacity-reply",
                    "comm-1",
                    HmacPhoneHasher(world.secrets).hash(MOBILE),
                    NOW + timedelta(hours=1),
                )
                await uow.commit()

    response = await api.get(f"/invitations/{token}")

    assert response.status_code == expected.status_code
    assert response.json() == expected.json() == GONE
    assert response.headers["cache-control"] == "no-store"


async def test_an_invitation_on_a_host_no_tenant_owns_is_the_same_refusal(
    world: Container, tenant_id: str
) -> None:
    token = await seed_invitation(world, tenant_id)

    async with client_for(await build_app(world), "nobody.example.test") as stranger:
        response = await stranger.get(f"/invitations/{token}")

    assert (response.status_code, response.json()) == (410, GONE)


async def test_the_invitation_lookup_is_throttled_per_address(
    api: AsyncClient, world: Container
) -> None:
    answers = [await api.get(f"/invitations/{UNKNOWN_TOKEN}") for _ in range(61)]

    assert [a.status_code for a in answers[:60]] == [410] * 60
    assert answers[60].status_code == 429
    assert "retry-after" in answers[60].headers


# ----------------------------------------------------------------------- code for an invitation


async def test_a_code_for_an_invitation_is_kept_and_queued_and_an_unusable_one_is_kept_and_discarded(
    api: AsyncClient, world: Container, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    token = await seed_invitation(world, tenant_id)

    known = await api.post(f"/identity/invitations/{token}/code", json={})
    unknown = await api.post(f"/identity/invitations/{UNKNOWN_TOKEN}/code", json={})

    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content
    assert known.json() == {"accepted": True, "resendAfterSeconds": 60}
    assert await outbox_count(neo4j_driver, "SendCode") == 1
    assert await outbox_count(neo4j_driver, "DiscardCode") == 1
    phone_hash = HmacPhoneHasher(world.secrets).hash(MOBILE)
    with bind_tenant(tenant_id):
        held = await world.codes.get("setup", phone_hash)
    assert held is not None
    for body in (known.text, unknown.text):
        assert "7700" not in body


async def test_a_code_for_an_invitation_takes_no_number_or_tenant(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    token = await seed_invitation(world, tenant_id)

    refused = await api.post(
        f"/identity/invitations/{token}/code", json={"mobile": MOBILE, "tenant": "other"}
    )

    assert refused.status_code == 400


async def test_a_right_code_for_an_invitation_registers_the_device_and_the_pin_and_channel_follow(
    api: AsyncClient, world: Container, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    token = await seed_invitation(world, tenant_id)
    await hold_code(world, tenant_id)

    verified = await api.post(
        f"/identity/invitations/{token}/code/verify", json={"code": CODE, "deviceId": NEW_DEVICE}
    )

    assert verified.status_code == 200
    assert verified.json() == {"verified": True}
    device = await node_props(neo4j_driver, "Device", id=NEW_DEVICE)
    assert device["status"] == "active"
    assert device["lastVerifiedAt"] is not None

    chosen = await api.post("/identity/channel", json={"deviceId": NEW_DEVICE, "channel": "app"})
    assert chosen.status_code == 200
    assert chosen.json() == {"channel": "app"}
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            role = await uow.people.get_role("role-invitee")
    assert role is not None and role.channel is Channel.PUSH

    set_pin = await api.post("/identity/pin", json={"deviceId": NEW_DEVICE, "pin": PIN})
    assert set_pin.status_code == 200


async def test_a_wrong_code_names_the_tries_left_and_five_ask_for_a_new_code(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    token = await seed_invitation(world, tenant_id)
    await hold_code(world, tenant_id)

    answers = [
        await api.post(
            f"/identity/invitations/{token}/code/verify",
            json={"code": "000000", "deviceId": NEW_DEVICE},
        )
        for _ in range(5)
    ]

    assert [a.status_code for a in answers] == [400] * 5
    texts = [a.json()["issue"][0]["diagnostics"] for a in answers]
    assert texts == ["That code is not right"] * 4 + ["Ask for a new code"]
    assert [a.json()["triesLeft"] for a in answers] == [4, 3, 2, 1, 0]


async def test_a_wrong_code_for_an_unknown_invitation_answers_as_one_for_a_real_one(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    token = await seed_invitation(world, tenant_id)
    await api.post(f"/identity/invitations/{token}/code", json={})
    await api.post(f"/identity/invitations/{UNKNOWN_TOKEN}/code", json={})

    real = await api.post(
        f"/identity/invitations/{token}/code/verify",
        json={"code": "000000", "deviceId": NEW_DEVICE},
    )
    unknown = await api.post(
        f"/identity/invitations/{UNKNOWN_TOKEN}/code/verify",
        json={"code": "000000", "deviceId": NEW_DEVICE},
    )

    assert real.status_code == unknown.status_code == 400
    assert real.json() == unknown.json()


async def test_an_expired_invitation_cannot_be_verified_even_with_the_code_that_was_sent(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    token = await seed_invitation(world, tenant_id)
    await hold_code(world, tenant_id)
    world.clock.advance(timedelta(hours=41))  # type: ignore[attr-defined]
    try:
        late = await api.post(
            f"/identity/invitations/{token}/code/verify",
            json={"code": CODE, "deviceId": NEW_DEVICE},
        )
    finally:
        world.clock.advance(timedelta(hours=-41))  # type: ignore[attr-defined]

    assert late.status_code == 400


# ----------------------------------------------------------------------- code for a device


@pytest.mark.parametrize("purpose", ["reverify", "pin-reset"])
async def test_a_device_code_goes_to_the_owner_and_an_unknown_device_is_the_same_answer(
    api: AsyncClient, world: Container, neo4j_driver: AsyncDriver, tenant_id: str, purpose: str
) -> None:
    known = await api.post("/identity/device/code", json={"deviceId": DEVICE, "purpose": purpose})
    unknown = await api.post(
        "/identity/device/code", json={"deviceId": UNKNOWN_DEVICE, "purpose": purpose}
    )

    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content
    assert await outbox_count(neo4j_driver, "SendCode") == 1
    assert await outbox_count(neo4j_driver, "DiscardCode") == 1
    phone_hash = HmacPhoneHasher(world.secrets).hash(MOBILE)
    with bind_tenant(tenant_id):
        assert await world.codes.get(purpose, phone_hash) is not None


async def test_a_device_code_is_for_the_30_day_check_or_a_pin_reset_and_nothing_else(
    api: AsyncClient,
) -> None:
    for purpose in ("setup", "new-device", "register"):
        refused = await api.post(
            "/identity/device/code", json={"deviceId": DEVICE, "purpose": purpose}
        )
        assert refused.status_code == 400


@pytest.mark.parametrize("purpose", ["reverify", "pin-reset"])
async def test_a_right_device_code_stamps_the_verification_and_a_pin_can_follow(
    api: AsyncClient, world: Container, neo4j_driver: AsyncDriver, tenant_id: str, purpose: str
) -> None:
    await hold_code(world, tenant_id, purpose=purpose)

    verified = await api.post(
        "/identity/device/code/verify",
        json={"deviceId": DEVICE, "purpose": purpose, "code": CODE},
    )

    assert verified.status_code == 200
    assert verified.json() == {"verified": True}
    status = await api.get("/identity/status", headers={"X-Device-Id": DEVICE})
    assert status.json() == {"reverifyDue": False, "daysLeft": 30}
    assert (
        await api.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN})
    ).status_code == 200


async def test_a_wrong_device_code_names_the_tries_left_and_an_unknown_device_answers_alike(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await hold_code(world, tenant_id, purpose="reverify")
    await api.post(
        "/identity/device/code", json={"deviceId": UNKNOWN_DEVICE, "purpose": "reverify"}
    )

    known = await api.post(
        "/identity/device/code/verify",
        json={"deviceId": DEVICE, "purpose": "reverify", "code": "000000"},
    )
    unknown = await api.post(
        "/identity/device/code/verify",
        json={"deviceId": UNKNOWN_DEVICE, "purpose": "reverify", "code": "000000"},
    )

    assert known.status_code == unknown.status_code == 400
    assert known.json() == unknown.json()
    assert known.json()["triesLeft"] == 4


async def test_the_code_of_another_purpose_does_not_verify_a_device(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await hold_code(world, tenant_id, purpose="pin-reset")

    refused = await api.post(
        "/identity/device/code/verify",
        json={"deviceId": DEVICE, "purpose": "reverify", "code": CODE},
    )

    assert refused.status_code == 400


# ----------------------------------------------------------------------- channel of a device


async def test_a_channel_needs_a_device_that_a_text_code_verified_in_the_last_ten_minutes(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    # The seeded device was verified three days ago.
    stale = await api.post("/identity/channel", json={"deviceId": DEVICE, "channel": "text"})
    unknown = await api.post(
        "/identity/channel", json={"deviceId": UNKNOWN_DEVICE, "channel": "text"}
    )

    assert stale.status_code == unknown.status_code == 403
    assert stale.json() == unknown.json()

    await hold_code(world, tenant_id, purpose="pin-reset")
    await api.post(
        "/identity/device/code/verify",
        json={"deviceId": DEVICE, "purpose": "pin-reset", "code": CODE},
    )
    fresh = await api.post("/identity/channel", json={"deviceId": DEVICE, "channel": "text"})
    assert (fresh.status_code, fresh.json()) == (200, {"channel": "text"})

    world.clock.advance(timedelta(minutes=11))  # type: ignore[attr-defined]
    try:
        late = await api.post("/identity/channel", json={"deviceId": DEVICE, "channel": "app"})
    finally:
        world.clock.advance(timedelta(minutes=-11))  # type: ignore[attr-defined]
    assert late.status_code == 403


@pytest.mark.parametrize("channel", ["push", "sms", "", "APP"])
async def test_a_channel_the_screens_do_not_offer_is_refused(
    api: AsyncClient, channel: str
) -> None:
    refused = await api.post("/identity/channel", json={"deviceId": DEVICE, "channel": channel})

    assert refused.status_code == 400


# ----------------------------------------------------------------------- the push key


async def test_the_push_key_is_the_public_key_and_cannot_be_cached(api: AsyncClient) -> None:
    response = await api.get("/public/push-key")

    assert response.status_code == 200
    assert response.json() == {"publicKey": VAPID_PUBLIC_KEY}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["vary"] == "Host"


async def test_the_push_key_is_not_served_to_a_host_no_tenant_owns(world: Container) -> None:
    async with client_for(await build_app(world), "nobody.example.test") as stranger:
        response = await stranger.get("/public/push-key")

    assert response.status_code == 404


# ----------------------------------------------------------------------- nothing leaks


async def test_no_log_line_or_body_holds_a_token_a_number_a_code_or_a_device_id(
    api: AsyncClient, world: Container, tenant_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    token = await seed_invitation(world, tenant_id)
    await hold_code(world, tenant_id)
    answers = [
        await api.get(f"/invitations/{token}"),
        await api.post(f"/identity/invitations/{token}/code", json={}),
        await api.post(
            f"/identity/invitations/{token}/code/verify",
            json={"code": CODE, "deviceId": OTHER_DEVICE},
        ),
        await api.post("/identity/device/code", json={"deviceId": DEVICE, "purpose": "reverify"}),
    ]

    for secret in (token, MOBILE, MOBILE.replace(" ", ""), CODE, OTHER_DEVICE, DEVICE, PERSON):
        assert secret not in caplog.text
        for answer in answers:
            assert secret not in answer.text
    assert TEST_BFF_SECRET.decode() not in caplog.text
