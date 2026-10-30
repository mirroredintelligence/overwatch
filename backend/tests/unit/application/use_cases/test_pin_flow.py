"""SetPin, PinSignIn and RecordTextCodeVerified against recording stand-ins for their ports.

Task U32. The order of the calls, what is written and what is not, that every unknown or unusable
identity gets the answer of a known person on a new device, that the lock holds, and that no PIN and
no hash reaches an audit entry. What is really stored, read back from Neo4j, is in
tests/integration/application/test_pin.py. Sample values only: the PINs are samples.
"""

import hmac
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases import pin as pin_module
from diucs.application.use_cases.pin import (
    PIN_HMAC_SECRET,
    PinRateLimited,
    PinSignIn,
    PinSignInCommand,
    PinSignInResult,
    RecordTextCodeVerified,
    RecordTextCodeVerifiedCommand,
    SetPin,
    SetPinCommand,
    limiter_key,
    pin_hash,
)
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.rules.identity_policy import PIN_MAX_TRIES, PinOutcome, PinState
from tests.support.registration_rig import StubUnits

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
SECRET = b"pin-hmac-test-secret-0123456789abcdef"
SECRETS = FixedSecretStore({PIN_HMAC_SECRET: SECRET})
PIN = "482913"
OTHER_PIN = "135790"
PERSON = "prac-1"
DEVICE = "dev-1"
NEEDS_CODE = PinSignInResult(
    ok=False,
    locked=False,
    tries_left=0,
    needs_text_code=True,
    practitioner_id=None,
    role=None,
    service_ids=(),
)


class World:
    def __init__(self) -> None:
        self.units = StubUnits()
        self.clock = FixedClock(NOW)
        self.limiter = _limiter()
        self.units.people.practitioners[PERSON] = Practitioner(
            id=PERSON, active=True, display_name="Sample Reporter", phone_hash=None
        )
        for number, service in enumerate(("svc-west", "svc-east"), start=1):
            self.units.people.roles[f"role-{number}"] = PractitionerRole(
                id=f"role-{number}",
                practitioner_id=PERSON,
                service_id=service,
                code=PractitionerRoleCode.DUTY_MANAGER,
                active=True,
                channel=None,
                period_start=NOW - timedelta(days=30),
            )
        self.set_pin = SetPin(self.units, SECRETS, self.clock, self.limiter)
        self.sign_in = PinSignIn(self.units, SECRETS, self.clock, self.limiter)
        self.record = RecordTextCodeVerified(self.units, self.clock)

    def device(
        self,
        device_id: str = DEVICE,
        *,
        verified_ago: timedelta | None = timedelta(minutes=2),
        revoked: bool = False,
    ) -> None:
        verified = None if verified_ago is None else NOW - verified_ago
        self.units.devices.held[(PERSON, device_id)] = {
            "revoked": revoked,
            "verified_at": verified,
            "at": NOW,
        }

    def credential(
        self, pin: str = PIN, device_id: str = DEVICE, state: PinState | None = None
    ) -> None:
        self.units.pins.held[(PERSON, device_id)] = (
            pin_hash(SECRET, PERSON, device_id, pin),
            state or PinState(),
        )

    def state(self, device_id: str = DEVICE) -> PinState:
        return self.units.pins.held[(PERSON, device_id)][1]

    async def sign(
        self, pin: str, device_id: str = DEVICE, person: str = PERSON
    ) -> PinSignInResult:
        return await self.sign_in.execute(PinSignInCommand(person, device_id, pin))

    async def set(self, pin: str, ago: timedelta, device_id: str = DEVICE) -> Any:
        return await self.set_pin.execute(SetPinCommand(PERSON, device_id, pin, NOW - ago))


def _limiter() -> Any:
    from tests.support.registration_rig import StubLimiter

    return StubLimiter()


# Setting a PIN


async def test_a_pin_set_after_a_code_two_minutes_ago_stores_only_its_keyed_hash() -> None:
    world = World()
    world.device()

    result = await world.set(PIN, timedelta(minutes=2))

    assert result.ok is True
    stored_hash, state = world.units.pins.held[(PERSON, DEVICE)]
    assert stored_hash == pin_hash(SECRET, PERSON, DEVICE, PIN)
    assert PIN not in stored_hash
    assert state == PinState()
    assert world.units.commits == 1


