"""Support codes and the support console's JSON routes (R18), over the use cases of O06 and R18.

Person (any signed-in role, its own codes and opens): POST /support/codes, DELETE
/support/codes/current, GET /support/accesses. Support (the support role): POST
/support/sessions/open, GET /support/sessions, POST /support/sessions/{id}/ticket, GET
/support/sessions/{id}/events, DELETE /support/sessions/{id}, GET /support/traces/{traceId}.
Lead (the lead role): POST /support/tickets/{id}/approve.

Answers (the spec's): a wrong or expired code is 403 with one message, whatever was wrong; a
support route for another role is the non-revealing 404 (the role guard runs first); the events
of a session are 403 unless the caller's own open of it is live. A code is returned in the
creation response only. Nothing a route returns or logs carries a field value, page text, query
text or a code, except the code in that one creation response.

Idempotency: every POST and DELETE needs an Idempotency-Key. The creation of a code is the
exception to the HTTP replay cache: a cached response would keep a live code in the cache for 24
hours, so the key is checked and the create runs once per request (decision for R18).

Tenancy (transitional rule until TEN-018): no tenant is read from a request; the unit of work is
the one the container gives, as the other JSON routes do.
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal, Protocol, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import current_actor, require_role
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.adapters.inbound.fhir_rest.errors import operation_outcome
from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import secret_is_configured
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.telemetry_query import (
    SessionFilters,
    TelemetryQuery,
    TelemetryUnavailable,
    as_utc,
)
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.support_access import (
    OPEN_REFUSED,
    CreateSupportCode,
    CreateSupportCodeCommand,
    ListMyAccesses,
    ListMyAccessesCommand,
    StopSharing,
    StopSharingCommand,
)
from diucs.application.use_cases.support_console import (
    EVENTS_REFUSED,
    ApproveSupportTicket,
    EndSupportAccess,
    OpenSupportSession,
    ReadSessionEvents,
    ReadTrace,
    RequestSupportTicket,
    SearchSessions,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.rules.support import SUPPORT_CODE_SECRET

router = APIRouter(prefix="/support")

CODE_REFUSED_TEXT: Final = "That code is not valid or has expired."
EVENTS_REFUSED_TEXT: Final = "This session is not open to you."
TELEMETRY_UNAVAILABLE_TEXT: Final = "The telemetry store cannot be read right now."
SESSION_FILTER_TEXT: Final = "This filter is not available yet."
_NO_STORE: Final = {"Cache-Control": "no-store"}
_SESSION_ID: Final = r"[a-f0-9]{16,32}"
_RELEASE: Final = r"\d+\.\d+\.\d+"


class _SupportContainer(Protocol):
    uow_factory: UnitOfWorkFactory
    clock: Clock
    ids: IdGenerator
    secrets: SecretStore
    telemetry: TelemetryQuery


class CreateCodeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionId: str = Field(pattern=_SESSION_ID)
    deviceType: Literal["phone", "tablet", "desktop"]
    appMode: Literal["browser", "installed"]
    release: str = Field(pattern=_RELEASE, max_length=32)


class OpenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supportCode: str | None = Field(default=None, max_length=32)
    ticket: str | None = Field(default=None, max_length=32)


class TicketBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket: str = Field(min_length=1, max_length=32)


def _container(request: Request) -> _SupportContainer:
    return cast(_SupportContainer, get_container(request))


def _support_secret(container: _SupportContainer) -> None:
    """Fail closed: a missing support secret is a configuration error (a 500), never an open
    route."""
    if not secret_is_configured(container.secrets, SUPPORT_CODE_SECRET):
        raise RuntimeError("the support code secret is not configured")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json(status: int, body: Any) -> Response:
    return JSONResponse(body, status_code=status, headers=_NO_STORE)


def _empty() -> Response:
    return Response(status_code=204, headers=_NO_STORE)


async def _answer(run: Any) -> Response:
    """Run one request and map what it can answer. The refusals this module owns get their own
    answers; every other NotAllowed is left to the app's non-revealing 404.
    """
    try:
        return cast(Response, await run())
    except NotAllowed as error:
        text = str(error)
        if text == OPEN_REFUSED:
            return operation_outcome(403, "forbidden", CODE_REFUSED_TEXT, headers=_NO_STORE)
        if text == EVENTS_REFUSED:
            return operation_outcome(403, "forbidden", EVENTS_REFUSED_TEXT, headers=_NO_STORE)
        raise
    except TelemetryUnavailable:
        return operation_outcome(503, "unavailable", TELEMETRY_UNAVAILABLE_TEXT, headers=_NO_STORE)


# ---- the person ----------------------------------------------------------------------------


@router.post("/codes", status_code=201)
async def create_code(
    body: CreateCodeBody,
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
) -> Response:
    idempotency_key(request)

    async def run() -> Response:
        container = _container(request)
        _support_secret(container)
        result = await CreateSupportCode(
            container.uow_factory, container.clock, container.ids, container.secrets
        ).execute(
            CreateSupportCodeCommand(
                actor=actor,
                session_id=body.sessionId,
                device_type=body.deviceType,
                app_mode=body.appMode,
                release=body.release,
            )
        )
        return _json(201, {"code": result.code, "expiresAt": _iso(result.expires_at)})

    return await _answer(run)


@router.delete("/codes/current", status_code=204)
async def stop_sharing(
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
    session_id: Annotated[str, Query(alias="sessionId", pattern=_SESSION_ID)],
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        container = _container(request)
        await StopSharing(container.uow_factory, container.clock).execute(
            StopSharingCommand(actor=actor, session_id=session_id)
        )
        return _empty()

    return await _answer(lambda: replay_or_run(request, actor, key, run))


@router.get("/accesses")
async def my_accesses(
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
    session_id: Annotated[str, Query(alias="sessionId", pattern=_SESSION_ID)],
) -> Response:
    async def run() -> Response:
        container = _container(request)
        views = await ListMyAccesses(container.uow_factory, container.clock).execute(
            ListMyAccessesCommand(actor=actor, session_id=session_id)
        )
        return _json(200, [{"openedAt": _iso(view.opened_at), "role": view.by} for view in views])

    return await _answer(run)


# ---- support ---------------------------------------------------------------------------------


@router.post("/sessions/open")
async def open_session(
    body: OpenBody,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.SUPPORT))],
) -> Response:
    key = idempotency_key(request)
    if (body.supportCode is None) == (body.ticket is None):
        return operation_outcome(400, "invalid", "Give one of supportCode or ticket.")

    async def run() -> Response:
        container = _container(request)
        _support_secret(container)
        result = await OpenSupportSession(
            container.uow_factory, container.clock, container.ids, container.secrets
        ).execute(actor, code=body.supportCode, ticket=body.ticket)
        return _json(200, {"sessionId": result.session_id, "expiresAt": _iso(result.expires_at)})

    return await _answer(lambda: replay_or_run(request, actor, key, run))


@router.get("/sessions")
async def search_sessions(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.SUPPORT))],
    session_id: Annotated[str | None, Query(alias="sessionId")] = None,
    trace_id: Annotated[str | None, Query(alias="traceId")] = None,
    reference: str | None = None,
    role: str | None = None,
    release: str | None = None,
    since: str | None = None,
) -> Response:
    if trace_id is not None or reference is not None:
        return operation_outcome(400, "not-supported", SESSION_FILTER_TEXT, headers=_NO_STORE)

    async def run() -> Response:
        container = _container(request)
        try:
            started_from = None if since is None else as_utc(since)
        except ValueError:
            raise ValidationFailed("since", "must be a UTC instant") from None
        filters = SessionFilters(role=role, release=release, started_from=started_from)
        found = await SearchSessions(container.telemetry).execute(actor, filters, session_id)
        items = [
            {
                "sessionId": session.session_id,
                "role": session.role,
                "device": session.device,
                "release": session.release,
                "started": _iso(session.started),
                "eventCount": session.event_count,
                "frictionCount": session.friction_count,
                "errorCount": session.error_count,
            }
            for session in found
        ]
        return _json(200, {"items": items})

    return await _answer(run)


@router.post("/sessions/{session_id}/ticket")
async def request_ticket(
    session_id: str,
    body: TicketBody,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.SUPPORT))],
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        container = _container(request)
        record = await RequestSupportTicket(container.uow_factory, container.clock).execute(
            actor, session_id, body.ticket
        )
        return _json(200, {"state": record.state})

    return await _answer(lambda: replay_or_run(request, actor, key, run))


@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.SUPPORT))],
    filter: Literal["all", "errors", "friction", "api", "navigation"] = "all",  # noqa: A002
) -> Response:
    async def run() -> Response:
        container = _container(request)
        result = await ReadSessionEvents(
            container.uow_factory, container.clock, container.telemetry
        ).execute(actor, session_id, filter)
        return _json(
            200,
            {
                "meta": {"sessionId": session_id, "filter": filter, "count": len(result.events)},
                "standout": result.standout,
                "events": result.events,
            },
        )

    return await _answer(run)


@router.delete("/sessions/{session_id}", status_code=204)
async def end_access(
    session_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.SUPPORT))],
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        container = _container(request)
        await EndSupportAccess(container.uow_factory, container.clock).execute(actor, session_id)
        return _empty()

    return await _answer(lambda: replay_or_run(request, actor, key, run))


@router.get("/traces/{trace_id}")
async def trace(
    trace_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.SUPPORT))],
) -> Response:
    async def run() -> Response:
        container = _container(request)
        view = await ReadTrace(container.telemetry).execute(actor, trace_id)
        return _json(200, {"name": view.name, "totalMs": view.total_ms, "spans": view.spans})

    return await _answer(run)


# ---- the lead ----------------------------------------------------------------------------------


@router.post("/tickets/{ticket_id}/approve")
async def approve_ticket(
    ticket_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        container = _container(request)
        await ApproveSupportTicket(container.uow_factory, container.clock).execute(actor, ticket_id)
        return _json(200, {"state": "approved"})

    return await _answer(lambda: replay_or_run(request, actor, key, run))
