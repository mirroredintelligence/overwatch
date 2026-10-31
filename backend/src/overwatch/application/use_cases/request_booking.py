"""RequestBooking: an advisor asks one service to take the patient on an open case (U17).

The use case stores a booking Task in `requested` state, writes its audit entry and its outbound
request, and schedules the 5-minute phone prompt and the 10-minute expiry. It sends nothing itself:
the request is an outbox message that the sender delivers. Timers and wording come from D14 and
D16 (booking_rules, the B1 to B3 templates); the state comes from D13 (booking_state).

One unit of work holds the booking, its audit entry, its outbox messages, its timers, its link
token and the replay record (DEC-106). The board snapshot is read before that unit opens, because
QueryBoard opens its own unit and a unit may not be nested (DEC-146).
"""

import hashlib
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.sealed_send import queue_message
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.application.tenant_settings import read_policy, resolve_link_base
from diucs.application.use_cases.query_board import QueryBoard, QueryBoardQuery
from diucs.application.use_cases.send_prompts import LinkTokenServiceFactory
from diucs.application.use_cases.suspend_service import WordingFor
from diucs.application.work import WorkKind
from diucs.domain.codes import AgeBand, BookingStatus, Channel, Role, Urgency
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import BookingRequested
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import RenderedMessage, render
from diucs.domain.model.booking import Booking
from diucs.domain.model.case import Case
from diucs.domain.model.tenant import TenantWording
from diucs.domain.rules.booking_rules import (
    REFERENCE_ATTEMPTS,
    booking_reply_by,
    can_request,
    new_reference,
    phone_prompt_at,
)
from diucs.domain.rules.booking_state import is_open
from diucs.domain.rules.london_time import format_hhmm
from diucs.domain.rules.need_words import need_words

LinkBaseUrlFor = Callable[[ScopeId], str | Awaitable[str]]
"""Text or an awaitable of text (`resolve_link_base`): the serving process's source is async."""
"""The link base URL of a tenant (`https://<host>`), given the bound scope. The composition root
backs it with the tenant directory, which holds the host (the Tenant record has none; DEC-134
item 3)."""
BOOKING_PURPOSE: Final = "booking-request"
"""The link token purpose of a booking request (L01 names booking purposes by this prefix)."""
USE_CASE: Final = "RequestBooking"
AUDIT_ACTION: Final = "C"
REQUEST_LINK_PATH: Final = "/l/"
"""The booking page is `/l/<token>/booking` (L02); the request link opens it."""
URGENCY_WORDING: Final[dict[Urgency, str]] = {
    Urgency.WITHIN_2_HRS: "within 2 hrs",
    Urgency.TODAY: "today",
    Urgency.PLANNED: "planned",
}
_MESSAGE_FOR_CHANNEL: Final[dict[Channel, MessageId]] = {
    Channel.TEXT: MessageId.B1,
    Channel.EMAIL: MessageId.B2,
    Channel.PUSH: MessageId.B3,
}


@dataclass(frozen=True, slots=True)
class RequestBookingCommand:
    idempotency_key: str
    actor: Actor
    case_id: str
    service_id: str


@dataclass(frozen=True, slots=True)
class RequestBookingResult:
    booking_id: str
    reference: str
    reply_by: datetime
    phone_prompt_at: datetime


@dataclass(frozen=True, slots=True)
class _StoredBooking:
    """What the idempotency store keeps for a command key: the result and the command's fingerprint
    (DEC-104)."""

    fingerprint: str
    result: RequestBookingResult


def urgency_wording(urgency: Urgency) -> str:
    """The rule-book wording of an urgency, as the B1 to B2 templates take it."""
    return URGENCY_WORDING[urgency]


def need_text(case: Case) -> str:
    """The needs of the case in plain words (DEC-062 item 2): all of them, no code (DEC-1150)."""
    return need_words(case.needs)


def message_for_channel(channel: Channel) -> MessageId:
    """The request's wording for the reporter's channel: text B1, email B2, push B3."""
    return _MESSAGE_FOR_CHANNEL[channel]


def command_key(scope: ScopeId, key: str) -> str:
    """The replay key, named by the tenant. Replay statements are not tenant-scoped yet (lesson
    L160), so the tenant is part of the key."""
    return f"request-booking:{scope}:{key}"


