"""The Analytics User's overview over HTTP (DEC-1368). Thin: one route, one use case.

GET /analytics/overview
    Analytics User only; {generatedAt, counts, outOfHours, services:[...], underPressure,
    underutilised}. Figures about the tenant's own services: no case, patient, postcode, phone
    number or outcome. A figure that is old or late carries no number.

Refusals: any other role is the non-revealing 404 (require_role). Every answer is no-store.
Tenancy: bound at the edge from the verified token (TEN-018); nothing is read from the body or the
query for it.
"""

from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from overwatch.adapters.inbound.fhir_rest.app import get_container
from overwatch.adapters.inbound.fhir_rest.auth import require_role
from overwatch.application.actor import Actor
from overwatch.application.idempotency import format_instant
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.analytics_views import (
    ANALYTICS_ROLES,
    AnalyticsOverview,
    GetAnalyticsOverview,
)
from overwatch.domain.codes import Status

router = APIRouter()

NO_STORE: Final = {"Cache-Control": "no-store"}
_COUNT_KEYS: Final = {
    Status.ACCEPTING: "accepting",
    Status.LIMITED: "limited",
    Status.NOT_ACCEPTING: "notAccepting",
    Status.OVER_CAPACITY: "overCapacity",
    Status.NOT_UPDATED: "notUpdated",
}


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...


def overview_json(view: AnalyticsOverview) -> dict[str, Any]:
    return {
        "generatedAt": format_instant(view.generated_at),
        "counts": {key: view.counts[status] for status, key in _COUNT_KEYS.items()},
        "outOfHours": view.out_of_hours,
        "areas": [{"id": a.id, "name": a.name, "places": a.places} for a in view.areas],
        "services": [
            {
                "serviceId": row.service_id,
                "name": row.name,
                "category": row.category.value,
                "status": row.status.value,
                "districts": list(row.districts),
                "area": row.area,
                "figureCurrent": row.figure_current,
                "available": row.available,
                "overBy": row.over_by,
                "unitLabel": row.unit_label,
                "reportedAt": None if row.reported_at is None else format_instant(row.reported_at),
            }
            for row in view.services
        ],
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
    }


@router.get("/analytics/overview")
async def read_overview(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*ANALYTICS_ROLES))],
) -> Response:
    container = cast(_Container, get_container(request))
    view = await GetAnalyticsOverview(
        container.uow_factory,
        container.clock,
        getattr(container, "areas", None),
        getattr(container, "postcodes", None),
    ).execute(actor)
    return JSONResponse(overview_json(view), headers=NO_STORE)


__all__ = ["router"]
