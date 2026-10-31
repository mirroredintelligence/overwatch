"""Clinical advice, the safety concern and the clinical queue over HTTP (R13).

Thin: each route reads its request, checks its shape, runs one use case and maps the result. The
use cases hold the rules (who may ask, take or advise; the lock; the protected text).

PUT  /clinical/presence
         clinical; {"presence": available, busy or away} (SetPresence, U40)
GET  /clinical/requests/{id}/seen
         clinical, holding the request: the display of the options the advisor had when they asked
         (ReadWhatAdvisorSaw, W9G)
GET  /clinical/requests/{id}/advisor-contact
         clinical, holding the request: the number to phone the advisor on, or none
         (ReadAdvisorContact, W9G)
GET  /clinical/available
         advisor, clinical or lead; {"available": n}, a count only, never a name
GET  /fhir/Task?code=clinical-advice&status=requested
         clinical; the queue (ListClinicalQueue)
GET  /fhir/Task?code=acknowledge-alert&owner=me
         executive or lead; the alert list (R12). This one path dispatches the two codes
POST /fhir/Task/{id}/$take
         clinical; Idempotency-Key; a request taken by another clinician is a 409
         (TakeClinicalRequest)
POST /fhir/Task/{id}/$advise
         clinical; Idempotency-Key; Parameters advice, reason, note (at most 280)
         (GiveClinicalAdvice)
POST /fhir/Task
         Idempotency-Key; a Task whose code is clinical-advice (an advisor asks: focus is
         the case; extensions urgency and why) or safety-concern (any signed-in role:
         extensions category, text, and an optional reference)

The free text of a safety concern is held in the protected store by its use case. It is never in
a response or a log; the response carries the reference only (for example SC-0192). A note or a
text of more than 280 characters is refused by name and never echoed.

Tenancy: the tenant is bound at the REST edge from the verified token (TEN-018), by current_actor.
Nothing here reads a tenant from the body, the query or a header.
"""

import json
from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from diucs.adapters.inbound.fhir_rest import routes_bookings
from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import current_actor, require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.clinical_mapping import (
    clinical_task,
    contact_json,
    seen_json,
)
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.adapters.inbound.fhir_rest.parameters import (
    PARAMETERS,
    enum_value,
    index_parameters,
    optional_text,
    reference_id,
    single,
    text,
)
from diucs.adapters.inbound.fhir_rest.routes_alerts import alert_list
from diucs.adapters.inbound.fhir_rest.subscription_mapping import ALERT_CODE
from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.uow_idempotency import UnitOfWorkIdempotency
from diucs.application.use_cases.clinical_advice import (
    ADVICE_CHOICES,
    ADVICE_REASONS,
    LIST_DONE,
    LIST_MINE,
    LIST_WAITING,
    REQUEST_URGENCIES,
    REQUEST_WHYS,
    AvailableClinicians,
    GiveClinicalAdvice,
    GiveClinicalAdviceCommand,
    ListClinicalRequests,
    ReadPresence,
    RequestClinicalAdvice,
    RequestClinicalAdviceCommand,
    SetPresence,
    SetPresenceCommand,
    TakeClinicalRequest,
    TakeClinicalRequestCommand,
)
from diucs.application.use_cases.clinical_context import ReadAdvisorContact, ReadWhatAdvisorSaw
from diucs.application.use_cases.safety_concern import (
    ReportProblem,
    ReportProblemCommand,
    ReportSafetyConcern,
    ReportSafetyConcernCommand,
)
from diucs.domain.codes import Role, code_system_url
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.rules.clinical_queue import Presence
from diucs.domain.rules.safety_report import (
    MAX_TEXT_LENGTH,
    ProblemCategory,
    SafetyConcernCategory,
    checked_concern_text,
)

router = APIRouter()

CLINICAL_CODE: Final = "clinical-advice"
SAFETY_CODE: Final = "safety-concern"
REQUESTED: Final = "requested"
NOTE_LIMIT: Final = 280
ADVISORS: Final = (Role.ADVISOR, Role.CLINICAL, Role.LEAD)
NO_STORE: Final = {"Cache-Control": "no-store"}
TASK_CODE_SYSTEM: Final = code_system_url("task-code")
TASK_INPUT: Final = "task-input"
"""The inputs of a Task that are not a FHIR element: each is an extension under this name."""


