"""The practitioner app's routes, behind a signed-in person's bearer token (DEC-1306 to DEC-1309).

GET  /practitioner/shift                   status, location choice, today's visits, next, offers
PUT  /practitioner/settings                the optional status and the location choice
GET  /practitioner/visits/{id}             one offer or visit; address and contact only when active
POST /practitioner/visits/{id}/accept      accept the offer (Idempotency-Key)
POST /practitioner/visits/{id}/decline     decline the offer (Idempotency-Key)
POST /practitioner/visits/{id}/status      on-my-way, arrived, done, not-reached (Idempotency-Key)
POST /visits/offers                        an advisor or clinician offers a booking to the round (no
                                           Idempotency-Key: a repeat is a 409)

The practitioner signs in as a reporter's device does (DEC-1306): role `reporter`, the person and
the device of the token checked on every use. What a person may see is decided by who an offer was
made to, read from the graph: another person's offer, another tenant's and an unknown id are the
same 404. The routes hold no business rule: the tenant is bound by `current_actor`, each route runs
one use case and maps its result. Responses are `no-store`. An address, contact or postcode is never
in a log line or an error, and the replay cache holds only answers that carry neither (the read is
not replayed).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import Field

from overwatch.adapters.inbound.fhir_rest.auth import require_role
from overwatch.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from overwatch.adapters.inbound.fhir_rest.routes_identity import (
    _answer,
    _Body,
    _Container,
    _container,
    _json,
    _signed_in,
)
from overwatch.application.actor import Actor
from overwatch.application.uow_idempotency import UnitOfWorkIdempotency
from overwatch.application.use_cases.link_access import iso_utc
from overwatch.application.use_cases.respond_to_booking import RespondToBooking
from overwatch.application.use_cases.visit_offers import (
    OFFER_ROLES,
    AcceptVisit,
    DeclineVisit,
    OfferVisit,
    ReportsNotReached,
    RespondsToBooking,
    SettingsCommand,
    SetVisitSettings,
    ShiftView,
    UpdateVisitStatus,
    VisitReader,
    VisitView,
)
from overwatch.application.use_cases.withdraw_booking import ReportNotReached
from overwatch.domain.codes import Role
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.visit import (
    PRACTITIONER_STATUSES,
    LocationChoice,
    ShiftStatus,
    VisitState,
)

router = APIRouter()
_Practitioner = Annotated[Actor, Depends(require_role(Role.REPORTER))]
_Offerer = Annotated[Actor, Depends(require_role(*OFFER_ROLES))]


class SettingsBody(_Body):
    """Either answer may be left out. `status: null` clears the status."""

    status: str | None = Field(default=None, max_length=16)
    location: str | None = Field(default=None, max_length=16)


class StatusBody(_Body):
    status: str = Field(max_length=16)
    etaMinutes: int | None = Field(default=None, strict=True)


class OfferBody(_Body):
    bookingId: str = Field(min_length=1, max_length=64)
    postcode: str = Field(min_length=1, max_length=16)
    address: str = Field(min_length=1, max_length=400)
    contact: str = Field(min_length=1, max_length=240)


def _stamp(moment: Any) -> str | None:
    return iso_utc(moment)


def shift_json(view: ShiftView) -> dict[str, Any]:
    return {
        "status": None if view.status is None else view.status.value,
        "location": view.location.value,
        "visitsToday": view.visits_today,
        "next": None
        if view.next_visit is None
        else {
            "id": view.next_visit.id,
            "sector": view.next_visit.sector,
            "dueBy": _stamp(view.next_visit.due_by),
            "wantedWithin": view.next_visit.wanted_within,
        },
        "offers": [
            {
                "id": offer.id,
                "need": offer.need,
                "sector": offer.sector,
                "wantedWithin": offer.wanted_within,
                "expiresAt": _stamp(offer.expires_at),
            }
            for offer in view.offers
        ],
        "round": [
            {
                "id": item.id,
                "sector": item.sector,
                "state": item.state.value,
                "dueBy": _stamp(item.due_by),
                "wantedWithin": item.wanted_within,
            }
            for item in view.round
        ],
    }


def visit_json(view: VisitView) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": view.id,
        "reference": view.reference,
        "state": view.state.value,
        "need": view.need,
        "sector": view.sector,
        "wantedWithin": view.wanted_within,
        "expiresAt": _stamp(view.expires_at),
        "fitsMinutes": view.fits_minutes,
        "etaAt": _stamp(view.eta_at),
        "location": view.location.value,
    }
    if view.address is not None and view.contact is not None:
        body["address"] = view.address
        body["contact"] = view.contact
    return body


def _status_word(value: str) -> ShiftStatus:
    try:
        return ShiftStatus(value)
    except ValueError:
        raise ValidationFailed("status", "is not one of the answers") from None


def _location_word(value: str) -> LocationChoice:
    try:
        return LocationChoice(value)
    except ValueError:
        raise ValidationFailed("location", "is not one of the answers") from None


def _visit_state(value: str) -> VisitState:
    """One of the four answers of the status list, before anything is read."""
    try:
        state = VisitState(value)
    except ValueError:
        raise ValidationFailed("status", "is not one of the answers") from None
    if state not in PRACTITIONER_STATUSES:
        raise ValidationFailed("status", "is not one of the answers")
    return state


async def _signed(request: Request, actor: Actor) -> _Container:
    container = _container(request)
    await _signed_in(container, actor)
    return container


def _reader(container: _Container) -> VisitReader:
    return VisitReader(container.uow_factory, container.clock, container.sealer)


def _respond(container: _Container) -> RespondToBooking:
    return RespondToBooking(
        container.uow_factory,
        UnitOfWorkIdempotency(container.uow_factory),
        container.clock,
        container.ids,
        container.sealer,
    )


# ------------------------------------------------------------------------------- reads


@router.get("/practitioner/shift")
async def shift(request: Request, actor: _Practitioner) -> Response:
    container = await _signed(request, actor)
    return _json(200, shift_json(await _reader(container).shift(actor)))


@router.get("/practitioner/visits/{offer_id}")
async def visit(offer_id: str, request: Request, actor: _Practitioner) -> Response:
    container = await _signed(request, actor)
    return _json(200, visit_json(await _reader(container).view(actor, offer_id)))


# ------------------------------------------------------------------------------- writes


@router.put("/practitioner/settings")
async def settings(body: SettingsBody, request: Request, actor: _Practitioner) -> Response:
    container = await _signed(request, actor)
    command = SettingsCommand(
        set_status="status" in body.model_fields_set,
        status=None if body.status is None else _status_word(body.status),
        location=None if body.location is None else _location_word(body.location),
    )
    changed = await SetVisitSettings(container.uow_factory, container.clock).execute(actor, command)
    return _json(
        200,
        {
            "status": None if changed.status is None else changed.status.value,
            "location": changed.location.value,
        },
    )


@router.post("/practitioner/visits/{offer_id}/accept")
async def accept(offer_id: str, request: Request, actor: _Practitioner) -> Response:
    key = idempotency_key(request)
    container = await _signed(request, actor)

    async def run() -> Response:
        answer = await AcceptVisit(
            container.uow_factory,
            container.clock,
            container.ids,
            RespondsToBooking(_respond(container)),
        ).execute(actor, offer_id)
        return _json(200, {"id": answer.id, "state": answer.state.value})

    return await _answer(
        lambda: replay_or_run(request, actor, f"visit-accept:{offer_id}:{key}", run)
    )


@router.post("/practitioner/visits/{offer_id}/decline")
async def decline(offer_id: str, request: Request, actor: _Practitioner) -> Response:
    key = idempotency_key(request)
    container = await _signed(request, actor)

    async def run() -> Response:
        answer = await DeclineVisit(container.uow_factory, container.clock).execute(actor, offer_id)
        return _json(200, {"id": answer.id, "state": answer.state.value})

    return await _answer(
        lambda: replay_or_run(request, actor, f"visit-decline:{offer_id}:{key}", run)
    )


@router.post("/practitioner/visits/{offer_id}/status")
async def update_status(
    offer_id: str, body: StatusBody, request: Request, actor: _Practitioner
) -> Response:
    key = idempotency_key(request)
    status = _visit_state(body.status)
    container = await _signed(request, actor)

    async def run() -> Response:
        answer = await UpdateVisitStatus(
            container.uow_factory,
            container.clock,
            ReportsNotReached(
                ReportNotReached(
                    container.uow_factory,
                    UnitOfWorkIdempotency(container.uow_factory),
                    container.clock,
                )
            ),
        ).execute(actor, offer_id, status, body.etaMinutes)
        return _json(200, {"id": answer.id, "state": answer.state.value})

    return await _answer(
        lambda: replay_or_run(request, actor, f"visit-status:{offer_id}:{key}", run)
    )


@router.post("/visits/offers")
async def offer_visit(body: OfferBody, request: Request, actor: _Offerer) -> Response:
    # No replay cache here: it keeps a digest of the whole body, and this body holds an address
    # and a contact, which must not leave a digest anywhere. A repeat is the use case's 409 (a
    # booking is offered once), which is safe and honest.
    container = _container(request)

    async def run() -> Response:
        result = await OfferVisit(
            container.uow_factory, container.clock, container.ids, container.sealer
        ).execute(actor, body.bookingId, body.postcode, body.address, body.contact)
        return _json(201, {"offeredTo": result.offered_to, "expiresAt": _stamp(result.expires_at)})

    return await _answer(run)


__all__ = ["router"]
