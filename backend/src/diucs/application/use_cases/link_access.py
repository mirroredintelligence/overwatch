"""Link access: look at, answer and renew a one-tap link (L01, DEC-167, domain-rules 7).

A link is a bearer token sent by text. It names one prompt and one phone, works once and expires
with the prompt's reply-by time. Three use cases serve it:

- `ViewLink` shows what is on record and writes nothing at all: no burn, no report, no audit entry.
- `RespondViaLink` records a confirm, a new number or "closed" through the same use cases as a text
  reply (`ConfirmCapacity`, `ReportCapacity`), so the report-flag rules (U07) and hazards H-31 and
  H-32 (a Y never makes an old figure current) apply to a link as they do to a text.
- `RenewLink` queues a fresh prompt (C1 or C2 with a new link) when a link has expired.

The tenant is bound by the edge before any of these runs, from the host through the tenant
directory (DEC-134 item 3), and the link-token statements are scoped to it: another tenant's link
is simply not found. Nothing here takes a tenant from a command. A link that is unknown, malformed,
another tenant's or for a purpose this page does not serve gets the same answer as an expired one
(`LinkGone("expired")`), so the answer says nothing about which links exist.

Single use is decided by the replay key, not by the burn. A link's command key is
`link:<tenant>:<token hash>`; the use cases store their result under it in the unit of work that
writes the figure, so a second, different answer to the same link is refused with `Conflict`
(answered as "used") and writes nothing, whichever request arrives first and however the two
interleave, and a link whose key is stored is read as used from then on. The token is burned after
the figure is stored (a use case opens its own unit of work and a second cannot be opened inside
it, DEC-146 item 4), so a failure between the two leaves the figure recorded and the link read as
used, never open for a second answer.

Rate limits are kept in the cache (nothing of record) and counted per tenant: every link request
spends one slot of the tenant's budget, a request that finds no link spends a slot of its
address's bad-attempt budget (a link that exists gives its slot back), and a renewal that queues a
text spends one of the tenant's few renewals. The CSRF token is the HMAC-SHA256 of the token hash,
keyed with the secret `link-csrf`, and is checked before anything is read.

No token, hash, value or address is logged or put in an error: the errors here carry a state word
and numbers from the service's own record, nothing from the request.
"""

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol
from zoneinfo import ZoneInfo

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_tenant
from diucs.application.use_cases.confirm_capacity import (
    ConfirmCapacityCommand,
    ConfirmCapacityResult,
)
from diucs.application.use_cases.handle_inbound_text import (
    figure_is_out_of_date,
    recorded_since_prompt,
)
from diucs.application.use_cases.pair_wall_screen import AttemptLimiter
from diucs.application.use_cases.report_capacity import (
    ReportCapacityCommand,
    ReportCapacityResult,
)
from diucs.application.use_cases.send_prompts import (
    LINK_PLACEHOLDER,
    LINK_PURPOSE,
    MESSAGES_TOPIC,
    SEND_MESSAGE,
    LinkTokenServiceFactory,
    _render,
    _send_payload,
    split_unit_label,
)
from diucs.domain.codes import ReportSource, ReportType, Role
from diucs.domain.errors import (
    ConfirmLimitReached,
    Conflict,
    DomainError,
    LatestReportChanged,
    NotAllowed,
    NotFound,
    NothingToConfirm,
    ValidationFailed,
)
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.model.people import PractitionerRole
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules.london_time import LONDON
from diucs.domain.rules.reply_parser import Confirm, Number
from diucs.domain.rules.reply_policy import (
    AskRecheck,
    Decision,
    NeedNumber,
    PromptState,
    RecordConfirm,
    RecordNumber,
    RejectConfirmLimit,
    decide_capacity_reply,
)
from diucs.domain.rules.schedule import next_due, reply_by
from diucs.domain.rules.tokens import LinkCheck, LinkTokenRecord, check_link, hash_token

LINK_CSRF_SECRET: Final = "link-csrf"
"""The name of the secret that keys the CSRF token."""

CAPACITY_PURPOSE: Final = LINK_PURPOSE
"""The purpose of the capacity link, as U03 and U06 store it: reply to this prompt, from this
phone. (The prompt text of L01 calls it `capacity-prompt`; the stored value is the one that is
issued, DEC-167.)"""