async def test_a_text_code_eleven_minutes_ago_is_not_enough_and_nothing_is_stored() -> None:
    world = World()
    world.device(verified_ago=timedelta(minutes=11))

    result = await world.set(PIN, timedelta(minutes=11))

    assert result.ok is False
    assert world.units.pins.held == {}
    assert "pins.set_pin" not in world.units.writes.names


async def test_the_callers_own_claim_of_a_fresh_verification_is_not_believed() -> None:
    world = World()
    world.device(verified_ago=timedelta(hours=3))

    result = await world.set(PIN, timedelta(minutes=1))

    assert result.ok is False
    assert world.units.pins.held == {}


async def test_a_device_never_verified_or_unknown_or_revoked_cannot_get_a_pin() -> None:
    world = World()
    world.device("dev-never", verified_ago=None)
    world.device("dev-revoked", revoked=True)

    for device in ("dev-never", "dev-revoked", "dev-unknown"):
        result = await world.set(PIN, timedelta(minutes=1), device_id=device)
        assert result.ok is False

    assert world.units.pins.held == {}


async def test_an_unknown_or_inactive_practitioner_gets_the_same_refusal() -> None:
    world = World()
    world.device(verified_ago=timedelta(minutes=1))
    world.units.people.practitioners[PERSON] = replace(
        world.units.people.practitioners[PERSON], active=False
    )

    inactive = await world.set(PIN, timedelta(minutes=1))
    del world.units.people.practitioners[PERSON]
    unknown = await world.set(PIN, timedelta(minutes=1))

    assert inactive == unknown
    assert inactive.ok is False
    assert world.units.pins.held == {}


@pytest.mark.parametrize("bad", ["48291", "48291a", "4829134", "", "٤٨٢٩١٣", " 482913", "482913\n"])
async def test_a_pin_that_is_not_exactly_six_ascii_digits_is_refused_before_anything_is_read(
    bad: str,
) -> None:
    world = World()
    world.device()

    with pytest.raises(ValidationFailed) as raised:
        await world.set(bad, timedelta(minutes=1))

    assert raised.value.field == "pin"
    assert bad == "" or bad.strip() not in str(raised.value)
    assert world.units.calls == []
    assert world.units.writes.names == []
    assert world.limiter.counts == {}


async def test_setting_a_pin_again_clears_a_lock_and_the_failed_count() -> None:
    world = World()
    world.device(verified_ago=timedelta(minutes=1))
    world.credential(state=PinState(failed_tries=5, locked=True, last_outcome=PinOutcome.LOCKED))

    await world.set(OTHER_PIN, timedelta(minutes=1))

    assert world.state() == PinState()
    assert world.units.pins.held[(PERSON, DEVICE)][0] == pin_hash(SECRET, PERSON, DEVICE, OTHER_PIN)


async def test_the_audit_entry_of_a_set_holds_no_pin_and_no_hash() -> None:
    world = World()
    world.device(verified_ago=timedelta(minutes=1))

    await world.set(PIN, timedelta(minutes=1))

    text = repr(world.units.audit.entries)
    assert PIN not in text
    assert pin_hash(SECRET, PERSON, DEVICE, PIN) not in text
    assert [entry.use_case for entry in world.units.audit.entries] == ["SetPin"]


async def test_setting_pins_is_throttled_per_person_before_anything_is_read() -> None:
    world = World()
    world.device(verified_ago=timedelta(minutes=1))
    tries = 0
    with pytest.raises(PinRateLimited):
        for _ in range(100):
            tries += 1
            await world.set(PIN, timedelta(minutes=1))
    assert 1 < tries < 100
    reads_before = len(world.units.calls)
    with pytest.raises(PinRateLimited):
        await world.set(PIN, timedelta(minutes=1))
    assert len(world.units.calls) == reads_before


# Signing in


async def test_the_right_pin_on_the_same_device_signs_in_with_the_role_and_both_services() -> None:
    world = World()
    world.device()
    world.credential()

    result = await world.sign(PIN)

    assert result == PinSignInResult(
        ok=True,
        locked=False,
        tries_left=PIN_MAX_TRIES,
        needs_text_code=False,
        practitioner_id=PERSON,
        role=Role.REPORTER,
        service_ids=("svc-east", "svc-west"),
    )


