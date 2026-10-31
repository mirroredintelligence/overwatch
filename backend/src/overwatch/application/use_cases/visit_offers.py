"""The practitioner app's use cases: a visit offered to the people on a visiting service's round,
and what a practitioner does with it (DEC-1306 to DEC-1309).

How a booking becomes an offer (OfferVisit). An advisor or clinician has asked a visiting service
to take a patient (RequestBooking: the booking Task, `requested`, with a reply-by time). They then
offer the visit to the round: one `VisitOffer` for each person who holds the service's reporter
post now (the holder, or the cover while there is one). The offer carries what is needed in plain
words, the postcode sector, the urgency and the booking's reply-by time as its own time limit, and
the address and contact sealed for that one person. It carries nothing about the patient beyond
that.

What a practitioner does with it. Accepting runs the booking's own confirmation (RespondToBooking,
with its state machine, timers, echo and audit) and then marks the offer, and the same person's
colleagues' offers for the booking become withdrawn: the booking can be confirmed once, so only one
accept wins. Declining affects that person's offer only. An offer past its time or whose booking is
no longer waiting reads as expired or withdrawn (`effective_state`): no timer rewrites it. A visit
under way takes the status list (on my way, arrived, done, could not reach the patient); done
completes the booking in the same unit of work, and could not reach reports it not reached through
ReportNotReached.

Minimisation and fairness (DEC-1308). The address and contact are shown only to the person whose
visit is active, are sealed at rest, and are erased by every end state. An estimated arrival is
stored only while the person has chosen to share it, as one overwritten instant that arrival
erases. Nothing here scores, orders or compares people: the round is ordered by the time each visit
is wanted by and by nothing about who does it.

An offer of another practitioner, of another tenant, an unknown id and a visit that is no longer the
caller's are the one `NotFound`. No address, contact or postcode is in an audit snapshot, an error
or a log line.
"""

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from typing import Any, Final, Protocol

from overwatch.application.actor import Actor, timer_actor
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.ids import IdGenerator
from overwatch.application.ports.outbound.sealing import ContentSealer
from overwatch.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from overwatch.application.scheduling import schedule_work
from overwatch.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_tenant
from overwatch.application.use_cases.request_booking import need_text, urgency_wording
from overwatch.application.use_cases.respond_to_booking import (
    RespondToBooking,
    RespondToBookingCommand,
    RespondToBookingResult,
)
from overwatch.application.use_cases.withdraw_booking import (
    ReportNotReached,
    ReportNotReachedCommand,
)
from overwatch.application.work import DONE, SCHEDULED, ScheduledWork, WorkKind
from overwatch.domain.codes import BookingStatus, NotReachedReason, ReportSource, Role
from overwatch.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from overwatch.domain.model.people import Practitioner, role_holder
from overwatch.domain.model.visit import (
    ACTIVE_STATES,
    PRACTITIONER_STATUSES,
    LocationChoice,
    ShiftStatus,
    VisitOffer,
    VisitSettings,
    VisitState,
    default_settings,
)
from overwatch.domain.rules.london_time import local_to_utc, to_local
from overwatch.domain.rules.postcode import normalise_postcode, postcode_sector
from overwatch.domain.rules.visit_rules import (
    VISIT_LAPSE,
    check_details,
    check_eta_minutes,
    close_overdue,
    current_status,
    due_by,
    effective_state,
    order_of_round,
)

OFFER_USE_CASE: Final = "OfferVisit"
ACCEPT_USE_CASE: Final = "AcceptVisit"
DECLINE_USE_CASE: Final = "DeclineVisit"
STATUS_USE_CASE: Final = "UpdateVisitStatus"
SETTINGS_USE_CASE: Final = "SetVisitSettings"
CLOSE_USE_CASE: Final = "CloseVisitOffer"
CLOSE_AFTER: Final = timedelta(minutes=1)
NO_VISIT: Final = "no visit with this id"
OFFER_ROLES: Final = frozenset({Role.ADVISOR, Role.CLINICAL})
SIGNED_IN_ROLE: Final = Role.REPORTER
"""The practitioner app signs in as the reporter's device sign-in does (DEC-1306): the token names a
person and a device, and what the person may see is decided by who an offer was made to."""


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


async def _person(uow: UnitOfWork, actor: Actor) -> Practitioner:
    """The signed-in person, who must still be active in this tenant."""
    if actor.role is not SIGNED_IN_ROLE or actor.practitioner_id is None:
        raise NotAllowed("only a signed-in practitioner has a practitioner app")
    person = await uow.people.get_practitioner(actor.practitioner_id)
    if person is None or not person.active:
        raise NotFound(NO_VISIT)
    return person


