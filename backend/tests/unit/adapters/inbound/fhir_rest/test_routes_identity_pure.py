"""The reporter identity routes (R11), called through an in-process transport on recording stand-ins
for the stores: no Docker, no Neo4j, no Redis. What is really stored is in the integration test.

The rules the routes keep, each pinned here: one answer for a known and an unknown number; a right
code is recorded on its device; a wrong code, a lapsed code, five tries, a PIN with no recent code,
a wrong PIN, a lock and the 30-day check answer as the prompt says; every refusal for an unknown or
unusable device is the answer of the others; the tenant is the host and nothing else; the attempts
are throttled per address with a key that holds no identifier; a session store that cannot be
reached answers 503 and does nothing; the push routes check the person and the device on every use;
and no number, code, PIN, device id or session id is in a log line or a body that should not hold
it. Synthetic values only: no patient data, no real number.
"""

import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from diucs.adapters.inbound.fhir_rest import routes_identity
from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_code_store import InMemoryCodeStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.pin import PIN_HMAC_SECRET, pin_hash
from diucs.application.use_cases.text_code import CODE_HMAC_SECRET, code_hash
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.tenant import TenantStatus
from diucs.domain.rules.identity_policy import CodeState, PinState
from tests.support.registration_rig import StubLimiter, StubUnits
from tests.support.session_rig import StubSessions
from tests.support.tenant_samples import make_tenant

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
HOST = "tenant-a.example.test"
SUSPENDED_HOST = "tenant-s.example.test"
UNKNOWN_HOST = "tenant-x.example.test"
TENANT = "example-icb"
SECRETS = {
    BFF_SECRET_NAME: TEST_BFF_SECRET,
    PHONE_HASH_SECRET: b"phone-hash-pure-test-secret-0123456789ab",
    CODE_HMAC_SECRET: b"code-hmac-pure-test-secret-0123456789abc",
    PIN_HMAC_SECRET: b"pin-hmac-pure-test-secret-0123456789abcd",
    "link-token": b"link-token-pure-test-secret-0123456789ab",
}
MOBILE = "07700 900123"
OTHER_MOBILE = "07700 900456"
UNKNOWN_MOBILE = "07700 900789"
CODE = "482913"
PIN = "135790"
PERSON = "prac-1"
DEVICE = "device-aaaaaaaaaaaaaaaaaaaaaa"
OTHER_DEVICE = "device-bbbbbbbbbbbbbbbbbbbbbb"
UNKNOWN_DEVICE = "device-cccccccccccccccccccccc"
JSON_HEADERS = {"Content-Type": "application/json"}
SUBSCRIPTION = {
    "endpoint": "https://push.example/sample-endpoint",
    "keys": {"p256dh": "sample-p256dh", "auth": "sample-auth"},
}


class _Directory:
    def __init__(self) -> None:
        self._by_host = {HOST: make_tenant(), SUSPENDED_HOST: make_tenant(TenantStatus.SUSPENDED)}

    async def get(self, tenant_id: str) -> Any:
        return make_tenant(id=tenant_id)

    async def by_host(self, host: str) -> Any:
        return self._by_host.get(host)


class _Sealer:
    def seal(self, content: str, *, message_id: str, tenant_id: str, recipient_role_id: str) -> str:
        return f"sealed:{message_id}"

    def unseal(
        self, sealed: str, *, message_id: str, tenant_id: str, recipient_role_id: str
    ) -> str:
        raise AssertionError("a route never opens a sealed code")


