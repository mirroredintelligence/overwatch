"""PairWallScreen: pairing a wall display with a six-digit code (U10, DEC-160).

Three steps, one use case each:

1. StartPairing: the wall display asks for a code. It gets a code to show ("482 913"), a secret that
   only it holds, and the time the code lapses (ten minutes). Two single-use link-token records are
   stored (purposes `wall-pairing` and `wall-pairing-secret`, both about the pairing id), each as a
   keyed hash. Neither the code nor the secret is stored.
2. ConfirmPairing: a shift lead types the code and a screen name. The code is burned, the device is
   saved as `paired-unclaimed`, and one audit entry is written. Only the role `lead` may confirm.
3. ClaimPairing: the display collects its device token with the secret. The token (128 bits) is
   returned once and only its keyed hash is stored; the device becomes `active` and the secret is
   burned. Any later claim says `paired` and gives no token.

The tenant is never an input (DEC-130, DEC-134 item 3). The edge binds it before the unit of work
opens (from the sub-domain for the unauthenticated steps, from the signed token for the lead), and
the use case reads it from the unit of work only. Every code and secret is hashed together with that
tenant, so the same six digits in two tenants are two different records, and a code or secret of
another tenant is found by nobody: it reads as a wrong one, with the same refusal.

Refusals (DEC-160): a code that is wrong, malformed, expired, used or another tenant's, and a secret
that is wrong or another pairing's or another tenant's, all raise NotAllowed with the same fixed
message, so an answer cannot tell them apart. Only a lead may confirm; any other role is refused
before the code is looked at. A lead who fails CONFIRM_FAILURE_LIMIT times in LIMIT_WINDOW is
refused with PairingRateLimited, whatever code they then type; starts are limited per tenant. The
counts live in the cache (nothing of record), keyed by the tenant.
"""

import hashlib
import random
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final, Literal

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, DomainError, NotAllowed
from diucs.domain.model.device import (
    BoardScope,
    Device,
    DeviceStatus,
    DeviceType,
    check_screen_label,
)
from diucs.domain.rules.tokens import (
    LINK_TOKEN_ALPHABET,
    LINK_TOKEN_LENGTH,
    PAIRING_CODE_VALID_FOR,
    LinkCheck,
    LinkTokenRecord,
    check_link,
    format_pairing_code,
    hash_token,
    new_link_token,
    new_pairing_code,
)

USE_CASE: Final = "PairWallScreen"
PAIRING_PURPOSE: Final = "wall-pairing"
PAIRING_SECRET_PURPOSE: Final = "wall-pairing-secret"
ACTION_PAIRED: Final = "wall-screen-paired"
ACTION_CLAIMED: Final = "wall-screen-claimed"
SCREEN_CHANNEL: Final = "screen"

START_LIMIT: Final = 20
"""Codes a tenant may start in LIMIT_WINDOW. Bounds the codes alive at once, so a guess has few to
hit, and the link-token nodes an unauthenticated caller can make."""
CONFIRM_FAILURE_LIMIT: Final = 5
"""Wrong confirmations one lead may make in LIMIT_WINDOW before every further one is refused."""
LIMIT_WINDOW: Final = PAIRING_CODE_VALID_FOR
CODE_ATTEMPTS: Final = 10
"""Draws of a fresh code before a start gives up. A code the tenant holds is drawn again."""

REFUSED_MESSAGE: Final = "This code or screen is not valid."
LEAD_ONLY_MESSAGE: Final = "Only a shift lead can connect a screen."
RATE_LIMITED_MESSAGE: Final = "Too many attempts. Wait a few minutes and try again."
NO_CODE_MESSAGE: Final = "Could not issue a pairing code. Try again."

_CODE: Final = re.compile(r"[0-9]{6}")
_SECRET: Final = re.compile(f"[{LINK_TOKEN_ALPHABET}]{{{LINK_TOKEN_LENGTH}}}")
_CODE_SEPARATORS: Final = re.compile(r"[ \-]")


class PairingRateLimited(DomainError):
    """Too many pairing attempts for now. The message is fixed and names nothing."""


