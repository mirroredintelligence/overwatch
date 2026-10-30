"""The reporter's sign-in to the registration flow and the exchange of a PIN session for a token
(W7B A2), through the app on recording stand-ins: the invitation read, the code request by
invitation, the right code that ends in a reporter token, and the session exchange.

The back end issues the token (TEN-043, DEC-134 item 2): the BFF holds no signing secret. The tenant
is the host's and nothing else; the token names it, the person the invitation names (never one the
caller sends), the services that person holds a reporter post for, and the device the code was
checked on. Every refusal that could tell a caller which tokens or numbers exist is the one 404 (an
invitation) or the one 400 (a code). No number, code, device id or token is in a log or a body that
should not hold it. Sample values only."""

import logging
from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.application.ports.outbound.identity import SessionStore
from diucs.domain.codes import PractitionerRoleCode, RegistrationStatus, Role
from diucs.domain.model.people import PractitionerRole
from diucs.domain.rules.bff_token import TokenRejected, decode_bff_token
from tests.support.w7b_rig import (
    CODE,
    DEVICE,
    INVITE_TOKEN,
    INVITEE,
    MOBILE,
    NOW,
    REGISTRATION,
    SERVICE,
    SERVICE_NAME,
    SUSPENDED_HOST,
    TENANT,
    Rig,
    client,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

INVITATION = "/identity/invitation"
CODE_PATH = "/identity/registration/code"
SESSION = "/identity/registration/session"
SESSION_TOKEN = "/identity/session-token"
OTHER_TOKEN = "WvUtSrQpOnMlKjIhGfEdCbA"


NOW_PLUS_ONE_MINUTE = NOW + timedelta(minutes=1)


def _claims(body: dict[str, Any]) -> Any:
    return decode_bff_token(body["token"], TEST_BFF_SECRET, NOW_PLUS_ONE_MINUTE)


def _sign_in(**changes: Any) -> dict[str, Any]:
    return {"invitation": INVITE_TOKEN, "code": CODE, "deviceId": DEVICE, **changes}


# ------------------------------------------------------------------------------ the invitation


async def test_an_open_invitation_tells_the_page_the_service_and_the_end_of_the_number() -> None:
    rig = Rig()
    rig.invite()
    async with client(rig) as http:
        response = await http.post(INVITATION, json={"invitation": INVITE_TOKEN})

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "open"
    assert body["serviceName"] == SERVICE_NAME
    assert body["numberEnding"] == "123"
    assert body["expiresAt"] == "2026-11-01T09:00:00Z"
    assert response.headers["cache-control"] == "no-store"
    for secret in (MOBILE.replace(" ", ""), "7700900123", TENANT, SERVICE):
        assert secret not in response.text


async def test_an_expired_or_used_invitation_says_only_that_it_is_not_open() -> None:
    rig = Rig()
    rig.invite()
    rig.link(OTHER_TOKEN, None, expires_in=timedelta(hours=-1))
    rig.link("UsedTokenUsedTokenUsedTo", None, used=True)
    async with client(rig) as http:
        expired = await http.post(INVITATION, json={"invitation": OTHER_TOKEN})
        used = await http.post(INVITATION, json={"invitation": "UsedTokenUsedTokenUsedTo"})

    assert expired.json() == {"state": "expired"}
    assert used.json() == {"state": "used"}


async def test_an_unknown_a_malformed_and_a_too_long_invitation_are_one_404() -> None:
    rig = Rig()
    rig.invite()
    async with client(rig) as http:
        unknown = await http.post(INVITATION, json={"invitation": OTHER_TOKEN})
        malformed = await http.post(INVITATION, json={"invitation": "not a token!"})
        long = await http.post(INVITATION, json={"invitation": "A" * 200})

    assert unknown.status_code == malformed.status_code == long.status_code == 404
    assert unknown.content == malformed.content == long.content
    assert rig.units.writes.names == []


async def test_the_invitation_route_takes_no_tenant_and_no_other_field() -> None:
    rig = Rig()
    rig.invite()
    async with client(rig) as http:
        for extra in ({"tenant": TENANT}, {"role": "lead"}, {"mobile": MOBILE}):
            response = await http.post(INVITATION, json={"invitation": INVITE_TOKEN, **extra})
            assert response.status_code == 400
        no_token = await http.post(INVITATION, json={})
    assert no_token.status_code == 400


async def test_a_host_no_tenant_owns_and_a_suspended_tenants_host_answer_404() -> None:
    rig = Rig()
    rig.invite()
    async with client(rig, host="tenant-x.example.test") as unknown:
        a = await unknown.post(INVITATION, json={"invitation": INVITE_TOKEN})
    async with client(rig, host=SUSPENDED_HOST) as suspended:
        b = await suspended.post(INVITATION, json={"invitation": INVITE_TOKEN})
    assert a.status_code == b.status_code == 404
    assert a.content == b.content


# ----------------------------------------------------------------------------- the code request


async def test_a_code_is_sent_to_the_number_the_invitation_holds_and_the_body_has_no_number() -> (
    None
):
    rig = Rig()
    rig.invite()
    async with client(rig) as http:
        response = await http.post(CODE_PATH, json={"invitation": INVITE_TOKEN})

    assert response.status_code == 202
    assert response.json() == {"accepted": True, "resendAfterSeconds": 60}
    assert [m.event_type for m in rig.units.outbox.messages] == ["SendCode"]
    assert await rig.codes.get("setup", rig.hasher.hash(MOBILE)) is not None
    assert "7700900123" not in response.text


async def test_no_code_is_sent_for_an_invitation_that_is_expired_used_or_unknown() -> None:
    rig = Rig()
    rig.invite()
    rig.link(OTHER_TOKEN, None, expires_in=timedelta(hours=-1))
    async with client(rig) as http:
        expired = await http.post(CODE_PATH, json={"invitation": OTHER_TOKEN})
        unknown = await http.post(CODE_PATH, json={"invitation": "ZzZzZzZzZzZzZzZzZzZzZzZ"})

    assert expired.status_code == unknown.status_code == 404
    assert expired.content == unknown.content
    assert rig.units.outbox.messages == []


async def test_a_second_request_inside_the_cooldown_is_still_202_and_sends_no_second_code() -> None:
    rig = Rig()
    rig.invite()
    async with client(rig) as http:
        first = await http.post(CODE_PATH, json={"invitation": INVITE_TOKEN})
        again = await http.post(CODE_PATH, json={"invitation": INVITE_TOKEN})

    assert first.status_code == again.status_code == 202
    assert len(rig.units.outbox.messages) == 1


# ----------------------------------------------------------------------------- the right code


async def test_a_right_code_ends_in_a_reporter_token_for_the_invited_person() -> None:
    rig = Rig()
    rig.invite()
    await rig.hold_code()
    async with client(rig) as http:
        response = await http.post(SESSION, json=_sign_in())

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "token",
        "expiresAt",
        "role",
        "tenant",
        "registrationId",
        "serviceId",
        "serviceName",
    }
    assert body["role"] == "reporter"
    # The tenant the host bound, so the BFF can keep it in its sealed session (DEC-900 item 2).
    assert body["tenant"] == TENANT
    assert (body["registrationId"], body["serviceId"]) == (REGISTRATION, SERVICE)
    claims = _claims(body)
    assert claims.sub == INVITEE
    assert claims.role is Role.REPORTER
    assert claims.tenant == TENANT
    assert claims.services == frozenset({SERVICE})
    assert claims.device == DEVICE
    assert claims.epoch == 1
    assert claims.expires_at == NOW_PLUS_ONE_MINUTE - timedelta(minutes=1) + timedelta(hours=2)
    assert response.headers["cache-control"] == "no-store"
    # The code is recorded on the device in the same call, as the code check does.
    assert rig.units.devices.held[(INVITEE, DEVICE)]["verified_at"] is not None


