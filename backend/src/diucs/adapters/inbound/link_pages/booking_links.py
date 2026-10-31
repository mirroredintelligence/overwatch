"""Booking links (L02, DEC-167 for the link API): the request link a service opens, and the change
link it is given on confirming.

A request link (purpose `booking-request`, stored by RequestBooking) shows the booking and takes a
confirm or a decline with its reason. A confirmation gives back a change link (purpose
`booking-change`, 24 hours [ASSUMED], tied to the same booking and phone), which takes a
withdrawal or a not-reached report once the booking is confirmed.

Both purposes resolve the booking and the phone through the tenant the edge bound: the link's
booking must be held by a reporter of its service, or the link is expired (L01's shape). The
answers run the use cases (RespondToBooking, WithdrawBooking, ReportNotReached), which check the
booking's state and the actor again. Each answer is single use: the link is burned under its key.
"""

from collections.abc import Callable, Iterable
from datetime import timedelta
from typing import Any, Final, Literal

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import current_tenant
from diucs.application.use_cases.link_access import (
    Body,
    ClosedDetail,
    LinkAction,
    LinkConflict,
    LinkGone,
    LinkPurposeHandler,
    LinkRequest,
    command_key,
    iso_utc,
)
from diucs.application.use_cases.request_booking import need_text, urgency_wording
from diucs.application.use_cases.respond_to_booking import (
    ChangeLinkRequest,
    RespondToBooking,
    RespondToBookingCommand,
)
from diucs.application.use_cases.withdraw_booking import (
    ReportNotReached,
    ReportNotReachedCommand,
    WithdrawBooking,
    WithdrawBookingCommand,
)
from diucs.domain.codes import (
    BookingStatus,
    DeclineReason,
    NotReachedReason,
    ReportSource,
    Role,
    WithdrawReason,
)
from diucs.domain.errors import Conflict, InvalidTransition, ValidationFailed
from diucs.domain.model.booking import Booking
from diucs.domain.model.case import Case
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant import ContactKind

REQUEST_PURPOSE: Final = "booking-request"
CHANGE_PURPOSE: Final = "booking-change"
CHANGE_TOKEN_LIFETIME: Final = timedelta(hours=24)  # [ASSUMED] L02 prompt
CONFIRM: Final = "confirm"
DECLINE: Final = "decline"
WITHDRAW: Final = "withdraw"
NOT_REACHED: Final = "not-reached"
_GONE_STATES: Final[dict[BookingStatus, str]] = {
    BookingStatus.EXPIRED: "expired",
    BookingStatus.CANCELLED_BEFORE: "cancelled",
    BookingStatus.CANCELLED_AFTER: "cancelled",
    BookingStatus.DECLINED: "declined",
    BookingStatus.WITHDRAWN: "withdrawn",
    BookingStatus.NOT_REACHED: "not-reached",
}


def check_request_action(action: LinkAction) -> DeclineReason | None:
    """A confirmation takes no reason and no figure; a decline takes a decline reason or none."""
    if action.action == CONFIRM:
        if action.reason is not None:
            raise ValidationFailed("reason", "only a decline has a reason")
        return None
    if action.action != DECLINE:
        raise ValidationFailed("action", "is not one of confirm, decline")
    if action.reason is None:
        return None
    try:
        return DeclineReason(action.reason)
    except ValueError:
        raise ValidationFailed("reason", "is not a decline reason") from None


def check_change_action(action: LinkAction) -> WithdrawReason | NotReachedReason:
    """A withdrawal takes a withdraw reason, a not-reached report a not-reached reason; each is
    required."""
    if action.action == WITHDRAW:
        enum_cls: type[WithdrawReason] | type[NotReachedReason] = WithdrawReason
    elif action.action == NOT_REACHED:
        enum_cls = NotReachedReason
    else:
        raise ValidationFailed("action", "is not one of withdraw, not-reached")
    if action.reason is None:
        raise ValidationFailed("reason", "is required")
    try:
        return enum_cls(action.reason)
    except ValueError:
        raise ValidationFailed("reason", "is not a reason of this action") from None


def gone_state(status: BookingStatus) -> str:
    """The state word a closed booking shows on its link (L01's `state`); a request that was
    confirmed and is already answered shows `used`."""
    return _GONE_STATES.get(status, "used")


_CANCELLED: Final = frozenset({BookingStatus.CANCELLED_BEFORE, BookingStatus.CANCELLED_AFTER})


def closed_detail(booking: Booking, phone: str | None) -> ClosedDetail:
    """What a closed booking link says: when it closed (the time of its last move, or its reply-by
    time when no move was recorded, as for a request whose window has passed), when it was confirmed
    and when it was cancelled, and the tenant's coordination number (KI-169, KI-648, KI-649, KI-664,
    KI-665; H-486, H-488, H-499)."""
    closed_at = booking.responded_at or booking.reply_by
    return ClosedDetail(
        closed_at=closed_at,
        confirmed_at=booking.confirmed_at,
        cancelled_at=closed_at if booking.status in _CANCELLED else None,
        coordination_phone=phone,
        booking=True,
        reference=booking.reference,
    )


