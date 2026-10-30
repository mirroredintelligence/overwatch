"""Reporter identity at the edge (R11): what the identity routes run, over U25 (text codes), U32
(PIN) and U37 (new phone).

The routes name a device, never a person: a person's id is not shown to a signed-out client (U32
known issue), so the person behind a device is read here, from the device's own record. A device id
is a random secret the person's phone holds. Authentication rules this module keeps (DEC-410 to
DEC-414):
- Every successful text code is recorded on its device by the same call that verified it, in one
  place, so no route can verify a code and forget to record it (U32: the verification time a PIN is
  set against, and the 30-day check, both read that record).
- An unknown device is answered as a known device that cannot sign in: the same result, the same
  calls, a stand-in person named from the device (never the device id itself), so nothing says which
  devices exist.
- A session is created only under the epoch read before the PIN was checked (U37): a sign-in that
  raced a sign out everywhere leaves no session.
- A person who is not a reporter, or whose device is revoked or waiting for a call-back, is never
  given a session. No PIN, code, number, session id or device id is in a repr, an audit entry or a
  throttle key.
"""

import hashlib
import math
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Final, Protocol

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import SessionEpochChanged, SessionStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantNotBound
from diucs.application.use_cases.pin import (
    VERIFIED_PURPOSES,
    PinSignIn,
    PinSignInCommand,
    PinSignInResult,
    RecordTextCodeVerifiedCommand,
    RecordTextCodeVerifiedResult,
    SetPin,
    SetPinCommand,
)
from diucs.application.use_cases.remove_person import (
    NEW_DEVICE_PURPOSE,
    StartNewPhoneCommand,
    StartNewPhoneResult,
)
from diucs.application.use_cases.text_code import VerifyTextCodeCommand, VerifyTextCodeResult
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.identity_policy import REVERIFY_EVERY, needs_reverification

UNKNOWN_PREFIX: Final = "unknown-"
PUSH_DEVICE_PREFIX: Final = "app-"
"""The edge names the installed app's push device `app-<device id>` (R11), and device ids are unique
in a tenant across kinds. A device id of the phone never starts with it, so a client cannot choose
an id that is another device's push name."""
MAX_DEVICE_ID_LENGTH: Final = 128
_ONE_DAY: Final = timedelta(days=1)


def unknown_person(device_id: str) -> str:
    """The stand-in for the person behind a device that no one holds: named from a digest of the
    device id, so it is stable for one device and is never the device id. It is never a real
    practitioner id (real ids are ids the application generated, which never start with it)."""
    digest = hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:24]
    return f"{UNKNOWN_PREFIX}{digest}"


def _device(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_DEVICE_ID_LENGTH
        or not value.isprintable()
        or value.startswith(PUSH_DEVICE_PREFIX)
    ):
        raise ValidationFailed("device_id", "is not a valid identifier")
    return value


def _tenant_bound(uow: UnitOfWork) -> None:
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound


async def _owner(uow_factory: UnitOfWorkFactory, device_id: str) -> str:
    """The practitioner who holds this device in the bound tenant, or the stand-in for an unknown
    one. A revoked or waiting device still names its owner: its refusal is the sign-in's."""
    async with uow_factory() as uow:
        _tenant_bound(uow)
        owner = await uow.devices.owner_of(device_id)
    return unknown_person(device_id) if owner is None else owner


class _Verify(Protocol):
    async def execute(self, command: VerifyTextCodeCommand) -> VerifyTextCodeResult: ...


class _Record(Protocol):
    async def execute(
        self, command: RecordTextCodeVerifiedCommand
    ) -> RecordTextCodeVerifiedResult: ...


class _Start(Protocol):
    async def execute(self, command: StartNewPhoneCommand) -> StartNewPhoneResult: ...


@dataclass(frozen=True, slots=True)
class ConfirmDeviceCommand:
    phone: str = field(repr=False)
    code: str = field(repr=False)
    purpose: str
    device_id: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ConfirmDeviceResult:
    verified: bool
    """The code was right (and in time). True also for a number with only an invitation: nothing is
    recorded on a device for it."""
    tries_left: int
    needs_new_code: bool
    device_refused: bool
    """The code was right but the device cannot be set up with it (a revoked device id, a person
    who has left, a device id that someone holds): the person starts again on a new device id."""
    awaiting_callback: bool
    """A `new-device` code started a new phone: it waits for the lead's call-back (U37)."""


class ConfirmDeviceByTextCode:
    """Verify a text code and, when it is right, record the verification on the device, in the same
    call. A `new-device` code starts the new phone (U37) instead: the old devices are signed out and
    the new one waits for the lead's call-back."""

    def __init__(self, verify: _Verify, record: _Record, start: _Start, clock: Clock) -> None:
        self._verify = verify
        self._record = record
        self._start = start
        self._clock = clock

    async def execute(self, command: ConfirmDeviceCommand) -> ConfirmDeviceResult:
        if command.purpose not in VERIFIED_PURPOSES:
            raise ValidationFailed("purpose", "must be setup, reverify, pin-reset or new-device")
        device = _device(command.device_id)
        checked = await self._verify.execute(
            VerifyTextCodeCommand(command.phone, command.purpose, command.code)
        )
        if not checked.ok or checked.verified_at is None:
            return ConfirmDeviceResult(
                verified=False,
                tries_left=checked.tries_left,
                needs_new_code=checked.needs_new_code,
                device_refused=False,
                awaiting_callback=False,
            )
        if checked.practitioner_id is None:
            # A number with only an invitation (U24) has no person yet and so no device to record.
            return ConfirmDeviceResult(True, checked.tries_left, False, False, False)
        if command.purpose == NEW_DEVICE_PURPOSE:
            started = await self._start.execute(
                StartNewPhoneCommand(checked.practitioner_id, device, checked.verified_at)
            )
            return ConfirmDeviceResult(
                verified=True,
                tries_left=checked.tries_left,
                needs_new_code=False,
                device_refused=not started.started,
                awaiting_callback=started.started,
            )
        recorded = await self._record.execute(
            RecordTextCodeVerifiedCommand(
                checked.practitioner_id, device, checked.verified_at, command.purpose
            )
        )
        return ConfirmDeviceResult(
            verified=True,
            tries_left=checked.tries_left,
            needs_new_code=False,
            device_refused=not recorded.device_known,
            awaiting_callback=False,
        )