class _Container:
    def __init__(self) -> None:
        self.clock = FixedClock(NOW)
        self.ids = SequentialIds()
        self.rng = random.Random(7)
        self.units = StubUnits(ScopeId.tenant(TENANT))
        self.uow_factory = self.units
        self.tenants = _Directory()
        self.secrets = FixedSecretStore(SECRETS)
        self.codes = InMemoryCodeStore(self.clock)
        self.sessions = StubSessions(self.units.events)
        self.rate_limiter = StubLimiter()
        self.sealer = _Sealer()
        self.cache = InMemoryCache(self.clock)
        self.hasher = HmacPhoneHasher(self.secrets)
        self.units.people.practitioners[PERSON] = Practitioner(
            id=PERSON,
            active=True,
            display_name="Sample Reporter",
            phone_hash=self.hasher.hash(MOBILE),
        )
        self.units.people.roles["role-1"] = PractitionerRole(
            id="role-1",
            practitioner_id=PERSON,
            service_id="svc-west",
            code=PractitionerRoleCode.DUTY_MANAGER,
            active=True,
            channel=None,
            period_start=NOW - timedelta(days=30),
        )

    def register_device(
        self, device: str = DEVICE, *, verified_ago: timedelta | None = timedelta(minutes=1)
    ) -> None:
        self.units.devices.held[(PERSON, device)] = {
            "revoked": False,
            "pending": False,
            "verified_at": None if verified_ago is None else NOW - verified_ago,
            "at": NOW - timedelta(days=60),
        }

    def give_pin(self, device: str = DEVICE, pin: str = PIN) -> None:
        secret = SECRETS[PIN_HMAC_SECRET]
        self.units.pins.held[(PERSON, device)] = (pin_hash(secret, PERSON, device, pin), PinState())

    async def hold_code(
        self, mobile: str = MOBILE, purpose: str = "setup", code: str = CODE
    ) -> None:
        phone_hash = self.hasher.hash(mobile)
        stored = code_hash(SECRETS[CODE_HMAC_SECRET], phone_hash, purpose, code)
        await self.codes.save(purpose, phone_hash, stored, CodeState(NOW - timedelta(seconds=30)))


def client(
    container: _Container, host: str = HOST, address: str = "203.0.113.9"
) -> httpx.AsyncClient:
    app = create_app(container)  # type: ignore[arg-type]
    app.state.secrets = container.secrets
    app.state.cache = container.cache
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(address, 1234)),
        base_url=f"http://{host}",
    )


def bearer(
    role: Role = Role.REPORTER, device: str | None = DEVICE, sub: str = PERSON
) -> dict[str, str]:
    token = issue_test_token(
        role,
        ["svc-west"],
        sub,
        tenant=TENANT,
        device=device,
        expires_at=NOW + timedelta(hours=8),
    )
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ ask for a code


async def test_a_known_and_an_unknown_number_get_the_same_202_and_only_the_known_one_is_sent() -> (
    None
):
    container = _Container()
    async with client(container) as http:
        known = await http.post("/identity/code", json={"mobile": MOBILE})
        unknown = await http.post("/identity/code", json={"mobile": UNKNOWN_MOBILE})
    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content
    events = [message.event_type for message in container.units.outbox.messages]
    assert events == ["SendCode", "DiscardCode"]


async def test_a_resend_inside_the_cooldown_is_still_202_and_sends_no_second_code() -> None:
    container = _Container()
    async with client(container) as http:
        first = await http.post("/identity/code", json={"mobile": MOBILE})
        again = await http.post("/identity/code", json={"mobile": MOBILE})
    assert first.status_code == again.status_code == 202
    assert first.content == again.content
    assert len(container.units.outbox.messages) == 1


async def test_no_body_holds_the_number_or_the_code_and_the_answer_is_not_cached() -> None:
    container = _Container()
    async with client(container) as http:
        response = await http.post("/identity/code", json={"mobile": MOBILE})
    assert MOBILE.replace(" ", "") not in response.text.replace(" ", "")
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("mobile", ["0161 496 0000", "not a number", "07700"])
async def test_a_number_that_is_not_a_uk_mobile_is_a_400_that_does_not_echo_it(mobile: str) -> None:
    container = _Container()
    async with client(container) as http:
        response = await http.post("/identity/code", json={"mobile": mobile})
    assert response.status_code == 400
    assert mobile not in response.text
    assert container.units.writes.names == []


async def test_the_purpose_defaults_to_setup_and_register_is_not_one_the_route_takes() -> None:
    container = _Container()
    async with client(container) as http:
        ok = await http.post("/identity/code", json={"mobile": MOBILE})
        bad = await http.post("/identity/code", json={"mobile": MOBILE, "purpose": "register"})
    assert ok.status_code == 202
    assert bad.status_code == 400


async def test_a_body_that_names_a_tenant_or_a_person_is_refused() -> None:
    container = _Container()
    async with client(container) as http:
        for extra in ({"tenant": TENANT}, {"practitionerId": PERSON}, {"role": "lead"}):
            response = await http.post("/identity/code", json={"mobile": MOBILE, **extra})
            assert response.status_code == 400
    assert container.units.writes.names == []


