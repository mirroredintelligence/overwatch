"""Text codes for registration, reporter set-up and re-verification (U25).

A six-digit code is sent by text to a known number and verified by the person who receives it. A
known number is one with an open invitation (a link token of purpose `invite`, U24) or a registered
practitioner's phone hash. An unknown number gets exactly the same answers and no text, so a caller
cannot tell which numbers are known (domain-rules 7; DEC-044 for the choices).

Only a keyed hash of a code is stored, under the key code:<phone hash>:<purpose>, with a lifetime of
ten minutes (CODE_VALID_FOR). A code is kept for an unknown number too, so the unknown and the known
paths store the same things. A request sends only after its unit of work commits, so an audit entry
never exists for a code that was not stored.
"""

import hashlib
import hmac
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from diucs.application.actor import anonymous_actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import CodeStore, PhoneHasher
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.rules.identity_policy import (
    CODE_MAX_TRIES,
    CODE_RESEND_AFTER,
    CodeOutcome,
    CodeState,
    code_attempt,
)

CODE_HMAC_SECRET: Final = "code-hmac"
INVITATION_PURPOSE: Final = "invite"
"""The link token purpose of an invitation (U24). An open invitation makes its phone known."""
PURPOSES: Final = frozenset({"register", "setup", "reverify", "pin-reset", "new-device"})
CODE_DIGITS: Final = 6
CODE_CHOICES: Final = 10
RESEND_AFTER_SECONDS: Final = int(CODE_RESEND_AFTER.total_seconds())
CODES_TOPIC: Final = "codes.dispatch"
SEND_CODE: Final = "SendCode"
"""The outbox event of a code for a known number: the sender opens the sealed code and texts it."""
DISCARD_CODE: Final = "DiscardCode"
"""The outbox event of a code for an unknown number: written so both paths make the same calls, and
never sent. The sender sends SendCode only."""
REQUEST_USE_CASE: Final = "RequestTextCode"
VERIFY_USE_CASE: Final = "VerifyTextCode"
REQUEST_ACTION: Final = "C"
VERIFY_ACTION: Final = "U"
OUTCOME_REQUESTED: Final = "requested"
ACTOR_CHANNEL: Final = "text-code"


@dataclass(frozen=True, slots=True)
class RequestTextCodeCommand:
    idempotency_key: str
    phone: str
    purpose: str


@dataclass(frozen=True, slots=True)
class RequestTextCodeResult:
    sent: bool
    retry_after_seconds: int


@dataclass(frozen=True, slots=True)
class VerifyTextCodeCommand:
    phone: str
    purpose: str
    code: str


@dataclass(frozen=True, slots=True)
class VerifyTextCodeResult:
    ok: bool
    tries_left: int
    needs_new_code: bool
    practitioner_id: str | None
    invitation_id: str | None
    verified_at: datetime | None


@dataclass(frozen=True, slots=True)
class _RequestStored:
    """A request's result under its command key, with the fingerprint of the request (DEC-104)."""

    fingerprint: str
    result: RequestTextCodeResult


def check_purpose(purpose: str) -> str:
    """The purpose, exactly one of the five names (U25). Any other text is refused."""
    if not isinstance(purpose, str) or purpose not in PURPOSES:
        raise ValidationFailed(
            "purpose", "must be register, setup, reverify, pin-reset or new-device"
        )
    return purpose


def code_key(phone_hash: str, purpose: str) -> str:
    """The store key of a phone's code for one purpose. The tenant prefix is the store's (I13)."""
    return f"code:{phone_hash}:{check_purpose(purpose)}"


def new_code(rng: random.Random) -> str:
    """Six digits, each drawn on its own from ten values, so every code is equally likely."""
    return "".join(str(rng.randrange(0, CODE_CHOICES)) for _ in range(CODE_DIGITS))