@dataclass(frozen=True, slots=True)
class StartPairingResult:
    pairing_id: str
    code_display: str
    screen_secret: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ConfirmPairingCommand:
    idempotency_key: str
    actor: Actor
    code: str
    screen_name: str
    location: str | None
    board_scope: BoardScope = BoardScope.TENANT


@dataclass(frozen=True, slots=True)
class ConfirmPairingResult:
    device_id: str
    screen_name: str
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ClaimPairingCommand:
    pairing_id: str
    screen_secret: str


@dataclass(frozen=True, slots=True)
class ClaimPairingResult:
    """`waiting`: no lead has confirmed yet. `paired`: confirmed; the token is given once, to the
    claim that collected it, and never again. `expired`: the ten minutes ran out first, so the
    screen must ask for a new code."""

    status: Literal["waiting", "paired", "expired"]
    device_token: str | None


def normalise_code(text: str) -> str | None:
    """The six digits of a typed code ("482 913", "482-913", "482913"), or None for anything else.
    Only ASCII digits count, and only spaces and hyphens may be dropped."""
    if not isinstance(text, str):
        return None
    compact = _CODE_SEPARATORS.sub("", text)
    return compact if _CODE.fullmatch(compact) else None


class AttemptLimiter:
    """A count of events inside a window, kept in the cache (nothing of record: losing it loses no
    fact). Each event takes the first free slot `<name>#<n>`, written with the window as its
    lifetime, so a slot comes free one window after it was taken and the window is counted from each
    event, not from the first. Taking a slot is one atomic step per slot (`set_if_absent`), so
    parallel callers can never hold more than `limit` slots between them."""

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    async def take(self, name: str, limit: int, window: timedelta) -> str | None:
        """Count one event, and return the slot it took, or None (and count nothing) when `limit`
        events are already inside the window. A cache that cannot be reached raises: the caller is
        refused, never let through."""
        _check_limit(limit)
        for slot in range(limit):
            key = f"{name}#{slot}"
            if await self._cache.set_if_absent(key, "1", window):
                return key
        return None

    async def release(self, slot: str) -> None:
        """Give back a slot that `take` returned. A slot that is already free does nothing."""
        await self._cache.delete(slot)


def _check_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be at least 1")


def _tenant_scope(uow: UnitOfWork) -> ScopeId:
    """The tenant this unit of work is bound to. Nothing bound, or a network scope, is a missing
    binding: a screen is paired to one tenant (DEC-132 item 5), never to a network."""
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def _keyed(secret: bytes, scope: ScopeId, text: str) -> str:
    """The stored hash of a code or a secret, made with the tenant as well: the same text in two
    tenants gives two hashes. The text holds no hyphen, and a tenant id holds no other text after
    its last hyphen, so `<tenant>-<text>` cannot be read two ways."""
    return hash_token(f"{scope}-{text}", secret)


def _secret_hash(secret: bytes, scope: ScopeId, screen_secret: str) -> str | None:
    if not isinstance(screen_secret, str) or not _SECRET.fullmatch(screen_secret):
        return None
    return _keyed(secret, scope, screen_secret)


def _command_key(scope: ScopeId, key: str) -> str:
    """The key handed to the replay store and the link-token burn: the tenant is part of it, so two
    tenants that use the same key are two commands. Needed while the replay statements are
    unconverted and key their records by the key alone (known-issues); the one place to change."""
    return f"pairing:{scope}:{key}"