# ------------------------------------------------------------------ verify a code


def verify_body(**changes: Any) -> dict[str, Any]:
    return {"mobile": MOBILE, "code": CODE, "deviceId": DEVICE, **changes}


async def test_a_right_code_is_200_and_is_recorded_on_the_device() -> None:
    container = _Container()
    await container.hold_code()
    async with client(container) as http:
        response = await http.post("/identity/code/verify", json=verify_body())
    assert response.status_code == 200
    assert response.json() == {"verified": True}
    held = container.units.devices.held[(PERSON, DEVICE)]
    assert held["verified_at"] == NOW
    assert held["pending"] is False


async def test_a_wrong_code_is_a_400_that_is_not_right_and_the_fifth_says_ask_for_a_new_code() -> (
    None
):
    container = _Container()
    await container.hold_code()
    async with client(container) as http:
        answers = [
            await http.post("/identity/code/verify", json=verify_body(code="000000"))
            for _ in range(5)
        ]
    texts = [answer.json()["issue"][0]["diagnostics"] for answer in answers]
    assert [answer.status_code for answer in answers] == [400] * 5
    assert texts == ["That code is not right"] * 4 + ["Ask for a new code"]
    assert (PERSON, DEVICE) not in container.units.devices.held


async def test_a_lapsed_code_and_a_number_with_no_code_both_say_ask_for_a_new_code() -> None:
    container = _Container()
    await container.hold_code()
    container.clock.advance(timedelta(minutes=11))
    async with client(container) as http:
        lapsed = await http.post("/identity/code/verify", json=verify_body())
        none_held = await http.post("/identity/code/verify", json=verify_body(mobile=OTHER_MOBILE))
    assert lapsed.json() == none_held.json()
    assert lapsed.json()["issue"][0]["diagnostics"] == "Ask for a new code"


async def test_a_wrong_code_for_an_unknown_number_answers_as_for_a_known_one() -> None:
    container = _Container()
    async with client(container) as http:
        await http.post("/identity/code", json={"mobile": MOBILE})
        await http.post("/identity/code", json={"mobile": UNKNOWN_MOBILE})
        known = await http.post("/identity/code/verify", json=verify_body(code="000000"))
        unknown = await http.post(
            "/identity/code/verify", json=verify_body(mobile=UNKNOWN_MOBILE, code="000000")
        )
    assert known.status_code == unknown.status_code == 400
    assert known.content == unknown.content


async def test_a_new_device_code_signs_the_old_phones_out_and_asks_for_the_callback() -> None:
    container = _Container()
    container.register_device()
    await container.hold_code(purpose="new-device")
    async with client(container) as http:
        response = await http.post(
            "/identity/code/verify", json=verify_body(deviceId=OTHER_DEVICE, purpose="new-device")
        )
    assert response.status_code == 200
    assert response.json() == {"verified": True, "callbackRequired": True}
    assert container.units.devices.held[(PERSON, DEVICE)]["revoked"] is True
    assert container.units.devices.held[(PERSON, OTHER_DEVICE)]["pending"] is True


async def test_a_right_code_on_a_revoked_device_id_is_a_409_start_again() -> None:
    container = _Container()
    container.register_device()
    container.units.devices.held[(PERSON, DEVICE)]["revoked"] = True
    await container.hold_code()
    async with client(container) as http:
        response = await http.post("/identity/code/verify", json=verify_body())
    assert response.status_code == 409


async def test_a_number_that_is_no_longer_known_when_its_code_is_checked_is_refused() -> None:
    container = _Container()
    del container.units.people.practitioners[PERSON]
    await container.hold_code()
    async with client(container) as http:
        response = await http.post("/identity/code/verify", json=verify_body())
    assert response.status_code == 400
    assert container.units.devices.held == {}


@pytest.mark.parametrize(
    "device", ["short", "x" * 57, "device with spaces 0123456789", "../../etc/passwd-0123456789"]
)
async def test_a_device_id_that_is_not_a_long_random_id_is_a_400(device: str) -> None:
    container = _Container()
    async with client(container) as http:
        response = await http.post("/identity/code/verify", json=verify_body(deviceId=device))
    assert response.status_code == 400
    assert device not in response.text


