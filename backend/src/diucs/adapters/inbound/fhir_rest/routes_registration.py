"""Registration, the scope list and the review of a registration over HTTP (R10). Thin: each route
reads the body, checks its shape, runs one use case and maps the result. No business rule lives
here, except the two that answer 409 business-rule (refusal_outcome), and those only name a
refusal the use case has already made.

GET    /fhir/List/scope-list                       lead; the scope list (ListScope, U23)
POST   /fhir/List/scope-list/$entry                lead; Idempotency-Key; Parameters service,
                                                   category, flag, reason; 201 (AddScopeEntry)
POST   /fhir/Task/$invite-reporter                 lead; Idempotency-Key; Parameters service, role,
                                                   mobile, suggestedChannel; 201 with numberEnding
                                                   only (InviteReporter, U24); a service not in the
                                                   pilot is 409 business-rule
PUT    /fhir/Task/{id}/$draft                      reporter; Idempotency-Key; JSON {"step",
                                                   "values"} with camelCase values; 400 with an
                                                   issue per field (SaveRegistrationStep, U26)
POST   /fhir/Task/{id}/$submit                     reporter; Idempotency-Key
                                                   (SubmitRegistration, U26)
POST   /fhir/Task/{id}/$callback                   lead; Parameters numberCalled, spokeToRole,
                                                   result (RecordCallBack, U28)
POST   /fhir/Task/{id}/$scope-decision             lead; Parameters onDorsetPathway,
                                                   takesSpoaReferrals, canReport,
                                                   categoryOnPilotList, flag, reason
                                                   (RecordScopeDecision, U28)
POST   /fhir/Task/{id}/$approve                    lead; approval before every check is done is 409
                                                   business-rule naming what is missing (U29)
POST   /fhir/Task/{id}/$send-back                  lead; Parameters note, at most 280 (U29)
POST   /fhir/Task/{id}/$not-approve                lead; Parameters note, at most 280 (U29)
POST   /fhir/Task/{id}/$set-live                   lead (SetServiceLive, U29)

Every POST and the PUT need an Idempotency-Key, checked before the body. A role the route does not
take is a non-revealing 404 (require_role). Notes are short and carry no patient information. An
error names the part, never its value.

Tenancy: the tenant is bound at the REST edge from the verified token (TEN-018), by current_actor.
Nothing here reads a tenant from the body, the query or a header.
"""

import dataclasses
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.adapters.inbound.fhir_rest.errors import operation_outcome
from diucs.adapters.inbound.fhir_rest.parameters import (
    PARAMETERS,
    enum_value,
    index_parameters,
    optional_text,
    reference_part,
    single,
    text,
)
from diucs.adapters.inbound.fhir_rest.routes_lead import number_ending
from diucs.application.actor import Actor
from diucs.application.idempotency import format_instant
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.geo import Geocoder
from diucs.application.ports.outbound.identity import HmacPhoneHasher, normalise_uk_mobile
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.terminology import Terminology
from diucs.application.ports.outbound.tokens import LinkTokenService, SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.uow_idempotency import UnitOfWorkIdempotency
from diucs.application.use_cases.approve_registration import (
    ApproveRegistration,
    NotApproveRegistration,
    NoteCommand,
    RegistrationDecisionCommand,
    SendBackRegistration,
    SetServiceLive,
)
from diucs.application.use_cases.invite_reporter import (
    MOBILE_MESSAGE,
    NOT_IN_PILOT_MESSAGE,
    InviteReporter,
    InviteReporterCommand,
    LinkBaseUrlFor,
)
from diucs.application.use_cases.registration_draft import (
    ApiStep,
    FieldError,
    LocationStep,
    OrganisationStep,
    ReportingStep,
    SaveRegistrationStep,
    SaveRegistrationStepCommand,
    ServiceStep,
    SubmitRegistration,
    SubmitRegistrationCommand,
    validate_step,
)
from diucs.application.use_cases.registration_submit import PersistRegistration
from diucs.application.use_cases.review_registration import (
    AreaDistrictsFor,
    RecordCallBack,
    RecordCallBackCommand,
    RecordScopeDecision,
    RecordScopeDecisionCommand,
    ScopeAnswers,
)
from diucs.application.use_cases.scope_list import (
    AddScopeEntry,
    AddScopeEntryCommand,
    ListScope,
    ScopeRow,
)
from diucs.domain.codes import Channel, Role, ScopeFlag, ServiceCategory, code_system_url
from diucs.domain.errors import DomainError, NotAllowed, ValidationFailed
from diucs.domain.model.registration import Answer, CallBackResult

