"""Coverage by postcode district over HTTP (DEC-1305). Thin: each route runs one use case and maps
the result to camelCase JSON. Not FHIR resources, so at the root, not under /fhir.

GET /planning/coverage?window=all|night|morning|afternoon|evening
    shift lead or executive; {window, districts:[{district, services:[names]}],
    uncovered:{count|null, suppressed, days}}. A count under 10 is withheld (DEC-393).
GET /lead/services/{id}/coverage
    shift lead; {service:{id,name}, available, others:[{district,service}], districts,
    responseHours|null, days}
PUT /lead/services/{id}/coverage
    shift lead; Idempotency-Key required; {districts, responseHours (1..72), days (mon..sun)};
    answers the same body as the GET.

Refusals: a role that may not use the route is the non-revealing 404 (require_role). A service that
is not the caller's tenant's is a 404 like an unknown one. A bad element is a 400 that names it.
Every answer is no-store. Tenancy: bound at the edge from the verified token (TEN-018); nothing is
read from the body or the query for it.
"""

import json
from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from overwatch.adapters.inbound.fhir_rest.app import get_container
from overwatch.adapters.inbound.fhir_rest.auth import require_role
from overwatch.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.ids import IdGenerator
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.coverage import (
    PLANNERS,
    CoverageByWindow,
    GetCoverageByWindow,
    GetServiceCoverage,
    ServiceCoverageView,
    SetServiceCoverage,
)
from overwatch.domain.codes import Role
from overwatch.domain.errors import ValidationFailed

router = APIRouter()

NO_STORE: Final = {"Cache-Control": "no-store"}
_BODY_KEYS: Final = frozenset({"districts", "responseHours", "days"})


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...
    @property
    def ids(self) -> IdGenerator: ...
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


def window_json(result: CoverageByWindow) -> dict[str, Any]:
    return {
        "window": result.window,
        "districts": [
            {"district": item.district, "services": list(item.services)}
            for item in result.districts
        ],
        "uncovered": {
            "count": result.uncovered.count,
            "suppressed": result.uncovered.suppressed,
            "days": result.uncovered.days,
        },
    }


def service_json(view: ServiceCoverageView) -> dict[str, Any]:
    return {
        "service": {"id": view.service_id, "name": view.service_name},
        "available": list(view.available),
        "others": [{"district": item.district, "service": item.service} for item in view.others],
        "districts": list(view.districts),
        "responseHours": view.response_hours,
        "days": list(view.days),
    }


def setting_body(raw: bytes) -> dict[str, Any]:
    """The three answers of a save, and nothing else."""
    try:
        body = json.loads(raw)
    except ValueError:
        raise ValidationFailed("body", "is not valid JSON") from None
    if not isinstance(body, dict):
        raise ValidationFailed("body", "must be a JSON object")
    if set(body) - _BODY_KEYS:
        raise ValidationFailed("body", "names a value this route does not take")
    return body


@router.get("/planning/coverage")
async def planning_coverage(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*PLANNERS))],
) -> Response:
    container = _container(request)
    result = await GetCoverageByWindow(container.uow_factory, container.clock).execute(
        actor, request.query_params.get("window", "all")
    )
    return JSONResponse(window_json(result), headers=NO_STORE)


@router.get("/lead/services/{service_id}/coverage")
async def read_service_coverage(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    view = await GetServiceCoverage(_container(request).uow_factory).execute(actor, service_id)
    return JSONResponse(service_json(view), headers=NO_STORE)


@router.put("/lead/services/{service_id}/coverage")
async def set_service_coverage(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    key = idempotency_key(request)
    body = setting_body(await request.body())
    container = _container(request)

    async def run() -> Response:
        view = await SetServiceCoverage(
            container.uow_factory, container.clock, container.ids
        ).execute(
            actor, service_id, body.get("districts"), body.get("responseHours"), body.get("days")
        )
        return JSONResponse(service_json(view), headers=NO_STORE)

    return await replay_or_run(request, actor, f"lead-coverage:{service_id}:{key}", run)


__all__ = ["router"]
