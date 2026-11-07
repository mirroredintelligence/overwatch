"""Check in by the QR code printed for a service (DEC-1346, builds DEC-1341 item 3).

The shift lead makes a check-in code for a service: a link token of its own purpose, valid for ten
years, drawn as a QR code to print. The code names the service and nothing else. A duty manager
scans it, gives their mobile number and is texted a six-digit code, and only a number that is on
this service's roster is ever sent one, so the page never says who is on a roster: whatever number
is typed, the answer is the same. The right code puts them on shift for this service (or off), by
the same use cases as the texts ON and OFF.

  * `IssueServiceCheckIn`: the lead makes a code; the old one stops working at once.
  * `ViewServiceCheckIn`: the page asks which service the code is for.
  * `SendCheckInCode`: a code is texted to a number on the roster, and to no other.
  * `ConfirmServiceCheckIn`: the code typed is checked, and the person goes on or off shift.

Only a keyed hash of the six digits is kept (in the cache, for ten minutes). Every limit counts all
numbers alike, so a limit never shows whether a number is on a roster. A cache that cannot be
reached refuses the request. Nothing here puts a token, a number or a code in a log or an audit
entry.
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.ports.outbound.cache import Cache
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.identity import PhoneHasher, normalise_uk_mobile
from overwatch.application.ports.outbound.ids import IdGenerator
from overwatch.application.ports.outbound.sealing import ContentSealer
from overwatch.application.ports.outbound.tokens import (
    LINK_TOKEN_SECRET,
    LinkTokenService,
    SecretStore,
)
from overwatch.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from overwatch.application.sealed_send import queue_message
from overwatch.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_tenant
from overwatch.application.use_cases.duty_roster import CheckIn, ShiftChange, SignOff
from overwatch.application.use_cases.lead_views import check_lead
from overwatch.application.use_cases.link_access import (
    LINK_CSRF_SECRET,
    CsrfRejected,
    csrf_token,
)
from overwatch.application.use_cases.pair_wall_screen import AttemptLimiter, normalise_code
from overwatch.domain.codes import Channel, Role
from overwatch.domain.errors import DomainError, NotAllowed, NotFound, ValidationFailed
from overwatch.domain.messages.catalogue import MessageId
from overwatch.domain.messages.templates import render
from overwatch.domain.rules.tokens import LinkCheck, check_link, hash_token, new_pairing_code

CHECKIN_PURPOSE: Final = "checkin"
TOKEN_LIFE: Final = timedelta(days=3650)
CODE_LIFE: Final = timedelta(minutes=10)
WINDOW: Final = timedelta(minutes=10)
REQUESTS_PER_ADDRESS: Final = 30
CODES_PER_NUMBER: Final = 3
WRONG_CODES_PER_NUMBER: Final = 5
ISSUE_ACTION: Final = "checkin-code-made"
REPLACED_KEY: Final = "replaced"
ON: Final = "on"
OFF: Final = "off"


class CheckInGone(DomainError):
    """The code is unknown, replaced, expired, or not for this host: one answer for all of them."""

    def __init__(self) -> None:
        super().__init__("gone")


class CheckInRateLimited(DomainError):
    """A limit was reached. Carries the seconds to wait."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate-limited")
        self.retry_after_seconds = retry_after_seconds


class CheckInCodeWrong(DomainError):
    """The code typed is not the one texted, or it has expired."""

    def __init__(self) -> None:
        super().__init__("code-wrong")


@dataclass(frozen=True, slots=True)
class CheckInPage:
    """What the page asks: the service, and the CSRF token its writes must send back."""

    service_name: str
    csrf_token: str


@dataclass(frozen=True, slots=True)
class CheckInOutcome:
    state: str  # "on-shift" or "off-shift"
    changes: tuple[ShiftChange, ...]


def _scope(uow: UnitOfWork) -> ScopeId:
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