def _fingerprint(command: RequestBookingCommand) -> str:
    body = repr(
        (
            command.case_id,
            command.service_id,
            command.actor.role.value,
            command.actor.practitioner_id,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _replay(stored: _StoredBooking, fingerprint: str) -> RequestBookingResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different booking")
    return stored.result


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


@dataclass(frozen=True, slots=True)
class _OpenCase:
    case: Case
    age_band: AgeBand
    urgency: Urgency


def _check_case(case: Case | None) -> _OpenCase:
    """The case must be open, with an age band, needs and an urgency (U17)."""
    if case is None:
        raise NotFound("no case with this id")
    if case.closed_at is not None:
        raise ValidationFailed("case", "must be open")
    if case.age_band is None or case.urgency is None or not case.needs:
        raise ValidationFailed("case", "must have an age band, needs and an urgency")
    return _OpenCase(case, case.age_band, case.urgency)


def _render_request(
    channel: Channel,
    *,
    reference: str,
    service_name: str,
    open_case: _OpenCase,
    link: str | None,
    reply_by: datetime,
    referral_system_name: str | None,
) -> RenderedMessage:
    """B1, B2 or B3 for the channel. The fields are the request's own: never the postcode.
    `referral_system_name` is the tenant's word for its referral system (TEN-022); B3 has none."""
    message = message_for_channel(channel)
    reply_by_text = format_hhmm(reply_by)
    if message is MessageId.B3:
        return render(
            message, channel, reference=reference, service=service_name, reply_by=reply_by_text
        )
    return render(
        message,
        channel,
        reference=reference,
        service=service_name,
        age_band=open_case.age_band.value,
        need=need_text(open_case.case),
        urgency=urgency_wording(open_case.urgency),
        link=link or "",
        reply_by=reply_by_text,
        referral_system_name=referral_system_name,
    )


class RequestBooking:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        link_tokens: LinkTokenServiceFactory,
        clock: Clock,
        ids: IdGenerator,
        rng: random.Random,
        query_board: QueryBoard,
        sealer: ContentSealer,
        wording_for: WordingFor,
        *,
        link_base_url_for: LinkBaseUrlFor,
    ) -> None:
        """`link_tokens` builds the link service over the unit's own repository. The link host of
        a tenant comes from its configuration, through `link_base_url_for` (DEC-134 item 3). The
        request is sealed with `sealer` and queued as the senders read it (DEC-305); the tenant's
        referral wording comes from `wording_for`, as SuspendService's does (TEN-022)."""
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._link_tokens = link_tokens
        self._clock = clock
        self._ids = ids
        self._rng = rng
        self._query_board = query_board
        self._sealer = sealer
        self._wording_for = wording_for
        self._link_base_url_for = link_base_url_for

    async def execute(self, command: RequestBookingCommand) -> RequestBookingResult:
        if command.actor.role not in (Role.ADVISOR, Role.CLINICAL):
            raise NotAllowed("only an advisor or a clinician may request a booking")
        if command.actor.practitioner_id is None:
            raise NotAllowed("a booking needs the requesting practitioner")
        fingerprint = _fingerprint(command)
        early = await self._idempotency.get(command_key(current_scope(), command.idempotency_key))
        if isinstance(early, _StoredBooking):
            return _replay(early, fingerprint)

        # The board snapshot of the service, read before the unit opens (DEC-146). A service that
        # is not active, or is another tenant's, is not on the board and is refused as not found.
        board = await self._query_board.execute(QueryBoardQuery(actor=command.actor))
        entry = next(
            (item for item in board.entries if item.service_id == command.service_id), None
        )
        if entry is None:
            raise NotFound("no active service with this id")
        now = self._clock.now()
        data_age_minutes = (
            None
            if entry.reported_at is None
            else int((now - entry.reported_at).total_seconds() // 60)
        )

        # The tenant's wording, read before the unit opens: the production source reads the tenant's
        # configuration through a unit of its own, and a unit cannot open inside another.
        wording = await self._wording_for(current_scope())

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = command_key(scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _StoredBooking):
                return _replay(stored, fingerprint)

            open_case = _check_case(await uow.cases.get(command.case_id))
            case = open_case.case
            profile = await uow.services.get(command.service_id)
            if profile is None or not profile.active:
                raise NotFound("no active service with this id")
            if not can_request([b.status for b in await uow.bookings.open_for_service(profile.id)]):
                raise Conflict("this service already has a booking request waiting for a reply")

            policy = await read_policy(uow)
            reporters = await uow.people.reporter_roles_for_service(profile.id, now)
            if not reporters:
                raise ValidationFailed("service", "has no reporter to send the request to")
            role = min(reporters, key=lambda candidate: candidate.id)
            channel = role.channel or Channel.TEXT
            reporter = await uow.people.get_practitioner(role.practitioner_id)
            if reporter is None:
                raise NotFound("the reporter of this service")

            referral_system_name = self._referral_system_name(wording, channel)

            reference = await self._free_reference(uow)
            reply_by = booking_reply_by(now, policy)
            phone_at = phone_prompt_at(now, policy)
            booking = Booking(
                id=self._ids.new_id(),
                reference=reference,
                service_id=profile.id,
                case_id=case.id,
                requester_id=command.actor.practitioner_id,
                status=BookingStatus.REQUESTED,
                requested_at=now,
                reply_by=reply_by,
                phone_prompt_at=phone_at,
            )

            link: str | None = None
            if channel is not Channel.PUSH:
                token = await self._link_tokens(uow.link_tokens).issue(
                    BOOKING_PURPOSE,
                    booking.id,
                    reporter.phone_hash if channel is Channel.TEXT else None,
                    reply_by,
                )
                link_base = await resolve_link_base(self._link_base_url_for, scope)
                link = f"{link_base}{REQUEST_LINK_PATH}{token}"

            rendered = _render_request(
                channel,
                reference=reference,
                service_name=profile.name,
                open_case=open_case,
                link=link,
                reply_by=reply_by,
                referral_system_name=referral_system_name,
            )
            request_message_id = await queue_message(
                uow,
                self._ids,
                self._sealer,
                scope=scope,
                rendered=rendered,
                recipient_role_id=role.id,
                about_id=profile.id,
                now=now,
                link=link,
            )
            # The booking keeps the id of the message that asked the service, so a read can say what
            # is known of its delivery (H-494).
            await uow.bookings.add(replace(booking, request_message_id=request_message_id))
            await uow.outbox.add(
                outbox_message_for(
                    BookingRequested(
                        booking_id=booking.id,
                        service_id=profile.id,
                        reference=reference,
                        at=now,
                    ),
                    id=self._ids.new_id(),
                    now=now,
                )
            )
            await schedule_work(
                uow,
                self._ids,
                kind=WorkKind.BOOKING_PHONE_PROMPT,
                about_id=booking.id,
                due_at=phone_at,
                now=now,
            )
            await schedule_work(
                uow,
                self._ids,
                kind=WorkKind.BOOKING_EXPIRE,
                about_id=booking.id,
                due_at=reply_by,
                now=now,
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=command.actor,
                    entity_ids=(booking.id, profile.id, case.id),
                    snapshot={
                        "service_id": profile.id,
                        "status": entry.status.value,
                        "effective_available": entry.effective_available,
                        "data_age_minutes": data_age_minutes,
                        "pending": entry.pending,
                    },
                    at=now,
                )
            )
            result = RequestBookingResult(
                booking_id=booking.id,
                reference=reference,
                reply_by=reply_by,
                phone_prompt_at=phone_at,
            )
            await uow.idempotency.put(key, _StoredBooking(fingerprint, result))
            await uow.commit()
        return result

    @staticmethod
    def _referral_system_name(wording: TenantWording | None, channel: Channel) -> str | None:
        """The tenant's word for its referral system, which B1 and B2 print. A tenant with no
        wording cannot be activated (H-T15), so none here is a configuration fault: the request is
        refused before anything is written. The push message names no system."""
        if message_for_channel(channel) is MessageId.B3:
            return None
        if wording is None:
            raise ValidationFailed("referral_system_name", "the tenant has set no wording")
        return wording.referral_system_name

    async def _free_reference(self, uow: UnitOfWork) -> str:
        """A four-digit reference that no open booking of this tenant holds (domain-rules 3.2,
        lesson L29). A reference that only closed bookings hold may be reused. The most recent
        booking with a candidate's reference is the only one that can still be open, so checking
        that one is enough."""
        taken: set[str] = set()
        for _ in range(REFERENCE_ATTEMPTS):
            candidate = new_reference(self._rng, taken)
            holder = await uow.bookings.get_by_reference(candidate)
            if holder is None or not is_open(holder.status):
                return candidate
            taken.add(candidate)
        raise Conflict("no free booking reference after repeated collisions")