async def _closed_for(uow: UnitOfWork, booking: Booking) -> ClosedDetail:
    return closed_detail(booking, coordination_phone(await uow.tenant_config.contacts()))


def coordination_phone(contacts: Iterable[Any]) -> str | None:
    """The SPOA's coordination phone from the tenant's own contacts, or None when it has none.
    Never a default: a page shows the number the tenant set, or no number."""
    return next(
        (contact.value for contact in contacts if contact.kind is ContactKind.COORDINATION_PHONE),
        None,
    )


def change_view_body(
    booking: Booking, service_name: str, case: Case, phone: str | None
) -> dict[str, Any]:
    """The change page of a confirmed booking: the reference, service, age band, needs, urgency,
    status and the SPOA's phone. No postcode, name or case id, as for the request page."""
    return {
        "reference": booking.reference,
        "serviceName": service_name,
        "ageBand": None if case.age_band is None else case.age_band.value,
        "need": need_text(case),
        "urgency": None if case.urgency is None else urgency_wording(case.urgency),
        "bookingStatus": booking.status.value,
        "coordinationPhone": phone,
        "confirmedAt": iso_utc(booking.confirmed_at),
    }


def view_body(booking: Booking, service_name: str, case: Case, phone: str | None) -> dict[str, Any]:
    """The request page: the reference, service, age band, needs, urgency, reply-by, status and the
    SPOA's phone. No postcode, name or case id (the page is open to anyone holding the link)."""
    return {
        "reference": booking.reference,
        "serviceName": service_name,
        "ageBand": None if case.age_band is None else case.age_band.value,
        "need": need_text(case),
        "urgency": None if case.urgency is None else urgency_wording(case.urgency),
        "replyBy": booking.reply_by.isoformat(),
        "bookingStatus": booking.status.value,
        "coordinationPhone": phone,
    }


async def _holder(
    uow: UnitOfWork, link: LinkRequest, booking: Booking
) -> tuple[ServiceProfile, str]:
    """The service of the booking and the practitioner who holds this phone for it, or
    `LinkGone("expired")` when either is gone (a service not active, a phone that holds no role
    for it, or two people on one phone). The same answer as an unknown link."""
    profile = await uow.services.get(booking.service_id)
    phone_hash = link.record.phone_hash
    if profile is None or not profile.active or phone_hash is None:
        raise LinkGone("expired")
    try:
        practitioner = await uow.people.find_by_phone_hash(phone_hash)
    except Conflict:
        raise LinkGone("expired") from None
    held = await uow.people.services_for_phone_hash(phone_hash, link.now)
    if practitioner is None or not any(role.service_id == profile.id for role, _ in held):
        raise LinkGone("expired")
    return profile, practitioner.id


def _actor(practitioner_id: str, service_id: str) -> Actor:
    """The link's actor: the anonymous-link role, for the one service and the one practitioner the
    phone holds. The tenant is the one the edge bound (current_tenant)."""
    return Actor(
        role=Role.ANONYMOUS_LINK,
        practitioner_id=practitioner_id,
        device_id=None,
        channel="link",
        service_ids=frozenset({service_id}),
        tenant_id=current_tenant(),
    )


async def _burn(
    uow_factory: UnitOfWorkFactory,
    tokens: Callable[[LinkTokenRepository], LinkTokenService],
    link: LinkRequest,
    key: str,
) -> None:
    async with uow_factory() as uow:
        await tokens(uow.link_tokens).burn(link.token, key)
        await uow.commit()


async def _closed_detail_of(
    uow_factory: UnitOfWorkFactory, link: LinkRequest
) -> ClosedDetail | None:
    """What the closed link of a booking says, from the booking it names in the bound tenant."""
    async with uow_factory() as uow:
        booking = await uow.bookings.get(link.record.about_id)
        return None if booking is None else await _closed_for(uow, booking)