async def test_the_token_names_only_the_services_the_person_holds_a_reporter_post_for() -> None:
    rig = Rig()
    rig.invite()
    await rig.hold_code()
    for role_id, service, code, active in (
        ("role-b", "svc-b", PractitionerRoleCode.COORDINATOR, True),
        ("role-c", "svc-c", PractitionerRoleCode.DUTY_MANAGER, False),
        ("role-d", "svc-d", PractitionerRoleCode.SHIFT_LEAD, True),
    ):
        rig.units.people.roles[role_id] = PractitionerRole(
            id=role_id,
            practitioner_id=INVITEE,
            service_id=service,
            code=code,
            active=active,
            channel=None,
            period_start=NOW_PLUS_ONE_MINUTE - timedelta(days=1),
        )
    async with client(rig) as http:
        response = await http.post(SESSION, json=_sign_in())

    assert _claims(response.json()).services == frozenset({SERVICE, "svc-b"})


async def test_a_wrong_code_gives_no_token_and_five_wrong_tries_say_ask_for_a_new_code() -> None:
    rig = Rig()
    rig.invite()
    await rig.hold_code()
    async with client(rig) as http:
        answers = [await http.post(SESSION, json=_sign_in(code="000000")) for _ in range(5)]

    assert [a.status_code for a in answers] == [400] * 5
    texts = [a.json()["issue"][0]["diagnostics"] for a in answers]
    assert texts == ["That code is not right"] * 4 + ["Ask for a new code"]
    assert all("token" not in a.json() for a in answers)
    assert (INVITEE, DEVICE) not in rig.units.devices.held


