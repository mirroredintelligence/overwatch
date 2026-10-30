"""Alert subscriptions, alert acknowledgement and the week summary over HTTP (R12).

Thin: each route checks its request, runs one use case and maps the result. The mapping lives in
subscription_mapping.py. No rule lives here.

GET    /fhir/Subscription
           exec or lead; the caller's own preferences as a Bundle of one Subscription
           (GetAlertPreferences, U33)
PUT    /fhir/Subscription/{id}
           exec or lead; Idempotency-Key and If-Match; a Subscription body. Another
           practitioner's id is a 404; a stale version is 412 (SaveAlertPreferences, U33)
GET    /fhir/Task?code=acknowledge-alert&owner=me[&status=new|escalated]
           exec or lead; the caller's open alerts (U34)
POST   /fhir/Task/{id}/$acknowledge
           exec or lead; Idempotency-Key; another owner's alert is a 404 (AcknowledgeAlert, U34)
POST   /fhir/Task/{id}/$snooze
           exec or lead; Idempotency-Key; the next escalation moves one hour on
           (SnoozeAlert, U34)
GET    /fhir/HealthcareService/$week-summary?weekStart=YYYY-MM-DD[&scope=tenant]
           exec or lead; weekStart is a Monday; scope=tenant (the network variant is
           reserved); a count under ten is withheld (GetWeekSummary, U35)

An acknowledgement does not change the board. A refused role is a non-revealing 404
(require_role); the platform operator's token is refused at the edge (401). Nothing here carries
patient data.

Tenancy: the tenant is bound at the REST edge from the verified token (TEN-018), by current_actor.
Nothing here reads a tenant from the body, the query or a header.
"""

import json
from datetime import date
from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest import routes_bookings
from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import current_actor, require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.concurrency import (
    check_version,
    idempotency_key,
    replay_or_run,
    require_if_match,
    versioned_response,
)
from diucs.adapters.inbound.fhir_rest.routes_services import UnitOfWorkIdempotency
from diucs.adapters.inbound.fhir_rest.subscription_mapping import (
    LISTED_STATUSES,
    alert_to_task,
    save_command,
    subscription_to_fhir,
    subscription_version,
    summary_parameters,
)
from diucs.application.actor import Actor
from diucs.application.idempotency import format_instant
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.alerts import (
    AcknowledgeAlert,
    AcknowledgeAlertCommand,
    SnoozeAlert,
    SnoozeAlertCommand,
)
from diucs.application.use_cases.subscribe_alert import (
    GetAlertPreferences,
    ListLeaders,
    SaveAlertPreferences,
)
from diucs.application.use_cases.week_summary import GetWeekSummary, GetWeekSummaryCommand
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed

router = APIRouter(prefix="/fhir")

SUBSCRIBERS: Final = (Role.EXEC, Role.LEAD)
NO_STORE: Final = {"Cache-Control": "no-store"}
SCOPE_TENANT: Final = "tenant"
"""The one scope the summary answers for. The network variant (DEC-132) is reserved."""
ME: Final = "me"
FINISHED_STATUSES: Final = frozenset({"acknowledged", "closed"})
LIST_LIMIT: Final = 50
"""The most alerts an acknowledged or closed list shows (W7A, DEC-775)."""


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...
    @property
    def ids(self) -> IdGenerator: ...
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


class _WeekSettings:
    """The summary's settings. The minutes per avoided call are a tenant setting (TEN-026): until
    the tenant's configuration is read here, the time-back text is not shown, and no number is
    made up."""

    minutes_per_avoided_call: int | None = None


def _week_start(query: Any) -> date:
    raw = query.get("weekStart")
    if raw is None:
        raise ValidationFailed("weekStart", "is required")
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        raise ValidationFailed("weekStart", "must be a date as YYYY-MM-DD") from None
    if day.weekday() != 0:
        raise ValidationFailed("weekStart", "must be a Monday")
    return day


def _json_body(raw: bytes) -> object:
    try:
        parsed: object = json.loads(raw)
    except ValueError:
        raise ValidationFailed("Subscription", "the body is not valid JSON") from None
    return parsed


@router.get("/Subscription")
async def read_subscription(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*SUBSCRIBERS))],
) -> Response:
    subscription = await GetAlertPreferences(_container(request).uow_factory).execute(actor)
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": 1,
        "entry": [{"resource": subscription_to_fhir(subscription)}],
    }
    return FhirJSONResponse(content=bundle, headers=NO_STORE)


@router.get("/Practitioner")
async def read_leaders(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*SUBSCRIBERS))],
) -> Response:
    """The leaders a deputy can be chosen from: `?role=leadership`, each an id and a display name.
    No phone, no email, no role, no period (W7A, DEC-776)."""
    if request.query_params.get("role") != "leadership":
        raise ValidationFailed("role", "must be leadership")
    container = _container(request)
    leaders = await ListLeaders(container.uow_factory, container.clock).execute(actor)
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(leaders),
        "entry": [
            {
                "resource": {
                    "resourceType": "Practitioner",
                    "id": leader.id,
                    "name": [{"text": leader.display_name}],
                }
            }
            for leader in leaders
        ],
    }
    return FhirJSONResponse(content=bundle, headers=NO_STORE)


