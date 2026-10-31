"""Booking Tasks over FHIR (R09) and the advisor's acknowledgement of a withdrawal (R17).

POST /fhir/Task                     open a booking request (RequestBooking, U17); advisor, clinical
GET  /fhir/Task/{id}                read a booking; a reporter sees the projection of their service
PUT  /fhir/Task/{id}                refused: booking status changes only through operations (405)
POST /fhir/Task/{id}/$respond       confirm or decline (RespondToBooking, U18); reporter
POST /fhir/Task/{id}/$cancel        cancel (CancelBooking, U20); advisor or clinical
POST /fhir/Task/{id}/$withdraw      withdraw a confirmed booking (WithdrawBooking, U21); reporter
POST /fhir/Task/{id}/$not-reached   report a confirmed patient not reached (U21); reporter
POST /fhir/Task/{id}/$acknowledge   the advisor has seen a withdrawal or a not-reached booking
                                    (AcknowledgeWithdrawal, U21); advisor or clinical (R17)

The routes hold no business rule: each one reads the request's shape, calls one use case and answers
with the Task as stored, projected for the caller (`PROJECTIONS`, R02). The tenant is the signed
token's and nothing else (TEN-018). A booking of another tenant, or of another service for a
reporter, answers the same 404 as an unknown id.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from fhir.resources.R4B.task import Task

from diucs.adapters.fhir_shared.booking_task import booking_to_fhir
from diucs.adapters.inbound.fhir_rest import capability
from diucs.adapters.inbound.fhir_rest.app import ApiContainer, get_container
from diucs.adapters.inbound.fhir_rest.auth import PROJECTIONS, current_actor, require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.clinical_mapping import clinical_task
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key
from diucs.adapters.inbound.fhir_rest.errors import operation_outcome
from diucs.adapters.inbound.fhir_rest.mapping import validate_outbound
from diucs.application.actor import Actor
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.uow_idempotency import UnitOfWorkIdempotency
from diucs.application.use_cases.cancel_booking import CancelBooking, CancelBookingCommand
from diucs.application.use_cases.clinical_advice import ReadClinicalRequest
from diucs.application.use_cases.query_board import QueryBoard
from diucs.application.use_cases.request_booking import (
    RequestBooking,
    RequestBookingCommand,
)
from diucs.application.use_cases.respond_to_booking import (
    RespondToBooking,
    RespondToBookingCommand,
)
from diucs.application.use_cases.withdraw_booking import (
    AcknowledgeWithdrawal,
    AcknowledgeWithdrawalCommand,
    ReportNotReached,
    ReportNotReachedCommand,
    WithdrawBooking,
    WithdrawBookingCommand,
)
from diucs.domain.codes import (
    BASE_URL,
    BookingStatus,
    CancelReason,
    DeclineReason,
    NotReachedReason,
    ReportSource,
    Role,
    WithdrawReason,
)
from diucs.domain.errors import InvalidTransition, NotFound, ValidationFailed
from diucs.domain.model.booking import Booking
from diucs.domain.rules.booking_response import responder_may_act

BOOKING_REQUEST: Final = "booking-request"
_FOCUS: Final = re.compile(r"ServiceRequest/([A-Za-z0-9.-]{1,64})")
OPERATION_BASE: Final = f"{BASE_URL}OperationDefinition/"
CREATE_ROLES: Final = (Role.ADVISOR, Role.CLINICAL)
NO_BOOKING: Final = "no booking with this id"
PUT_REFUSED: Final = "Booking status changes only through operations."
NOT_ACKNOWLEDGEABLE: Final = "Only a withdrawn or not-reached booking can be acknowledged."
SEEING_ROLES: Final = (Role.ADVISOR, Role.CLINICAL)

router = APIRouter(prefix="/fhir")
capability.register_resource(
    "Task",
    ("create", "read", "search-type"),
    tuple(
        f"{OPERATION_BASE}{name}"
        for name in ("respond", "cancel", "withdraw", "not-reached", "acknowledge")
    ),
)


@dataclass(frozen=True, slots=True)
class BookingRequestBody:
    """The case and the service of a booking request: the focus and the owner of the Task."""

    case_id: str
    service_id: str


# -- request bodies (pure) -------------------------------------------------------------------------


def _reference(item: Any, element: str, resource: str) -> str:
    reference = item.get("reference") if isinstance(item, dict) else None
    prefix = f"{resource}/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ValidationFailed(element, f"must be a reference to a {resource}")
    value = reference.removeprefix(prefix)
    if not value:
        raise ValidationFailed(element, f"must be a reference to a {resource}")
    return value


def parse_booking_request(body: Any) -> BookingRequestBody:
    """A Task with the booking-request code, its focus (the case) and its owner (the service)."""
    if not isinstance(body, dict) or body.get("resourceType") != "Task":
        raise ValidationFailed("body", "must be a Task resource")
    code = body.get("code")
    codings = code.get("coding", []) if isinstance(code, dict) else []
    if not any(isinstance(c, dict) and c.get("code") == BOOKING_REQUEST for c in codings):
        raise ValidationFailed("code", f"must be {BOOKING_REQUEST}")
    return BookingRequestBody(
        case_id=_reference(body.get("focus"), "focus", "ServiceRequest"),
        service_id=_reference(body.get("owner"), "owner", "HealthcareService"),
    )


def parameters_by_name(body: Any) -> dict[str, list[dict[str, Any]]]:
    """The parts of a Parameters body, grouped by name (a name may repeat)."""
    if not isinstance(body, dict) or body.get("resourceType") != "Parameters":
        raise ValidationFailed("body", "must be a Parameters resource")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in body.get("parameter", []):
        if not isinstance(item, dict):
            raise ValidationFailed("parameter", "must be a named part")
        grouped.setdefault(str(item.get("name")), []).append(item)
    return grouped


def _one_code(grouped: dict[str, list[dict[str, Any]]], name: str, *, required: bool) -> str | None:
    parts = grouped.get(name, [])
    if not parts:
        if required:
            raise ValidationFailed(name, "is required")
        return None
    if len(parts) > 1:
        raise ValidationFailed(name, "is given once")
    value = parts[0].get("valueCode")
    if not isinstance(value, str) or not value:
        raise ValidationFailed(name, "must be a code")
    return value


def _member[E](enum_cls: type[E], code: str, element: str) -> E:
    """The member of `enum_cls` with this code. The code is looked up as text, so a member of
    another enum with the same value is refused (lesson L3)."""
    try:
        return enum_cls(code)  # type: ignore[call-arg]
    except ValueError:
        raise ValidationFailed(element, "is not a known reason") from None


def _required_code(grouped: dict[str, list[dict[str, Any]]], name: str) -> str:
    code = _one_code(grouped, name, required=True)
    if code is None:
        raise ValidationFailed(name, "is required")
    return code


def decision_of(grouped: dict[str, list[dict[str, Any]]]) -> Literal["confirm", "decline"]:
    decision = _required_code(grouped, "decision")
    if decision == "confirm":
        return "confirm"
    if decision == "decline":
        return "decline"
    raise ValidationFailed("decision", "must be confirm or decline")


def decline_reason_of(grouped: dict[str, list[dict[str, Any]]]) -> DeclineReason | None:
    code = _one_code(grouped, "reason", required=False)
    if code is None:
        return None
    return _member(DeclineReason, code, "reason")


def cancel_reason_of(grouped: dict[str, list[dict[str, Any]]]) -> CancelReason:
    return _member(CancelReason, _required_code(grouped, "reason"), "reason")


def withdraw_reason_of(grouped: dict[str, list[dict[str, Any]]]) -> WithdrawReason:
    return _member(WithdrawReason, _required_code(grouped, "reason"), "reason")


def not_reached_reason_of(grouped: dict[str, list[dict[str, Any]]]) -> NotReachedReason:
    return _member(NotReachedReason, _required_code(grouped, "reason"), "reason")


def check_acknowledgement_body(body: Any) -> None:
    """An acknowledgement takes no parameters: no body, or a Parameters resource with none."""
    if body is None:
        return
    grouped = parameters_by_name(body)
    if grouped:
        raise ValidationFailed("parameter", "the acknowledgement takes no parameters")


def acknowledgement_path(status: BookingStatus) -> Literal["withdrawn", "not-reached"] | None:
    """What an acknowledgement does for a booking: withdrawn cancels the escalation, not-reached has
    nothing to cancel. Any other status is refused (None)."""
    if status is BookingStatus.WITHDRAWN:
        return "withdrawn"
    if status is BookingStatus.NOT_REACHED:
        return "not-reached"
    return None


# -- the request and the answer --------------------------------------------------------------------


async def _json(request: Request) -> Any:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise ValidationFailed("body", "is not valid JSON") from None


async def _optional_json(request: Request) -> Any:
    raw = await request.body()
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except ValueError:
        raise ValidationFailed("body", "is not valid JSON") from None


async def _delivery_of(uow: UnitOfWork, booking: Booking) -> str | None:
    """The delivery state of the message that asked the service (queued, sent, delivered, failed),
    or None when the booking has no message or the message is gone (H-494)."""
    if booking.request_message_id is None:
        return None
    message = await uow.communications.get(booking.request_message_id)
    return None if message is None else message.delivery_status


async def _seen(uow: UnitOfWork, booking: Booking, actor: Actor) -> dict[str, Any]:
    delivery = await _delivery_of(uow, booking)
    task = Task.model_validate(booking_to_fhir(booking, delivery_status=delivery))
    seen = PROJECTIONS.project(task, actor)
    return validate_outbound(seen.model_dump(by_alias=True, exclude_none=True, mode="json"))


async def _booking_seen_by(
    factory: UnitOfWorkFactory, booking_id: str, actor: Actor
) -> dict[str, Any]:
    """The booking as the caller may see it: the stored Task, with the delivery state of its request
    read now, projected for the caller's role (R02). A reporter's view of another service's booking
    is refused before this is called."""
    async with factory() as uow:
        booking = await uow.bookings.get(booking_id)
        if booking is None:
            raise NotFound(NO_BOOKING)
        return await _seen(uow, booking, actor)


def _search_bundle(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(entries),
        "entry": [{"fullUrl": f"Task/{task['id']}", "resource": task} for task in entries],
    }


def parse_search(query: Mapping[str, str]) -> tuple[Literal["case", "alerts"], str]:
    """What a search of bookings asks for: the bookings of one case (`focus=ServiceRequest/<id>`) or
    the open alerts (`alert=open`), one of the two and nothing else. Anything else is refused, and
    the message names the parameter, never the value."""
    names = set(query)
    if names == {"focus"}:
        match = _FOCUS.fullmatch(query["focus"])
        if match is None:
            raise ValidationFailed("focus", "must be ServiceRequest/<case id>")
        return "case", match.group(1)
    if names == {"alert"}:
        if query["alert"] != "open":
            raise ValidationFailed("alert", "must be open")
        return "alerts", ""
    raise ValidationFailed("search", "name focus or alert, and nothing else")


def _request_booking(container: ApiContainer) -> RequestBooking:
    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, container.secrets, container.clock)

    return RequestBooking(
        container.uow_factory,
        UnitOfWorkIdempotency(container.uow_factory),
        tokens,
        container.clock,
        container.ids,
        container.rng,
        QueryBoard(container.uow_factory, container.clock),
        container.sealer,
        container.wording_for,
        link_base_url_for=container.link_base_url_for,
    )


# -- routes ----------------------------------------------------------------------------------------


@router.post("/Task")
async def create_booking(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CREATE_ROLES))],
) -> Response:
    key = idempotency_key(request)
    target = parse_booking_request(await _json(request))
    container = get_container(request)
    result = await _request_booking(container).execute(
        RequestBookingCommand(
            idempotency_key=key,
            actor=actor,
            case_id=target.case_id,
            service_id=target.service_id,
        )
    )
    content = await _booking_seen_by(container.uow_factory, result.booking_id, actor)
    return FhirJSONResponse(
        content=content,
        status_code=201,
        headers={"Location": f"/fhir/Task/{result.booking_id}"},
    )


async def search_bookings(request: Request, actor: Actor) -> Response:
    """The bookings of a case, or the open alerts: for an advisor or a clinician; any other role
    reads the one 404 of an unknown id (WB4). `GET /fhir/Task` is one path with several searches:
    routes_clinical.read_tasks dispatches by its parameters and calls this when no `code` is
    given."""
    if actor.role not in SEEING_ROLES:
        raise NotFound(NO_BOOKING)
    kind, case_id = parse_search(dict(request.query_params))
    container = get_container(request)
    async with container.uow_factory() as uow:
        found = (
            await uow.bookings.for_case(case_id)
            if kind == "case"
            else await uow.bookings.unacknowledged_exceptions()
        )
        entries = [await _seen(uow, booking, actor) for booking in found]
    return FhirJSONResponse(
        content=_search_bundle(entries), status_code=200, headers={"Cache-Control": "no-store"}
    )


@router.get("/Task/{booking_id}")
async def read_booking(
    booking_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
) -> Response:
    container = get_container(request)
    # The same path reads a clinical advice request (W7A, B1): for the advisor who asked and for a
    # clinical advisor. Any other caller of one reads the same NotFound as for an unknown id.
    asked = await ReadClinicalRequest(container.uow_factory, container.clock).execute(
        actor, booking_id
    )
    if asked is not None:
        return FhirJSONResponse(
            content=clinical_task(asked), status_code=200, headers={"Cache-Control": "no-store"}
        )
    if actor.role not in SEEING_ROLES and actor.role is not Role.REPORTER:
        raise NotFound(NO_BOOKING)
    if actor.role is Role.REPORTER:
        async with container.uow_factory() as uow:
            booking = await uow.bookings.get(booking_id)
        if booking is None or not responder_may_act(
            actor.role, actor.service_ids, booking.service_id
        ):
            raise NotFound(NO_BOOKING)
    content = await _booking_seen_by(container.uow_factory, booking_id, actor)
    return FhirJSONResponse(content=content, status_code=200)


@router.put("/Task/{booking_id}")
async def refuse_put(
    booking_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
) -> Response:
    return operation_outcome(405, "not-supported", PUT_REFUSED)


@router.post("/Task/{booking_id}/$respond")
async def respond(
    booking_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.REPORTER))],
) -> Response:
    key = idempotency_key(request)
    grouped = parameters_by_name(await _json(request))
    decision = decision_of(grouped)
    reason = decline_reason_of(grouped)
    container = get_container(request)
    result = await RespondToBooking(
        container.uow_factory,
        UnitOfWorkIdempotency(container.uow_factory),
        container.clock,
        container.ids,
        container.sealer,
    ).execute(
        RespondToBookingCommand(
            idempotency_key=key,
            actor=actor,
            booking_id=booking_id,
            decision=decision,
            reason=reason,
            channel=ReportSource.APP,
        )
    )
    if result.already_final:
        raise InvalidTransition("this booking has already been answered")
    content = await _booking_seen_by(container.uow_factory, booking_id, actor)
    return FhirJSONResponse(content=content, status_code=200)


@router.post("/Task/{booking_id}/$cancel")
async def cancel(
    booking_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CREATE_ROLES))],
) -> Response:
    key = idempotency_key(request)
    reason = cancel_reason_of(parameters_by_name(await _json(request)))
    container = get_container(request)
    await CancelBooking(
        container.uow_factory,
        UnitOfWorkIdempotency(container.uow_factory),
        container.clock,
        container.ids,
        container.sealer,
    ).execute(
        CancelBookingCommand(idempotency_key=key, actor=actor, booking_id=booking_id, reason=reason)
    )
    content = await _booking_seen_by(container.uow_factory, booking_id, actor)
    return FhirJSONResponse(content=content, status_code=200)


@router.post("/Task/{booking_id}/$withdraw")
async def withdraw(
    booking_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.REPORTER))],
) -> Response:
    key = idempotency_key(request)
    reason = withdraw_reason_of(parameters_by_name(await _json(request)))
    container = get_container(request)
    await WithdrawBooking(
        container.uow_factory,
        UnitOfWorkIdempotency(container.uow_factory),
        container.clock,
        container.ids,
    ).execute(
        WithdrawBookingCommand(
            idempotency_key=key, actor=actor, booking_id=booking_id, reason=reason
        )
    )
    content = await _booking_seen_by(container.uow_factory, booking_id, actor)
    return FhirJSONResponse(content=content, status_code=200)


@router.post("/Task/{booking_id}/$not-reached")
async def not_reached(
    booking_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.REPORTER))],
) -> Response:
    key = idempotency_key(request)
    reason = not_reached_reason_of(parameters_by_name(await _json(request)))
    container = get_container(request)
    await ReportNotReached(
        container.uow_factory,
        UnitOfWorkIdempotency(container.uow_factory),
        container.clock,
    ).execute(
        ReportNotReachedCommand(
            idempotency_key=key, actor=actor, booking_id=booking_id, reason=reason
        )
    )
    content = await _booking_seen_by(container.uow_factory, booking_id, actor)
    return FhirJSONResponse(content=content, status_code=200)


@router.post("/Task/{booking_id}/$acknowledge")
async def acknowledge(
    booking_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CREATE_ROLES))],
) -> Response:
    key = idempotency_key(request)
    check_acknowledgement_body(await _optional_json(request))
    container = get_container(request)
    async with container.uow_factory() as uow:
        booking = await uow.bookings.get(booking_id)
    if booking is None:
        raise NotFound(NO_BOOKING)
    path = acknowledgement_path(booking.status)
    if path is None:
        return operation_outcome(409, "business-rule", NOT_ACKNOWLEDGEABLE)
    # Both a withdrawal and a not-reached report are acknowledged and stored on the booking
    # (KI-451); only a withdrawal has an escalation to cancel.
    await AcknowledgeWithdrawal(
        container.uow_factory,
        UnitOfWorkIdempotency(container.uow_factory),
        container.clock,
    ).execute(AcknowledgeWithdrawalCommand(idempotency_key=key, actor=actor, booking_id=booking_id))
    at: datetime = container.clock.now()
    body: dict[str, Any] = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "acknowledged", "valueBoolean": True},
            {"name": "acknowledgedAt", "valueDateTime": at.isoformat()},
        ],
    }
    return FhirJSONResponse(content=validate_outbound(body), status_code=200)