async def _own_offer(uow: UnitOfWork, actor: Actor, offer_id: str) -> VisitOffer:
    """The offer, when it was made to this person. Another person's, another tenant's and an
    unknown id are the one NotFound."""
    person = await _person(uow, actor)
    offer = await uow.visits.get(offer_id) if isinstance(offer_id, str) else None
    if offer is None or offer.practitioner_id != person.id:
        raise NotFound(NO_VISIT)
    return offer


async def _booking_status(uow: UnitOfWork, booking_id: str) -> BookingStatus | None:
    booking = await uow.bookings.get(booking_id)
    return None if booking is None else booking.status


async def _on_the_round(uow: UnitOfWork, offer: VisitOffer, now: datetime) -> bool:
    """True while the person is still a holder of one of the service's reporter posts."""
    roles = await uow.people.reporter_roles_for_service(offer.service_id, now)
    return any(role_holder(role, now) == offer.practitioner_id for role in roles)


def _seal(
    offer_id: str, scope: ScopeId, practitioner_id: str, sealer: ContentSealer, text: str
) -> str:
    return sealer.seal(
        text, message_id=offer_id, tenant_id=scope.value, recipient_role_id=practitioner_id
    )


def _details_of(offer: VisitOffer, scope: ScopeId, sealer: ContentSealer) -> tuple[str, str] | None:
    """The address and contact of an active visit, or None when they cannot be read (the screen then
    says to phone the coordination team). A text that does not open is never shown or logged."""
    if offer.sealed_details is None:
        return None
    try:
        opened = sealer.unseal(
            offer.sealed_details,
            message_id=offer.id,
            tenant_id=scope.value,
            recipient_role_id=offer.practitioner_id,
        )
        body = json.loads(opened)
        return str(body["address"]), str(body["contact"])
    except ValidationFailed, ValueError, KeyError, TypeError:
        return None


def _audit(
    actor: Actor,
    use_case: str,
    action: str,
    ids: tuple[str, ...],
    snapshot: dict[str, Any],
    at: datetime,
) -> AuditEntry:
    return AuditEntry(
        action=action, use_case=use_case, actor=actor, entity_ids=ids, snapshot=snapshot, at=at
    )


# ----------------------------------------------------------------------------------- the offer


@dataclass(frozen=True, slots=True)
class OfferVisitResult:
    offered_to: int
    expires_at: datetime