def _who(practitioner_id: str) -> str:
    return hashlib.sha256(practitioner_id.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class _StoredConfirm:
    """The result kept for a command key, with the fingerprint of the command that made it. The
    fingerprint holds the keyed hash of the code, never the code."""

    fingerprint: str
    result: ConfirmPairingResult


def _fingerprint(
    command: ConfirmPairingCommand, name: str, location: str | None, code_hash: str | None
) -> str:
    body = repr(
        (
            USE_CASE,
            command.actor.practitioner_id,
            name,
            location,
            command.board_scope.value,
            code_hash,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class StartPairing:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        rng: random.Random,
        secret_store: SecretStore,
        cache: Cache,
    ) -> None:
        """`rng` must be a cryptographic source in production (`secrets.SystemRandom()`); a seeded
        `random.Random` is for tests only. It gives the six digits and the 128-bit secret."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._rng = rng
        self._secrets = secret_store
        self._limiter = AttemptLimiter(cache)

    async def execute(self) -> StartPairingResult:
        link_secret = self._secrets.get(LINK_TOKEN_SECRET)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow)
            if (
                await self._limiter.take(f"pairing-start:{scope}", START_LIMIT, LIMIT_WINDOW)
                is None
            ):
                raise PairingRateLimited(RATE_LIMITED_MESSAGE)
            code, code_hash = await self._fresh_code(uow, scope, link_secret)
            pairing_id = self._ids.new_id()
            screen_secret = new_link_token(self._rng.randbytes)
            expires_at = now + PAIRING_CODE_VALID_FOR
            for token_hash, purpose in (
                (code_hash, PAIRING_PURPOSE),
                (_keyed(link_secret, scope, screen_secret), PAIRING_SECRET_PURPOSE),
            ):
                await uow.link_tokens.add(
                    LinkTokenRecord(
                        token_hash=token_hash,
                        purpose=purpose,
                        about_id=pairing_id,
                        phone_hash=None,
                        expires_at=expires_at,
                        used_at=None,
                    )
                )
            await uow.commit()
        return StartPairingResult(
            pairing_id=pairing_id,
            code_display=format_pairing_code(code),
            screen_secret=screen_secret,
            expires_at=expires_at,
        )

    async def _fresh_code(
        self, uow: UnitOfWork, scope: ScopeId, link_secret: bytes
    ) -> tuple[str, str]:
        """A code no record of this tenant holds, with its stored hash. A code that is held (live,
        used or expired: the record stays) is drawn again."""
        for _ in range(CODE_ATTEMPTS):
            code = new_pairing_code(self._rng.randrange)
            code_hash = _keyed(link_secret, scope, code)
            if await uow.link_tokens.get_by_hash(code_hash) is None:
                return code, code_hash
        raise Conflict(NO_CODE_MESSAGE)


class ConfirmPairing:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secret_store: SecretStore,
        cache: Cache,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._secrets = secret_store
        self._limiter = AttemptLimiter(cache)

    async def execute(self, command: ConfirmPairingCommand) -> ConfirmPairingResult:
        actor = command.actor
        if actor.role is not Role.LEAD or actor.practitioner_id is None:
            raise NotAllowed(LEAD_ONLY_MESSAGE)
        name = check_screen_label(command.screen_name, "screen_name")
        location = (
            None if command.location is None else check_screen_label(command.location, "location")
        )
        link_secret = self._secrets.get(LINK_TOKEN_SECRET)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow)
            digits = normalise_code(command.code)
            code_hash = None if digits is None else _keyed(link_secret, scope, digits)
            fingerprint = _fingerprint(command, name, location, code_hash)
            key = _command_key(scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if stored is not None:
                return _replay(stored, fingerprint)
            # The failure slot is taken before the code is looked up, in one atomic step, so
            # parallel requests cannot all pass a check that none has yet counted against. A slot
            # is kept for a refusal and given back for a success.
            attempts = f"pairing-confirm:{scope}:{_who(actor.practitioner_id)}"
            slot = await self._limiter.take(attempts, CONFIRM_FAILURE_LIMIT, LIMIT_WINDOW)
            if slot is None:
                raise PairingRateLimited(RATE_LIMITED_MESSAGE)
            device_id = await _burn_code(uow, code_hash, now, key)
            if device_id is None or await uow.devices.get(device_id) is not None:
                raise NotAllowed(REFUSED_MESSAGE)
            await self._limiter.release(slot)
            device = Device(
                id=device_id,
                status=DeviceStatus.PAIRED_UNCLAIMED,
                name=name,
                location=location,
                device_type=DeviceType.WALL_DISPLAY,
                token_hash=None,
                board_scope=command.board_scope,
            )
            await uow.devices.save(device)
            await uow.audit.append(
                AuditEntry(
                    action=ACTION_PAIRED,
                    use_case=USE_CASE,
                    actor=actor,
                    entity_ids=(device.id,),
                    snapshot={
                        "screen_name": device.name,
                        "location": device.location,
                        "board_scope": device.board_scope.value,
                    },
                    at=now,
                )
            )
            result = ConfirmPairingResult(device_id=device.id, screen_name=device.name)
            await uow.idempotency.put(key, _StoredConfirm(fingerprint, result))
            await uow.commit()
        return result


def _replay(stored: object, fingerprint: str) -> ConfirmPairingResult:
    """A stored result for this key replays only for the same confirmation by the same lead. Any
    other stored value is a Conflict (the key was used for something else)."""
    if not isinstance(stored, _StoredConfirm) or stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different command")
    return replace(stored.result, replayed=True)


async def _burn_code(uow: UnitOfWork, code_hash: str | None, now: datetime, key: str) -> str | None:
    """Burn the code and return the pairing id it is about, or None when the code is not a live
    pairing code of this tenant, or another confirmation burned it first."""
    if code_hash is None:
        return None
    record = await uow.link_tokens.get_by_hash(code_hash)
    if record is None or record.purpose != PAIRING_PURPOSE:
        return None
    if check_link(record, now) is not LinkCheck.OK:
        return None
    if not await uow.link_tokens.mark_used(code_hash, now, key):
        return None
    return record.about_id


class ClaimPairing:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        rng: random.Random,
        secret_store: SecretStore,
    ) -> None:
        """`rng` must be a cryptographic source in production (`secrets.SystemRandom()`): it gives
        the 128 bits of the device token."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._rng = rng
        self._secrets = secret_store

    async def execute(self, command: ClaimPairingCommand) -> ClaimPairingResult:
        """The result is never stored: it may hold the token, which exists in no record. Only the
        claim that burns the secret gets the token."""
        link_secret = self._secrets.get(LINK_TOKEN_SECRET)
        device_secret = self._secrets.get(DEVICE_TOKEN_SECRET)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow)
            # The screen is read first and takes its write lock, so claims for one pairing run one
            # after the other and the secret is read below as the claim before it left it (L85).
            device = await uow.devices.get(command.pairing_id)
            secret_hash = _secret_hash(link_secret, scope, command.screen_secret)
            record = None if secret_hash is None else await uow.link_tokens.get_by_hash(secret_hash)
            if (
                secret_hash is None
                or record is None
                or record.purpose != PAIRING_SECRET_PURPOSE
                or record.about_id != command.pairing_id
            ):
                raise NotAllowed(REFUSED_MESSAGE)
            state = check_link(record, now)
            if state is LinkCheck.USED:
                return ClaimPairingResult("paired", None)
            if state is LinkCheck.EXPIRED:
                return ClaimPairingResult("expired", None)
            if device is None:
                return ClaimPairingResult("waiting", None)
            if device.status is not DeviceStatus.PAIRED_UNCLAIMED:
                raise NotAllowed(REFUSED_MESSAGE)
            if not await uow.link_tokens.mark_used(secret_hash, now, f"claim:{device.id}"):
                return ClaimPairingResult("paired", None)
            token = new_link_token(self._rng.randbytes)
            active = replace(
                device,
                status=DeviceStatus.ACTIVE,
                token_hash=hash_token(token, device_secret),
            )
            await uow.devices.save(active)
            await uow.audit.append(
                AuditEntry(
                    action=ACTION_CLAIMED,
                    use_case=USE_CASE,
                    actor=Actor(
                        role=Role.WALL,
                        practitioner_id=None,
                        device_id=device.id,
                        channel=SCREEN_CHANNEL,
                        service_ids=frozenset(),
                        tenant_id=_tenant_scope(uow).value,
                    ),
                    entity_ids=(device.id,),
                    snapshot={"board_scope": device.board_scope.value},
                    at=now,
                )
            )
            await uow.commit()
        return ClaimPairingResult("paired", token)