async def test_the_pin_of_one_device_does_not_work_on_another() -> None:
    world = World()
    world.device()
    world.device("dev-2")
    world.credential(PIN, DEVICE)
    world.credential(OTHER_PIN, "dev-2")

    on_second = await world.sign(PIN, "dev-2")

    assert on_second.ok is False
    assert on_second.tries_left == PIN_MAX_TRIES - 1
    assert world.state("dev-2").failed_tries == 1
    assert world.state(DEVICE).failed_tries == 0


async def test_a_device_that_was_never_registered_needs_a_text_code() -> None:
    world = World()
    world.device()
    world.credential()

    result = await world.sign(PIN, "dev-other")

    assert result == NEEDS_CODE


async def test_five_wrong_pins_lock_and_the_right_pin_then_still_fails() -> None:
    world = World()
    world.device()
    world.credential()

    left = []
    for _ in range(PIN_MAX_TRIES):
        result = await world.sign(OTHER_PIN)
        assert result.ok is False
        left.append((result.tries_left, result.locked))

    assert left == [(4, False), (3, False), (2, False), (1, False), (0, True)]
    assert world.state().failed_tries == 5
    assert world.state().locked is True
    again = await world.sign(PIN)
    assert (again.ok, again.locked, again.tries_left, again.needs_text_code) == (
        False,
        True,
        0,
        False,
    )
    assert again.practitioner_id is None
    assert world.state().failed_tries == 5


async def test_a_right_pin_resets_the_wrong_count() -> None:
    world = World()
    world.device()
    world.credential()
    for _ in range(3):
        await world.sign(OTHER_PIN)
    assert world.state().failed_tries == 3

    result = await world.sign(PIN)

    assert result.ok is True
    assert world.state() == PinState(failed_tries=0, locked=False, last_outcome=PinOutcome.OK)


async def test_a_text_code_then_a_new_pin_unlocks() -> None:
    world = World()
    world.device()
    world.credential(state=PinState(failed_tries=5, locked=True, last_outcome=PinOutcome.LOCKED))
    now_stamp = NOW - timedelta(minutes=1)

    recorded = await world.record.execute(
        RecordTextCodeVerifiedCommand(PERSON, DEVICE, now_stamp, "pin-reset")
    )
    set_result = await world.set(OTHER_PIN, timedelta(minutes=1))
    signed = await world.sign(OTHER_PIN)

    assert recorded.device_known is True
    assert set_result.ok is True
    assert signed.ok is True
    assert world.state().failed_tries == 0
    assert world.state().locked is False


@pytest.mark.parametrize(
    ("ago", "needs_code"),
    [
        (timedelta(days=30, minutes=1), True),
        (timedelta(days=30), True),
        (timedelta(days=29, hours=23), False),
        (timedelta(days=1), False),
    ],
)
async def test_thirty_days_since_the_last_text_code_needs_a_new_one_and_changes_nothing_else(
    ago: timedelta, needs_code: bool
) -> None:
    world = World()
    world.device(verified_ago=ago)
    world.credential(state=PinState(failed_tries=2))

    result = await world.sign(PIN)

    assert result.needs_text_code is needs_code
    if needs_code:
        assert result == NEEDS_CODE
        assert world.state() == PinState(failed_tries=2)
        assert "pins.save_state" not in world.units.writes.names


async def test_a_locked_credential_on_a_stale_device_answers_needs_a_text_code() -> None:
    world = World()
    world.device(verified_ago=timedelta(days=40))
    world.credential(state=PinState(failed_tries=5, locked=True, last_outcome=PinOutcome.LOCKED))

    result = await world.sign(PIN)

    assert result == NEEDS_CODE
    assert world.state().failed_tries == 5


async def test_a_person_with_no_pin_yet_needs_a_text_code() -> None:
    world = World()
    world.device()

    assert await world.sign(PIN) == NEEDS_CODE