class OfferVisit:
    """An advisor or clinician offers a requested booking on a visiting service to its round."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, ids: IdGenerator, sealer: ContentSealer
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._sealer = sealer

    async def execute(
        self, actor: Actor, booking_id: str, postcode: object, address: object, contact: object
    ) -> OfferVisitResult:
        if actor.role not in OFFER_ROLES or actor.practitioner_id is None:
            raise NotAllowed("only an advisor or a clinician may offer a visit")
        full = normalise_postcode(postcode) if isinstance(postcode, str) else None
        if full is None:
            raise ValidationFailed("postcode", "must be a full postcode")
        sector = postcode_sector(full)
        address_text, contact_text = check_details(address, contact)
        details = json.dumps({"address": address_text, "contact": contact_text}, ensure_ascii=False)

        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            booking = await uow.bookings.get(booking_id) if isinstance(booking_id, str) else None
            if booking is None:
                raise NotFound("no booking with this id")
            if booking.status is not BookingStatus.REQUESTED or now >= booking.reply_by:
                raise Conflict("this booking is no longer waiting for an answer")
            profile = await uow.services.get(booking.service_id)
            if profile is None or not profile.active:
                raise NotFound("no active service for this booking")
            if booking.service_id not in await uow.positions.coverage_districts([profile.id]):
                raise ValidationFailed("service", "does not go out to patients")
            case = await uow.cases.get(booking.case_id)
            if case is None or case.urgency is None or not case.needs:
                raise ValidationFailed("case", "must have needs and an urgency")
            if await uow.visits.for_booking(booking.id):
                raise Conflict("this booking has already been offered to the round")

            holders: set[str] = set()
            for role in await uow.people.reporter_roles_for_service(profile.id, now):
                holders.add(role_holder(role, now))
            people = [await uow.people.get_practitioner(holder) for holder in sorted(holders)]
            round_ids = [person.id for person in people if person is not None and person.active]
            if not round_ids:
                raise ValidationFailed("service", "has nobody on its round to offer to")

            offers: list[VisitOffer] = []
            for practitioner_id in round_ids:
                offer_id = self._ids.new_id()
                offers.append(
                    VisitOffer(
                        id=offer_id,
                        booking_id=booking.id,
                        reference=booking.reference,
                        service_id=profile.id,
                        practitioner_id=practitioner_id,
                        need=need_text(case),
                        sector=sector,
                        urgency=case.urgency,
                        offered_at=now,
                        expires_at=booking.reply_by,
                        state=VisitState.OFFERED,
                        state_at=now,
                        sealed_details=_seal(
                            offer_id, scope, practitioner_id, self._sealer, details
                        ),
                    )
                )
            await uow.visits.add_many(offers)
            for offer in offers:
                # The close, a minute after the offer's time is up: what an unanswered offer holds
                # is erased even if nobody opens it again.
                await schedule_work(
                    uow,
                    self._ids,
                    kind=WorkKind.VISIT_CLOSE,
                    about_id=offer.id,
                    due_at=offer.expires_at + CLOSE_AFTER,
                    now=now,
                )
            await uow.audit.append(
                _audit(
                    actor,
                    OFFER_USE_CASE,
                    "C",
                    (booking.id, profile.id, *(offer.id for offer in offers)),
                    {"offered_to": len(offers), "urgency": case.urgency.value},
                    now,
                )
            )
            await uow.commit()
        return OfferVisitResult(len(offers), booking.reply_by)


# ------------------------------------------------------------------------------------- views


@dataclass(frozen=True, slots=True)
class OfferSummary:
    id: str
    need: str
    sector: str
    wanted_within: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class NextVisit:
    id: str
    sector: str
    due_by: datetime | None
    wanted_within: str


@dataclass(frozen=True, slots=True)
class RoundItem:
    """One of today's visits on the round list: the sector, when it is wanted, how far on."""

    id: str
    sector: str
    state: VisitState
    due_by: datetime | None
    wanted_within: str


@dataclass(frozen=True, slots=True)
class ShiftView:
    status: ShiftStatus | None
    location: LocationChoice
    visits_today: int
    next_visit: NextVisit | None
    offers: tuple[OfferSummary, ...]
    round: tuple[RoundItem, ...] = ()
    """Today's visits: those still to do in the order they are wanted, then those finished."""


@dataclass(frozen=True, slots=True)
class VisitView:
    id: str
    reference: str
    state: VisitState
    need: str
    sector: str
    wanted_within: str
    expires_at: datetime
    fits_minutes: int | None
    """How much an accepted visit adds to the person's round, in minutes. Not worked out in this
    build (there is no round planner, and nothing may rank people), so always None; the field is
    the contract for the day one exists."""
    address: str | None
    contact: str | None
    eta_at: datetime | None
    location: LocationChoice


def headline(need: str) -> str:
    """The needs in plain words as a screen heading: the first letter capitalised."""
    return need[:1].upper() + need[1:]


def _start_of_day(now: datetime) -> datetime:
    return local_to_utc(to_local(now).date(), time(0, 0))