LINK_PROMPT_MESSAGES: Final = frozenset(
    message.value for message in (MessageId.C1, MessageId.C2, MessageId.C8)
)
"""The prompts that carry a link. The current prompt of a role, for a renewal, is the latest of
these."""

ACTIONS: Final = frozenset({"confirm", "number", "closed"})
BOOKING_ACTIONS: Final = frozenset({"decline", "withdraw", "not-reached"})
"""The answers of the booking links (L02). The shared gate only checks their shape; the booking
purpose checks the reason and the state (booking_links.py)."""
CLOSED_VALUE: Final = 0
MAX_VALUE: Final = 999

STATE_OK: Final = "ok"
STATE_EXPIRED: Final = "expired"
STATE_USED: Final = "used"

MAX_TOKEN_LENGTH: Final = 64
"""A link token is 23 letters (DEC-154), or 22 characters of base64url for a link sent before
that; nothing longer than this can be one, so it is refused before it is hashed."""

# Rate limits ([ASSUMED], domain-rules 7). A tenant has tens of services and a few reporters each,
# so a busy minute is a few dozen taps; the budgets are well above that and well below a flood.
REQUEST_WINDOW: Final = timedelta(minutes=1)
REQUESTS_PER_WINDOW: Final = 60
"""Link requests of any kind that one tenant may make in REQUEST_WINDOW."""
BAD_ATTEMPT_WINDOW: Final = timedelta(minutes=10)
BAD_ATTEMPTS_PER_ADDRESS: Final = 20
"""Requests from one address in BAD_ATTEMPT_WINDOW that find no link (or fail the CSRF check)."""
RENEW_WINDOW: Final = timedelta(minutes=10)
RENEWALS_PER_WINDOW: Final = 20
"""New links one tenant may have texted in RENEW_WINDOW. Each one is a real text."""

_AUDIT_ACTION: Final = "C"
_RENEW_USE_CASE: Final = "RenewLink"
_LINK_CHANNEL: Final = "link"

type Body = Mapping[str, object]
"""The JSON body of a link page: text, whole numbers and None."""


@dataclass(frozen=True, slots=True)
class ClosedDetail:
    """What a closed link may say beyond its state word, for a link that exists in the bound tenant
    (KI-169, KI-648, KI-649, KI-664, KI-665). An unknown link, another tenant's link and a malformed
    one carry none, so the page says nothing about which links exist. `booking` marks a booking
    link, whose page shows the coordination number; the number is the tenant's own setting and is
    never a default (H-486, H-488)."""

    closed_at: datetime | None = None
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None
    coordination_phone: str | None = None
    booking: bool = False
    reference: str | None = None
    """The booking reference, so a service can match the page to a booking it has (H-499)."""


class LinkGone(DomainError):
    """The link cannot be used: `state` is `expired` (unknown, malformed, another tenant's, for
    another purpose, or past its reply-by time) or `used`. A link that exists also says when it
    closed (`detail`); an unknown one carries nothing else."""

    def __init__(self, state: str, detail: ClosedDetail | None = None) -> None:
        super().__init__(state)
        self.state = state
        self.detail = detail


class CsrfRejected(DomainError):
    """The CSRF token is missing or wrong. Nothing was read or written."""


class LinkConflict(DomainError):
    """The booking a link is for is no longer open for this answer (L02): `state` is its state word
    (expired, cancelled, declined, ...), and the page answers 409 with that word and, for a link
    that exists, when it closed (`detail`)."""

    def __init__(self, state: str, detail: ClosedDetail | None = None) -> None:
        super().__init__(state)
        self.state = state
        self.detail = detail


class LinkOutOfRange(DomainError):
    """The figure is outside the service's usual range and was not confirmed. Carries the range."""

    def __init__(self, usual_min: int, usual_max: int) -> None:
        super().__init__("out-of-range")
        self.usual_min = usual_min
        self.usual_max = usual_max