async def test_a_right_code_on_a_dead_invitation_gives_nothing_and_keeps_the_code() -> None:
    rig = Rig()
    rig.invite()
    rig.link(OTHER_TOKEN, None, expires_in=timedelta(hours=-1))
    await rig.hold_code()
    async with client(rig) as http:
        expired = await http.post(SESSION, json=_sign_in(invitation=OTHER_TOKEN))
        unknown = await http.post(SESSION, json=_sign_in(invitation="ZzZzZzZzZzZzZzZzZzZzZzZ"))
        right = await http.post(SESSION, json=_sign_in())

    assert expired.status_code == unknown.status_code == 404
    assert expired.content == unknown.content
    assert right.status_code == 200


async def test_a_suspended_tenants_host_gets_no_token_and_the_code_is_not_tried() -> None:
    rig = Rig()
    rig.invite()
    await rig.hold_code()
    async with client(rig, host=SUSPENDED_HOST) as http:
        response = await http.post(SESSION, json=_sign_in())

    assert response.status_code == 404
    assert rig.units.devices.held == {}


async def test_a_bad_device_id_is_a_400_and_a_revoked_device_is_a_409() -> None:
    rig = Rig()
    rig.invite()
    await rig.hold_code()
    rig.units.devices.held[(INVITEE, DEVICE)] = {
        "revoked": True,
        "pending": False,
        "verified_at": None,
        "at": NOW_PLUS_ONE_MINUTE,
    }
    async with client(rig) as http:
        short = await http.post(SESSION, json=_sign_in(deviceId="short"))
        held = await http.post(SESSION, json=_sign_in())

    assert short.status_code == 400
    assert held.status_code == 409
    assert "token" not in held.json()


async def test_the_body_names_the_invitation_or_the_mobile_not_both_and_no_tenant_or_person() -> (
    None
):
    rig = Rig()
    rig.invite()
    async with client(rig) as http:
        both = await http.post(SESSION, json=_sign_in(mobile=MOBILE))
        neither = await http.post(SESSION, json={"code": CODE, "deviceId": DEVICE})
        tenant = await http.post(SESSION, json=_sign_in(tenant="other-tenant"))
        person = await http.post(SESSION, json=_sign_in(practitionerId=INVITEE))
        role = await http.post(SESSION, json=_sign_in(role="lead"))
        services = await http.post(SESSION, json=_sign_in(services=["svc-x"]))

    for response in (both, neither, tenant, person, role, services):
        assert response.status_code == 400
    assert rig.units.writes.names == []