PROBLEM_ROLES: Final = tuple(role for role in Role if role not in (Role.WALL, Role.ANONYMOUS_LINK))
"""Who may report a problem: any signed-in person. A wall screen and an anonymous link are no one
(the use case refuses them too, U41)."""


class ProblemBody(BaseModel):
    """A problem report: its kind, an optional text of at most 280 characters, and whether the
    person was sharing their session with support. Nothing else is accepted."""

    model_config = ConfigDict(extra="forbid")

    category: ProblemCategory
    text: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    sessionShared: StrictBool = False


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...
    @property
    def ids(self) -> IdGenerator: ...
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...
    @property
    def cache(self) -> Cache: ...
    @property
    def sealer(self) -> ContentSealer: ...


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


async def _body(request: Request) -> object:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise ValidationFailed(PARAMETERS, "the body is not valid JSON") from None


def _input_url(name: str) -> str:
    return code_system_url(f"{TASK_INPUT}/{name}")


def _input(task: dict[str, Any], name: str, value_key: str) -> object | None:
    """One input of a Task, read from its extension. Given twice is refused by name."""
    url = _input_url(name)
    found = [item for item in task.get("extension") or [] if item.get("url") == url]
    if len(found) > 1:
        raise ValidationFailed(name, "is given once")
    if not found:
        return None
    value: object | None = found[0].get(value_key)
    return value


def _is_clinical_or_safety(task: object) -> bool:
    """True when the Task is one of the two codes this module takes (the rest is a booking)."""
    if not isinstance(task, dict):
        return False
    codings = (task.get("code") or {}).get("coding") or []
    code = codings[0].get("code") if codings and isinstance(codings[0], dict) else None
    return code in (CLINICAL_CODE, SAFETY_CODE)


def _task_code(task: object) -> str:
    """The code of a Task body: exactly one of the two codes this route takes."""
    if not isinstance(task, dict) or task.get("resourceType") != "Task":
        raise ValidationFailed("Task", "the body must be a FHIR Task")
    codings = (task.get("code") or {}).get("coding") or []
    code = codings[0].get("code") if codings and isinstance(codings[0], dict) else None
    if code not in (CLINICAL_CODE, SAFETY_CODE):
        raise ValidationFailed("code", "must be clinical-advice or safety-concern")
    return str(code)


def _case(task: dict[str, Any]) -> str:
    focus = task.get("focus") or {}
    reference = focus.get("reference") if isinstance(focus, dict) else None
    if reference is None:
        raise ValidationFailed("case", "is required")
    return reference_id(reference, "case", "ServiceRequest")


def _clinical_request(task: dict[str, Any], actor: Actor) -> RequestClinicalAdviceCommand:
    """The command of an advisor's request for clinical advice, checked before the store."""
    case_id = _case(task)
    urgency = _input(task, "urgency", "valueCode")
    if urgency not in REQUEST_URGENCIES:
        raise ValidationFailed("urgency", "must be now or within-15-min")
    why = _input(task, "why", "valueCode")
    if why not in REQUEST_WHYS:
        raise ValidationFailed("why", "is not a known reason")
    service = _input(task, "service", "valueString")
    if service is not None and (not isinstance(service, str) or not service.strip()):
        raise ValidationFailed("service", "must be a service id")
    return RequestClinicalAdviceCommand(
        actor=actor,
        case_id=case_id,
        urgency=str(urgency),
        why=str(why),
        service_id=None if service is None else str(service),
    )


def _safety_concern(task: dict[str, Any]) -> tuple[SafetyConcernCategory, str | None, str]:
    """The category, the optional reference and the text of a safety concern, checked here. The
    text is required and at most 280 characters, and is never echoed; the use case stores it in the
    protected store."""
    category = _input(task, "category", "valueCode")
    if category is None:
        raise ValidationFailed("category", "is required")
    kind = enum_value(SafetyConcernCategory, category, "category")
    raw = _input(task, "text", "valueString")
    if raw is None:
        raise ValidationFailed("text", "is required")
    reference = _input(task, "reference", "valueString")
    return kind, (None if reference is None else str(reference)), checked_concern_text(raw)


def _task_status(request_id: str, status: str) -> Response:
    return FhirJSONResponse(
        content={
            "resourceType": "Task",
            "id": request_id,
            "businessStatus": {"coding": [{"code": status}]},
        },
        headers=NO_STORE,
    )