class VisitReader:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock, sealer: ContentSealer) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._sealer = sealer

    async def shift(self, actor: Actor) -> ShiftView:
        """The shift home: the optional status, the location choice, today's visits, the next one
        and the offers waiting."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            person = await _person(uow, actor)
            settings = await uow.visits.settings(person.id) or default_settings(person.id)
            offers = await uow.visits.for_practitioner(person.id, _start_of_day(now), now)
            effective: list[tuple[VisitOffer, VisitState]] = []
            for offer in offers:
                status = await _booking_status(uow, offer.booking_id)
                effective.append((offer, effective_state(offer, status, now)))
        states = {o.id: s for o, s in effective}
        under_way = order_of_round([o for o, s in effective if s in ACTIVE_STATES])
        finished = sorted(
            (o for o, s in effective if s in (VisitState.DONE, VisitState.NOT_REACHED)),
            key=lambda o: (o.state_at, o.id),
        )
        today = [*under_way, *finished]
        waiting = [o for o, s in effective if s is VisitState.OFFERED]
        coming = order_of_round(
            [o for o, s in effective if s in (VisitState.ACCEPTED, VisitState.ON_MY_WAY)]
        )
        return ShiftView(
            status=current_status(settings, now),
            location=settings.location,
            visits_today=len(today),
            next_visit=None
            if not coming
            else NextVisit(
                coming[0].id,
                coming[0].sector,
                due_by(coming[0].urgency, coming[0].offered_at),
                urgency_wording(coming[0].urgency),
            ),
            offers=tuple(
                OfferSummary(
                    o.id, headline(o.need), o.sector, urgency_wording(o.urgency), o.expires_at
                )
                for o in sorted(waiting, key=lambda o: (o.expires_at, o.id))
            ),
            round=tuple(
                RoundItem(
                    o.id,
                    o.sector,
                    states[o.id],
                    due_by(o.urgency, o.offered_at),
                    urgency_wording(o.urgency),
                )
                for o in today
            ),
        )

    async def view(self, actor: Actor, offer_id: str) -> VisitView:
        """One offer or visit. The address and contact are in it only while the visit is active."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            offer = await _own_offer(uow, actor, offer_id)
            state = effective_state(offer, await _booking_status(uow, offer.booking_id), now)
            settings = await uow.visits.settings(offer.practitioner_id) or default_settings(
                offer.practitioner_id
            )
        details = _details_of(offer, scope, self._sealer) if state in ACTIVE_STATES else None
        return VisitView(
            id=offer.id,
            reference=offer.reference,
            state=state,
            need=headline(offer.need),
            sector=offer.sector,
            wanted_within=urgency_wording(offer.urgency),
            expires_at=offer.expires_at,
            fits_minutes=None,
            address=None if details is None else details[0],
            contact=None if details is None else details[1],
            eta_at=offer.eta_at if state in ACTIVE_STATES else None,
            location=settings.location,
        )


# ------------------------------------------------------------------- accept, decline, status


@dataclass(frozen=True, slots=True)
class VisitAnswer:
    id: str
    state: VisitState


class BookingConfirmer(Protocol):
    async def confirm(self, actor: Actor, offer: VisitOffer) -> RespondToBookingResult:
        """Confirm the offer's booking as the person who answers for its service."""
        ...


class NotReachedReporting(Protocol):
    async def report(self, actor: Actor, offer: VisitOffer, reason: NotReachedReason) -> None:
        """Report the offer's booking not reached."""
        ...


def _as_responder(actor: Actor, offer: VisitOffer) -> Actor:
    """The person answers for the service the offer was made for: the offer, checked against the
    graph by the caller just before, is what names the service (the token's own list was made at
    sign-in and may be older)."""
    return replace(actor, service_ids=frozenset({offer.service_id}))


class RespondsToBooking:
    """Confirms through the booking's own use case, replayed by a key of this offer."""

    def __init__(self, respond: RespondToBooking) -> None:
        self._respond = respond

    async def confirm(self, actor: Actor, offer: VisitOffer) -> RespondToBookingResult:
        return await self._respond.execute(
            RespondToBookingCommand(
                idempotency_key=f"visit-accept:{offer.id}",
                actor=_as_responder(actor, offer),
                booking_id=offer.booking_id,
                decision="confirm",
                channel=ReportSource.APP,
            )
        )


class ReportsNotReached:
    """Reports not reached through the booking's own use case, replayed by a key of this offer."""

    def __init__(self, report: ReportNotReached) -> None:
        self._report = report

    async def report(self, actor: Actor, offer: VisitOffer, reason: NotReachedReason) -> None:
        await self._report.execute(
            ReportNotReachedCommand(
                idempotency_key=f"visit-not-reached:{offer.id}",
                actor=_as_responder(actor, offer),
                booking_id=offer.booking_id,
                reason=reason,
            )
        )


