"""Effects that the booking use cases share: the timers of a booking, the text reporter that gets an
echo, and the expiry of a booking (U18, U19, U20, U36).

A use case never calls the event bus. Timers are cancelled through cancel_work (U03), which writes
the CancelWork message the relay (I03) delivers.
"""

from datetime import datetime
from typing import Final

from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.application.scheduling import cancel_work
from diucs.application.sealed_send import queue_message
from diucs.application.tenancy import ScopeId
from diucs.application.work import SCHEDULED, WorkKind
from diucs.domain.codes import BookingStatus, Channel
from diucs.domain.messages.templates import RenderedMessage
from diucs.domain.model.booking import Booking
from diucs.domain.model.people import PractitionerRole

BOOKING_TIMER_KINDS: Final = frozenset({WorkKind.BOOKING_PHONE_PROMPT, WorkKind.BOOKING_EXPIRE})


async def cancel_booking_timers(
    uow: UnitOfWork, booking_id: str, now: datetime, *, keep: str | None = None
) -> None:
    """Cancel every scheduled booking timer of this booking, except the one named by `keep`."""
    for work in await uow.scheduled_work.for_about(booking_id):
        if work.id == keep or work.kind not in BOOKING_TIMER_KINDS:
            continue
        if work.status == SCHEDULED:
            await cancel_work(uow, work, now)


async def text_reporter_role(
    uow: UnitOfWork, service_id: str, now: datetime
) -> PractitionerRole | None:
    """The reporter role a service's echoes go to: the one a request goes to (the lowest id), when
    it is on text. The echo wording (B4 to B6, K4) is text only in D16, so an email or push
    reporter gets no echo (hazard H-135, DEC-300 item 3)."""
    roles = await uow.people.reporter_roles_for_service(service_id, now)
    if not roles:
        return None
    role = min(roles, key=lambda candidate: candidate.id)
    return role if (role.channel or Channel.TEXT) is Channel.TEXT else None


def expired(booking: Booking, at: datetime) -> Booking:
    """The booking after its reply window has passed. The Task is `cancelled` with businessStatus
    `expired` (D13); the move is checked by the state machine."""
    return booking.with_status(BookingStatus.EXPIRED, at)


async def queue_echo(
    uow: UnitOfWork,
    ids: IdGenerator,
    sealer: ContentSealer,
    *,
    scope: ScopeId,
    rendered: RenderedMessage,
    booking: Booking,
    recipient_role_id: str,
    now: datetime,
) -> str:
    """Queue the echo of a booking reply or cancellation to the service's reporter.

    The Communication is about the SERVICE: the store links a Communication's about id to a
    HealthcareService with that id, so a booking id here would create a placeholder service and
    clash on the unique Resource id (fixD, U17-1). The booking is named in the text only.
    """
    return await queue_message(
        uow,
        ids,
        sealer,
        scope=scope,
        rendered=rendered,
        recipient_role_id=recipient_role_id,
        about_id=booking.service_id,
        now=now,
    )