async def test_a_pin_that_is_malformed_counts_as_one_wrong_try_and_is_never_echoed() -> None:
    world = World()
    world.device()
    world.credential()

    for bad in ("48291", "48291a", "", "٤٨٢٩١٣"):
        result = await world.sign(bad)
        assert result.ok is False
    assert world.state().failed_tries == 4
    assert PIN not in repr(world.units.audit.entries)


# The same answer for every identity that cannot sign in


async def test_an_unknown_practitioner_an_unknown_device_and_a_revoked_one_answer_alike() -> None:
    world = World()
    world.device()
    world.credential()
    world.device("dev-revoked", revoked=True)
    world.credential(PIN, "dev-revoked")
    world.units.people.practitioners["prac-gone"] = Practitioner(
        id="prac-gone", active=False, display_name="Left Person", phone_hash=None
    )

    answers = {
        "new device": await world.sign(PIN, "dev-new"),
        "unknown person": await world.sign(PIN, DEVICE, person="prac-unknown"),
        "revoked device": await world.sign(PIN, "dev-revoked"),
        "inactive person": await world.sign(PIN, DEVICE, person="prac-gone"),
    }

    assert set(answers.values()) == {NEEDS_CODE}


async def test_an_unknown_identity_makes_the_same_calls_as_a_known_person_on_a_new_device() -> None:
    world = World()
    world.device()
    world.credential()

    await world.sign(PIN, "dev-new")
    new_device_calls = list(world.units.calls)
    new_device_writes = list(world.units.writes.names)
    world.units.calls.clear()
    world.units.writes.names.clear()
    await world.sign(PIN, DEVICE, person="prac-unknown")

    assert world.units.calls == new_device_calls
    assert world.units.writes.names == new_device_writes
    assert world.units.commits == 2


async def test_every_comparison_is_constant_time_even_for_an_unknown_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    world.device()
    world.credential()
    compared: list[tuple[Any, Any]] = []
    real = hmac.compare_digest

    def spy(first: Any, second: Any) -> bool:
        compared.append((first, second))
        return real(first, second)

    monkeypatch.setattr(pin_module.hmac, "compare_digest", spy)

    await world.sign(PIN)
    known = len(compared)
    await world.sign(PIN, DEVICE, person="prac-unknown")

    assert known >= 1
    assert len(compared) == 2 * known
    for first, second in compared:
        assert PIN not in str(first) and PIN not in str(second)


# Auditing and logging


async def test_no_audit_entry_holds_a_pin_or_a_hash_whatever_the_outcome() -> None:
    world = World()
    world.device()
    world.credential()

    await world.sign(OTHER_PIN)
    await world.sign(PIN)
    await world.sign(PIN, "dev-new")
    for _ in range(PIN_MAX_TRIES):
        await world.sign(OTHER_PIN)
    await world.sign(PIN, DEVICE, person="prac-unknown")

    text = repr(world.units.audit.entries)
    for secret in (PIN, OTHER_PIN, pin_hash(SECRET, PERSON, DEVICE, PIN), SECRET.decode()):
        assert secret not in text
    assert all(entry.use_case == "PinSignIn" for entry in world.units.audit.entries)
    assert all("prac-unknown" not in repr(entry) for entry in world.units.audit.entries)


# The throttle


async def test_an_attempt_past_the_limit_is_refused_before_any_unit_opens() -> None:
    world = World()
    world.device()
    world.credential()

    attempts = 0
    with pytest.raises(PinRateLimited) as raised:
        for _ in range(100):
            attempts += 1
            await world.sign(OTHER_PIN)
    assert attempts > PIN_MAX_TRIES
    commits = world.units.commits
    reads = len(world.units.calls)
    with pytest.raises(PinRateLimited):
        await world.sign(PIN)
    assert world.units.commits == commits
    assert len(world.units.calls) == reads
    assert raised.value.retry_after_seconds > 0


async def test_an_unknown_identity_is_throttled_exactly_like_a_known_one() -> None:
    known = World()
    known.device()
    known.credential()
    unknown = World()

    async def attempts_until_refused(world: World, person: str) -> int:
        count = 0
        with pytest.raises(PinRateLimited):
            for _ in range(100):
                count += 1
                await world.sign(OTHER_PIN, DEVICE, person=person)
        return count

    assert await attempts_until_refused(known, PERSON) == await attempts_until_refused(
        unknown, "prac-unknown"
    )