async def test_a_device_id_that_looks_like_a_push_name_is_a_400() -> None:
    container = _Container()
    async with client(container) as http:
        response = await http.post(
            "/identity/pin/verify", json={"deviceId": "app-" + DEVICE, "pin": PIN}
        )
    assert response.status_code == 400


# ------------------------------------------------------------------ set a PIN and sign in


async def test_a_pin_is_set_on_a_device_that_was_verified_in_the_last_ten_minutes() -> None:
    container = _Container()
    container.register_device(verified_ago=timedelta(minutes=2))
    async with client(container) as http:
        response = await http.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN})
    assert response.status_code == 200
    assert response.json() == {"pinSet": True}
    assert (PERSON, DEVICE) in container.units.pins.held
    assert PIN not in repr(container.units.pins.held[(PERSON, DEVICE)][0])


@pytest.mark.parametrize("ago", [timedelta(minutes=11), None])
async def test_a_pin_with_no_recent_verification_is_refused(ago: timedelta | None) -> None:
    container = _Container()
    container.register_device(verified_ago=ago)
    async with client(container) as http:
        response = await http.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN})
    assert response.status_code == 403
    assert container.units.pins.held == {}


async def test_a_pin_for_an_unknown_device_is_refused_in_the_same_words() -> None:
    container = _Container()
    container.register_device(verified_ago=timedelta(minutes=11))
    async with client(container) as http:
        stale = await http.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN})
        unknown = await http.post("/identity/pin", json={"deviceId": UNKNOWN_DEVICE, "pin": PIN})
    assert stale.status_code == unknown.status_code == 403
    assert stale.content == unknown.content


@pytest.mark.parametrize("pin", ["12345", "1234567", "12a456", " 12345"])
async def test_a_pin_that_is_not_six_digits_is_a_400_and_never_echoed(pin: str) -> None:
    container = _Container()
    container.register_device(verified_ago=timedelta(minutes=2))
    async with client(container) as http:
        response = await http.post("/identity/pin", json={"deviceId": DEVICE, "pin": pin})
    assert response.status_code == 400
    assert pin.strip() not in response.text or pin.strip() == ""
    assert container.units.pins.held == {}


async def test_the_right_pin_signs_in_and_makes_a_session() -> None:
    container = _Container()
    container.register_device(verified_ago=timedelta(days=2))
    container.give_pin()
    async with client(container) as http:
        response = await http.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
    body = response.json()
    assert response.status_code == 200
    assert body["signedIn"] is True
    assert body["role"] == "reporter"
    assert body["services"] == ["svc-west"]
    assert body["sessionId"] in container.sessions.sessions
    # The tenant the host named, so the front end's session can say whose it is (it never guesses).
    assert body["tenant"] == TENANT
    assert PERSON not in response.text
    assert response.headers["cache-control"] == "no-store"


async def test_five_wrong_pins_lock_it_with_a_423_and_the_credential_shows_the_lock() -> None:
    container = _Container()
    container.register_device(verified_ago=timedelta(days=2))
    container.give_pin()
    async with client(container) as http:
        answers = [
            await http.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": "000000"})
            for _ in range(5)
        ]
        right = await http.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
    assert [answer.status_code for answer in answers] == [403, 403, 403, 403, 423]
    assert [answer.json().get("triesLeft") for answer in answers[:4]] == [4, 3, 2, 1]
    locked = answers[4].json()
    assert locked["issue"][0]["code"] == "lock-error"
    assert locked["issue"][0]["diagnostics"] == (
        "Your PIN is locked. Get a code by text to set a new PIN."
    )
    assert right.status_code == 423
    assert container.units.pins.held[(PERSON, DEVICE)][1].locked is True
    assert container.sessions.sessions == {}


async def test_an_unknown_device_a_stale_one_and_a_revoked_one_all_need_a_text_code() -> None:
    container = _Container()
    container.register_device(verified_ago=timedelta(days=31))
    container.give_pin()
    container.register_device(OTHER_DEVICE)
    container.give_pin(OTHER_DEVICE)
    container.units.devices.held[(PERSON, OTHER_DEVICE)]["revoked"] = True
    async with client(container) as http:
        answers = [
            await http.post("/identity/pin/verify", json={"deviceId": device, "pin": PIN})
            for device in (UNKNOWN_DEVICE, DEVICE, OTHER_DEVICE)
        ]
    assert [answer.status_code for answer in answers] == [403, 403, 403]
    assert answers[0].content == answers[1].content == answers[2].content
    assert answers[0].json()["needsTextCode"] is True
    assert container.sessions.sessions == {}