class SendTheNumber(DomainError):
    """A Y cannot be used, so the reporter must send the number: there is no figure to confirm
    (`no-figure`), the last two answers were Ys (`limit`), the figure was out of date when the
    prompt named it or a number has been reported since (`stale`, hazards H-31 and H-32), or a
    report landed while this one was being judged (`changed`). Nothing was recorded and the link is
    still open."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class LinkRateLimited(DomainError):
    """A rate limit was reached. Carries the seconds to wait."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate-limited")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class LinkAction:
    """What the reporter pressed: `confirm`, `number` with a value, or `closed` (the value 0)."""

    action: str
    value: int | None = None
    confirm_out_of_range: bool = False
    reason: str | None = None
    """The reason a booking answer gives (L02): a decline, a withdrawal or a not-reached reason."""


@dataclass(frozen=True, slots=True)
class ViewLinkQuery:
    token: str
    client: str
    """An opaque stable string for the caller's address, used only to count bad attempts. It is
    hashed before it reaches the cache."""


@dataclass(frozen=True, slots=True)
class RespondViaLinkCommand:
    token: str
    csrf_token: str | None
    action: LinkAction
    client: str


@dataclass(frozen=True, slots=True)
class RenewLinkCommand:
    token: str
    client: str
    link_base_url: str
    """Where a new link points: the tenant's own host, which the edge took from the verified host
    (DEC-134 item 3). It is never read from the request body."""


@dataclass(frozen=True, slots=True)
class LinkView:
    purpose: str
    body: Body
    """The page: `state`, `purpose`, the purpose's own fields, and `csrfToken`."""


@dataclass(frozen=True, slots=True)
class LinkResponse:
    body: Body


@dataclass(frozen=True, slots=True)
class LinkRequest:
    """A link found in the bound tenant, for a purpose this page serves, at `now`."""

    record: LinkTokenRecord
    token: str
    scope: ScopeId
    now: datetime


class LinkPurposeHandler(Protocol):
    """What one purpose of link does. L02 adds `booking-request` by registering another."""

    async def view(self, link: LinkRequest) -> Body: ...

    async def respond(self, link: LinkRequest, action: LinkAction) -> Body: ...

    async def renew(self, link: LinkRequest, link_base_url: str) -> bool:
        """Queue a fresh prompt for an expired link. True when one was queued."""
        ...

    async def closed(self, link: LinkRequest, state: str) -> ClosedDetail | None:
        """What the page of this closed link says about when and how it closed (`state` is
        `expired` or `used`), or None when it says nothing more."""
        ...


type LinkPurposes = Mapping[str, LinkPurposeHandler]


@dataclass(frozen=True, slots=True)
class _Renewed:
    """What the replay store keeps for a renewal: the new prompt. Written in the unit of work that
    queues it, so a second renewal of the same link does nothing."""

    communication_id: str


def csrf_token(token_hash: str, secret: bytes) -> str:
    """The CSRF token of a link: HMAC-SHA256 of its token hash, in hex, keyed with `link-csrf`."""
    return hmac.new(secret, token_hash.encode("ascii"), hashlib.sha256).hexdigest()


def iso_utc(moment: datetime | None) -> str | None:
    """An instant as ISO 8601 UTC with a Z, whole seconds (times are UTC in the page body)."""
    if moment is None:
        return None
    return moment.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_due_iso(
    profile: ServiceProfile, now: datetime, policy: TenantPolicy, zone: ZoneInfo
) -> str | None:
    """The next prompt of the service after `now`, as the page shows it: in the tenant's zone and
    under the tenant's policy (TEN-041), written in UTC. None when the service has none."""
    return iso_utc(next_due(profile, now, policy, zone))


def closed_body(state: str, detail: ClosedDetail | None) -> dict[str, object]:
    """The JSON of a closed link (410) or a refused answer (409): the state word, and for a link
    that exists, when it closed, when it was confirmed or cancelled, and the coordination number.
    Only what is known is there, and nothing else: no id, no name, no tenant."""
    body: dict[str, object] = {"state": state}
    if detail is None:
        return body
    if detail.booking:
        body["kind"] = "booking"
    if detail.reference is not None:
        body["reference"] = detail.reference
    for name, moment in (
        ("closedAt", detail.closed_at),
        ("confirmedAt", detail.confirmed_at),
        ("cancelledAt", detail.cancelled_at),
    ):
        if moment is not None:
            body[name] = iso_utc(moment)
    if detail.coordination_phone is not None:
        body["coordinationPhone"] = detail.coordination_phone
    return body