# ----------------------------------------------------------------------------- presence and count


@router.put("/clinical/presence")
async def set_presence(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.CLINICAL))],
) -> Response:
    body = await _body(request)
    if not isinstance(body, dict):
        raise ValidationFailed("presence", "is required")
    presence = enum_value(Presence, body.get("presence"), "presence")
    container = _container(request)
    await SetPresence(container.uow_factory, container.cache, container.clock).execute(
        SetPresenceCommand(actor=actor, presence=presence)
    )
    return FhirJSONResponse(content={"presence": presence.value}, headers=NO_STORE)


@router.get("/clinical/presence")
async def read_presence(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.CLINICAL))],
) -> Response:
    """The clinician's own presence, so the on-duty screen starts where it was left (null when none
    is set or it has lapsed), and how many clinical advisors are available. No name (W7A)."""
    container = _container(request)
    view = await ReadPresence(container.uow_factory, container.cache, container.clock).execute(
        actor
    )
    own = None if view.own is None else view.own.value
    return FhirJSONResponse(
        content={"presence": own, "available": view.available}, headers=NO_STORE
    )


@router.get("/clinical/available")
async def available_clinicians(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*ADVISORS))],
) -> Response:
    container = _container(request)
    count = await AvailableClinicians(
        container.uow_factory, container.cache, container.clock
    ).execute()
    return FhirJSONResponse(content={"available": count}, headers=NO_STORE)


@router.get("/clinical/requests/{request_id}/seen")
async def read_seen(
    request_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.CLINICAL))],
) -> Response:
    """What the advisor saw when they asked, for the clinician who holds the request (W9G). Anyone
    else, a request that is waiting and an id that is not there are the same 404."""
    container = _container(request)
    saw = await ReadWhatAdvisorSaw(container.uow_factory, container.clock).execute(
        actor, request_id
    )
    return FhirJSONResponse(content=seen_json(saw), headers=NO_STORE)


@router.get("/clinical/requests/{request_id}/advisor-contact")
async def read_advisor_contact(
    request_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.CLINICAL))],
) -> Response:
    """The number to phone the advisor on, for the clinician who holds the request (W9G). The number
    is in this answer only: the use case audits how it was found and nothing else about it."""
    container = _container(request)
    contact = await ReadAdvisorContact(container.uow_factory, container.clock).execute(
        actor, request_id
    )
    return FhirJSONResponse(content=contact_json(contact), headers=NO_STORE)


@router.post("/help/problems", status_code=201)
async def report_problem(
    body: ProblemBody,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*PROBLEM_ROLES))],
) -> Response:
    """A problem with the tool (U41, W7A-B4). The answer is the report's id and never the text,
    which the use case keeps in the protected store."""
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        result = await ReportProblem(
            container.uow_factory,
            UnitOfWorkIdempotency(container.uow_factory),
            container.ids,
            container.clock,
        ).execute(
            ReportProblemCommand(
                idempotency_key=key,
                actor=actor,
                category=body.category,
                text=body.text,
                session_shared=body.sessionShared,
            )
        )
        return FhirJSONResponse(content={"id": result.report_id}, status_code=201, headers=NO_STORE)

    return await replay_or_run(request, actor, f"problem:{key}", run)


# ------------------------------------------------------------------------------- the task routes


LISTS: Final = {REQUESTED: LIST_WAITING, "in-progress": LIST_MINE, "completed": LIST_DONE}
"""The Task statuses a clinical advisor lists, and the list each one is: the queue (requested),
Mine (in-progress) and Done (completed)."""


async def clinical_queue(request: Request, actor: Actor) -> Response:
    """The clinical lists. Only a clinical advisor reads them (any other role is a 404), and the
    status asked for is the queue, Mine or Done."""
    if actor.role is not Role.CLINICAL:
        raise NotAllowed("only a clinical advisor may see the clinical queue")
    which = LISTS.get(request.query_params.get("status") or "")
    if which is None:
        raise ValidationFailed("status", "must be requested, in-progress or completed")
    container = _container(request)
    views = await ListClinicalRequests(container.uow_factory, container.clock).execute(actor, which)
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(views),
        "entry": [{"resource": clinical_task(view)} for view in views],
    }
    return FhirJSONResponse(content=bundle, headers=NO_STORE)