async def test_a_device_waiting_for_the_callback_cannot_sign_in() -> None:
    container = _Container()
    container.register_device(verified_ago=timedelta(minutes=1))
    container.units.devices.held[(PERSON, DEVICE)]["pending"] = True
    container.give_pin()
    async with client(container) as http:
        response = await http.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
    assert response.status_code == 403
    assert response.json()["needsTextCode"] is True


async def test_a_session_store_that_cannot_be_reached_is_a_503_and_nothing_is_changed() -> None:
    container = _Container()
    container.register_device(verified_ago=timedelta(days=2))
    container.give_pin()

    async def down(practitioner_id: str) -> int:
        raise ConnectionError("redis 10.0.0.5 refused the connection")

    container.sessions.epoch = down  # type: ignore[method-assign]
    async with client(container) as http:
        response = await http.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
    assert response.status_code == 503
    assert "10.0.0.5" not in response.text
    assert container.units.writes.names == []


class _RedisDown(Exception):
    """Stands in for redis.exceptions.ConnectionError, which is not an OSError."""


_RedisDown.__module__ = "redis.exceptions"


async def test_a_redis_client_error_is_a_503_like_a_dropped_socket() -> None:
    container = _Container()
    container.register_device(verified_ago=timedelta(days=2))
    container.give_pin()

    async def down(practitioner_id: str) -> int:
        raise _RedisDown("redis 10.0.0.5 refused the connection")

    container.sessions.epoch = down  # type: ignore[method-assign]
    async with client(container) as http:
        response = await http.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
    assert response.status_code == 503
    assert "10.0.0.5" not in response.text


async def test_any_other_error_is_not_turned_into_a_503() -> None:
    container = _Container()
    container.register_device(verified_ago=timedelta(days=2))
    container.give_pin()

    async def broken(practitioner_id: str) -> int:
        raise KeyError("a bug")

    container.sessions.epoch = broken  # type: ignore[method-assign]
    async with client(container) as http:
        response = await http.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
    assert response.status_code == 500


# ------------------------------------------------------------------ the 30-day check


@pytest.mark.parametrize(
    "ago,due,left",
    [
        (timedelta(days=31), True, 0),
        (timedelta(days=29), False, 1),
        (timedelta(days=3), False, 27),
    ],
)
async def test_the_status_says_when_the_thirty_day_check_is_due(
    ago: timedelta, due: bool, left: int
) -> None:
    container = _Container()
    container.register_device(verified_ago=ago)
    async with client(container) as http:
        response = await http.get("/identity/status", headers={"X-Device-Id": DEVICE})
    assert response.status_code == 200
    assert response.json() == {"reverifyDue": due, "daysLeft": left}


async def test_the_status_of_an_unknown_device_is_due_and_a_missing_device_is_a_400() -> None:
    container = _Container()
    async with client(container) as http:
        unknown = await http.get("/identity/status", headers={"X-Device-Id": UNKNOWN_DEVICE})
        missing = await http.get("/identity/status")
        in_the_url = await http.get(f"/identity/status?deviceId={DEVICE}")
    assert unknown.json() == {"reverifyDue": True, "daysLeft": 0}
    assert missing.status_code == 400
    assert in_the_url.status_code == 400


# ------------------------------------------------------------------ the tenant is the host


@pytest.mark.parametrize("host", [UNKNOWN_HOST, SUSPENDED_HOST])
async def test_a_host_no_active_tenant_owns_is_the_one_404_and_does_nothing(host: str) -> None:
    container = _Container()
    async with client(container, host=host) as http:
        responses = [
            await http.post("/identity/code", json={"mobile": MOBILE}),
            await http.post("/identity/code/verify", json=verify_body()),
            await http.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN}),
            await http.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN}),
            await http.get("/identity/status", headers={"X-Device-Id": DEVICE}),
        ]
    assert [response.status_code for response in responses] == [404] * 5
    assert len({response.content for response in responses}) == 1
    assert container.units.writes.names == []
    assert container.rate_limiter.counts == {}