router = APIRouter(prefix="/fhir")

NOTE_LIMIT: Final = 280
"""The longest note a reviewer or a lead may write (R10). A note carries no patient information."""
REGISTER_SERVICE: Final = "register-service"
TASK_CODE_SYSTEM: Final = code_system_url("task-code")
REGISTRATION_STATUS_SYSTEM: Final = code_system_url("registration-status")
SCOPE_FLAG_SYSTEM: Final = code_system_url("scope-flag")
SCOPE_LIST_EXTENSION: Final = code_system_url("scope-list")
APPROVAL_BLOCKED: Final = "Approve is unavailable until: "
"""The start of the message the approval rule raises when a check is still missing (U29). A unit
test calls the rule itself, so this prefix cannot drift from it."""
NO_STORE: Final = {"Cache-Control": "no-store"}
_STEPS: Final[dict[str, type]] = {
    "organisation": OrganisationStep,
    "location": LocationStep,
    "service": ServiceStep,
    "reporting": ReportingStep,
    "api": ApiStep,
}
_SERVICE_STEP: Final = ServiceStep
"""The service step is checked by its use case only: only the use case knows the location's answer
(a visiting service must name districts), so the edge does not check it."""


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...
    @property
    def ids(self) -> IdGenerator: ...
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...
    @property
    def secrets(self) -> SecretStore: ...
    @property
    def sealer(self) -> ContentSealer: ...
    @property
    def geocoder(self) -> Geocoder: ...
    @property
    def terminology(self) -> Terminology: ...
    @property
    def area_districts_for(self) -> AreaDistrictsFor: ...
    @property
    def link_base_url_for(self) -> LinkBaseUrlFor: ...


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


async def _body(request: Request) -> object:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise ValidationFailed(PARAMETERS, "the body is not valid JSON") from None


# ------------------------------------------------------------------ refusals and their answers


def refusal_outcome(error: DomainError) -> Response | None:
    """The 409 business-rule answer for the two refusals a reviewer or an invitation needs to see
    the reason of: an approval with a check still missing, and an invitation for a service that is
    not in the pilot. Any other refusal is None, and the caller re-raises it (a role refusal stays
    a 404)."""
    if not isinstance(error, NotAllowed):
        return None
    message = str(error)
    if message.startswith(APPROVAL_BLOCKED) or message == NOT_IN_PILOT_MESSAGE:
        return operation_outcome(409, "business-rule", message, headers=NO_STORE)
    return None


def _camel(field: str) -> str:
    head, *rest = field.split("_")
    return head + "".join(part.capitalize() for part in rest)


def _issues(errors: list[FieldError] | tuple[FieldError, ...]) -> Response:
    """One OperationOutcome with an issue for every field that failed, each with its expression."""
    issues = [
        {
            "severity": "error",
            "code": "invalid",
            "diagnostics": error.message,
            "expression": [_camel(error.field)],
        }
        for error in errors
    ]
    return FhirJSONResponse(
        content={"resourceType": "OperationOutcome", "issue": issues},
        status_code=400,
        headers=NO_STORE,
    )