async def test_the_throttle_keys_hold_no_practitioner_or_device_id() -> None:
    world = World()
    world.device()
    world.credential()

    await world.sign(PIN)

    assert world.limiter.counts
    for key in world.limiter.counts:
        assert PERSON not in key
        assert DEVICE not in key
    assert limiter_key("pin-signin-device", PERSON, DEVICE) in world.limiter.counts


# The tenant


async def test_a_unit_with_no_tenant_bound_refuses_to_sign_in_or_set_a_pin() -> None:
    from diucs.application.tenancy import TenantNotBound

    world = World()
    world.device(verified_ago=timedelta(minutes=1))
    world.credential()
    world.units.scope_id = ScopeId.network("net-abc1")

    with pytest.raises(TenantNotBound):
        await world.sign(PIN)
    with pytest.raises(TenantNotBound):
        await world.set(PIN, timedelta(minutes=1))
    assert world.units.pins.held[(PERSON, DEVICE)][1] == PinState()


# Recording a verified text code


async def test_a_verified_code_registers_the_device_and_stamps_it() -> None:
    world = World()

    result = await world.record.execute(
        RecordTextCodeVerifiedCommand(PERSON, "dev-new", NOW - timedelta(seconds=30), "new-device")
    )

    assert result.device_known is True
    assert world.units.devices.held[(PERSON, "dev-new")]["verified_at"] == NOW - timedelta(
        seconds=30
    )
    assert world.units.commits == 1
    assert [e.use_case for e in world.units.audit.entries] == ["RecordTextCodeVerified"]


async def test_a_verification_stamped_in_the_future_is_clamped_to_now() -> None:
    world = World()

    await world.record.execute(
        RecordTextCodeVerifiedCommand(PERSON, DEVICE, NOW + timedelta(days=3), "setup")
    )

    assert world.units.devices.held[(PERSON, DEVICE)]["verified_at"] == NOW


@pytest.mark.parametrize("purpose", ["register", "login", "", "Setup"])
async def test_only_the_purposes_that_follow_a_text_code_for_a_person_stamp_a_device(
    purpose: str,
) -> None:
    world = World()

    with pytest.raises(ValidationFailed) as raised:
        await world.record.execute(RecordTextCodeVerifiedCommand(PERSON, DEVICE, NOW, purpose))

    assert raised.value.field == "purpose"
    assert world.units.writes.names == []


async def test_a_revoked_device_is_never_stamped_and_the_result_says_so() -> None:
    world = World()
    world.device(revoked=True, verified_ago=None)

    result = await world.record.execute(
        RecordTextCodeVerifiedCommand(PERSON, DEVICE, NOW, "reverify")
    )

    assert result.device_known is False
    assert "devices.mark_verified" not in world.units.writes.names
    assert world.units.devices.held[(PERSON, DEVICE)]["verified_at"] is None


async def test_an_unknown_or_inactive_practitioner_writes_nothing() -> None:
    world = World()
    del world.units.people.practitioners[PERSON]

    result = await world.record.execute(RecordTextCodeVerifiedCommand(PERSON, DEVICE, NOW, "setup"))

    assert result.device_known is False
    assert world.units.writes.names == []


async def test_a_naive_verification_time_is_refused() -> None:
    world = World()

    with pytest.raises(ValidationFailed):
        await world.record.execute(
            RecordTextCodeVerifiedCommand(PERSON, DEVICE, datetime(2026, 10, 29, 14, 0), "setup")
        )


async def test_a_pin_is_set_from_the_stored_verification_when_no_time_is_claimed() -> None:
    world = World()
    world.device(verified_ago=timedelta(minutes=2))
    result = await world.set_pin.execute(SetPinCommand(PERSON, DEVICE, PIN))
    assert result.ok is True
    assert world.state() == PinState()


async def test_a_pin_is_refused_with_no_claim_and_no_recent_stored_verification() -> None:
    world = World()
    world.device(verified_ago=timedelta(minutes=11))
    assert (await world.set_pin.execute(SetPinCommand(PERSON, DEVICE, PIN))).ok is False
    world.device(verified_ago=None)
    assert (await world.set_pin.execute(SetPinCommand(PERSON, DEVICE, PIN))).ok is False