async def test_a_tenant_header_or_query_changes_nothing() -> None:
    container = _Container()
    async with client(container) as http:
        response = await http.post(
            "/identity/code?tenant=other-tenant",
            json={"mobile": MOBILE},
            headers={"X-Tenant": "other-tenant", "X-Tenant-Id": "other-tenant"},
        )
    assert response.status_code == 202


# ------------------------------------------------------------------ throttle and secrets


async def test_an_address_is_throttled_with_a_key_that_holds_no_identifier() -> None:
    container = _Container()
    async with client(container) as http:
        answers = [
            await http.post("/identity/code", json={"mobile": f"0770090{n:04d}"})
            for n in range(routes_identity.ADDRESS_CODE_REQUESTS + 1)
        ]
        other = await http.post("/identity/code", json={"mobile": MOBILE})
    assert [a.status_code for a in answers[:-1]] == [202] * routes_identity.ADDRESS_CODE_REQUESTS
    assert answers[-1].status_code == 429
    assert answers[-1].headers["retry-after"] == "600"
    assert other.status_code == 429
    keys = list(container.rate_limiter.counts)
    assert keys
    for key in keys:
        assert "203.0.113.9" not in key
        assert MOBILE.replace(" ", "") not in key


async def test_another_address_has_its_own_allowance() -> None:
    container = _Container()
    async with client(container) as first, client(container, address="198.51.100.4") as second:
        for n in range(routes_identity.ADDRESS_CODE_REQUESTS):
            await first.post("/identity/code", json={"mobile": f"0770090{n:04d}"})
        blocked = await first.post("/identity/code", json={"mobile": MOBILE})
        free = await second.post("/identity/code", json={"mobile": MOBILE})
    assert (blocked.status_code, free.status_code) == (429, 202)


async def test_a_missing_secret_is_a_500_never_an_open_route() -> None:
    container = _Container()
    container.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    async with client(container) as http:
        response = await http.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
    assert response.status_code == 500


async def test_no_log_line_holds_a_number_a_code_a_pin_a_device_or_a_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    container = _Container()
    container.register_device(verified_ago=timedelta(minutes=2))
    await container.hold_code()
    caplog.set_level(logging.DEBUG)
    async with client(container) as http:
        await http.post("/identity/code", json={"mobile": MOBILE})
        await http.post("/identity/code/verify", json=verify_body())
        await http.post("/identity/pin", json={"deviceId": DEVICE, "pin": PIN})
        signed = await http.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": PIN})
        await http.post("/identity/pin/verify", json={"deviceId": DEVICE, "pin": "000000"})
        await http.get("/identity/status", headers={"X-Device-Id": DEVICE})
    text = caplog.text
    secrets = [MOBILE, MOBILE.replace(" ", ""), CODE, PIN, DEVICE, signed.json()["sessionId"]]
    for secret in secrets:
        assert secret not in text


# ------------------------------------------------------------------ push subscriptions


def push_body(**changes: Any) -> dict[str, Any]:
    return {
        "subscription": SUBSCRIPTION,
        "wordingVersion": "wording-v1",
        "deviceId": DEVICE,
        **changes,
    }


def key(value: str = "k1") -> dict[str, str]:
    return {"Idempotency-Key": value}


async def test_a_signed_in_reporter_saves_a_push_subscription_with_its_consent() -> None:
    container = _Container()
    container.register_device()
    async with client(container) as http:
        response = await http.post(
            "/identity/push-subscription", json=push_body(), headers={**bearer(), **key()}
        )
    assert response.status_code == 200
    assert response.json()["saved"] is True
    saved = container.units.push_subscriptions.held["app-" + DEVICE]
    assert saved.practitioner_id == PERSON
    assert saved.subscription["endpoint"] == SUBSCRIPTION["endpoint"]
    assert container.units.notification_consents.recorded == [
        (PERSON, "app-" + DEVICE, "wording-v1")
    ]
    assert SUBSCRIPTION["endpoint"] not in response.text
    assert SUBSCRIPTION["keys"]["auth"] not in response.text


async def test_the_same_key_twice_saves_once() -> None:
    container = _Container()
    container.register_device()
    async with client(container) as http:
        first = await http.post(
            "/identity/push-subscription", json=push_body(), headers={**bearer(), **key()}
        )
        second = await http.post(
            "/identity/push-subscription", json=push_body(), headers={**bearer(), **key()}
        )
    assert first.status_code == second.status_code == 200
    assert second.headers.get("idempotent-replay") == "true"
    assert len(container.units.notification_consents.recorded) == 1


