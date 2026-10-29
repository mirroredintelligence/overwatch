"""The booking timers: the phone prompt at +5 minutes, and the expiry at +10 minutes (U19).

The scheduled-work consumer (I05) calls these through the dispatch table `booking_timer_handlers`
built in the composition root. Each timer runs once per work item: the work is marked done in the
same unit of work that does the rest, so a second delivery finds it done and does nothing (DEC-190
item 4). Work that is not scheduled is ignored, and a late timer acts on the current state.

The outbox message ids are derived from the booking id, so one booking emits one event of each
kind however often its work is delivered.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Final

from diucs.application.actor import timer_actor
from diucs.application.booking_effects import cancel_booking_timers, expired
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import current_tenant
from diucs.application.work import DONE, SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.codes import BookingStatus
from diucs.domain.errors import NotFound
from diucs.domain.events import BookingExpired
from diucs.domain.events import BookingPhonePrompt as PhonePromptEvent
from diucs.domain.rules.booking_timers import TimerEffect, expiry_effect, phone_prompt_effect

AUDIT_ACTION: Final = "U"
EXPIRE_USE_CASE: Final = "ExpireBooking"
NO_BOOKING: Final = "no booking with this id"
NO_TIMER: Final = "no timer of this kind for this booking"

WorkHandler = Callable[[ScheduledWork], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class BookingPhonePromptCommand:
    work_id: str
    booking_id: str


@dataclass(frozen=True, slots=True)
class ExpireBookingCommand:
    work_id: str
    booking_id: str


@dataclass(frozen=True, slots=True)
class TimerResult:
    acted: bool


async def _timer_work(
    uow: UnitOfWork, work_id: str, booking_id: str, kind: WorkKind
) -> ScheduledWork | None:
    """The stored timer, or None when it is not scheduled any more (done or cancelled)."""
    work = await uow.scheduled_work.get(work_id)
    if work.kind is not kind or work.about_id != booking_id:
        raise NotFound(NO_TIMER)
    return work if work.status == SCHEDULED else None


class BookingPhonePrompt:
    """The phone prompt at +5 minutes: a BookingPhonePrompt event while the request is still
    waiting, and nothing once it is answered."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: BookingPhonePromptCommand) -> TimerResult:
        async with self._uow_factory() as uow:
            work = await _timer_work(
                uow, command.work_id, command.booking_id, WorkKind.BOOKING_PHONE_PROMPT
            )
            if work is None:
                return TimerResult(acted=False)
            booking = await uow.bookings.get(command.booking_id)
            if booking is None:
                raise NotFound(NO_BOOKING)
            await uow.scheduled_work.save(replace(work, status=DONE))
            if phone_prompt_effect(booking.status) is TimerEffect.NONE:
                await uow.commit()
                return TimerResult(acted=False)
            now = self._clock.now()
            await uow.outbox.add(
                outbox_message_for(
                    PhonePromptEvent(
                        booking_id=booking.id,
                        service_id=booking.service_id,
                        reference=booking.reference,
                        at=now,
                    ),
                    id=f"booking-phone-prompt-{booking.id}",
                    now=now,
                )
            )
            await uow.commit()
        return TimerResult(acted=True)


class ExpireBooking:
    """The expiry at +10 minutes: a requested booking becomes expired (Task `cancelled`, reason
    `expired`), its other timer is cancelled, BookingExpired is emitted and the change is audited
    under the system actor. A booking that is already final is left as it is."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: ExpireBookingCommand) -> TimerResult:
        async with self._uow_factory() as uow:
            work = await _timer_work(
                uow, command.work_id, command.booking_id, WorkKind.BOOKING_EXPIRE
            )
            if work is None:
                return TimerResult(acted=False)
            booking = await uow.bookings.get(command.booking_id)
            if booking is None:
                raise NotFound(NO_BOOKING)
            await uow.scheduled_work.save(replace(work, status=DONE))
            if expiry_effect(booking.status) is TimerEffect.NONE:
                await uow.commit()
                return TimerResult(acted=False)
            now = self._clock.now()
            await uow.bookings.save(expired(booking, now))
            await cancel_booking_timers(uow, booking.id, now, keep=work.id)
            await uow.outbox.add(
                outbox_message_for(
                    BookingExpired(booking_id=booking.id, service_id=booking.service_id, at=now),
                    id=f"booking-expired-{booking.id}",
                    now=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=EXPIRE_USE_CASE,
                    actor=timer_actor(current_tenant()),
                    entity_ids=(booking.id, booking.service_id),
                    snapshot={"status": BookingStatus.EXPIRED.value},
                    at=now,
                )
            )
            await uow.commit()
        return TimerResult(acted=True)


def booking_timer_handlers(
    phone_prompt: BookingPhonePrompt, expire: ExpireBooking
) -> Mapping[WorkKind, WorkHandler]:
    """The two dispatch entries for booking work: each stored work item runs its timer about its
    own booking (the work's `about_id`)."""

    async def on_phone_prompt(work: ScheduledWork) -> None:
        await phone_prompt.execute(
            BookingPhonePromptCommand(work_id=work.id, booking_id=work.about_id)
        )

    async def on_expire(work: ScheduledWork) -> None:
        await expire.execute(ExpireBookingCommand(work_id=work.id, booking_id=work.about_id))

    return {
        WorkKind.BOOKING_PHONE_PROMPT: on_phone_prompt,
        WorkKind.BOOKING_EXPIRE: on_expire,
    }