async def test_a_returning_applicant_signs_in_by_number_and_the_code() -> None:
    rig = Rig()
    rig.invite(RegistrationStatus.DRAFT)
    await rig.hold_code()
    async with client(rig) as http:
        response = await http.post(
            SESSION, json={"mobile": MOBILE, "code": CODE, "deviceId": DEVICE}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "registrationId" not in body
    claims = _claims(body)
    assert (claims.sub, claims.services, claims.role) == (
        INVITEE,
        frozenset({SERVICE}),
        Role.REPORTER,
    )


async def test_an_unknown_number_and_a_person_with_no_post_answer_as_a_wrong_code() -> None:
    rig = Rig()
    rig.invite()
    await rig.hold_code(mobile="07700 900789")
    await rig.hold_code(mobile="07700 900456")
    rig.units.people.practitioners["prac-nopost"] = rig.units.people.practitioners[
        INVITEE
    ].__class__(
        id="prac-nopost",
        active=True,
        display_name="Nobody",
        phone_hash=rig.hasher.hash("07700 900456"),
    )
    async with client(rig) as http:
        unknown = await http.post(
            SESSION, json={"mobile": "07700 900789", "code": CODE, "deviceId": DEVICE}
        )
        no_post = await http.post(
            SESSION, json={"mobile": "07700 900456", "code": CODE, "deviceId": DEVICE}
        )

    assert unknown.status_code == no_post.status_code == 400
    assert unknown.content == no_post.content
    assert "token" not in unknown.text


async def test_no_log_line_holds_the_number_the_code_the_device_or_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    rig.invite()
    await rig.hold_code()
    caplog.set_level(logging.DEBUG)
    async with client(rig) as http:
        await http.post(INVITATION, json={"invitation": INVITE_TOKEN})
        await http.post(CODE_PATH, json={"invitation": INVITE_TOKEN})
        response = await http.post(SESSION, json=_sign_in())
    logged = caplog.text
    for secret in (INVITE_TOKEN, CODE, DEVICE, "7700900123", response.json()["token"]):
        assert secret not in logged


async def test_a_token_made_with_another_secret_is_not_this_ones() -> None:
    rig = Rig()
    rig.invite()
    await rig.hold_code()
    async with client(rig) as http:
        body = (await http.post(SESSION, json=_sign_in())).json()
    with pytest.raises(TokenRejected):
        decode_bff_token(
            body["token"], b"another-secret-another-secret-another", NOW_PLUS_ONE_MINUTE
        )
    with pytest.raises(TokenRejected):
        decode_bff_token(body["token"], TEST_BFF_SECRET, NOW_PLUS_ONE_MINUTE + timedelta(hours=3))


# ------------------------------------------------------------------- the PIN session exchange


async def _session(
    rig: Rig, role: Role = Role.REPORTER, services: tuple[str, ...] = (SERVICE,)
) -> str:
    sessions: SessionStore = rig.sessions
    return await sessions.create(role, INVITEE, DEVICE, services, NOW_PLUS_ONE_MINUTE, epoch=0)


async def test_a_live_pin_session_is_exchanged_for_a_short_reporter_token() -> None:
    rig = Rig()
    rig.invite()
    session_id = await _session(rig)
    async with client(rig) as http:
        response = await http.post(SESSION_TOKEN, json={"sessionId": session_id})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"token", "expiresAt", "role"}
    claims = _claims(body)
    assert (claims.sub, claims.role, claims.services, claims.device) == (
        INVITEE,
        Role.REPORTER,
        frozenset({SERVICE}),
        DEVICE,
    )
    assert claims.tenant == TENANT
    assert claims.expires_at == NOW_PLUS_ONE_MINUTE - timedelta(minutes=1) + timedelta(minutes=30)


async def test_an_unknown_ended_or_signed_out_session_is_the_one_404() -> None:
    rig = Rig()
    rig.invite()
    ended = await _session(rig)
    await rig.sessions.delete(ended)
    signed_out = await _session(rig)
    await rig.sessions.delete_all_for_person(INVITEE)
    async with client(rig) as http:
        answers = [
            await http.post(SESSION_TOKEN, json={"sessionId": sid})
            for sid in ("never-existed", ended, signed_out)
        ]

    assert {a.status_code for a in answers} == {404}
    assert len({a.content for a in answers}) == 1


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.REPORTER])
async def test_a_session_of_a_role_that_is_not_a_reporter_gets_no_token(role: Role) -> None:
    # The token of a PIN session is a reporter's and nobody else's (W9H, DEC-1041): an executive
    # signs in through the directory, so a session that names the role is one nobody derived, and
    # it gets the one 404 of any session that cannot be exchanged. All thirteen roles, one answer.
    rig = Rig()
    rig.invite()
    session_id = await _session(rig, role)
    async with client(rig) as http:
        response = await http.post(SESSION_TOKEN, json={"sessionId": session_id})
        unknown = await http.post(SESSION_TOKEN, json={"sessionId": "never-existed"})
    assert response.status_code == 404
    assert response.content == unknown.content


async def test_the_exchange_takes_nothing_but_the_session_and_not_a_suspended_tenants_host() -> (
    None
):
    rig = Rig()
    rig.invite()
    session_id = await _session(rig)
    async with client(rig) as http:
        extra = await http.post(SESSION_TOKEN, json={"sessionId": session_id, "tenant": TENANT})
        empty = await http.post(SESSION_TOKEN, json={})
    async with client(rig, host=SUSPENDED_HOST) as suspended:
        refused = await suspended.post(SESSION_TOKEN, json={"sessionId": session_id})

    assert (extra.status_code, empty.status_code, refused.status_code) == (400, 400, 404)