@pytest.mark.parametrize("state", [{"revoked": True}, {"pending": True}])
async def test_a_reporter_whose_device_was_signed_out_cannot_subscribe_with_a_token_still_in_date(
    state: dict[str, bool],
) -> None:
    container = _Container()
    container.register_device()
    container.units.devices.held[(PERSON, DEVICE)].update(state)
    async with client(container) as http:
        response = await http.post(
            "/identity/push-subscription", json=push_body(), headers={**bearer(), **key()}
        )
    assert response.status_code == 401
    assert container.units.push_subscriptions.held == {}


async def test_a_removed_person_cannot_subscribe() -> None:
    container = _Container()
    container.register_device()
    container.units.people.practitioners[PERSON] = Practitioner(
        id=PERSON, active=False, display_name="Sample Reporter", phone_hash=None
    )
    async with client(container) as http:
        response = await http.post(
            "/identity/push-subscription", json=push_body(), headers={**bearer(), **key()}
        )
    assert response.status_code == 401


async def test_only_a_reporter_or_an_exec_may_subscribe_and_a_token_is_needed() -> None:
    container = _Container()
    container.register_device()
    async with client(container) as http:
        lead = await http.post(
            "/identity/push-subscription",
            json=push_body(),
            headers={**bearer(Role.LEAD), **key()},
        )
        none = await http.post("/identity/push-subscription", json=push_body(), headers=key())
    assert lead.status_code == 404
    assert none.status_code == 401


async def test_a_reporter_cannot_subscribe_another_device_and_an_exec_may_name_theirs() -> None:
    container = _Container()
    container.register_device()
    async with client(container) as http:
        other = await http.post(
            "/identity/push-subscription",
            json=push_body(deviceId=OTHER_DEVICE),
            headers={**bearer(), **key()},
        )
        exec_ = await http.post(
            "/identity/push-subscription",
            json=push_body(deviceId=OTHER_DEVICE),
            headers={**bearer(Role.EXEC, device=None), **key("k2")},
        )
    assert other.status_code == 400
    assert exec_.status_code == 200
    assert "app-" + OTHER_DEVICE in container.units.push_subscriptions.held


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://push.example/x",
        "https://169.254.169.254/x",
        "https://localhost/x",
        "https://10.0.0.1/x",
    ],
)
async def test_an_endpoint_that_could_reach_an_inside_address_is_a_400_and_stores_nothing(
    endpoint: str,
) -> None:
    container = _Container()
    container.register_device()
    body = push_body(subscription={**SUBSCRIPTION, "endpoint": endpoint})
    async with client(container) as http:
        response = await http.post(
            "/identity/push-subscription", json=body, headers={**bearer(), **key()}
        )
    assert response.status_code == 400
    assert endpoint not in response.text
    assert container.units.push_subscriptions.held == {}


async def test_a_push_save_needs_an_idempotency_key_and_a_whole_body() -> None:
    container = _Container()
    container.register_device()
    async with client(container) as http:
        no_key = await http.post("/identity/push-subscription", json=push_body(), headers=bearer())
        no_keys = await http.post(
            "/identity/push-subscription",
            json=push_body(subscription={"endpoint": SUBSCRIPTION["endpoint"]}),
            headers={**bearer(), **key()},
        )
        extra = await http.post(
            "/identity/push-subscription",
            json=push_body(practitionerId="prac-2"),
            headers={**bearer(), **key("k3")},
        )
    assert [no_key.status_code, no_keys.status_code, extra.status_code] == [400, 400, 400]


async def test_a_reporter_removes_their_push_subscription_and_the_consent_is_withdrawn() -> None:
    container = _Container()
    container.register_device()
    async with client(container) as http:
        await http.post(
            "/identity/push-subscription", json=push_body(), headers={**bearer(), **key()}
        )
        removed = await http.delete(
            "/identity/push-subscription", headers={**bearer(), **key("k2")}
        )
        again = await http.delete("/identity/push-subscription", headers={**bearer(), **key("k3")})
    assert removed.status_code == 200
    assert container.units.push_subscriptions.held == {}
    assert container.units.notification_consents.withdrawn == [(PERSON, "app-" + DEVICE)]
    assert again.status_code == 404
