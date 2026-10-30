"""PIN set, sign-in, lock, reset and the 30-day check for reporters (U32, domain-rules 7, DEC-044).

A reporter proves the phone with a text code (U25), then sets a six-digit PIN for that device; later
the PIN signs them in. The PIN is stored only as a keyed hash (HMAC-SHA256 under the secret
`pin-hmac`, over the practitioner, the device and the PIN), so a PIN set on one device does not work
on another, and the hash is compared in constant time. Five wrong tries lock the credential until a
verified text code and a new PIN reset it (the lock has no end time, DEC-044 item 2). Thirty days
after the last text code, or on a device never verified, sign-in asks for a text code instead.

Authentication rules this module keeps:
- The time a text code was verified is read from the device's own record (RecordTextCodeVerified
  stamps it on the server after U25's verify), never trusted from the caller: a PIN is set only when
  the stored verification is within PIN_SET_WINDOW and the caller's claim agrees with it.
- An identity that cannot sign in (unknown person, left person, unknown or revoked device, no PIN
  yet, 30 days passed) gets one answer, `needs_text_code`, with the same calls and the same work as
  a known person on a new device. The answer never says which of these it was.
- The throttle (the existing RateLimiter, per tenant) counts every attempt before anything is read,
  for known and unknown identities alike, under keys that hold no identifier.
- No PIN, hash or secret is in a log, an audit entry, a throttle key or a repr: the commands hide
  their PIN, the audit holds an outcome word only, and an unknown identifier is never written.

Decisions: DEC-321 to DEC-324 (U32).
"""

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from diucs.application.actor import anonymous_actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import RateLimiter
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.errors import DomainError, ValidationFailed
from diucs.domain.model.people import REPORTER_ROLE_CODES, PractitionerRole, is_in_effect
from diucs.domain.rules.identity_policy import (
    PIN_MAX_TRIES,
    PinOutcome,
    PinState,
    needs_reverification,
    pin_attempt,
    validate_pin_format,
)

PIN_HMAC_SECRET: Final = "pin-hmac"
PIN_SET_WINDOW: Final = timedelta(minutes=10)
"""A PIN is set only within this long of a verified text code (domain-rules 7)."""
VERIFIED_PURPOSES: Final = frozenset({"setup", "pin-reset", "new-device", "reverify"})
"""The text-code purposes that stamp a device. `register` is for a person with no device yet."""
RATE_WINDOW: Final = timedelta(minutes=10)
SIGN_IN_PER_DEVICE: Final = 10
"""[ASSUMED] attempts per device in a window: twice the five tries of the lock, so a person who
mistypes is locked (a durable, visible state) before the throttle (a fast, silent one) refuses."""
SIGN_IN_PER_PERSON: Final = 20
"""[ASSUMED] attempts per person in a window, across their devices."""
SET_PIN_PER_PERSON: Final = 10
"""[ASSUMED] PIN settings per person in a window."""
RATE_LIMITED_MESSAGE: Final = "Too many attempts. Try again later."
MAX_ID_LENGTH: Final = 128
SIGN_IN_USE_CASE: Final = "PinSignIn"
SET_USE_CASE: Final = "SetPin"
RECORD_USE_CASE: Final = "RecordTextCodeVerified"
AUDIT_UPDATE: Final = "U"
OUTCOME_OK: Final = "ok"
OUTCOME_WRONG: Final = "wrong"
OUTCOME_LOCKED: Final = "locked"
OUTCOME_NEEDS_CODE: Final = "needs-text-code"
_DUMMY_HASH: Final = "0" * 64
"""What an unknown identity is compared against, so the comparison runs for every answer."""
_ASCII_DIGITS: Final = frozenset("0123456789")
ACTOR_CHANNEL: Final = "pin"


class PinRateLimited(DomainError):
    """Too many attempts in the window. Carries the seconds to wait and nothing else: no identifier,
    no count. Edges answer 429."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(RATE_LIMITED_MESSAGE)
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class SetPinCommand:
    practitioner_id: str
    device_id: str
    pin: str = field(repr=False)
    verified_at: datetime
    """When the text code was verified, as VerifyTextCodeResult gave it. Checked against the
    device's stored verification and the clock; it can never make a stale verification fresh."""


@dataclass(frozen=True, slots=True)
class SetPinResult:
    ok: bool


@dataclass(frozen=True, slots=True)
class PinSignInCommand:
    practitioner_id: str
    device_id: str
    pin: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class PinSignInResult:
    ok: bool
    locked: bool
    tries_left: int
    needs_text_code: bool
    practitioner_id: str | None
    role: Role | None
    service_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecordTextCodeVerifiedCommand:
    practitioner_id: str
    device_id: str
    verified_at: datetime
    purpose: str