class BookingRequestLink:
    """The request link (`booking-request`): show the booking, then confirm or decline it."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        tokens: Callable[[LinkTokenRepository], LinkTokenService],
        respond: RespondToBooking,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._tokens = tokens
        self._respond = respond

    async def view(self, link: LinkRequest) -> Body:
        async with self._uow_factory() as uow:
            booking = await uow.bookings.get(link.record.about_id)
            if booking is None:
                raise LinkGone("expired")
            if booking.status is not BookingStatus.REQUESTED:
                raise LinkGone(gone_state(booking.status), await _closed_for(uow, booking))
            profile, _ = await _holder(uow, link, booking)
            case = await uow.cases.get(booking.case_id)
            if case is None:
                raise LinkGone("expired")
            phone = coordination_phone(await uow.tenant_config.contacts())
        return view_body(booking, profile.name, case, phone)

    async def respond(self, link: LinkRequest, action: LinkAction) -> Body:
        reason = check_request_action(action)
        key = command_key(link.scope, link.record)
        async with self._uow_factory() as uow:
            booking = await uow.bookings.get(link.record.about_id)
            if booking is None:
                raise LinkGone("expired")
            if booking.status is not BookingStatus.REQUESTED:
                raise LinkConflict(gone_state(booking.status), await _closed_for(uow, booking))
            profile, practitioner_id = await _holder(uow, link, booking)
        decision: Literal["confirm", "decline"] = (
            "confirm" if action.action == CONFIRM else "decline"
        )
        # The change link is issued in the unit that records the confirmation (KI-483).
        change_link = (
            ChangeLinkRequest(CHANGE_PURPOSE, link.record.phone_hash, CHANGE_TOKEN_LIFETIME)
            if decision == "confirm"
            else None
        )
        result = await self._respond.execute(
            RespondToBookingCommand(
                idempotency_key=key,
                actor=_actor(practitioner_id, profile.id),
                booking_id=booking.id,
                decision=decision,
                reason=reason,
                channel=ReportSource.LINK,
                change_link=change_link,
            )
        )
        if result.already_final:
            async with self._uow_factory() as uow:
                final = await uow.bookings.get(booking.id)
                detail = None if final is None else await _closed_for(uow, final)
            raise LinkConflict(gone_state(result.status), detail)
        body: dict[str, object] = {"bookingStatus": result.status.value}
        if result.responded_at is not None:
            body["confirmedAt" if decision == "confirm" else "respondedAt"] = iso_utc(
                result.responded_at
            )
        if result.change_token is not None:
            body["changeToken"] = result.change_token
        await _burn(self._uow_factory, self._tokens, link, key)
        return body

    async def renew(self, link: LinkRequest, link_base_url: str) -> bool:
        """A booking request is not renewed: a new request is the advisor's to send (False)."""
        return False

    async def closed(self, link: LinkRequest, state: str) -> ClosedDetail | None:
        return await _closed_detail_of(self._uow_factory, link)


class BookingChangeLink:
    """The change link (`booking-change`): withdraw a confirmed booking, or report it not
    reached."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        tokens: Callable[[LinkTokenRepository], LinkTokenService],
        withdraw: WithdrawBooking,
        not_reached: ReportNotReached,
    ) -> None:
        self._uow_factory = uow_factory
        self._tokens = tokens
        self._withdraw = withdraw
        self._not_reached = not_reached

    async def view(self, link: LinkRequest) -> Body:
        async with self._uow_factory() as uow:
            booking = await uow.bookings.get(link.record.about_id)
            if booking is None:
                raise LinkGone("expired")
            if booking.status is not BookingStatus.CONFIRMED:
                raise LinkGone(gone_state(booking.status), await _closed_for(uow, booking))
            profile, _ = await _holder(uow, link, booking)
            case = await uow.cases.get(booking.case_id)
            if case is None:
                raise LinkGone("expired")
            phone = coordination_phone(await uow.tenant_config.contacts())
        return change_view_body(booking, profile.name, case, phone)

    async def respond(self, link: LinkRequest, action: LinkAction) -> Body:
        reason = check_change_action(action)
        key = command_key(link.scope, link.record)
        async with self._uow_factory() as uow:
            booking = await uow.bookings.get(link.record.about_id)
            if booking is None:
                raise LinkGone("expired")
            if booking.status is not BookingStatus.CONFIRMED:
                raise LinkConflict(gone_state(booking.status), await _closed_for(uow, booking))
            profile, practitioner_id = await _holder(uow, link, booking)
        actor = _actor(practitioner_id, profile.id)
        try:
            if action.action == WITHDRAW:
                done = await self._withdraw.execute(
                    WithdrawBookingCommand(
                        idempotency_key=key,
                        actor=actor,
                        booking_id=booking.id,
                        reason=reason,  # type: ignore[arg-type]
                    )
                )
                status = done.status
            else:
                done_nr = await self._not_reached.execute(
                    ReportNotReachedCommand(
                        idempotency_key=key,
                        actor=actor,
                        booking_id=booking.id,
                        reason=reason,  # type: ignore[arg-type]
                    )
                )
                status = done_nr.status
        except InvalidTransition:
            raise LinkConflict(gone_state(booking.status)) from None
        await _burn(self._uow_factory, self._tokens, link, key)
        body: dict[str, object] = {"bookingStatus": status.value}
        async with self._uow_factory() as uow:
            done_booking = await uow.bookings.get(booking.id)
        if done_booking is not None and done_booking.responded_at is not None:
            body["respondedAt"] = iso_utc(done_booking.responded_at)
        return body

    async def renew(self, link: LinkRequest, link_base_url: str) -> bool:
        return False

    async def closed(self, link: LinkRequest, state: str) -> ClosedDetail | None:
        return await _closed_detail_of(self._uow_factory, link)


def booking_purposes(
    uow_factory: UnitOfWorkFactory,
    clock: Clock,
    tokens: Callable[[LinkTokenRepository], LinkTokenService],
    respond: RespondToBooking,
    withdraw: WithdrawBooking,
    not_reached: ReportNotReached,
) -> dict[str, LinkPurposeHandler]:
    """The two booking purposes, for the link purpose registry (link_access.LinkPurposes)."""
    return {
        REQUEST_PURPOSE: BookingRequestLink(uow_factory, clock, tokens, respond),
        CHANGE_PURPOSE: BookingChangeLink(uow_factory, tokens, withdraw, not_reached),
    }