def code_hash(secret: bytes, phone_hash: str, purpose: str, code: str) -> str:
    """The keyed hash that is stored: HMAC-SHA256 of the phone, the purpose and the code. The code
    itself is never stored (U25)."""
    message = f"{phone_hash}|{check_purpose(purpose)}|{code}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def cooldown_seconds(last_sent_at: datetime, now: datetime) -> int:
    """Whole seconds still to wait before a new code may be sent, rounded up; 0 when it may be sent
    (CODE_RESEND_AFTER after the last send)."""
    if last_sent_at.utcoffset() is None or now.utcoffset() is None:
        raise ValidationFailed("now", "must be timezone-aware")
    remaining = CODE_RESEND_AFTER - (now.astimezone(UTC) - last_sent_at.astimezone(UTC))
    if remaining <= timedelta(0):
        return 0
    return math.ceil(remaining.total_seconds())


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _replay_key(scope: ScopeId, key: str) -> str:
    """The replay key of a request, named by the tenant (lesson L160)."""
    return f"text-code:request:{scope}:{key}"


async def _is_known(uow: UnitOfWork, phone_hash: str, now: datetime) -> bool:
    """A number is known when a registered practitioner holds it or an invitation is open for it.
    Both lookups always run, so a known and an unknown number make the same calls (H-96)."""
    practitioner = await uow.people.find_by_phone_hash(phone_hash)
    invitation = await uow.link_tokens.open_for_phone(INVITATION_PURPOSE, phone_hash, now)
    return practitioner is not None or invitation is not None


def verify_fields(state: CodeState) -> tuple[int, bool]:
    """(tries left, whether a new code is needed) after one attempt (domain-rules 7, D27)."""
    tries_left = max(0, CODE_MAX_TRIES - state.failed_tries)
    needs_new_code = state.last_outcome is not CodeOutcome.WRONG
    return tries_left, needs_new_code


class RequestTextCode:
    """Request a code. The response is the same for a known and an unknown number, and so is the
    work done before it returns: the same lookups, the same store write, the same sealing and the
    same outbox and audit writes. Only the outbox event differs (SendCode for a known number), and
    the sender acts on that event alone, after the response (H-96)."""

    def __init__(
        self,
        code_store: CodeStore,
        phone_hasher: PhoneHasher,
        uow_factory: UnitOfWorkFactory,
        secret_store: SecretStore,
        sealer: ContentSealer,
        ids: IdGenerator,
        clock: Clock,
        rng: random.Random,
    ) -> None:
        self._codes = code_store
        self._hasher = phone_hasher
        self._uow_factory = uow_factory
        self._secrets = secret_store
        self._sealer = sealer
        self._ids = ids
        self._clock = clock
        self._rng = rng

    async def execute(self, command: RequestTextCodeCommand) -> RequestTextCodeResult:
        purpose = check_purpose(command.purpose)
        phone_hash = self._hasher.hash(command.phone)
        fingerprint = hashlib.sha256(f"{phone_hash}|{purpose}".encode()).hexdigest()
        now = self._clock.now()

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            replay_key = _replay_key(scope, command.idempotency_key)
            stored = await uow.idempotency.get(replay_key)
            if isinstance(stored, _RequestStored):
                if stored.fingerprint != fingerprint:
                    raise Conflict("this command key was used for a different request")
                return stored.result
            known = await _is_known(uow, phone_hash, now)

        key = code_key(phone_hash, purpose)
        previous = await self._codes.get(purpose, phone_hash)
        if previous is not None:
            wait = cooldown_seconds(previous[1].issued_at, now)
            if wait > 0:
                return RequestTextCodeResult(sent=False, retry_after_seconds=wait)

        code = new_code(self._rng)
        secret = self._secrets.get(CODE_HMAC_SECRET)
        await self._codes.save(
            purpose, phone_hash, code_hash(secret, phone_hash, purpose, code), CodeState(now)
        )

        result = RequestTextCodeResult(sent=True, retry_after_seconds=RESEND_AFTER_SECONDS)
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            message_id = self._ids.new_id()
            sealed = self._sealer.seal(
                code, message_id=message_id, tenant_id=scope.value, recipient_role_id=key
            )
            await uow.outbox.add(
                OutboxMessage(
                    id=message_id,
                    topic=CODES_TOPIC,
                    event_type=SEND_CODE if known else DISCARD_CODE,
                    payload={"sealed_code": sealed, "purpose": purpose},
                    created_at=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=REQUEST_ACTION,
                    use_case=REQUEST_USE_CASE,
                    actor=anonymous_actor(scope.value, ACTOR_CHANNEL),
                    entity_ids=(),
                    snapshot={"purpose": purpose, "outcome": OUTCOME_REQUESTED},
                    at=now,
                )
            )
            await uow.idempotency.put(
                _replay_key(scope, command.idempotency_key),
                _RequestStored(fingerprint, result),
            )
            await uow.commit()
        return result