@dataclass(frozen=True, slots=True)
class RecordTextCodeVerifiedResult:
    device_known: bool
    """False when the device is revoked or the person is unknown or has left: nothing stamped."""


NEEDS_TEXT_CODE: Final = PinSignInResult(
    ok=False,
    locked=False,
    tries_left=0,
    needs_text_code=True,
    practitioner_id=None,
    role=None,
    service_ids=(),
)
"""The one answer for every identity that cannot sign in."""


def pin_hash(secret: bytes, practitioner_id: str, device_id: str, pin: str) -> str:
    """The keyed hash that is stored: HMAC-SHA256 of the practitioner, the device and the PIN, with
    NUL between them so two ids that run together cannot give one message. The PIN is not stored."""
    message = "\x00".join((practitioner_id, device_id, pin)).encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(name, "must be timezone-aware")
    return value.astimezone(UTC)


def verification_is_fresh(stored: datetime | None, claimed: datetime, now: datetime) -> bool:
    """Whether a PIN may be set now: the device's stored verification exists, is not in the future,
    is within PIN_SET_WINDOW of now, and the caller's claim is neither fresher than the record nor
    older than the window. Every instant is compared in UTC (lesson L52)."""
    current = _aware(now, "now")
    claim = _aware(claimed, "verified_at")
    if stored is None:
        return False
    record = _aware(stored, "verified_at")
    if record > current or claim > record:
        return False
    return current - record <= PIN_SET_WINDOW and current - claim <= PIN_SET_WINDOW


def session_role(codes: list[PractitionerRoleCode]) -> Role | None:
    """The role a PIN session carries: reporter when the person holds a reporter post. Nothing
    else is guessed: a person with no reporter post gets None and never a higher role (the exec and
    lead sessions are built by the edge from their own records)."""
    return Role.REPORTER if any(code in REPORTER_ROLE_CODES for code in codes) else None


def reporter_service_ids(roles: list[PractitionerRole], now: datetime) -> tuple[str, ...]:
    """The services of the active reporter posts in effect at `now`, sorted and without repeats."""
    return tuple(
        sorted(
            {
                role.service_id
                for role in roles
                if role.active
                and role.code in REPORTER_ROLE_CODES
                and role.service_id is not None
                and is_in_effect(role, now)
            }
        )
    )


def limiter_key(kind: str, *parts: str) -> str:
    """A throttle key: the kind and a digest of the parts, so no identifier reaches Redis or a log
    (the tenant prefix is the limiter's, I13)."""
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{kind}:{digest}"


def _ident(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_ID_LENGTH
        or not value.isprintable()
    ):
        raise ValidationFailed(name, "is not a valid identifier")
    return value


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _format_ok(pin: object) -> bool:
    return isinstance(pin, str) and len(pin) == 6 and all(c in _ASCII_DIGITS for c in pin)


async def _throttle(limiter: RateLimiter, checks: tuple[tuple[str, int], ...]) -> None:
    """Count one attempt against each limit, in order, and refuse at the first that is used up."""
    for key, limit in checks:
        if not await limiter.allow(key, limit, RATE_WINDOW):
            raise PinRateLimited(int(RATE_WINDOW.total_seconds()))


async def _audit(
    uow: UnitOfWork, use_case: str, outcome: str, entity_ids: tuple[str, ...], now: datetime
) -> None:
    """The outcome word only: never the PIN, a hash or an identifier the caller invented."""
    await uow.audit.append(
        AuditEntry(
            action=AUDIT_UPDATE,
            use_case=use_case,
            actor=anonymous_actor(_tenant_scope(uow.unit_scope).value, ACTOR_CHANNEL),
            entity_ids=entity_ids,
            snapshot={"outcome": outcome},
            at=now,
        )
    )


