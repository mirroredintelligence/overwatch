"""The network reads of the shift lead's pages and the week summary (TEN-082 and the network
variants of W17 and W43). JSON outside `/fhir`, never cached, as `routes_network`.

GET /network/{id}/system-now   the counts of the network board by status, the services and
                               organisations shown, the pressure and the network pressure alert (a
                               state, raised while the pressure is HIGH; no task, no push). Every
                               role that sees a network (advisor, clinical, lead, owner, exec).
GET /network/{id}/phones       one row per service in the network: organisation, service, status
                               and the service line the organisation shared. Never a reporter's
                               number. The same roles.
GET /network/{id}/week         the week summary, capacity-derived only: `weekStart` (a Monday) is
                               required. Role exec or lead.

Every refusal is the one 404 of the network routes: a network outside the token's claim, a tenant
that is not an active member, an unknown network and a role the route does not allow cannot be told
apart (the claim routes and the registry decides, DEC-548). No body names a tenant, a grant or a
member's own service id.
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.routes_network import (
    NO_STORE,
    NetworkId,
    NetworkViewer,
    ensure_in_claim,
    network_services,
)
from diucs.application.actor import Actor
from diucs.application.use_cases.network_lead_views import (
    NetworkPhones,
    NetworkSystemNow,
    QueryPhones,
    QuerySystemNow,
)
from diucs.application.use_cases.network_week_summary import (
    READERS,
    NetworkWeekSummary,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.network_sample import WeekMeasure

router = APIRouter()
WeekReader = Annotated[Actor, Depends(require_role(*sorted(READERS)))]


def _time(value: Any) -> str | None:
    return None if value is None else str(value.isoformat())


def system_now_to_dict(view: NetworkSystemNow) -> dict[str, Any]:
    return {
        "generated_at": _time(view.generated_at),
        "services": view.services,
        "organisations": view.organisations,
        "by_status": dict(view.by_status),
        "pressure": view.pressure.value,
        "all_limited_or_worse": view.all_limited_or_worse,
        "alert": {
            "raised": view.alert.raised,
            "level": view.alert.level.value,
            "limited_or_worse": view.alert.limited_or_worse,
            "watch_from": view.alert.watch_from,
            "high_from": view.alert.high_from,
        },
        "system_name": view.system_name,
        "pathway_name": view.pathway_name,
        "time_zone": view.time_zone,
    }


def phones_to_dict(view: NetworkPhones) -> dict[str, Any]:
    return {
        "phones": [
            {
                "row_ref": p.row_ref,
                "organisation_name": p.organisation_name,
                "service_name": p.service_name,
                "category": p.category.value,
                "presentation": p.presentation.value,
                "status": None if p.status is None else p.status.value,
                "stale_warning": p.stale_warning,
                "reported_at": _time(p.reported_at),
                "contact_label": p.contact_label,
                "contact_phone": p.contact_phone,
            }
            for p in view.phones
        ],
        "organisations": view.organisations,
        "system_name": view.system_name,
        "pathway_name": view.pathway_name,
        "time_zone": view.time_zone,
    }


def _measure(measure: WeekMeasure) -> dict[str, Any]:
    return {"label": measure.label, "value": measure.value, "hidden": measure.hidden}


def week_to_dict(view: NetworkWeekSummary) -> dict[str, Any]:
    week = view.week
    return {
        "week_start": view.week_start.isoformat(),
        "withheld": week.withheld,
        "hours_sampled": _measure(week.hours_sampled),
        "on_time_pct": _measure(week.on_time_pct),
        "status_share": {status.value: _measure(m) for status, m in week.status_share},
        "pressure_hours": {level.value: _measure(m) for level, m in week.pressure_hours},
        "pressure_over_time": [
            {"hour": hour.isoformat(), "pressure": level.value}
            for hour, level in week.pressure_over_time
        ],
        "system_name": view.system_name,
        "pathway_name": view.pathway_name,
        "time_zone": view.time_zone,
    }


def _week_start(request: Request) -> date:
    raw = request.query_params.get("weekStart")
    if raw is None:
        raise ValidationFailed("weekStart", "is required")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValidationFailed("weekStart", "must be a date as YYYY-MM-DD") from None


@router.get("/network/{network_id}/system-now")
async def system_now(network_id: NetworkId, request: Request, actor: NetworkViewer) -> JSONResponse:
    ensure_in_claim(actor, network_id)
    view = await QuerySystemNow(network_services(request).projector).execute(actor, network_id)
    return JSONResponse(system_now_to_dict(view), headers=NO_STORE)


@router.get("/network/{network_id}/phones")
async def phones(network_id: NetworkId, request: Request, actor: NetworkViewer) -> JSONResponse:
    ensure_in_claim(actor, network_id)
    services = network_services(request)
    view = await QueryPhones(services.projector, services.directory).execute(actor, network_id)
    return JSONResponse(phones_to_dict(view), headers=NO_STORE)


@router.get("/network/{network_id}/week")
async def week(network_id: NetworkId, request: Request, actor: WeekReader) -> JSONResponse:
    ensure_in_claim(actor, network_id)
    start = _week_start(request)
    services = network_services(request)
    if services.weeks is None:
        raise RuntimeError("no network week summary is configured")
    view = await services.weeks.execute(actor, network_id, start)
    return JSONResponse(week_to_dict(view), headers=NO_STORE)