def _task(registration_id: str, status: str) -> dict[str, Any]:
    return {
        "resourceType": "Task",
        "id": registration_id,
        "code": {"coding": [{"system": TASK_CODE_SYSTEM, "code": REGISTER_SERVICE}]},
        "businessStatus": {"coding": [{"system": REGISTRATION_STATUS_SYSTEM, "code": status}]},
    }


def _task_response(registration_id: str, status: str) -> Response:
    return FhirJSONResponse(content=_task(registration_id, status), headers=NO_STORE)


# ------------------------------------------------------------------------ the scope list (U23)


def _extension(name: str, value: dict[str, Any]) -> dict[str, Any]:
    return {"url": f"{SCOPE_LIST_EXTENSION}/{name}", **value}


def _scope_list(rows: tuple[ScopeRow, ...]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        extensions = [
            _extension("name", {"valueString": row.name}),
            _extension("category", {"valueCode": row.category.value}),
            _extension("reason", {"valueString": row.reason}),
        ]
        if row.registration_status is not None:
            extensions.append(
                _extension("registration-status", {"valueCode": row.registration_status.value})
            )
        entries.append(
            {
                "item": {"reference": f"HealthcareService/{row.service_id}"},
                "flag": {"coding": [{"system": SCOPE_FLAG_SYSTEM, "code": row.flag.value}]},
                "extension": extensions,
            }
        )
    return {"resourceType": "List", "id": "scope-list", "status": "current", "entry": entries}


def scope_entry_command(body: object, actor: Actor, key: str) -> AddScopeEntryCommand:
    """The command of one $entry body. The name, the category and the flag are checked before the
    store is touched. The category is a part of its own: the use case needs one, and the prompt's
    part list did not name it (recorded in the fragment)."""
    index = index_parameters(body)
    name = text(single(index, "service", required=True), "service")
    category = enum_value(ServiceCategory, single(index, "category", required=True), "category")
    flag = enum_value(ScopeFlag, single(index, "flag", required=True), "flag")
    reason = optional_text(single(index, "reason", required=False), "reason", limit=NOTE_LIMIT)
    return AddScopeEntryCommand(
        idempotency_key=key,
        actor=actor,
        name=name,
        category=category,
        flag=flag,
        reason=reason,
    )


# ------------------------------------------------------------------------ the invitation (U24)


def invite_command(body: object, actor: Actor, key: str) -> tuple[InviteReporterCommand, str]:
    """The command of one $invite-reporter body, and the national form of the number. The answer
    shows only the last four digits of it. A mobile that is not a UK number is refused with the use
    case's wording and without the number."""
    index = index_parameters(body)
    parts = index.get("service") or []
    if len(parts) != 1:
        raise ValidationFailed("service", "is required" if not parts else "is given once")
    service_id = reference_part(parts[0], "service", "HealthcareService")
    role = text(single(index, "role", required=True), "role")
    national = _mobile(single(index, "mobile", required=True))
    channel = enum_value(
        Channel, single(index, "suggestedChannel", required=True), "suggestedChannel"
    )
    command = InviteReporterCommand(
        idempotency_key=key,
        actor=actor,
        service_id=service_id,
        role_label=role,
        mobile=national,
        suggested_channel=channel,
    )
    return command, national


def _mobile(value: object) -> str:
    """The national form of a UK mobile, or the use case's refusal. The input is never repeated."""
    try:
        if not isinstance(value, str):
            raise ValidationFailed("mobile", MOBILE_MESSAGE)
        return normalise_uk_mobile(value)
    except ValidationFailed:
        raise ValidationFailed("mobile", MOBILE_MESSAGE) from None


# ----------------------------------------------------------- the draft and the submit (U26)


Step = OrganisationStep | LocationStep | ServiceStep | ReportingStep | ApiStep


def _blank(item: dataclasses.Field[Any]) -> Any:
    """What a draft holds for a value the applicant has not given yet: nothing (empty text, no
    number, no date). A yes-or-no answer has no blank: the step hangs on it."""
    if item.type is bool:
        return dataclasses.MISSING
    return "" if item.type is str else None


def parse_draft(body: object, *, partial: bool = False) -> tuple[Step | None, list[FieldError]]:
    """The step a $draft body names, built from its values. A required value that is missing comes
    back as an error of its own, since the step cannot be built without it. An unknown step or an
    unknown value is refused outright, naming only the part. A `partial` draft (Save draft) fills
    what is not given with blanks, so a part-filled step can be saved; the step's own checks then
    say what is left (W7B A3). A yes-or-no answer is still needed."""
    if not isinstance(body, dict):
        raise ValidationFailed("step", "must be a JSON object")
    name = body.get("step")
    kind = _STEPS.get(name) if isinstance(name, str) else None
    if kind is None:
        raise ValidationFailed("step", "is not a registration step")
    values = body.get("values")
    if not isinstance(values, dict):
        raise ValidationFailed("values", "is required")
    declared = {item.name: item for item in dataclasses.fields(kind)}
    names = {_camel(name): name for name in declared}
    kwargs: dict[str, Any] = {}
    for camel, value in values.items():
        field_name = names.get(camel)
        if field_name is None:
            raise ValidationFailed("values", "has a value this step does not take")
        kwargs[field_name] = value
    missing: list[FieldError] = []
    for item in declared.values():
        if item.name in kwargs or (
            item.default is not dataclasses.MISSING
            or item.default_factory is not dataclasses.MISSING
        ):
            continue
        blank = _blank(item) if partial else dataclasses.MISSING
        if blank is dataclasses.MISSING:
            missing.append(FieldError(item.name, "is required"))
        else:
            kwargs[item.name] = blank
    if missing:
        return None, missing
    return kind(**kwargs), []


def callback_command(
    body: object, actor: Actor, key: str, registration_id: str
) -> RecordCallBackCommand:
    """The command of one $callback body. The role spoken to is optional here: the use case needs
    it only when the call confirmed the number (a lead may not know who answered otherwise)."""
    index = index_parameters(body)
    return RecordCallBackCommand(
        idempotency_key=key,
        actor=actor,
        registration_id=registration_id,
        number_called=text(single(index, "numberCalled", required=True), "numberCalled"),
        role_spoken_to=optional_text(single(index, "spokeToRole", required=False), "spokeToRole"),
        result=enum_value(CallBackResult, single(index, "result", required=True), "result"),
    )


# ---------------------------------------------------------------------------------------- routes


@router.get("/List/scope-list")
async def read_scope_list(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    rows = await ListScope(_container(request).uow_factory).execute(actor)
    return FhirJSONResponse(content=_scope_list(rows), headers=NO_STORE)


@router.post("/List/scope-list/$entry", status_code=201)
async def add_scope_entry(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    key = idempotency_key(request)
    command = scope_entry_command(await _body(request), actor, key)
    container = _container(request)

    async def run() -> Response:
        result = await AddScopeEntry(
            container.uow_factory,
            UnitOfWorkIdempotency(container.uow_factory),
            container.ids,
            container.clock,
        ).execute(command)
        return FhirJSONResponse(
            content={
                "resourceType": PARAMETERS,
                "parameter": [{"name": "serviceId", "valueString": result.service_id}],
            },
            status_code=201,
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"scope-entry:{key}", run)


@router.post("/Task/$invite-reporter", status_code=201)
async def invite_reporter(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    key = idempotency_key(request)
    command, national = invite_command(await _body(request), actor, key)
    container = _container(request)

    async def run() -> Response:
        try:
            result = await InviteReporter(
                container.uow_factory,
                lambda repo: LinkTokenService(repo, container.secrets, container.clock),
                HmacPhoneHasher(container.secrets),
                container.clock,
                container.ids,
                link_base_url_for=container.link_base_url_for,
            ).execute(command)
        except NotAllowed as error:
            refused = refusal_outcome(error)
            if refused is None:
                raise
            return refused
        return FhirJSONResponse(
            content={
                "resourceType": PARAMETERS,
                "parameter": [
                    {"name": "numberEnding", "valueString": number_ending(national)},
                    {"name": "invitationId", "valueString": result.invitation_id},
                    {"name": "registrationId", "valueString": result.registration_id},
                    {"name": "expiresAt", "valueDateTime": format_instant(result.expires_at)},
                ],
            },
            status_code=201,
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"invite:{key}", run)


@router.put("/Task/{registration_id}/$draft")
async def save_draft_step(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.REPORTER))],
) -> Response:
    key = idempotency_key(request)
    body = await _body(request)
    partial = isinstance(body, dict) and body.get("partial") is True
    step, shape = parse_draft(body, partial=partial)
    if shape:
        return _issues(shape)
    if step is None:
        raise ValidationFailed("step", "is not a registration step")
    if not partial and not isinstance(step, _SERVICE_STEP):
        errors = validate_step(step)
        if errors:
            return _issues(errors)
    container = _container(request)

    async def run() -> Response:
        result = await SaveRegistrationStep(
            container.uow_factory, container.ids, container.clock
        ).execute(
            SaveRegistrationStepCommand(
                idempotency_key=key,
                actor=actor,
                registration_id=registration_id,
                step=step,
                partial=partial,
            )
        )
        if partial:
            # A draft is saved whatever is left to do: the page is told what that is.
            return FhirJSONResponse(
                content={
                    **_task(registration_id, result.status.value),
                    "incomplete": [
                        {"field": _camel(error.field), "message": error.message}
                        for error in result.errors
                    ],
                },
                headers=NO_STORE,
            )
        if result.errors:
            return _issues(result.errors)
        return _task_response(registration_id, result.status.value)

    return await replay_or_run(request, actor, f"draft:{registration_id}:{key}", run)


@router.post("/Task/{registration_id}/$submit")
async def submit_registration(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.REPORTER))],
) -> Response:
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        result = await SubmitRegistration(
            container.uow_factory,
            container.ids,
            container.clock,
            persist=PersistRegistration(
                container.uow_factory,
                container.geocoder,
                container.terminology,
                container.ids,
                container.clock,
            ),
        ).execute(
            SubmitRegistrationCommand(
                idempotency_key=key, actor=actor, registration_id=registration_id
            )
        )
        if result.errors:
            return _issues(result.errors)
        return _task_response(registration_id, result.status.value)

    return await replay_or_run(request, actor, f"submit:{registration_id}:{key}", run)