class SetPin:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        secret_store: SecretStore,
        clock: Clock,
        rate_limiter: RateLimiter,
    ) -> None:
        self._uow_factory = uow_factory
        self._secrets = secret_store
        self._clock = clock
        self._limiter = rate_limiter

    async def execute(self, command: SetPinCommand) -> SetPinResult:
        validate_pin_format(command.pin)
        person = _ident(command.practitioner_id, "practitioner_id")
        device = _ident(command.device_id, "device_id")
        now = self._clock.now()
        await _throttle(self._limiter, ((limiter_key("pin-set", person), SET_PIN_PER_PERSON),))
        stored_hash = pin_hash(self._secrets.get(PIN_HMAC_SECRET), person, device, command.pin)
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            practitioner = await uow.people.get_practitioner(person)
            verified = await uow.devices.verified_at(person, device)
            if (
                practitioner is None
                or not practitioner.active
                or not verification_is_fresh(verified, command.verified_at, now)
            ):
                return SetPinResult(ok=False)
            await uow.pins.set_pin(person, device, stored_hash)
            await _audit(uow, SET_USE_CASE, OUTCOME_OK, (person,), now)
            await uow.commit()
        return SetPinResult(ok=True)


class PinSignIn:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        secret_store: SecretStore,
        clock: Clock,
        rate_limiter: RateLimiter,
    ) -> None:
        self._uow_factory = uow_factory
        self._secrets = secret_store
        self._clock = clock
        self._limiter = rate_limiter

    async def execute(self, command: PinSignInCommand) -> PinSignInResult:
        person = _ident(command.practitioner_id, "practitioner_id")
        device = _ident(command.device_id, "device_id")
        now = self._clock.now()
        await _throttle(
            self._limiter,
            (
                (limiter_key("pin-signin-device", person, device), SIGN_IN_PER_DEVICE),
                (limiter_key("pin-signin-person", person), SIGN_IN_PER_PERSON),
            ),
        )
        format_ok = _format_ok(command.pin)
        candidate = pin_hash(
            self._secrets.get(PIN_HMAC_SECRET), person, device, command.pin if format_ok else ""
        )
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            practitioner = await uow.people.get_practitioner(person)
            known = await uow.devices.known(person, device)
            verified = await uow.devices.verified_at(person, device)
            held = await uow.pins.get(person, device)
            usable = practitioner is not None and practitioner.active and known and held is not None
            stored_hash, state = held if held is not None else (_DUMMY_HASH, PinState())
            # The comparison runs for every identity, so the work does not tell them apart.
            matches = hmac.compare_digest(candidate.encode("ascii"), stored_hash.encode("utf-8"))
            if not usable or needs_reverification(verified, now, device_known=usable):
                await _audit(uow, SIGN_IN_USE_CASE, OUTCOME_NEEDS_CODE, (), now)
                await uow.commit()
                return NEEDS_TEXT_CODE
            attempted = pin_attempt(state, matches and format_ok, now)
            await uow.pins.save_state(person, device, attempted)
            if attempted.last_outcome is PinOutcome.OK:
                roles = await uow.people.roles_for_practitioner(person)
                result = PinSignInResult(
                    ok=True,
                    locked=False,
                    tries_left=PIN_MAX_TRIES,
                    needs_text_code=False,
                    practitioner_id=person,
                    role=session_role([role.code for role in roles if role.active]),
                    service_ids=reporter_service_ids(roles, now),
                )
                outcome = OUTCOME_OK
            elif attempted.locked:
                result = PinSignInResult(False, True, 0, False, None, None, ())
                outcome = OUTCOME_LOCKED
            else:
                left = max(0, PIN_MAX_TRIES - attempted.failed_tries)
                result = PinSignInResult(False, False, left, False, None, None, ())
                outcome = OUTCOME_WRONG
            await _audit(uow, SIGN_IN_USE_CASE, outcome, (person,), now)
            await uow.commit()
        return result


class RecordTextCodeVerified:
    """Stamp a device with the time a text code was verified for its practitioner (call it after
    U25's VerifyTextCode succeeds). The device is registered when it is new. A time in the future is
    clamped to now, so it can never extend a window."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RecordTextCodeVerifiedCommand) -> RecordTextCodeVerifiedResult:
        if command.purpose not in VERIFIED_PURPOSES:
            raise ValidationFailed("purpose", "must be setup, pin-reset, new-device or reverify")
        person = _ident(command.practitioner_id, "practitioner_id")
        device = _ident(command.device_id, "device_id")
        now = self._clock.now()
        stamp = min(_aware(command.verified_at, "verified_at"), now)
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            practitioner = await uow.people.get_practitioner(person)
            if practitioner is None or not practitioner.active:
                return RecordTextCodeVerifiedResult(device_known=False)
            await uow.devices.register(person, device, now)
            if not await uow.devices.known(person, device):
                return RecordTextCodeVerifiedResult(device_known=False)
            await uow.devices.mark_verified(person, device, stamp)
            await _audit(uow, RECORD_USE_CASE, command.purpose, (person,), now)
            await uow.commit()
        return RecordTextCodeVerifiedResult(device_known=True)
