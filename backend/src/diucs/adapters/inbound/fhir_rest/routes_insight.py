"""The insight console's two routes (W9F): the browser's events in, the five tabs out.

POST /telemetry/ui
    any signed-in role but the platform operator: the BFF sends the batch of its own browser's
    ui.* events (already cut down to the allow-list). They are counted into the tenant's daily
    aggregates and kept nowhere (RecordBrowserEvents). Answers {accepted, dropped}.
GET /support/insight/{tab}?range=24h|7d|30d[&device=phone|tablet|desktop]
    the support role only (the role guard runs first: another role gets the non-revealing 404).
    tab is funnels, paths, friction, performance or releases. Aggregates only: a group under ten
    sessions has no number, no figure names a person, and no advisor is ranked (observability.md).

Both are at the root, not under /fhir. Tenancy: the tenant is bound at the REST edge from the
verified token (TEN-018) by the role guard or `current_actor`; nothing here reads a tenant from a
body, a query or a header. The role counted for an event is the token's, not the browser's claim.
"""

from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import current_actor, require_role
from diucs.adapters.inbound.fhir_rest.errors import operation_outcome
from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import secret_is_configured
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.browser_insight import (
    ReadInsightTab,
    RecordBrowserEvents,
    ReleasesView,
)
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.browser_insight import MARKER_SECRET, MAX_BATCH_EVENTS
from diucs.domain.rules.insight_views import (
    FrictionTable,
    FunnelView,
    PathsView,
    PerformanceView,
)

router = APIRouter()

TABS: Final = ("funnels", "paths", "friction", "performance", "releases")
NO_STORE: Final = {"Cache-Control": "no-store"}
UNAVAILABLE_TEXT: Final = "Telemetry counting is not set up on this server."
_MAX_ATTRIBUTES: Final = 30
_MAX_TEXT: Final = 120


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...
    @property
    def secrets(self) -> SecretStore: ...


class EventBody(BaseModel):
    # `at` (the browser's clock) and any other key are ignored: the day is the server's.
    model_config = ConfigDict(extra="ignore")

    name: Annotated[str, StringConstraints(max_length=40)]
    attributes: dict[
        Annotated[str, StringConstraints(max_length=40)],
        Annotated[str, StringConstraints(max_length=_MAX_TEXT)] | int | float | bool,
    ] = Field(max_length=_MAX_ATTRIBUTES)


class EventsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[EventBody] = Field(max_length=MAX_BATCH_EVENTS)


@router.post("/telemetry/ui")
async def record_events(
    body: EventsBody,
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
) -> Response:
    container = cast(_Container, get_container(request))
    if not body.events:
        return JSONResponse({"accepted": 0, "dropped": 0}, headers=NO_STORE)
    if not secret_is_configured(container.secrets, MARKER_SECRET):
        # Fail closed: counting without the key would have to keep the session ids.
        return operation_outcome(503, "transient", UNAVAILABLE_TEXT, headers=NO_STORE)
    result = await RecordBrowserEvents(
        container.uow_factory, container.clock, container.secrets
    ).execute(actor, [{"name": e.name, "attributes": e.attributes} for e in body.events])
    return JSONResponse({"accepted": result.accepted, "dropped": result.dropped}, headers=NO_STORE)


# ---- the shapes the console reads ---------------------------------------------------------------


def funnels_json(views: list[FunnelView], range_name: str, device: str | None) -> dict[str, Any]:
    return {
        "tab": "funnels",
        "range": range_name,
        "device": device,
        "funnels": [
            {
                "name": view.name,
                "label": view.label,
                "steps": [
                    {
                        "name": step.name,
                        "count": step.count,
                        "pct": step.pct,
                        "suppressed": step.suppressed,
                    }
                    for step in view.steps
                ],
                "split": [
                    {"channel": item.channel, "pct": item.pct, "suppressed": item.suppressed}
                    for item in view.split
                ],
            }
            for view in views
        ],
    }


def paths_json(view: PathsView, range_name: str, device: str | None) -> dict[str, Any]:
    def row(route: str, sessions: int | None, suppressed: bool) -> dict[str, Any]:
        return {
            "route": route,
            "sessions": sessions,
            "medianSeconds": None,
            "suppressed": suppressed,
        }

    return {
        "tab": "paths",
        "range": range_name,
        "device": device,
        "mostCommon": [row(u.route, u.sessions, u.suppressed) for u in view.most_common],
        "uTurns": [row(u.route, u.sessions, u.suppressed) for u in view.u_turns],
        # The controls nobody used need the list of every control, which the back end does not
        # hold: said as "not measured", never as an empty list.
        "unused": None,
    }


def friction_json(table: FrictionTable, range_name: str, device: str | None) -> dict[str, Any]:
    return {
        "tab": "friction",
        "range": range_name,
        "device": device,
        "rows": [
            {
                "elementId": row.element_id,
                "kind": row.kind,
                "route": row.route,
                "events": row.events,
                "interactions": row.interactions,
                "rate": row.rate,
                "review": row.review,
            }
            for row in table.rows
        ],
        "suppressedGroups": table.suppressed_groups,
    }


def performance_json(view: PerformanceView, range_name: str, device: str | None) -> dict[str, Any]:
    return {
        "tab": "performance",
        "range": range_name,
        "device": device,
        "vitals": [
            {
                "measure": vital.label,
                "metric": vital.measure,
                "device": vital.device,
                "p75": vital.p75,
                "budget": vital.budget,
                "unit": vital.unit,
                "suppressed": vital.suppressed,
            }
            for vital in view.vitals
        ],
        "slowestRoutes": [{"name": s.name, "p95Ms": s.p95_ms} for s in view.slowest_routes],
        "slowestQueries": [{"name": s.name, "p95Ms": s.p95_ms} for s in view.slowest_queries],
        # Prompt to board needs the trace from the scheduler to the stream; not counted here.
        "promptToBoard": None,
    }


def releases_json(view: ReleasesView, range_name: str) -> dict[str, Any]:
    compare = view.compare
    return {
        "tab": "releases",
        "range": range_name,
        "compare": None if compare is None else {"old": compare.old, "new": compare.new},
        "measures": []
        if compare is None
        else [
            {
                "measure": m.measure,
                "old": m.old,
                "new": m.new,
                "unit": m.unit,
                "review": m.review,
            }
            for m in compare.measures
        ],
        "pipeline": [
            {
                "name": p.name,
                "active": p.active,
                "deadLettered": p.dead_lettered,
                "oldestSeconds": p.oldest_seconds,
            }
            for p in view.pipeline
        ],
    }


@router.get("/support/insight/{tab}")
async def insight(
    tab: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.SUPPORT))],
    range_name: Annotated[str, Query(alias="range")] = "7d",
    device: str | None = None,
) -> Response:
    if tab not in TABS:
        raise ValidationFailed("tab", "must be funnels, paths, friction, performance or releases")
    container = cast(_Container, get_container(request))
    read = ReadInsightTab(container.uow_factory, container.clock)
    body: dict[str, Any]
    if tab == "funnels":
        body = funnels_json(await read.funnels(actor, range_name, device), range_name, device)
    elif tab == "paths":
        body = paths_json(await read.paths(actor, range_name, device), range_name, device)
    elif tab == "friction":
        body = friction_json(await read.friction(actor, range_name, device), range_name, device)
    elif tab == "performance":
        body = performance_json(
            await read.performance(actor, range_name, device), range_name, device
        )
    else:
        if device is not None:
            raise ValidationFailed("device", "does not apply to the release comparison")
        body = releases_json(await read.releases(actor, range_name), range_name)
    return JSONResponse(body, headers=NO_STORE)