@dataclass(frozen=True, slots=True)
class SetDevicePinCommand:
    device_id: str = field(repr=False)
    pin: str = field(repr=False)


class SetDevicePin:
    """Set the PIN of a device for the person who holds it. True when it was set; False for every
    reason it was not (no recent verification, an unknown or revoked device, a person who has left),
    so the answer does not say which devices exist."""

    def __init__(self, uow_factory: UnitOfWorkFactory, set_pin: SetPin) -> None:
        self._uow_factory = uow_factory
        self._set_pin = set_pin

    async def execute(self, command: SetDevicePinCommand) -> bool:
        device = _device(command.device_id)
        person = await _owner(self._uow_factory, device)
        result = await self._set_pin.execute(SetPinCommand(person, device, command.pin))
        return result.ok


class SignInKind(StrEnum):
    SIGNED_IN = "signed-in"
    WRONG_PIN = "wrong-pin"
    LOCKED = "locked"
    NEEDS_TEXT_CODE = "needs-text-code"


@dataclass(frozen=True, slots=True)
class ReporterSignInCommand:
    device_id: str = field(repr=False)
    pin: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ReporterSignInResult:
    kind: SignInKind
    tries_left: int
    session_id: str | None = field(repr=False)
    role: Role | None
    service_ids: tuple[str, ...]


_NEEDS_TEXT_CODE: Final = ReporterSignInResult(SignInKind.NEEDS_TEXT_CODE, 0, None, None, ())


class ReporterSignIn:
    """Sign in with a PIN on a device. The session is created only under the epoch read before the
    PIN was checked, so a sign out everywhere (or a removal) in between leaves no session, and only
    for a person who holds a reporter post: a session never carries a role nobody derived."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        pin_sign_in: PinSignIn,
        sessions: SessionStore,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._pin_sign_in = pin_sign_in
        self._sessions = sessions
        self._clock = clock

    async def execute(self, command: ReporterSignInCommand) -> ReporterSignInResult:
        device = _device(command.device_id)
        person = await _owner(self._uow_factory, device)
        epoch = await self._sessions.epoch(person)
        answer = await self._pin_sign_in.execute(PinSignInCommand(person, device, command.pin))
        if answer.ok:
            return await self._session(person, device, epoch, answer)
        if answer.locked:
            return ReporterSignInResult(SignInKind.LOCKED, 0, None, None, ())
        if answer.needs_text_code:
            return _NEEDS_TEXT_CODE
        return ReporterSignInResult(SignInKind.WRONG_PIN, answer.tries_left, None, None, ())

    async def _session(
        self, person: str, device: str, epoch: int, answer: PinSignInResult
    ) -> ReporterSignInResult:
        if answer.role is not Role.REPORTER:
            return _NEEDS_TEXT_CODE
        try:
            session_id = await self._sessions.create(
                Role.REPORTER, person, device, answer.service_ids, self._clock.now(), epoch=epoch
            )
        except SessionEpochChanged:
            return _NEEDS_TEXT_CODE
        return ReporterSignInResult(
            SignInKind.SIGNED_IN, answer.tries_left, session_id, Role.REPORTER, answer.service_ids
        )


@dataclass(frozen=True, slots=True)
class ReverifyStatusResult:
    reverify_due: bool
    days_left: int


class ReverifyStatus:
    """The 30-day check of a device: whether a text code is due and the whole days left before it
    is. A device that cannot sign in for any reason (unknown, revoked, waiting for a call-back,
    never verified) is due with no days left, so the answer does not say which devices exist."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, device_id: str) -> ReverifyStatusResult:
        device = _device(device_id)
        person = await _owner(self._uow_factory, device)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            _tenant_bound(uow)
            known = await uow.devices.known(person, device)
            verified = await uow.devices.verified_at(person, device)
        if needs_reverification(verified, now, device_known=known) or verified is None:
            return ReverifyStatusResult(reverify_due=True, days_left=0)
        remaining = REVERIFY_EVERY - (now - verified)
        return ReverifyStatusResult(
            reverify_due=False, days_left=max(0, math.ceil(remaining / _ONE_DAY))
        )


class CheckReporterAccess:
    """Whether the person behind a verified token may still act: they are active and, for a
    reporter, the device the token was made for is still known (not revoked, not waiting for a
    call-back). A token is a signed claim that cannot be recalled, so a route that acts for a
    reporter asks this first: signing out and removal then take effect at once, not at expiry. A
    wall screen, an actor with no person, and a reporter token with no device never have access."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor) -> bool:
        if actor.practitioner_id is None or actor.role not in (Role.REPORTER, Role.EXEC):
            return False
        if actor.role is Role.REPORTER and actor.device_id is None:
            return False
        async with self._uow_factory() as uow:
            _tenant_bound(uow)
            person = await uow.people.get_practitioner(actor.practitioner_id)
            if person is None or not person.active:
                return False
            if actor.role is Role.REPORTER and actor.device_id is not None:
                return await uow.devices.known(actor.practitioner_id, actor.device_id)
        return True