# ------------------------------------------------------------------------- the review (U28, U29)


@router.post("/Task/{registration_id}/$callback")
async def record_call_back(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    key = idempotency_key(request)
    command = callback_command(await _body(request), actor, key, registration_id)
    container = _container(request)

    async def run() -> Response:
        result = await RecordCallBack(
            container.uow_factory,
            HmacPhoneHasher(container.secrets),
            container.secrets,
            container.ids,
            container.clock,
            area_districts_for=container.area_districts_for,
        ).execute(command)
        return FhirJSONResponse(
            content={
                "resourceType": PARAMETERS,
                "parameter": [
                    {"name": "result", "valueCode": result.result.value},
                    {"name": "callbackConfirmed", "valueBoolean": result.callback_confirmed},
                ],
            },
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"callback:{registration_id}:{key}", run)


@router.post("/Task/{registration_id}/$scope-decision")
async def record_scope_decision(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    key = idempotency_key(request)
    index = index_parameters(await _body(request))
    answers = ScopeAnswers(
        on_dorset_pathway=enum_value(
            Answer, single(index, "onDorsetPathway", required=True), "onDorsetPathway"
        ),
        takes_spoa_referrals=enum_value(
            Answer, single(index, "takesSpoaReferrals", required=True), "takesSpoaReferrals"
        ),
        can_report=enum_value(Answer, single(index, "canReport", required=True), "canReport"),
        category_on_pilot_list=enum_value(
            Answer, single(index, "categoryOnPilotList", required=True), "categoryOnPilotList"
        ),
    )
    decision = enum_value(ScopeFlag, single(index, "flag", required=True), "flag")
    reason = optional_text(single(index, "reason", required=False), "reason", limit=NOTE_LIMIT)
    command = RecordScopeDecisionCommand(
        idempotency_key=key,
        actor=actor,
        registration_id=registration_id,
        answers=answers,
        decision=decision,
        reason=reason,
    )
    container = _container(request)

    async def run() -> Response:
        result = await RecordScopeDecision(
            container.uow_factory,
            HmacPhoneHasher(container.secrets),
            container.clock,
            area_districts_for=container.area_districts_for,
        ).execute(command)
        return FhirJSONResponse(
            content={
                "resourceType": PARAMETERS,
                "parameter": [{"name": "flag", "valueCode": result.decision.value}],
            },
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"scope-decision:{registration_id}:{key}", run)


def _note(index: dict[str, list[dict[str, Any]]]) -> str:
    """A note: optional text of at most NOTE_LIMIT characters. A longer one is refused by name."""
    return optional_text(single(index, "note", required=False), "note", limit=NOTE_LIMIT)


async def _decide(
    request: Request,
    actor: Actor,
    registration_id: str,
    operation: str,
    decide: Callable[[_Container], Awaitable[Response]],
) -> Response:
    """One approval-stage decision, keyed and replayed, with the two business-rule refusals shown
    as 409 and every other refusal left to the app's own mapping."""
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        try:
            return await decide(container)
        except NotAllowed as error:
            refused = refusal_outcome(error)
            if refused is None:
                raise
            return refused

    return await replay_or_run(request, actor, f"{operation}:{registration_id}:{key}", run)


@router.post("/Task/{registration_id}/$approve")
async def approve_registration(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    async def decide(container: _Container) -> Response:
        result = await ApproveRegistration(
            container.uow_factory,
            container.clock,
            container.ids,
            container.sealer,
            phone_hasher=HmacPhoneHasher(container.secrets),
            area_districts_for=container.area_districts_for,
        ).execute(RegistrationDecisionCommand(registration_id=registration_id, actor=actor))
        return _task_response(registration_id, result.status.value)

    return await _decide(request, actor, registration_id, "approve", decide)


@router.post("/Task/{registration_id}/$send-back")
async def send_back_registration(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    note = _note(index_parameters(await _body(request)))

    async def decide(container: _Container) -> Response:
        result = await SendBackRegistration(container.uow_factory, container.clock).execute(
            NoteCommand(registration_id=registration_id, actor=actor, note=note)
        )
        return _task_response(registration_id, result.status.value)

    return await _decide(request, actor, registration_id, "send-back", decide)


@router.post("/Task/{registration_id}/$not-approve")
async def not_approve_registration(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    note = _note(index_parameters(await _body(request)))

    async def decide(container: _Container) -> Response:
        result = await NotApproveRegistration(container.uow_factory, container.clock).execute(
            NoteCommand(registration_id=registration_id, actor=actor, note=note)
        )
        return _task_response(registration_id, result.status.value)

    return await _decide(request, actor, registration_id, "not-approve", decide)


@router.post("/Task/{registration_id}/$set-live")
async def set_service_live(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    async def decide(container: _Container) -> Response:
        result = await SetServiceLive(
            container.uow_factory, container.clock, container.ids
        ).execute(RegistrationDecisionCommand(registration_id=registration_id, actor=actor))
        return _task_response(registration_id, result.status.value)

    return await _decide(request, actor, registration_id, "set-live", decide)


__all__ = [
    "APPROVAL_BLOCKED",
    "NOTE_LIMIT",
    "callback_command",
    "invite_command",
    "parse_draft",
    "refusal_outcome",
    "router",
    "scope_entry_command",
]