class AcceptVisit:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        respond: BookingConfirmer,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._respond = respond

    async def execute(self, actor: Actor, offer_id: str) -> VisitAnswer:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            offer = await _own_offer(uow, actor, offer_id)
            if offer.state is VisitState.ACCEPTED:
                return VisitAnswer(offer.id, offer.state)  # the same person pressing again
            # The booking's status is not read here: if this person's own earlier press confirmed
            # it and the offer was not marked, the confirmation below replays by its key, and if
            # someone else confirmed it the same command says so (`already_final`).
            if offer.state is not VisitState.OFFERED or now >= offer.expires_at:
                raise Conflict("this offer is no longer open")
            if not await _on_the_round(uow, offer, now):
                raise NotFound(NO_VISIT)

        # The booking's own confirmation first: it can happen once, so it decides who is first. A
        # repeat of this call replays it by its key.
        answered = await self._respond.confirm(actor, offer)
        if answered.already_final:
            raise Conflict("this offer is no longer open")

        async with self._uow_factory() as uow:
            offer = await _own_offer(uow, actor, offer_id)
            if offer.state is VisitState.ACCEPTED:
                return VisitAnswer(offer.id, offer.state)
            accepted = offer.with_state(VisitState.ACCEPTED, now)
            if not await uow.visits.change(accepted, VisitState.OFFERED):
                raise Conflict("this offer is no longer open")
            for other in await uow.visits.for_booking(offer.booking_id):
                if other.id != offer.id and other.state is VisitState.OFFERED:
                    await uow.visits.change(
                        other.with_state(VisitState.WITHDRAWN, now), VisitState.OFFERED
                    )
            # A visit nobody finishes is closed a day on, which erases its details.
            await schedule_work(
                uow,
                self._ids,
                kind=WorkKind.VISIT_CLOSE,
                about_id=offer.id,
                due_at=now + VISIT_LAPSE,
                now=now,
            )
            await uow.audit.append(
                _audit(
                    actor,
                    ACCEPT_USE_CASE,
                    "U",
                    (offer.id, offer.booking_id, offer.service_id),
                    {"state": VisitState.ACCEPTED.value},
                    now,
                )
            )
            await uow.commit()
        return VisitAnswer(offer.id, VisitState.ACCEPTED)


class DeclineVisit:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, offer_id: str) -> VisitAnswer:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            offer = await _own_offer(uow, actor, offer_id)
            state = effective_state(offer, await _booking_status(uow, offer.booking_id), now)
            if state is VisitState.DECLINED:
                return VisitAnswer(offer.id, state)
            if state is not VisitState.OFFERED:
                raise Conflict("this offer is no longer open")
            if not await uow.visits.change(
                offer.with_state(VisitState.DECLINED, now), VisitState.OFFERED
            ):
                raise Conflict("this offer is no longer open")
            await uow.audit.append(
                _audit(
                    actor,
                    DECLINE_USE_CASE,
                    "U",
                    (offer.id, offer.booking_id),
                    {"state": VisitState.DECLINED.value},
                    now,
                )
            )
            await uow.commit()
        return VisitAnswer(offer.id, VisitState.DECLINED)


class UpdateVisitStatus:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        not_reached: NotReachedReporting,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._not_reached = not_reached

    async def execute(
        self, actor: Actor, offer_id: str, status: object, eta_minutes: object = None
    ) -> VisitAnswer:
        if not isinstance(status, VisitState) or status not in PRACTITIONER_STATUSES:
            raise ValidationFailed("status", "is not one the practitioner can set")
        minutes = None if eta_minutes is None else check_eta_minutes(eta_minutes)
        if minutes is not None and status is not VisitState.ON_MY_WAY:
            raise ValidationFailed("eta_minutes", "can only be given when on the way")
        now = self._clock.now()

        offer = await self._checked(actor, offer_id, status, minutes, now)
        if status is VisitState.NOT_REACHED:
            # The booking is told first, by a command that replays by its key: if the write below
            # fails, the same press repeats it and goes on.
            await self._not_reached.report(actor, offer, NotReachedReason.NO_ANSWER)

        async with self._uow_factory() as uow:
            fresh = await self._open_offer(uow, actor, offer_id, now)
            moved = fresh.with_state(status, now)
            if minutes is not None:
                moved = moved.with_eta(now + timedelta(minutes=minutes))
            if not await uow.visits.change(moved, fresh.state):
                raise Conflict("this visit has just changed")
            if status is VisitState.DONE:
                booking = await uow.bookings.get(fresh.booking_id)
                if booking is not None and booking.status is BookingStatus.CONFIRMED:
                    await uow.bookings.save(booking.with_status(BookingStatus.COMPLETED, now))
            await uow.audit.append(
                _audit(
                    actor,
                    STATUS_USE_CASE,
                    "U",
                    (fresh.id, fresh.booking_id, fresh.service_id),
                    {"state": status.value, "eta_given": minutes is not None},
                    now,
                )
            )
            await uow.commit()
        return VisitAnswer(offer.id, status)

    async def _open_offer(
        self, uow: UnitOfWork, actor: Actor, offer_id: str, now: datetime
    ) -> VisitOffer:
        offer = await _own_offer(uow, actor, offer_id)
        state = effective_state(offer, await _booking_status(uow, offer.booking_id), now)
        if state not in ACTIVE_STATES:
            raise Conflict("this visit is not open")
        return offer

    async def _checked(
        self, actor: Actor, offer_id: str, status: VisitState, minutes: int | None, now: datetime
    ) -> VisitOffer:
        async with self._uow_factory() as uow:
            offer = await self._open_offer(uow, actor, offer_id, now)
            if minutes is not None:
                settings = await uow.visits.settings(offer.practitioner_id)
                if settings is None or settings.location is not LocationChoice.TRAVEL:
                    raise ValidationFailed("eta_minutes", "location is not shared")
            offer.with_state(status, now)  # an InvalidTransition before anything is sent
            return offer