def command_key(scope: ScopeId, record: LinkTokenRecord) -> str:
    """The replay key of the one answer a link may have. The tenant is part of it, so two tenants
    can never share a key (the replay statements are not tenant-scoped yet, L160)."""
    return f"link:{scope}:{record.token_hash}"


def _renew_key(scope: ScopeId, record: LinkTokenRecord) -> str:
    return f"renew:{scope}:{record.token_hash}"


def _limit_key(kind: str, tenant: str, part: str) -> str:
    """The one place a rate-limit key is built, so the tenant is part of every key."""
    return f"diucs:linkpage:{tenant}:{kind}:{part}"


def _gone() -> LinkGone:
    return LinkGone(STATE_EXPIRED)


def _tenant_scope(uow: UnitOfWork) -> ScopeId:
    """The tenant this unit of work is bound to. Nothing bound, or a network scope, is a missing
    binding: a link belongs to one tenant, and the edge must have bound it."""
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def _token_hash(token: str, secrets: SecretStore) -> str | None:
    """The keyed hash of a token, or None for text that cannot be a token (too long, or not URL-safe
    text): such a link is treated as an unknown one."""
    if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
        return None
    try:
        return hash_token(token, secrets.get(LINK_TOKEN_SECRET))
    except ValidationFailed as error:
        if error.field == "token":
            return None
        raise


class _Gate:
    """What every link request goes through, in order: the rate limits, then the token."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secrets: SecretStore,
        cache: Cache,
        link_tokens: LinkTokenServiceFactory,
        purposes: LinkPurposes,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._secrets = secrets
        self._limiter = AttemptLimiter(cache)
        self._link_tokens = link_tokens
        self._purposes = purposes

    async def admit(self, client: str) -> str:
        """Spend a slot of the tenant's budget and one of the address's bad-attempt budget, and
        return the second slot, which `find` gives back when the link is found. A budget that is
        used up refuses the request (`LinkRateLimited`) before anything is read."""
        tenant = current_tenant()
        budget = await self._limiter.take(
            _limit_key("requests", tenant, "all"), REQUESTS_PER_WINDOW, REQUEST_WINDOW
        )
        if budget is None:
            raise LinkRateLimited(int(REQUEST_WINDOW.total_seconds()))
        address = hashlib.sha256(client.encode("utf-8")).hexdigest()[:32]
        slot = await self._limiter.take(
            _limit_key("bad", tenant, address), BAD_ATTEMPTS_PER_ADDRESS, BAD_ATTEMPT_WINDOW
        )
        if slot is None:
            raise LinkRateLimited(int(BAD_ATTEMPT_WINDOW.total_seconds()))
        return slot

    def check_csrf(self, token: str, given: str | None) -> None:
        """CsrfRejected unless `given` is the CSRF token of this link. Decided from the token text
        alone, before any read, so a wrong token and a right one that is unknown or used cannot be
        told apart by it."""
        token_hash = _token_hash(token, self._secrets)
        if token_hash is None or not isinstance(given, str):
            raise CsrfRejected
        expected = csrf_token(token_hash, self._secrets.get(LINK_CSRF_SECRET))
        if not hmac.compare_digest(expected.encode("ascii"), given.encode("utf-8")):
            raise CsrfRejected

    def csrf_of(self, record: LinkTokenRecord) -> str:
        return csrf_token(record.token_hash, self._secrets.get(LINK_CSRF_SECRET))

    async def find(self, token: str, slot: str) -> tuple[LinkRequest, LinkCheck]:
        """The link in the bound tenant, and what `check_link` says of it (a link whose answer key
        is stored is used, whatever the token says). A link that is not there (unknown, malformed,
        another tenant's, or a purpose this page does not serve) is `LinkGone("expired")` and keeps
        the bad-attempt slot; a link that is there gives the slot back, whatever its state."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow)
            record = await self._link_tokens(uow.link_tokens).resolve(token)
            answered = (
                record is not None
                and await uow.idempotency.get(command_key(scope, record)) is not None
            )
        if record is None or record.purpose not in self._purposes:
            raise _gone()
        await self._limiter.release(slot)
        state = LinkCheck.USED if answered else check_link(record, now)
        return LinkRequest(record=record, token=token, scope=scope, now=now), state

    async def open(self, token: str, slot: str) -> LinkRequest:
        """The link, open at this moment. `LinkGone` with `used` or `expired` otherwise."""
        link, state = await self.find(token, slot)
        if state is LinkCheck.USED:
            raise LinkGone(
                STATE_USED, await self._purposes[link.record.purpose].closed(link, STATE_USED)
            )
        if state is LinkCheck.EXPIRED:
            raise LinkGone(
                STATE_EXPIRED, await self._purposes[link.record.purpose].closed(link, STATE_EXPIRED)
            )
        return link


class ViewLink:
    """GET /links/{token}: show the link, change nothing."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secrets: SecretStore,
        cache: Cache,
        link_tokens: LinkTokenServiceFactory,
        purposes: LinkPurposes,
    ) -> None:
        self._gate = _Gate(uow_factory, clock, secrets, cache, link_tokens, purposes)
        self._purposes = purposes

    async def execute(self, query: ViewLinkQuery) -> LinkView:
        slot = await self._gate.admit(query.client)
        link = await self._gate.open(query.token, slot)
        page = await self._purposes[link.record.purpose].view(link)
        return LinkView(
            purpose=link.record.purpose,
            body={
                "state": STATE_OK,
                "purpose": link.record.purpose,
                **page,
                "csrfToken": self._gate.csrf_of(link.record),
            },
        )


class RespondViaLink:
    """POST /links/{token}: record the answer through the purpose's use cases."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secrets: SecretStore,
        cache: Cache,
        link_tokens: LinkTokenServiceFactory,
        purposes: LinkPurposes,
    ) -> None:
        self._gate = _Gate(uow_factory, clock, secrets, cache, link_tokens, purposes)
        self._purposes = purposes

    async def execute(self, command: RespondViaLinkCommand) -> LinkResponse:
        check_action(command.action)
        slot = await self._gate.admit(command.client)
        self._gate.check_csrf(command.token, command.csrf_token)
        link = await self._gate.open(command.token, slot)
        body = await self._purposes[link.record.purpose].respond(link, command.action)
        return LinkResponse(body=body)


