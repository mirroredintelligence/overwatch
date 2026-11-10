"""The Advisor v2 reads (DEC-1366): find a service, and the capacity overview. Browse only.

POST /advisor-v2/find       {postcode, ageBand, needs[], urgency}: the services whose criteria
take this
                            patient, with travel from the district's centre, each one's site
                            position and the area it covers, and `notSuitable[]`: every other
                            service on the board with its reasons (DEC-1379). Nothing is stored: no
                            case is
                            opened, and the postcode, age band and needs are used for this answer
                            and dropped.
                            The postcode is read from the body, never from a URL, and never logged.
POST /advisor-v2/services/{id}/check  the same body: does this one service take this patient
                            (DEC-1377); nothing is stored.
POST /advisor-v2/services/{id}/ask    queue a capacity request to the service (DEC-1377).
GET  /advisor-v2/capacity   the five counts, the Needs attention lists (the shift lead's rules),
and one row
                            per service by name.

Who may call: the advisor and Advisor v2 (FIND_ROLES); any other role is the 404 a missing record
gets.
Every answer is no-store. Tenancy: bound at the edge from the verified token; nothing is read from
the body
or the query for it.
"""

import json
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from overwatch.adapters.inbound.fhir_rest.app import get_container
from overwatch.adapters.inbound.fhir_rest.auth import require_role
from overwatch.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from overwatch.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from overwatch.application.actor import Actor
from overwatch.application.idempotency import format_instant
from overwatch.application.use_cases.ask_capacity_now import ASK_ROLES, AskCapacityNow
from overwatch.application.use_cases.find_services import (
    ATTENTION_SHOWN,
    FIND_ROLES,
    CapacityOverview,
    CheckServiceFit,
    CheckServiceFitCommand,
    FindServices,
    FindServicesCommand,
    FoundService,
    NotSuitableService,
    ReadCapacityOverview,
)
from overwatch.application.use_cases.query_board import QueryBoard
from overwatch.domain.codes import AgeBand, NeedCategory, Status, Urgency
from overwatch.domain.errors import ValidationFailed

router = APIRouter(prefix="/advisor-v2")

NO_STORE: Final = {"Cache-Control": "no-store"}
MAX_NEEDS: Final = 9
_COUNT_KEYS: Final = {
    Status.ACCEPTING: "accepting",
    Status.LIMITED: "limited",
    Status.NOT_ACCEPTING: "notAccepting",
    Status.OVER_CAPACITY: "overCapacity",
    Status.NOT_UPDATED: "notUpdated",
}


def _at(value: Any) -> str | None:
    return None if value is None else format_instant(value)


def _enum[E: (AgeBand, Urgency, NeedCategory)](kind: type[E], value: Any, name: str) -> E:
    try:
        return kind(value)
    except ValueError:
        raise ValidationFailed(name, "is not a known value") from None


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = json.loads(await request.body())
    except ValueError:
        raise ValidationFailed("body", "is not valid JSON") from None
    if not isinstance(body, dict):
        raise ValidationFailed("body", "must be a JSON object")
    return body


def _position(position: Any) -> dict[str, float] | None:
    return None if position is None else {"lat": position.lat, "lon": position.lon}


def _coverage(item: FoundService) -> dict[str, Any]:
    circle = item.coverage.circle
    return {
        "districts": list(item.coverage.districts),
        "circle": None
        if circle is None
        else {"lat": circle.lat, "lon": circle.lon, "radiusMeters": circle.radius_km * 1000},
    }


def _not_suitable(item: NotSuitableService) -> dict[str, Any]:
    return {
        "serviceId": item.service_id,
        "name": item.name,
        "category": item.category.value,
        "status": item.status.value,
        "reasons": list(item.reasons),
        "position": _position(item.position),
    }


def _found(item: FoundService) -> dict[str, Any]:
    return {
        "serviceId": item.service_id,
        "name": item.name,
        "category": item.category.value,
        "status": item.status.value,
        "effectiveAvailable": item.effective_available,
        "overBy": item.over_by,
        "unitLabel": item.unit_label,
        "dataAgeSeconds": None if item.data_age is None else int(item.data_age.total_seconds()),
        "reportedAt": _at(item.reported_at),
        "nextDueAt": _at(item.next_due_at),
        "cadence": None if item.cadence is None else item.cadence.value,
        "overdue": item.overdue,
        "staleWarning": item.stale_warning,
        "figureUnavailable": item.figure_unavailable,
        "lastFigure": item.last_figure,
        "criteriaVersion": item.criteria_version,
        "fits": list(item.fits),
        "warnings": list(item.warnings),
        "phone": item.phone,
        "position": _position(item.position),
        "coverage": _coverage(item),
        "travel": None
        if item.travel is None
        else {
            "low": item.travel.low_minutes,
            "high": item.travel.high_minutes,
            "source": item.travel.source,
        },
    }


