"""The planning analysis over HTTP (W51, U43).

GET /planning?period=30d|90d|12m&need=all|falls-frailty|iv-therapy|palliative
    shift lead or executive; the aggregates of the closed cases of the period (RunPlanningAnalysis).

The answer is aggregates only (DEC-393): a count under 10 is `null` with `suppressed: true`, and
so is a share whose base is under 10 and every cell of the day-by-time grid under 10 (a hidden cell
is not a zero). No case id, reference, postcode, practitioner or advisor is in it. The route is at
the root, not under /fhir: it is not a FHIR resource.

Tenancy: the tenant is bound at the REST edge from the verified token (TEN-018), by require_role.
Nothing here reads a tenant from the body, the query or a header.
"""

from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.planning_analysis import (
    ALLOWED_ROLES,
    BANDS,
    HiddenCount,
    PlanningQuery,
    PlanningResult,
    RunPlanningAnalysis,
    RunPlanningCommand,
)
from diucs.domain.errors import ValidationFailed

router = APIRouter()

PERIOD_DAYS: Final = {"30d": 30, "90d": 90, "12m": 365}
NEED_GROUP: Final = {
    "all": "all",
    "falls-frailty": "falls-and-frailty",
    "iv-therapy": "iv-therapy",
    "palliative": "palliative",
}
NEED_WORDS: Final = {
    "all": "all needs",
    "falls-and-frailty": "falls and frailty",
    "iv-therapy": "IV therapy",
    "palliative": "palliative",
}
NO_STORE: Final = {"Cache-Control": "no-store"}
DAYS: Final = 7


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...


def query_from(period: str | None, need: str | None) -> PlanningQuery:
    """The browser's period and need as the use case's. An unlisted value is a 400 that names it."""
    days = PERIOD_DAYS.get(period or "")
    if days is None:
        raise ValidationFailed("period", "must be 30d, 90d or 12m")
    group = NEED_GROUP.get(need or "")
    if group is None:
        raise ValidationFailed("need", "must be all, falls-frailty, iv-therapy or palliative")
    return PlanningQuery(period_days=days, need_group=group)


def cohort_text(query: PlanningQuery) -> str:
    return (
        f"Cohort: age 65+, {NEED_WORDS[query.need_group]}, within 2 hrs, ambulance crew or care "
        "home referrers. Groups under 10 are hidden."
    )


def _figure(count: HiddenCount) -> dict[str, Any]:
    return {"count": count.value, "suppressed": count.hidden}


def planning_json(result: PlanningResult, query: PlanningQuery) -> dict[str, Any]:
    grid: list[list[int | None]] = [
        [
            result.heat[(day, label)].value if (day, label) in result.heat else None
            for _, _, label in BANDS
        ]
        for day in range(DAYS)
    ]
    busiest: dict[str, int] | None = None
    if result.busiest is not None:
        day, label = result.busiest
        band = [name for _, _, name in BANDS].index(label)
        count = result.heat[result.busiest].value
        busiest = {"day": day, "band": band, "count": count or 0}
    unavailable = result.best_fit_unavailable
    return {
        "cohort": cohort_text(query),
        "referrals": _figure(result.referrals),
        "bestFitUnavailable": {
            "count": unavailable.value,
            "pct": result.best_fit_unavailable_pct.value,
            "suppressed": unavailable.hidden,
        },
        "wentElsewhere": _figure(result.went_elsewhere),
        "flows": [
            {
                "bestFit": flow.best_fit,
                "state": flow.state,
                "wentTo": flow.destination,
                "count": flow.count.value,
                "suppressed": flow.count.hidden,
            }
            for flow in result.flows
        ],
        "grid": grid,
        "busiest": busiest,
        "declinedDespite": [
            {"service": name, "count": count.value, "suppressed": count.hidden}
            for name, count in result.declined_despite
        ],
    }


@router.get("/planning")
async def planning(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*ALLOWED_ROLES))],
) -> Response:
    query = query_from(
        request.query_params.get("period", "90d"), request.query_params.get("need", "all")
    )
    container = cast(_Container, get_container(request))
    result = await RunPlanningAnalysis(container.uow_factory, container.clock).execute(
        RunPlanningCommand(actor=actor, query=query)
    )
    return JSONResponse(planning_json(result, query), headers=NO_STORE)


__all__ = ["router"]