class RenewLink:
    """POST /links/{token}/renew: queue a fresh prompt when this link's window has closed. Says
    nothing about whether it did."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secrets: SecretStore,
        cache: Cache,
        link_tokens: LinkTokenServiceFactory,
        purposes: LinkPurposes,
    ) -> None:
        self._gate = _Gate(uow_factory, clock, secrets, cache, link_tokens, purposes)
        self._limiter = AttemptLimiter(cache)
        self._purposes = purposes

    async def execute(self, command: RenewLinkCommand) -> None:
        slot = await self._gate.admit(command.client)
        try:
            link, state = await self._gate.find(command.token, slot)
        except LinkGone:
            return
        if state is not LinkCheck.EXPIRED:
            return
        renewal = await self._limiter.take(
            _limit_key("renewals", current_tenant(), "all"), RENEWALS_PER_WINDOW, RENEW_WINDOW
        )
        if renewal is None:
            raise LinkRateLimited(int(RENEW_WINDOW.total_seconds()))
        queued = await self._purposes[link.record.purpose].renew(link, command.link_base_url)
        if not queued:
            await self._limiter.release(renewal)  # nothing was texted, so nothing is spent


def check_action(action: LinkAction) -> None:
    """The shape of the answer, before anything is read: an action the page knows, a figure only
    for `number`, a whole number from 0 to 999, and `confirmOutOfRange` only where a figure is
    sent. Field names only in the refusals."""
    if action.action in BOOKING_ACTIONS:
        if action.value is not None or action.confirm_out_of_range:
            raise ValidationFailed("value", "a booking answer takes no figure")
        return
    if action.action not in ACTIONS:
        raise ValidationFailed("action", "is not one of confirm, number, closed")
    if action.reason is not None:
        raise ValidationFailed("reason", "is not a field of this link")
    if action.action == "number":
        value = action.value
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationFailed("value", "must be a whole number")
        if not 0 <= value <= MAX_VALUE:
            raise ValidationFailed("value", "must be from 0 to 999")
    elif action.value is not None:
        raise ValidationFailed("value", "is only sent with the number action")
    if not isinstance(action.confirm_out_of_range, bool):
        raise ValidationFailed("confirmOutOfRange", "must be true or false")
    if action.action == "confirm" and action.confirm_out_of_range:
        raise ValidationFailed("confirmOutOfRange", "only a number can be confirmed out of range")


class _Reports(Protocol):
    async def execute(self, command: ReportCapacityCommand) -> ReportCapacityResult: ...


class _Confirms(Protocol):
    async def execute(self, command: ConfirmCapacityCommand) -> ConfirmCapacityResult: ...


@dataclass(frozen=True, slots=True)
class _Target:
    """What a capacity link is about: the prompt it was sent with, the service, the role the phone
    holds and the person who holds it."""

    prompt: Communication
    profile: ServiceProfile
    role: PractitionerRole
    practitioner_id: str


def figure_of(action: LinkAction) -> int:
    """The figure an action sends: the number, or 0 for `closed`."""
    return CLOSED_VALUE if action.action == "closed" else int(action.value or 0)


def prompt_state(
    link: LinkRequest,
    profile: ServiceProfile,
    latest: CapacityReport | None,
    trailing: int,
    action: LinkAction,
) -> PromptState:
    """The reply policy's view of this link as a prompt: it is open until the link expires, and a
    figure sent with `confirmOutOfRange` is the second sending of it."""
    second = action.action != "confirm" and action.confirm_out_of_range
    return PromptState(
        service_id=profile.id,
        reply_by=link.record.expires_at,
        recorded_value=None if latest is None else latest.value,
        consecutive_confirms=trailing,
        last_accepted_at=None if latest is None else latest.effective_at,
        last_accepted_value=None if latest is None else latest.value,
        pending_out_of_range=figure_of(action) if second else None,
        usual_range=profile.usual_range,
    )


def judge(
    decision: Decision,
    profile: ServiceProfile,
    latest: CapacityReport | None,
    prompt_sent_at: datetime,
    number_since_prompt: bool,
) -> RecordNumber | RecordConfirm:
    """What the reply policy and the hazards allow, or the refusal. A Y is also refused when the
    figure was older than its window when the prompt named it (H-31) or a number has been written
    since the prompt (H-32), as for a Y by text (DEC-148 items 2, 17 and 20)."""
    match decision:
        case AskRecheck():
            raise LinkOutOfRange(*profile.usual_range)
        case NeedNumber():
            raise SendTheNumber("no-figure")
        case RejectConfirmLimit():
            raise SendTheNumber("limit")
        case RecordConfirm():
            if (
                latest is None
                or figure_is_out_of_date(latest.effective_at, prompt_sent_at)
                or number_since_prompt
            ):
                raise SendTheNumber("stale")
            return decision
        case RecordNumber():
            return decision
        case _:
            # A late answer. The link expires with the prompt, so none can reach here; it is
            # refused as an expired link all the same.
            raise _gone()


async def number_after_prompt(
    uow: UnitOfWork, service_id: str, latest: CapacityReport, prompt_sent_at: datetime
) -> bool:
    """True when a number was written for the service since the prompt was sent (hazard H-32): the
    record order, not the effective time, as for a Y by text (DEC-148 item 20)."""
    since = await uow.capacity.reports_since(service_id, prompt_sent_at)
    return any(
        report.report_type is ReportType.NUMBER and recorded_since_prompt(report, prompt_sent_at)
        for report in [*since, latest]
    )


class CapacityLinkHandler:
    """The capacity-reply purpose: report, confirm or renew for one prompt of one service."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        link_tokens: LinkTokenServiceFactory,
        sealer: ContentSealer,
        reports: _Reports,
        confirms: _Confirms,
        *,
        zone: ZoneInfo = LONDON,
    ) -> None:
        """`zone` is the tenant's time zone, read by the route from the host's tenant record
        (TEN-041). The default is the one zone the allow-list holds today (DEC-353): a caller that
        knows no tenant, a test rig, gets London's."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._link_tokens = link_tokens
        self._sealer = sealer
        self._reports = reports
        self._confirms = confirms
        self._zone = zone

    @staticmethod
    async def _target(uow: UnitOfWork, link: LinkRequest) -> _Target:
        """The prompt, service, role and person the link names, or `LinkGone("expired")` when any
        of them is gone: a service that is no longer active, a phone that no longer holds the
        role, a phone two people hold. A link for a post nobody holds any more is a dead link."""
        record = link.record
        prompt = await uow.communications.get(record.about_id)
        if (
            prompt is None
            or prompt.about_id is None
            or prompt.recipient_role_id is None
            or record.phone_hash is None
        ):
            raise _gone()
        profile = await uow.services.get(prompt.about_id)
        if profile is None or not profile.active:
            raise _gone()
        try:
            practitioner = await uow.people.find_by_phone_hash(record.phone_hash)
        except Conflict:
            raise _gone() from None
        held = await uow.people.services_for_phone_hash(record.phone_hash, link.now)
        role = next(
            (
                role
                for role, _ in held
                if role.id == prompt.recipient_role_id and role.service_id == profile.id
            ),
            None,
        )
        if practitioner is None or role is None:
            raise _gone()
        return _Target(prompt, profile, role, practitioner.id)

    async def view(self, link: LinkRequest) -> Body:
        async with self._uow_factory() as uow:
            target = await self._target(uow, link)
            latest = await uow.capacity.latest(target.profile.id)
            config = await uow.tenant_config.current_version()
        policy = DEFAULT_POLICY if config is None else config.policy
        profile = target.profile
        return {
            "serviceName": profile.name,
            "unitLabel": profile.unit_label,
            "recordedValue": None if latest is None else latest.value,
            "asOf": None if latest is None else iso_utc(latest.effective_at),
            "usualMin": profile.usual_range[0],
            "usualMax": profile.usual_range[1],
            "replyBy": iso_utc(link.record.expires_at),
            "nextDue": next_due_iso(profile, link.now, policy, self._zone),
        }

    async def respond(self, link: LinkRequest, action: LinkAction) -> Body:
        if action.action not in ACTIONS:
            raise ValidationFailed("action", "is not one of confirm, number, closed")
        async with self._uow_factory() as uow:
            target = await self._target(uow, link)
            profile = target.profile
            latest = await uow.capacity.latest(profile.id)
            trailing = await uow.capacity.trailing_confirmations(profile.id)
            since = (
                action.action == "confirm"
                and latest is not None
                and await number_after_prompt(uow, profile.id, latest, target.prompt.sent_at)
            )
        reply = Confirm() if action.action == "confirm" else Number(figure_of(action))
        decision = judge(
            decide_capacity_reply(
                reply, prompt_state(link, profile, latest, trailing, action), link.now
            ),
            profile,
            latest,
            target.prompt.sent_at,
            since,
        )
        key = command_key(link.scope, link.record)
        result = await self._write(target, key, decision, latest)
        async with self._uow_factory() as uow:
            await self._link_tokens(uow.link_tokens).burn(link.token, key)
            await uow.commit()
        async with self._uow_factory() as uow:
            report = await uow.capacity.get(result.report_id)
        if report is None:
            raise RuntimeError("the report that was just stored cannot be read")
        return {
            "serviceName": profile.name,
            "value": report.value,
            "unitLabel": profile.unit_label,
            "recordedAt": iso_utc(report.effective_at),
            "nextDue": iso_utc(result.next_due),
        }

    async def _write(
        self,
        target: _Target,
        key: str,
        decision: RecordNumber | RecordConfirm,
        latest: CapacityReport | None,
    ) -> ReportCapacityResult | ConfirmCapacityResult:
        """Record the answer through ReportCapacity or ConfirmCapacity under the link's key."""
        actor = Actor(
            role=Role.REPORTER,
            practitioner_id=target.practitioner_id,
            device_id=None,
            channel=_LINK_CHANNEL,
            service_ids=frozenset({target.profile.id}),
            tenant_id=current_tenant(),
        )
        try:
            if isinstance(decision, RecordNumber):
                return await self._reports.execute(
                    ReportCapacityCommand(
                        idempotency_key=key,
                        actor=actor,
                        service_id=target.profile.id,
                        value=decision.value,
                        source=ReportSource.LINK,
                        performer_role_id=target.role.id,
                        replaced_value=(
                            latest.value if decision.is_correction and latest is not None else None
                        ),
                        flag=decision.flag,
                    )
                )
            return await self._confirms.execute(
                ConfirmCapacityCommand(
                    idempotency_key=key,
                    actor=actor,
                    service_id=target.profile.id,
                    source=ReportSource.LINK,
                    performer_role_id=target.role.id,
                    expected_latest_id=None if latest is None else latest.id,
                )
            )
        except LatestReportChanged:
            raise SendTheNumber("changed") from None
        except ConfirmLimitReached:
            raise SendTheNumber("limit") from None
        except NothingToConfirm:
            raise SendTheNumber("no-figure") from None
        except NotFound, NotAllowed:
            raise _gone() from None
        except Conflict:
            # The key holds another answer: this link has been answered.
            raise LinkGone(STATE_USED) from None

    async def closed(self, link: LinkRequest, state: str) -> ClosedDetail | None:
        """A closed prompt link says nothing beyond its state word: an expired one must answer as an
        unknown one does (L01, DEC-167), so the page cannot tell a person which links exist
        (DEC-1151). A booking link says more (booking_links.py), because its holder is told by the
        state word anyway and needs the coordination number."""
        return None

    async def renew(self, link: LinkRequest, link_base_url: str) -> bool:
        now = self._clock.now()
        key = _renew_key(link.scope, link.record)
        async with self._uow_factory() as uow:
            try:
                target = await self._target(uow, link)
            except LinkGone:
                return False
            profile = target.profile
            current = await uow.communications.latest_prompt_for_phone(
                {target.role.id}, LINK_PROMPT_MESSAGES
            )
            suspended = any(
                flag.code == SERVICE_FLAG_SUSPENDED
                for flag in await uow.flags.service_flags(profile.id)
            )
            latest = await uow.capacity.latest(profile.id)
            window = split_unit_label(profile.unit_label)
            if (
                current is None
                or current.id != target.prompt.id  # a later prompt has been sent: use that link
                or suspended
                or (latest is None and not window[1])  # nothing can be worded for it
                or await uow.idempotency.get(key) is not None  # renewed already
            ):
                return False
            reply = reply_by(now)
            communication_id = self._ids.new_id()
            token = await self._link_tokens(uow.link_tokens).issue(
                CAPACITY_PURPOSE, communication_id, link.record.phone_hash, reply
            )
            url = f"{link_base_url.rstrip('/')}/{token}"
            message_id, rendered = _render(profile, latest, window, url, reply, zone=self._zone)
            await uow.communications.add(
                Communication(
                    id=communication_id,
                    message_id=message_id.value,
                    channel=profile.channel,
                    recipient_role_id=target.role.id,
                    about_id=profile.id,
                    payload_text=rendered.text.replace(url, LINK_PLACEHOLDER),
                    sent_at=now,
                    delivery_status="queued",
                )
            )
            outbox_id = self._ids.new_id()
            await uow.outbox.add(
                OutboxMessage(
                    id=outbox_id,
                    topic=MESSAGES_TOPIC,
                    event_type=SEND_MESSAGE,
                    payload=_send_payload(
                        outbox_id,
                        communication_id,
                        message_id,
                        target.role,
                        rendered,
                        self._sealer,
                        str(link.scope),
                    ),
                    created_at=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=_AUDIT_ACTION,
                    use_case=_RENEW_USE_CASE,
                    actor=Actor(
                        role=Role.REPORTER,
                        practitioner_id=target.practitioner_id,
                        device_id=None,
                        channel=_LINK_CHANNEL,
                        service_ids=frozenset({profile.id}),
                        tenant_id=_tenant_scope(uow).value,
                    ),
                    entity_ids=(communication_id, profile.id),
                    snapshot={"message_id": message_id.value},
                    at=now,
                )
            )
            await uow.idempotency.put(key, _Renewed(communication_id))
            await uow.commit()
        return True


class UnitOfWorkIdempotency:
    """The idempotency store of a use case's early replay check, on the application's own unit of
    work, so an inbound adapter needs no outbound adapter. The authoritative check and the write
    of the key are inside the use case's unit of work."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, key: str) -> object | None:
        async with self._uow_factory() as uow:
            return await uow.idempotency.get(key)

    async def put(self, key: str, result: object) -> None:
        async with self._uow_factory() as uow:
            await uow.idempotency.put(key, result)
            await uow.commit()