# ------------------------------------------------------------------------------------ settings


@dataclass(frozen=True, slots=True)
class SettingsCommand:
    set_status: bool
    status: ShiftStatus | None
    location: LocationChoice | None


class SetVisitSettings:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, command: SettingsCommand) -> VisitSettings:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            person = await _person(uow, actor)
            held = await uow.visits.settings(person.id) or default_settings(person.id)
            changed = replace(
                held,
                status=command.status if command.set_status else held.status,
                status_at=(None if command.status is None else now)
                if command.set_status
                else held.status_at,
                location=command.location or held.location,
            )
            await uow.visits.save_settings(changed)
            if changed.location is LocationChoice.NEVER:
                # "Never" means never: an estimate given earlier is erased now.
                for offer in await uow.visits.for_practitioner(person.id, _start_of_day(now), now):
                    if offer.eta_at is not None:
                        await uow.visits.change(offer.with_eta(None), offer.state)
            await uow.audit.append(
                _audit(
                    actor,
                    SETTINGS_USE_CASE,
                    "U",
                    (person.id,),
                    {
                        "status": None if changed.status is None else changed.status.value,
                        "location": changed.location.value,
                    },
                    now,
                )
            )
            await uow.commit()
        return changed


# ------------------------------------------------------------------------------------- the close


@dataclass(frozen=True, slots=True)
class CloseResult:
    acted: bool


class CloseVisitOffer:
    """The scheduled close of one offer (DEC-1308 item 7). It runs once per work item (the work is
    marked done in the same unit), acts on the current state (`close_overdue`), and ends what is
    overdue so that its sealed details, estimate and sector are erased: an offer nobody answered
    in time, an offer whose booking was answered or cancelled, a visit nobody finished a day after
    its last change. A visit still within its day is left, and the close is scheduled again for the
    day after its last change, so no open visit is ever without one."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def execute(self, work_id: str, offer_id: str) -> CloseResult:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            work = await uow.scheduled_work.get(work_id)
            if work.kind is not WorkKind.VISIT_CLOSE or work.about_id != offer_id:
                raise NotFound(NO_VISIT)
            if work.status != SCHEDULED:
                return CloseResult(acted=False)
            await uow.scheduled_work.save(replace(work, status=DONE))
            offer = await uow.visits.get(offer_id)
            if offer is None:
                await uow.commit()
                return CloseResult(acted=False)
            target = close_overdue(offer, await _booking_status(uow, offer.booking_id), now)
            if target is None:
                if offer.state in ACTIVE_STATES:
                    await schedule_work(
                        uow,
                        self._ids,
                        kind=WorkKind.VISIT_CLOSE,
                        about_id=offer.id,
                        due_at=offer.state_at + VISIT_LAPSE,
                        now=now,
                    )
                await uow.commit()
                return CloseResult(acted=False)
            if not await uow.visits.change(offer.with_state(target, now), offer.state):
                await uow.commit()
                return CloseResult(acted=False)
            await uow.audit.append(
                _audit(
                    timer_actor(current_tenant()),
                    CLOSE_USE_CASE,
                    "U",
                    (offer.id, offer.booking_id, offer.service_id),
                    {"state": target.value},
                    now,
                )
            )
            await uow.commit()
        return CloseResult(acted=True)


WorkHandler = Callable[[ScheduledWork], Awaitable[None]]


def visit_close_handlers(close: CloseVisitOffer) -> Mapping[WorkKind, WorkHandler]:
    """The one dispatch entry for visit work: each stored work item closes its own offer (the work's
    `about_id`)."""

    async def on_close(work: ScheduledWork) -> None:
        await close.execute(work.id, work.about_id)

    return {WorkKind.VISIT_CLOSE: on_close}


__all__ = [
    "AcceptVisit",
    "BookingConfirmer",
    "CloseVisitOffer",
    "DeclineVisit",
    "NotReachedReporting",
    "OfferVisit",
    "ReportsNotReached",
    "RespondsToBooking",
    "SetVisitSettings",
    "UpdateVisitStatus",
    "VisitReader",
    "visit_close_handlers",
]