@router.put("/Subscription/{subscription_id}")
async def save_subscription(
    subscription_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*SUBSCRIBERS))],
) -> Response:
    key = idempotency_key(request)
    if subscription_id != actor.practitioner_id:
        # Another practitioner's preferences are not this caller's to see or change: not found.
        raise NotFound("no subscription with this id")
    command = save_command(_json_body(await request.body()), actor, key)
    expected = require_if_match(request)
    container = _container(request)

    async def run() -> Response:
        uow_factory = container.uow_factory
        current = await GetAlertPreferences(uow_factory).execute(actor)
        check_version(expected, subscription_version(current))
        await SaveAlertPreferences(
            uow_factory, UnitOfWorkIdempotency(uow_factory), container.clock
        ).execute(command)
        saved = await GetAlertPreferences(uow_factory).execute(actor)
        return versioned_response(
            subscription_to_fhir(saved), version_id=subscription_version(saved)
        )

    return await replay_or_run(request, actor, f"subscription:{subscription_id}:{key}", run)


async def alert_list(request: Request, actor: Actor) -> Response:
    """The caller's open alerts, as Tasks. Reached through `GET /fhir/Task`, which the clinical
    module dispatches by code (one path, one handler per code, R13). A role that is not an
    executive or a lead is a non-revealing 404, as a route guard would make it."""
    if actor.role not in SUBSCRIBERS:
        raise NotAllowed("the alert list is for an executive or a shift lead")
    query = request.query_params
    if query.get("owner") != ME:
        raise ValidationFailed("owner", "must be me")
    status = query.get("status")
    if status is not None and status not in LISTED_STATUSES:
        raise ValidationFailed("status", "must be new, escalated, acknowledged or closed")
    async with _container(request).uow_factory() as uow:
        if status in FINISHED_STATUSES:
            records = await uow.alerts.for_owner_with_status(
                actor.practitioner_id or "", status, LIST_LIMIT
            )
        else:
            records = await uow.alerts.open_for_owner(actor.practitioner_id or "")
    if status is not None and status not in FINISHED_STATUSES:
        records = [record for record in records if record.status == status]
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(records),
        "entry": [{"resource": alert_to_task(record)} for record in records],
    }
    return FhirJSONResponse(content=bundle, headers=NO_STORE)


@router.post("/Task/{alert_id}/$acknowledge")
async def acknowledge_alert(
    alert_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
) -> Response:
    """An executive's or a lead's acknowledgement of an alert. The same path is an advisor's
    acknowledgement of a booking's withdrawal (R17, routes_bookings.acknowledge), whose roles do not
    overlap with these: an advisor or a clinical advisor is handed over to it, with the role that
    route takes checked here."""
    if actor.role not in SUBSCRIBERS:
        if actor.role not in routes_bookings.CREATE_ROLES:
            raise NotAllowed("the acknowledgement is for an executive, a lead or an advisor")
        return await routes_bookings.acknowledge(alert_id, request, actor)
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        result = await AcknowledgeAlert(container.uow_factory, container.clock).execute(
            AcknowledgeAlertCommand(alert_id=alert_id, actor=actor)
        )
        return FhirJSONResponse(
            content={
                "resourceType": "Task",
                "id": result.alert_id,
                "businessStatus": {"coding": [{"code": result.status}]},
            },
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"acknowledge:{alert_id}:{key}", run)


@router.post("/Task/{alert_id}/$snooze")
async def snooze_alert(
    alert_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*SUBSCRIBERS))],
) -> Response:
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        result = await SnoozeAlert(container.uow_factory, container.ids, container.clock).execute(
            SnoozeAlertCommand(alert_id=alert_id, actor=actor)
        )
        return FhirJSONResponse(
            content={
                "resourceType": "Parameters",
                "parameter": [
                    {"name": "alertId", "valueString": result.alert_id},
                    {
                        "name": "escalationDueAt",
                        "valueDateTime": format_instant(result.escalation_due_at),
                    },
                ],
            },
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"snooze:{alert_id}:{key}", run)


@router.get("/HealthcareService/$week-summary")
async def week_summary(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*SUBSCRIBERS))],
) -> Response:
    query = request.query_params
    scope = query.get("scope", SCOPE_TENANT)
    if scope != SCOPE_TENANT:
        raise ValidationFailed("scope", "must be tenant: the network view is not built yet")
    week_start = _week_start(query)
    container = _container(request)
    summary = await GetWeekSummary(container.uow_factory, _WeekSettings(), container.clock).execute(
        GetWeekSummaryCommand(actor=actor, week_start=week_start)
    )
    return FhirJSONResponse(content=summary_parameters(summary), headers=NO_STORE)


__all__ = ["router"]
