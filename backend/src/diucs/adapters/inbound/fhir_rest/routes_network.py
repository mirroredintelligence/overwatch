"""The network read routes (TEN-059, DEC-548, DEC-132 item 4): GET /networks and
GET /network/{network_id}/board, /directory and /criteria.

Not FHIR: a network is not a FHIR resource, and the answers are plain JSON, never cached
(`Cache-Control: no-store`). The routes hold no business rule. Each checks that the network the path
names is one the token's `networks` claim lists (the claim only routes: a network outside it is
answered at once, with no read), then runs one use case, and the use case asks the registry about
the viewer on every call (`NetworkAccess`), which is the authority: a stale claim reads nothing.

Every refusal is the one 404 the rest of the API gives (`NotFound` and `NotAllowed` both map to it):
a network that does not exist, one the tenant never joined, one it left a minute ago, one outside
the claim, and a role that never sees a network cannot be told apart, so network ids and who
belongs to them are not discoverable. No body names a tenant or a grant; a row is referred to by its
listing id.

The services are on `app.state.network_services` (set by the process that serves the app, as the
cache and the secrets are); with none, the routes fail closed with a 500.
"""

from dataclasses import dataclass
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse

from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.application.actor import Actor
from diucs.application.network_access import NETWORK_VIEW_ROLES, NetworkAccess
from diucs.application.use_cases.filter_network_options import FilterNetworkOptions
from diucs.application.use_cases.network_board_projector import (
    NetworkBoardProjector,
    network_board_to_dict,
)
from diucs.application.use_cases.network_week_summary import GetNetworkWeekSummary
from diucs.application.use_cases.query_network_directory import (
    NetworkCriteriaEntry,
    NetworkCriteriaView,
    NetworkDirectoryEntry,
    NetworkDirectoryView,
    QueryNetworkCriteria,
    QueryNetworkDirectory,
)
from diucs.domain.errors import NotFound
from diucs.domain.rules.projection import LocationProjection, OpeningHourProjection

# The network id pattern of the domain (`check_network_id`): `net-` and lower-case letters, digits
# and hyphens, 31 characters at most in all (a test keeps the two equal).
NETWORK_ID_PATTERN: Final = r"^net-[a-z0-9][a-z0-9-]{1,26}$"
NO_STORE: Final = {"Cache-Control": "no-store"}

router = APIRouter()
NetworkViewer = Annotated[Actor, Depends(require_role(*sorted(NETWORK_VIEW_ROLES)))]
NetworkId = Annotated[str, Path(pattern=NETWORK_ID_PATTERN)]


@dataclass(frozen=True, slots=True)
class NetworkServices:
    access: NetworkAccess
    projector: NetworkBoardProjector
    directory: QueryNetworkDirectory
    criteria: QueryNetworkCriteria
    # The week summary reads the samples with its own read-only unit (TEN-082); a process that does
    # not wire it answers the route with a 500, never an empty week.
    weeks: GetNetworkWeekSummary | None = None
    # The network variant of the advisor's options (KI-349), asked through `$filter-options` with a
    # `network` part; a process that does not wire it answers that request with a 500, never an
    # empty list.
    options: FilterNetworkOptions | None = None


def network_services(request: Request) -> NetworkServices:
    # Fail closed: a missing wiring is a configuration error (a 500), never an empty answer.
    services: NetworkServices | None = getattr(request.app.state, "network_services", None)
    if services is None:
        raise RuntimeError("no network services are configured for the network routes")
    return services


def ensure_in_claim(actor: Actor, network_id: str) -> None:
    """The claim routes; it does not authorise. A network the token does not list is answered as a
    network that does not exist, before anything is read."""
    if network_id not in actor.network_ids:
        raise NotFound("the network was not found")


def _time(value: Any) -> str | None:
    return None if value is None else str(value.isoformat())


def _location(location: LocationProjection | None) -> dict[str, Any] | None:
    if location is None:
        return None
    return {
        "location_name": location.location_name,
        "postal_district": location.postal_district,
        "city": location.city,
        "latitude": location.latitude,
        "longitude": location.longitude,
    }


def _hour(hour: OpeningHourProjection) -> dict[str, Any]:
    return {
        "position": hour.position,
        "days": list(hour.days),
        "all_day": hour.all_day,
        "start": None if hour.start is None else hour.start.strftime("%H:%M"),
        "end": None if hour.end is None else hour.end.strftime("%H:%M"),
    }


def _end(entry: NetworkDirectoryEntry | NetworkCriteriaEntry) -> dict[str, Any]:
    return {
        "ended_at": _time(entry.ended_at),
        "end_reason": None if entry.end_reason is None else entry.end_reason.value,
    }


def directory_to_dict(view: NetworkDirectoryView) -> dict[str, Any]:
    return {
        "entries": [
            {
                "row_ref": e.row_ref,
                "organisation_name": e.organisation_name,
                "service_name": e.service_name,
                "category": e.category.value,
                "active": e.active,
                "source": e.source.value,
                "contact_label": e.contact_label,
                "contact_phone": e.contact_phone,
                "location": _location(e.location),
                "opening_hours": [_hour(h) for h in e.opening_hours],
                "presentation": e.presentation.value,
                **_end(e),
            }
            for e in view.entries
        ],
        "system_name": view.system_name,
        "pathway_name": view.pathway_name,
        "time_zone": view.time_zone,
    }


def criteria_to_dict(view: NetworkCriteriaView) -> dict[str, Any]:
    return {
        "entries": [
            {
                "row_ref": e.row_ref,
                "organisation_name": e.organisation_name,
                "service_name": e.service_name,
                "version": e.version,
                "age_min": e.age_min,
                "age_max": e.age_max,
                "districts": list(e.districts),
                "accepts": [need.value for need in e.accepts],
                "excludes": [need.value for need in e.excludes],
                "review_by": e.review_by.isoformat(),
                **_end(e),
            }
            for e in view.entries
        ],
        "system_name": view.system_name,
        "pathway_name": view.pathway_name,
        "time_zone": view.time_zone,
    }


@router.get("/networks")
async def networks(request: Request, actor: NetworkViewer) -> JSONResponse:
    contexts = await network_services(request).access.networks_of(actor)
    return JSONResponse(
        {
            "networks": [
                {
                    "id": c.network.id,
                    "name": c.network.name,
                    "system_name": c.settings.system_name,
                    "pathway_name": c.settings.pathway_name,
                    "time_zone": c.settings.time_zone,
                }
                for c in contexts
            ]
        },
        headers=NO_STORE,
    )


@router.get("/network/{network_id}/board")
async def board(network_id: NetworkId, request: Request, actor: NetworkViewer) -> JSONResponse:
    ensure_in_claim(actor, network_id)
    view = await network_services(request).projector.get_board(actor, network_id)
    return JSONResponse(network_board_to_dict(view), headers=NO_STORE)


@router.get("/network/{network_id}/directory")
async def directory(
    network_id: NetworkId, request: Request, actor: NetworkViewer, history: bool = False
) -> JSONResponse:
    ensure_in_claim(actor, network_id)
    view = await network_services(request).directory.execute(actor, network_id, history=history)
    return JSONResponse(directory_to_dict(view), headers=NO_STORE)


@router.get("/network/{network_id}/criteria")
async def criteria(
    network_id: NetworkId, request: Request, actor: NetworkViewer, history: bool = False
) -> JSONResponse:
    ensure_in_claim(actor, network_id)
    view = await network_services(request).criteria.execute(actor, network_id, history=history)
    return JSONResponse(criteria_to_dict(view), headers=NO_STORE)