async def _patient(request: Request) -> tuple[str, AgeBand, tuple[NeedCategory, ...], Urgency]:
    """The body of find and check: the postcode, age band, needs and urgency, validated. Read from
    the body only and never logged."""
    body = await _body(request)
    needs = body.get("needs")
    if not isinstance(needs, list) or not 1 <= len(needs) <= MAX_NEEDS:
        raise ValidationFailed("needs", "must be a list of one or more needs")
    return (
        body.get("postcode"),  # type: ignore[return-value]
        _enum(AgeBand, body.get("ageBand"), "ageBand"),
        tuple(_enum(NeedCategory, need, "needs") for need in needs),
        _enum(Urgency, body.get("urgency"), "urgency"),
    )


@router.post("/find")
async def find(
    request: Request, actor: Annotated[Actor, Depends(require_role(*FIND_ROLES))]
) -> Response:
    postcode, age_band, needs, urgency = await _patient(request)
    command = FindServicesCommand(
        actor=actor, postcode=postcode, age_band=age_band, needs=needs, urgency=urgency
    )
    container = get_container(request)
    result = await FindServices(
        container.uow_factory,
        container.clock,
        QueryBoard(container.uow_factory, container.clock),
        container.postcodes,
        container.travel,
    ).execute(command)
    return FhirJSONResponse(
        content={
            "generatedAt": format_instant(result.generated_at),
            "notFound": result.not_found,
            "groupTotals": {key.value: count for key, count in result.group_totals.items()},
            "services": [_found(item) for item in result.services],
            "notSuitable": [_not_suitable(item) for item in result.not_suitable],
        },
        headers=NO_STORE,
    )


def _overview_body(view: CapacityOverview) -> dict[str, Any]:
    return {
        "generatedAt": _at(view.generated_at),
        "counts": {key: view.counts[status] for status, key in _COUNT_KEYS.items()},
        "attentionShown": ATTENTION_SHOWN,
        "underPressure": [
            {
                "serviceId": item.service_id,
                "name": item.name,
                "status": item.status.value,
                "reason": item.reason,
                "usedPercent": item.used_percent,
            }
            for item in view.under_pressure
        ],
        "underutilised": [
            {
                "serviceId": item.service_id,
                "name": item.name,
                "usedPercent": item.used_percent,
                "spare": item.spare,
                "unitLabel": item.unit_label,
            }
            for item in view.underutilised
        ],
        "services": [
            {
                "serviceId": row.service_id,
                "name": row.name,
                "category": row.category.value,
                "status": row.status.value,
                "effectiveAvailable": row.effective_available,
                "overBy": row.over_by,
                "unitLabel": row.unit_label,
                "reportedAt": _at(row.reported_at),
                "figureUnavailable": row.figure_unavailable,
                "lastFigure": row.last_figure,
                "districts": list(row.districts),
                "area": row.area,
            }
            for row in view.rows
        ],
        "areas": [{"id": a.id, "name": a.name, "places": a.places} for a in view.areas],
    }


@router.get("/capacity")
async def capacity(
    request: Request, actor: Annotated[Actor, Depends(require_role(*FIND_ROLES))]
) -> Response:
    container = get_container(request)
    view = await ReadCapacityOverview(
        container.uow_factory,
        container.clock,
        QueryBoard(container.uow_factory, container.clock),
        getattr(container, "areas", None),
        getattr(container, "postcodes", None),
    ).execute(actor)
    return FhirJSONResponse(content=_overview_body(view), headers=NO_STORE)


@router.post("/services/{service_id}/check")
async def check_service(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*FIND_ROLES))],
) -> Response:
    """Does this one service take this patient (DEC-1377)? The find rule for one service. Nothing
    is stored; the audit entry holds the service id and the result only."""
    postcode, age_band, needs, urgency = await _patient(request)
    container = get_container(request)
    result = await CheckServiceFit(
        container.uow_factory, container.clock, QueryBoard(container.uow_factory, container.clock)
    ).execute(
        CheckServiceFitCommand(
            actor=actor,
            service_id=service_id,
            postcode=postcode,
            age_band=age_band,
            needs=needs,
            urgency=urgency,
        )
    )
    return FhirJSONResponse(
        content={
            "serviceId": result.service_id,
            "fits": result.fits,
            "reasons": list(result.reasons),
            "fitsNeeds": list(result.fits_needs),
            "warnings": list(result.warnings),
            "phone": result.phone,
            "status": result.status.value,
            "figureUnavailable": result.figure_unavailable,
        },
        headers=NO_STORE,
    )


@router.post("/services/{service_id}/ask")
async def ask_service(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*ASK_ROLES))],
) -> Response:
    """Ask the service for its capacity figure now (DEC-1377, DEC-1335): queued, not sent here."""
    key = idempotency_key(request)
    container = get_container(request)

    async def run() -> Response:
        result = await AskCapacityNow(
            container.uow_factory, container.ids, container.clock
        ).execute(actor, service_id)
        return FhirJSONResponse(
            content={"queued": True, "dueAt": _at(result.due_at)}, headers=NO_STORE
        )

    return await replay_or_run(request, actor, f"advisor-v2-ask:{service_id}:{key}", run)