@router.get("/fhir/Task")
async def read_tasks(
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
) -> Response:
    """`GET /fhir/Task`, dispatched by its code: the alert list or the clinical queue. A search with
    no code is a search of booking Tasks (the bookings of a case, the open withdrawal alerts: WB4).
    Any other code is a 400 that names the parameter."""
    code = request.query_params.get("code")
    if code is None:
        return await routes_bookings.search_bookings(request, actor)
    if code == ALERT_CODE:
        return await alert_list(request, actor)
    if code == CLINICAL_CODE:
        return await clinical_queue(request, actor)
    raise ValidationFailed("code", "must be acknowledge-alert or clinical-advice")


@router.post("/fhir/Task/{request_id}/$take")
async def take_request(
    request_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.CLINICAL))],
) -> Response:
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        await TakeClinicalRequest(container.uow_factory, container.ids, container.clock).execute(
            TakeClinicalRequestCommand(actor=actor, request_id=request_id)
        )
        return _task_status(request_id, "in-progress")

    return await replay_or_run(request, actor, f"take:{request_id}:{key}", run)


@router.post("/fhir/Task/{request_id}/$advise")
async def give_advice(
    request_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.CLINICAL))],
) -> Response:
    key = idempotency_key(request)
    index = index_parameters(await _body(request))
    choice = text(single(index, "advice", required=True), "advice")
    if choice not in ADVICE_CHOICES:
        raise ValidationFailed("advice", "is not a known advice choice")
    reason = optional_text(single(index, "reason", required=False), "reason")
    if reason and reason not in ADVICE_REASONS:
        raise ValidationFailed("reason", "is not a known reason")
    note = optional_text(single(index, "note", required=False), "note", limit=NOTE_LIMIT)
    container = _container(request)

    async def run() -> Response:
        result = await GiveClinicalAdvice(
            container.uow_factory, container.ids, container.clock
        ).execute(
            GiveClinicalAdviceCommand(
                actor=actor,
                request_id=request_id,
                choice=choice,
                reason=reason or None,
                note=note or None,
            )
        )
        return _task_status(result.request_id, "completed")

    return await replay_or_run(request, actor, f"advise:{request_id}:{key}", run)


@router.post("/fhir/Task")
async def post_task(
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
) -> Response:
    """A clinical-advice request (an advisor) or a safety concern (any signed-in role). The key and
    the Task's shape are checked first; each use case then refuses a role that may not act."""
    key = idempotency_key(request)
    task = await _body(request)
    if not _is_clinical_or_safety(task):
        # A booking request is the same path (R09, routes_bookings.create_booking): hand it over
        # with the role that route takes, so the role check is not lost in the dispatch.
        if actor.role not in routes_bookings.CREATE_ROLES:
            raise NotAllowed("only an advisor or a clinical advisor may request a booking")
        return await routes_bookings.create_booking(request, actor)
    code = _task_code(task)
    container = _container(request)
    if code == CLINICAL_CODE:
        command = _clinical_request(cast(dict[str, Any], task), actor)

        async def ask() -> Response:
            result = await RequestClinicalAdvice(
                container.uow_factory,
                container.ids,
                container.clock,
                container.cache,
                container.sealer,
            ).execute(command)
            return FhirJSONResponse(
                content={
                    "resourceType": "Task",
                    "id": result.request_id,
                    "businessStatus": {"coding": [{"code": REQUESTED}]},
                    "output": [{"valueInteger": result.notified}],
                },
                status_code=201,
                headers=NO_STORE,
            )

        return await replay_or_run(request, actor, f"request:{key}", ask)

    category, reference, concern_text = _safety_concern(cast(dict[str, Any], task))

    async def report() -> Response:
        result = await ReportSafetyConcern(
            container.uow_factory,
            UnitOfWorkIdempotency(container.uow_factory),
            container.ids,
            container.clock,
            container.sealer,
        ).execute(
            ReportSafetyConcernCommand(
                idempotency_key=key,
                actor=actor,
                category=category,
                reference=reference,
                text=concern_text,
            )
        )
        return FhirJSONResponse(
            content={
                "resourceType": "Task",
                "code": {"coding": [{"system": TASK_CODE_SYSTEM, "code": SAFETY_CODE}]},
                "identifier": [{"value": result.reference}],
            },
            status_code=201,
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"concern:{key}", report)


__all__ = ["ALERT_CODE", "CLINICAL_CODE", "SAFETY_CODE", "router"]
