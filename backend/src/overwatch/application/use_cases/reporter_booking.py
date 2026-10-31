"""The booking a reporter sees and answers in the app, by the 4-digit reference (W7C, DEC-821 to
DEC-823).

A notification and a text carry the booking's reference (domain-rules 3.2: four digits, unique
among the tenant's open bookings), never the Task id. These two use cases map the reference to the
booking of the bound tenant, and only for a service the reporter holds now: a reference that is
unknown, malformed, another tenant's or for another service is the one `NotFound` (H-455). The
reporter sees the age band, the need and the urgency, as on the link page, and never the case, the
postcode or the person who asked. The decision runs through `RespondToBooking`, as the FHIR
`$respond` and the link do, so the state machine, the timers, the echo and the audit are one.
"""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.reporter_app import held_services
from diucs.application.use_cases.request_booking import need_text, urgency_wording
from diucs.application.use_cases.respond_to_booking import (
    RespondToBooking,
    RespondToBookingCommand,
)
from diucs.domain.codes import BookingStatus, DeclineReason, ReportSource
from diucs.domain.errors import InvalidTransition, NotFound
from diucs.domain.model.tenant import ContactKind

REFERENCE_PATTERN: Final = re.compile(r"[0-9]{4}")
NO_BOOKING: Final = "no booking with this reference"

type AppBookingStatus = Literal["requested", "confirmed", "declined", "expired"]


def app_status(status: BookingStatus) -> AppBookingStatus:
    """The four states the booking screen has. Every other state (expired, cancelled, withdrawn,
    not reached, completed) is a request the reporter can no longer answer, which the screen shows
    as expired; the exact word is `bookingStatus`."""
    if status is BookingStatus.REQUESTED:
        return "requested"
    if status is BookingStatus.CONFIRMED:
        return "confirmed"
    if status is BookingStatus.DECLINED:
        return "declined"
    return "expired"


@dataclass(frozen=True, slots=True)
class BookingView:
    reference: str
    task_id: str
    service: str
    age_band: str | None
    need: str
    urgency: str | None
    reply_by: datetime
    status: AppBookingStatus
    booking_status: str
    multi_service: bool
    confirmed_at: datetime | None
    spoa_phone: str | None


def _reference(value: str) -> str:
    if not isinstance(value, str) or REFERENCE_PATTERN.fullmatch(value) is None:
        raise NotFound(NO_BOOKING)
    return value


class ReporterBookingReader:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def view(self, actor: Actor, reference: str) -> BookingView:
        reference = _reference(reference)
        async with self._uow_factory() as uow:
            held = await held_services(uow, actor, self._clock.now())
            booking = await uow.bookings.get_by_reference(reference)
            if booking is None or booking.service_id not in held.roles:
                raise NotFound(NO_BOOKING)
            case = await uow.cases.get(booking.case_id)
            if case is None:
                raise NotFound(NO_BOOKING)
            contacts = await uow.tenant_config.contacts()
        phone = next((c.value for c in contacts if c.kind is ContactKind.COORDINATION_PHONE), None)
        return BookingView(
            reference=booking.reference,
            task_id=booking.id,
            service=held.names[booking.service_id],
            age_band=None if case.age_band is None else case.age_band.value,
            need=need_text(case),
            urgency=None if case.urgency is None else urgency_wording(case.urgency),
            reply_by=booking.reply_by,
            status=app_status(booking.status),
            booking_status=booking.status.value,
            multi_service=len(held.roles) > 1,
            confirmed_at=booking.confirmed_at,
            spoa_phone=phone,
        )


@dataclass(frozen=True, slots=True)
class BookingAnswer:
    status: AppBookingStatus
    confirmed_at: datetime | None


class ReporterBookingResponder:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, respond: RespondToBooking
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._respond = respond

    async def execute(
        self,
        actor: Actor,
        reference: str,
        key: str,
        decision: Literal["confirm", "decline"],
        reason: DeclineReason | None,
    ) -> BookingAnswer:
        reference = _reference(reference)
        async with self._uow_factory() as uow:
            held = await held_services(uow, actor, self._clock.now())
            booking = await uow.bookings.get_by_reference(reference)
            if booking is None or booking.service_id not in held.roles:
                raise NotFound(NO_BOOKING)
        result = await self._respond.execute(
            RespondToBookingCommand(
                idempotency_key=key,
                actor=replace(actor, service_ids=frozenset(held.roles)),
                booking_id=booking.id,
                decision=decision,
                reason=reason,
                channel=ReportSource.APP,
            )
        )
        if result.already_final:
            raise InvalidTransition("this booking has already been answered")
        return BookingAnswer(
            status=app_status(result.status),
            confirmed_at=result.responded_at if result.status is BookingStatus.CONFIRMED else None,
        )