async def _take(limiter: AttemptLimiter, name: str, limit: int) -> str:
    slot = await limiter.take(name, limit, WINDOW)
    if slot is None:
        raise CheckInRateLimited(int(WINDOW.total_seconds()))
    return slot


class IssueServiceCheckIn:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secrets: SecretStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._secrets = secrets

    async def execute(self, actor: Actor, service_id: str) -> str:
        """The token text, shown once. The code made before, if any, stops working."""
        check_lead(actor)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            if await uow.services.get(service_id) is None:
                raise NotFound("no service with this id")
            previous = await uow.link_tokens.open_for_about(CHECKIN_PURPOSE, service_id, now)
            if previous is not None:
                await uow.link_tokens.mark_used(previous.token_hash, now, REPLACED_KEY)
            token = await LinkTokenService(uow.link_tokens, self._secrets, self._clock).issue(
                CHECKIN_PURPOSE, service_id, None, now + TOKEN_LIFE
            )
            await uow.audit.append(
                AuditEntry(
                    action=ISSUE_ACTION,
                    use_case="IssueServiceCheckIn",
                    actor=actor,
                    entity_ids=(service_id,),
                    snapshot={"service_id": service_id, "replaced": previous is not None},
                    at=now,
                )
            )
            await uow.commit()
        return token


