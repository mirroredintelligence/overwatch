"""The reporter identity use cases of the edge (R11): the device code check that always records the
verification, PIN set and sign-in by device, the session epoch, the 30-day status and the access
check of the push routes. Recording stand-ins for the ports; what is really stored is proved in
tests/integration/application/test_reporter_identity.py. Sample values only.
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.use_cases.pin import (
    PIN_HMAC_SECRET,
    PinRateLimited,
    PinSignIn,
    PinSignInResult,
    RecordTextCodeVerifiedCommand,
    RecordTextCodeVerifiedResult,
    SetPin,
    pin_hash,
)
from diucs.application.use_cases.remove_person import StartNewPhoneCommand, StartNewPhoneResult
from diucs.application.use_cases.reporter_identity import (
    UNKNOWN_PREFIX,
    CheckReporterAccess,
    ConfirmDeviceByTextCode,
    ConfirmDeviceCommand,
    ReporterSignIn,
    ReporterSignInCommand,
    ReverifyStatus,
    SetDevicePin,
    SetDevicePinCommand,
    SignInKind,
    unknown_person,
)
from diucs.application.use_cases.text_code import VerifyTextCodeCommand, VerifyTextCodeResult
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.rules.identity_policy import PinState
from tests.support.actors import ACTOR_TENANT
from tests.support.registration_rig import StubLimiter, StubUnits
from tests.support.session_rig import StubSessions

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
SECRET = b"pin-hmac-test-secret-0123456789abcdef"
SECRETS = FixedSecretStore({PIN_HMAC_SECRET: SECRET})
PIN = "482913"
PERSON = "prac-1"
DEVICE = "device-aaaaaaaaaaaaaaaaaaaaaa"
PHONE = "07700 900123"


class FakeVerify:
    def __init__(self, result: VerifyTextCodeResult) -> None:
        self.result = result
        self.commands: list[VerifyTextCodeCommand] = []

    async def execute(self, command: VerifyTextCodeCommand) -> VerifyTextCodeResult:
        self.commands.append(command)
        return self.result


class FakeRecord:
    def __init__(self, known: bool = True) -> None:
        self.known = known
        self.commands: list[RecordTextCodeVerifiedCommand] = []

    async def execute(self, command: RecordTextCodeVerifiedCommand) -> RecordTextCodeVerifiedResult:
        self.commands.append(command)
        return RecordTextCodeVerifiedResult(device_known=self.known)


class FakeStart:
    def __init__(self, started: bool = True) -> None:
        self.started = started
        self.commands: list[StartNewPhoneCommand] = []

    async def execute(self, command: StartNewPhoneCommand) -> StartNewPhoneResult:
        self.commands.append(command)
        return StartNewPhoneResult(started=self.started, devices_signed_out=1)


def _verified(practitioner: str | None = PERSON, invitation: str | None = None) -> Any:
    return VerifyTextCodeResult(
        ok=True,
        tries_left=5,
        needs_new_code=False,
        practitioner_id=practitioner,
        invitation_id=invitation,
        verified_at=NOW - timedelta(seconds=3),
    )


def _failed(tries_left: int = 3, needs_new_code: bool = False) -> Any:
    return VerifyTextCodeResult(
        ok=False,
        tries_left=tries_left,
        needs_new_code=needs_new_code,
        practitioner_id=None,
        invitation_id=None,
        verified_at=None,
    )


def _confirm(
    verify: Any, record: FakeRecord | None = None, start: FakeStart | None = None
) -> tuple[ConfirmDeviceByTextCode, FakeRecord, FakeStart]:
    record = record or FakeRecord()
    start = start or FakeStart()
    return ConfirmDeviceByTextCode(verify, record, start, FixedClock(NOW)), record, start


def _command(purpose: str = "setup") -> ConfirmDeviceCommand:
    return ConfirmDeviceCommand(PHONE, "123456", purpose, DEVICE)


# Confirm a device by text code


@pytest.mark.parametrize("purpose", ["setup", "reverify", "pin-reset"])
async def test_every_successful_code_is_recorded_on_the_device(purpose: str) -> None:
    use, record, start = _confirm(FakeVerify(_verified()))
    result = await use.execute(_command(purpose))
    assert result.verified is True
    assert result.device_refused is False
    assert result.awaiting_callback is False
    assert record.commands == [
        RecordTextCodeVerifiedCommand(PERSON, DEVICE, NOW - timedelta(seconds=3), purpose)
    ]
    assert start.commands == []


async def test_a_new_device_code_starts_the_new_phone_and_records_nothing_else() -> None:
    use, record, start = _confirm(FakeVerify(_verified()))
    result = await use.execute(_command("new-device"))
    assert result.verified is True
    assert result.awaiting_callback is True
    assert start.commands == [StartNewPhoneCommand(PERSON, DEVICE, NOW - timedelta(seconds=3))]
    assert record.commands == []


async def test_a_new_device_that_cannot_start_is_refused() -> None:
    use, _, _ = _confirm(FakeVerify(_verified()), start=FakeStart(started=False))
    result = await use.execute(_command("new-device"))
    assert result.device_refused is True
    assert result.awaiting_callback is False


async def test_a_device_that_cannot_be_recorded_is_refused() -> None:
    use, _, _ = _confirm(FakeVerify(_verified()), record=FakeRecord(known=False))
    result = await use.execute(_command())
    assert result.verified is True
    assert result.device_refused is True


@pytest.mark.parametrize("tries,new", [(3, False), (0, True)])
async def test_a_failed_code_records_nothing_and_passes_the_tries_through(
    tries: int, new: bool
) -> None:
    use, record, start = _confirm(FakeVerify(_failed(tries, new)))
    result = await use.execute(_command())
    assert (result.verified, result.tries_left, result.needs_new_code) == (False, tries, new)
    assert record.commands == [] and start.commands == []


async def test_a_code_for_an_invitation_only_records_no_device() -> None:
    use, record, start = _confirm(FakeVerify(_verified(practitioner=None, invitation="inv-1")))
    result = await use.execute(_command())
    assert result.verified is True
    assert result.device_refused is False
    assert record.commands == [] and start.commands == []


async def test_the_purpose_register_is_not_a_device_purpose() -> None:
    verify = FakeVerify(_verified())
    use, record, _ = _confirm(verify)
    with pytest.raises(ValidationFailed):
        await use.execute(_command("register"))
    assert verify.commands == [] and record.commands == []


async def test_the_code_check_gets_the_number_the_purpose_and_the_code() -> None:
    verify = FakeVerify(_verified())
    use, _, _ = _confirm(verify)
    await use.execute(_command("reverify"))
    assert verify.commands == [VerifyTextCodeCommand(PHONE, "reverify", "123456")]


async def test_the_result_holds_no_number_code_or_person() -> None:
    use, _, _ = _confirm(FakeVerify(_verified()))
    result = await use.execute(_command())
    text = repr(result)
    assert PHONE not in text and PERSON not in text and "123456" not in text


# The device and the person behind it


class World:
    def __init__(self) -> None:
        self.units = StubUnits()
        self.clock = FixedClock(NOW)
        self.limiter = StubLimiter()
        self.sessions = StubSessions(self.units.events)
        self.units.people.practitioners[PERSON] = Practitioner(
            id=PERSON, active=True, display_name="Sample Reporter", phone_hash=None
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
        self.units.devices.held[(PERSON, DEVICE)] = {
            "revoked": False,
            "pending": False,
            "verified_at": NOW - timedelta(days=3),
            "at": NOW - timedelta(days=40),
        }
        self.units.pins.held[(PERSON, DEVICE)] = (pin_hash(SECRET, PERSON, DEVICE, PIN), PinState())
        self.pin_sign_in = PinSignIn(self.units, SECRETS, self.clock, self.limiter)
        self.set_pin = SetPin(self.units, SECRETS, self.clock, self.limiter)
        self.sign_in = ReporterSignIn(self.units, self.pin_sign_in, self.sessions, self.clock)
        self.set_device_pin = SetDevicePin(self.units, self.set_pin)
        self.status = ReverifyStatus(self.units, self.clock)
        self.access = CheckReporterAccess(self.units)

    def device(self, **changes: Any) -> None:
        self.units.devices.held[(PERSON, DEVICE)].update(changes)


def test_an_unknown_person_is_named_from_the_device_and_never_the_device_itself() -> None:
    name = unknown_person(DEVICE)
    assert name.startswith(UNKNOWN_PREFIX)
    assert DEVICE not in name
    assert unknown_person(DEVICE) == name
    assert unknown_person("device-bbbbbbbbbbbbbbbbbbbbbb") != name


# Sign in


async def test_a_sign_in_makes_a_session_under_the_epoch_read_before_the_check() -> None:
    world = World()
    world.sessions.epochs[PERSON] = 4
    result = await world.sign_in.execute(ReporterSignInCommand(DEVICE, PIN))
    assert result.kind is SignInKind.SIGNED_IN
    assert result.role is Role.REPORTER
    assert result.service_ids == ("svc-west",)
    assert result.session_id is not None
    session = world.sessions.sessions[result.session_id]
    assert (session.practitioner_id, session.device_id, session.epoch) == (PERSON, DEVICE, 4)


async def test_a_sign_in_that_raced_a_sign_out_everywhere_leaves_no_session() -> None:
    world = World()
    original = world.pin_sign_in.execute

    async def raced(command: Any) -> PinSignInResult:
        result = await original(command)
        await world.sessions.delete_all_for_person(PERSON)  # the person signs out, in between
        return result

    world.pin_sign_in.execute = raced  # type: ignore[method-assign]
    result = await world.sign_in.execute(ReporterSignInCommand(DEVICE, PIN))
    assert result.kind is SignInKind.NEEDS_TEXT_CODE
    assert result.session_id is None
    assert world.sessions.sessions == {}


async def test_a_wrong_pin_says_how_many_tries_are_left_and_makes_no_session() -> None:
    world = World()
    result = await world.sign_in.execute(ReporterSignInCommand(DEVICE, "000000"))
    assert (result.kind, result.tries_left, result.session_id) == (SignInKind.WRONG_PIN, 4, None)
    assert world.sessions.sessions == {}


async def test_five_wrong_pins_lock_and_the_right_pin_is_then_refused() -> None:
    world = World()
    for _ in range(5):
        last = await world.sign_in.execute(ReporterSignInCommand(DEVICE, "000000"))
    assert last.kind is SignInKind.LOCKED
    again = await world.sign_in.execute(ReporterSignInCommand(DEVICE, PIN))
    assert again.kind is SignInKind.LOCKED
    assert world.sessions.sessions == {}


async def test_an_unknown_device_gets_the_answer_of_a_stale_one() -> None:
    world = World()
    unknown = await world.sign_in.execute(
        ReporterSignInCommand("device-zzzzzzzzzzzzzzzzzzzzzz", PIN)
    )
    world.device(verified_at=NOW - timedelta(days=31))
    stale = await world.sign_in.execute(ReporterSignInCommand(DEVICE, PIN))
    assert unknown == stale
    assert unknown.kind is SignInKind.NEEDS_TEXT_CODE
    assert (unknown.session_id, unknown.role, unknown.service_ids) == (None, None, ())


@pytest.mark.parametrize("state", [{"revoked": True}, {"pending": True}])
async def test_a_revoked_or_waiting_device_needs_a_text_code(state: dict[str, bool]) -> None:
    world = World()
    world.device(**state)
    result = await world.sign_in.execute(ReporterSignInCommand(DEVICE, PIN))
    assert result.kind is SignInKind.NEEDS_TEXT_CODE
    assert world.sessions.sessions == {}


async def test_a_person_with_no_reporter_post_gets_no_session() -> None:
    world = World()
    del world.units.people.roles["role-1"]
    result = await world.sign_in.execute(ReporterSignInCommand(DEVICE, PIN))
    assert result.kind is SignInKind.NEEDS_TEXT_CODE
    assert world.sessions.sessions == {}


async def test_a_removed_person_cannot_sign_in() -> None:
    world = World()
    world.units.people.practitioners[PERSON] = replace(
        world.units.people.practitioners[PERSON], active=False
    )
    result = await world.sign_in.execute(ReporterSignInCommand(DEVICE, PIN))
    assert result.kind is SignInKind.NEEDS_TEXT_CODE


async def test_the_throttle_is_counted_for_an_unknown_device_too() -> None:
    world = World()
    for _ in range(10):
        await world.sign_in.execute(ReporterSignInCommand("device-zzzzzzzzzzzzzzzzzzzzzz", PIN))
    with pytest.raises(PinRateLimited):
        await world.sign_in.execute(ReporterSignInCommand("device-zzzzzzzzzzzzzzzzzzzzzz", PIN))
    assert world.sessions.sessions == {}


async def test_a_result_never_holds_the_pin_or_a_person() -> None:
    world = World()
    result = await world.sign_in.execute(ReporterSignInCommand(DEVICE, PIN))
    assert PIN not in repr(result)
    assert PERSON not in repr(result)
    assert PIN not in repr(ReporterSignInCommand(DEVICE, PIN))


# Set a PIN


async def test_a_pin_is_set_for_the_owner_of_a_freshly_verified_device() -> None:
    world = World()
    world.device(verified_at=NOW - timedelta(minutes=2))
    del world.units.pins.held[(PERSON, DEVICE)]
    assert await world.set_device_pin.execute(SetDevicePinCommand(DEVICE, PIN)) is True
    assert (PERSON, DEVICE) in world.units.pins.held


@pytest.mark.parametrize(
    "state",
    [
        {"verified_at": NOW - timedelta(minutes=11)},
        {"verified_at": None},
        {"revoked": True, "verified_at": NOW - timedelta(minutes=1)},
    ],
)
async def test_a_pin_is_refused_without_a_recent_verification(state: dict[str, Any]) -> None:
    world = World()
    del world.units.pins.held[(PERSON, DEVICE)]
    world.device(**state)
    assert await world.set_device_pin.execute(SetDevicePinCommand(DEVICE, PIN)) is False
    assert world.units.pins.held == {}


async def test_a_pin_for_an_unknown_device_is_refused_the_same_way() -> None:
    world = World()
    assert (
        await world.set_device_pin.execute(
            SetDevicePinCommand("device-zzzzzzzzzzzzzzzzzzzzzz", PIN)
        )
        is False
    )
    assert world.units.writes.names == []


# The 30-day status


@pytest.mark.parametrize(
    "ago,due,left",
    [
        (timedelta(days=3), False, 27),
        (timedelta(days=29, hours=23), False, 1),
        (timedelta(days=30), True, 0),
        (timedelta(days=31), True, 0),
    ],
)
async def test_the_status_counts_the_days_to_the_thirty_day_check(
    ago: timedelta, due: bool, left: int
) -> None:
    world = World()
    world.device(verified_at=NOW - ago)
    result = await world.status.execute(DEVICE)
    assert (result.reverify_due, result.days_left) == (due, left)


@pytest.mark.parametrize("state", [{"revoked": True}, {"pending": True}, {"verified_at": None}])
async def test_a_device_that_cannot_sign_in_is_due(state: dict[str, Any]) -> None:
    world = World()
    world.device(**state)
    result = await world.status.execute(DEVICE)
    assert (result.reverify_due, result.days_left) == (True, 0)


async def test_an_unknown_device_is_due_like_any_other() -> None:
    world = World()
    result = await world.status.execute("device-zzzzzzzzzzzzzzzzzzzzzz")
    assert (result.reverify_due, result.days_left) == (True, 0)


# The access check of the push routes


def _actor(role: Role, person: str | None = PERSON, device: str | None = DEVICE) -> Actor:
    return Actor(
        role=role,
        practitioner_id=person,
        device_id=device,
        channel="api",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


async def test_a_reporter_with_a_known_device_has_access() -> None:
    world = World()
    assert await world.access.execute(_actor(Role.REPORTER)) is True


@pytest.mark.parametrize("state", [{"revoked": True}, {"pending": True}])
async def test_a_reporter_whose_device_was_signed_out_has_no_access(
    state: dict[str, bool],
) -> None:
    world = World()
    world.device(**state)
    assert await world.access.execute(_actor(Role.REPORTER)) is False


async def test_a_reporter_token_with_no_device_or_another_device_has_no_access() -> None:
    world = World()
    assert await world.access.execute(_actor(Role.REPORTER, device=None)) is False
    assert await world.access.execute(_actor(Role.REPORTER, device="other-device")) is False


async def test_a_removed_person_has_no_access_in_any_role() -> None:
    world = World()
    world.units.people.practitioners[PERSON] = replace(
        world.units.people.practitioners[PERSON], active=False
    )
    assert await world.access.execute(_actor(Role.REPORTER)) is False
    assert await world.access.execute(_actor(Role.EXEC, device=None)) is False


async def test_an_exec_who_is_active_has_access_without_a_device() -> None:
    world = World()
    assert await world.access.execute(_actor(Role.EXEC, device=None)) is True


async def test_a_wall_screen_or_a_person_less_actor_has_no_access() -> None:
    world = World()
    assert await world.access.execute(_actor(Role.WALL, person=None, device=None)) is False
    assert await world.access.execute(_actor(Role.REPORTER, person=None)) is False
    assert await world.access.execute(_actor(Role.LEAD)) is False