class VerifyTextCode:
    def __init__(
        self,
        code_store: CodeStore,
        phone_hasher: PhoneHasher,
        uow_factory: UnitOfWorkFactory,
        secret_store: SecretStore,
        clock: Clock,
    ) -> None:
        self._codes = code_store
        self._hasher = phone_hasher
        self._uow_factory = uow_factory
        self._secrets = secret_store
        self._clock = clock

    async def execute(self, command: VerifyTextCodeCommand) -> VerifyTextCodeResult:
        purpose = check_purpose(command.purpose)
        phone_hash = self._hasher.hash(command.phone)
        now = self._clock.now()
        held = await self._codes.get(purpose, phone_hash)
        if held is None:
            # No code was asked for (or it has lapsed). Known and unknown numbers get this answer.
            return _refused(needs_new_code=True)

        stored_hash, state = held
        secret = self._secrets.get(CODE_HMAC_SECRET)
        entered_ok = hmac.compare_digest(
            code_hash(secret, phone_hash, purpose, command.code), stored_hash
        )
        attempted = code_attempt(state, entered_ok, now)
        await self._codes.save(purpose, phone_hash, stored_hash, attempted)

        async with self._uow_factory() as uow:
            outcome = attempted.last_outcome
            outcome_text = outcome.value if outcome is not None else ""
            if attempted.last_outcome is not CodeOutcome.VERIFIED:
                await self._audit(uow, purpose, outcome_text, now)
                await uow.commit()
                tries_left, needs_new_code = verify_fields(attempted)
                return VerifyTextCodeResult(
                    ok=False,
                    tries_left=tries_left,
                    needs_new_code=needs_new_code,
                    practitioner_id=None,
                    invitation_id=None,
                    verified_at=None,
                )

            practitioner = await uow.people.find_by_phone_hash(phone_hash)
            invitation = await uow.link_tokens.open_for_phone(INVITATION_PURPOSE, phone_hash, now)
            if practitioner is None and invitation is None:
                # The number stopped being known after the code was sent: nothing is verified.
                await self._audit(uow, purpose, "unknown-number", now)
                await uow.commit()
                return _refused(needs_new_code=True)
            await self._audit(uow, purpose, outcome_text, now)
            await uow.commit()
        tries_left, _ = verify_fields(attempted)
        return VerifyTextCodeResult(
            ok=True,
            tries_left=tries_left,
            needs_new_code=False,
            practitioner_id=None if practitioner is None else practitioner.id,
            invitation_id=None if invitation is None else invitation.about_id,
            verified_at=now,
        )

    async def _audit(self, uow: UnitOfWork, purpose: str, outcome: str, now: datetime) -> None:
        """Purpose and outcome only: never the code, the number or its hash (U25)."""
        await uow.audit.append(
            AuditEntry(
                action=VERIFY_ACTION,
                use_case=VERIFY_USE_CASE,
                actor=anonymous_actor(_tenant_scope(uow.unit_scope).value, ACTOR_CHANNEL),
                entity_ids=(),
                snapshot={"purpose": purpose, "outcome": outcome},
                at=now,
            )
        )


def _refused(*, needs_new_code: bool) -> VerifyTextCodeResult:
    return VerifyTextCodeResult(
        ok=False,
        tries_left=0,
        needs_new_code=needs_new_code,
        practitioner_id=None,
        invitation_id=None,
        verified_at=None,
    )


__all__ = [
    "CODE_HMAC_SECRET",
    "INVITATION_PURPOSE",
    "PURPOSES",
    "RequestTextCode",
    "RequestTextCodeCommand",
    "RequestTextCodeResult",
    "VerifyTextCode",
    "VerifyTextCodeCommand",
    "VerifyTextCodeResult",
    "check_purpose",
    "code_hash",
    "code_key",
    "cooldown_seconds",
    "new_code",
    "verify_fields",
]