class _Checkin:
    """What the three public steps share: the limits, the token and the code."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secrets: SecretStore,
        cache: Cache,
        hasher: PhoneHasher,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._secrets = secrets
        self._cache = cache
        self._hasher = hasher
        self._limiter = AttemptLimiter(cache)

    async def _admit(self, client: str) -> None:
        await _take(self._limiter, f"checkin-req:{current_tenant()}:{client}", REQUESTS_PER_ADDRESS)

    async def _service_of(self, uow: UnitOfWork, token: str) -> str:
        """The service the code is for. A code that is unknown, replaced, expired or of another
        purpose is `CheckInGone`; the tenant is the bound one (the link statements are scoped)."""
        service = LinkTokenService(uow.link_tokens, self._secrets, self._clock)
        record = await service.resolve(token)
        if (
            record is None
            or record.purpose != CHECKIN_PURPOSE
            or check_link(record, self._clock.now()) is not LinkCheck.OK
        ):
            raise CheckInGone
        return record.about_id

    def _csrf_of(self, token: str) -> str:
        """The CSRF token of this code: a keyed hash of the token's own hash, as for a capacity
        link. A text that cannot be a token has none, and is the same refusal as a wrong one."""
        try:
            token_hash = hash_token(token, self._secrets.get(LINK_TOKEN_SECRET))
        except ValidationFailed:
            raise CsrfRejected from None
        return csrf_token(token_hash, self._secrets.get(LINK_CSRF_SECRET))

    def _check_csrf(self, token: str, given: str | None) -> None:
        if given is None or not hmac.compare_digest(self._csrf_of(token), given):
            raise CsrfRejected

    def _phone_hash(self, mobile: str) -> str:
        try:
            return self._hasher.hash(normalise_uk_mobile(mobile))
        except ValidationFailed:
            raise ValidationFailed("mobile", "must be a UK mobile number") from None

    def _otp_key(self, service_id: str, phone_hash: str) -> str:
        return f"checkin-otp:{current_tenant()}:{service_id}:{phone_hash}"

    def _code_hash(self, service_id: str, phone_hash: str, code: str) -> str:
        secret = self._secrets.get(LINK_TOKEN_SECRET)
        text = f"{current_tenant()}|{service_id}|{phone_hash}|{code}"
        return hmac.new(secret, text.encode("utf-8"), hashlib.sha256).hexdigest()


class ViewServiceCheckIn(_Checkin):
    async def execute(self, token: str, client: str) -> CheckInPage:
        """The service the code is for, and the CSRF token for the writes that follow."""
        await self._admit(client)
        async with self._uow_factory() as uow:
            service_id = await self._service_of(uow, token)
            profile = await uow.services.get(service_id)
            if profile is None or not profile.active:
                raise CheckInGone
            return CheckInPage(profile.name, self._csrf_of(token))


class SendCheckInCode(_Checkin):
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secrets: SecretStore,
        cache: Cache,
        hasher: PhoneHasher,
        ids: IdGenerator,
        sealer: ContentSealer,
    ) -> None:
        super().__init__(uow_factory, clock, secrets, cache, hasher)
        self._ids = ids
        self._sealer = sealer

    async def execute(self, token: str, mobile: str, client: str, csrf: str | None) -> None:
        """Text a code to this number if it is on the roster of the service. The answer is the same
        whether it is or not."""
        self._check_csrf(token, csrf)
        await self._admit(client)
        phone_hash = self._phone_hash(mobile)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            service_id = await self._service_of(uow, token)
            # Counted for every number alike, so the limit says nothing about the roster.
            await _take(
                self._limiter, f"checkin-code:{current_tenant()}:{phone_hash}", CODES_PER_NUMBER
            )
            roles = [
                role
                for role in await uow.people.roster_roles_for_phone_hash(phone_hash)
                if role.service_id == service_id
            ]
            profile = await uow.services.get(service_id)
            if not roles or profile is None or not profile.active:
                return
            code = new_pairing_code()
            await self._cache.set(
                self._otp_key(service_id, phone_hash),
                self._code_hash(service_id, phone_hash, code),
                CODE_LIFE,
            )
            role = min(roles, key=lambda item: item.id)
            await queue_message(
                uow,
                self._ids,
                self._sealer,
                scope=_scope(uow),
                rendered=render(MessageId.K1, Channel.TEXT, code=code),
                recipient_role_id=role.id,
                about_id=service_id,
                now=now,
            )
            await uow.commit()


class ConfirmServiceCheckIn(_Checkin):
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secrets: SecretStore,
        cache: Cache,
        hasher: PhoneHasher,
        check_in: CheckIn,
        sign_off: SignOff,
    ) -> None:
        super().__init__(uow_factory, clock, secrets, cache, hasher)
        self._check_in = check_in
        self._sign_off = sign_off

    async def execute(
        self,
        token: str,
        mobile: str,
        code: str,
        action: str,
        hours: int | None,
        client: str,
        csrf: str | None,
    ) -> CheckInOutcome:
        """Check the code and put the person on or off shift for this service."""
        self._check_csrf(token, csrf)
        if action not in (ON, OFF):
            raise ValidationFailed("action", "must be on or off")
        await self._admit(client)
        phone_hash = self._phone_hash(mobile)
        async with self._uow_factory() as uow:
            service_id = await self._service_of(uow, token)
            practitioner = await uow.people.find_by_phone_hash(phone_hash)
        attempt = await _take(
            self._limiter, f"checkin-wrong:{current_tenant()}:{phone_hash}", WRONG_CODES_PER_NUMBER
        )
        digits = normalise_code(code)
        key = self._otp_key(service_id, phone_hash)
        stored = await self._cache.get(key)
        if (
            practitioner is None
            or stored is None
            or digits is None
            or not hmac.compare_digest(stored, self._code_hash(service_id, phone_hash, digits))
        ):
            raise CheckInCodeWrong
        await self._cache.delete(key)
        await self._limiter.release(attempt)  # a right code gives its attempt back
        actor = Actor(
            role=Role.REPORTER,
            practitioner_id=practitioner.id,
            device_id=None,
            channel="link",
            service_ids=frozenset({service_id}),
            tenant_id=current_tenant(),
        )
        if action == OFF:
            ended = await self._sign_off.execute(phone_hash, actor, service_id=service_id)
            return CheckInOutcome("off-shift", tuple(ended))
        started = await self._check_in.execute(phone_hash, hours, actor, service_id=service_id)
        if not started:
            raise NotAllowed("this number is not on the roster of this service")
        return CheckInOutcome("on-shift", tuple(started))
