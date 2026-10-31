"""Registration reads and actions over HTTP (W7B A1 and A4, DEC-794 to DEC-799). Thin: each route
checks its shape, runs one use case and maps the result to camelCase JSON. No rule lives here.

The applicant (role reporter, and only for the registration whose requester post they hold):
GET  /registrations/{id}/record          every wizard step: its state, values and problems
GET  /my/registrations                   the applicant's services and their status
GET  /registrations/{id}/status          what the status page shows
POST /registrations/{id}/test-notification   (also the lead) Idempotency-Key; 200 {sentAt, channel}
POST /registrations/{id}/review-request  Idempotency-Key; 200 {requestedAt}
POST /registrations/{id}/confirm-details Idempotency-Key; 200 {status, confirmedAt}
GET  /addresses?postcode=                {"addresses": [{id, label}]}, at most 20, over the
                                         geocoder port (the OS Places adapter when a key is set)

The shift lead:
GET  /registrations?tab=                 the queue: the tabs with counts, and the tab's rows
GET  /registrations/{id}/overview        checks, who registered, the numbers, the call-back words
GET  /registrations/{id}/decision        what is missing, the approvals, the test, the timeline
POST /fhir/Task/{id}/$start-review       Idempotency-Key; the registration is in review
POST /fhir/Task/{id}/$explain-check      Idempotency-Key; Parameters check, note

A role a route does not take is the non-revealing 404 (require_role); another person's registration
and an unknown id are the same 404. Every answer is no-store. A contact number is never in a body:
the last three digits stand for it. An address lookup that cannot answer is a 503, never an empty
list. Tenancy: the tenant is bound at the edge from the verified token (TEN-018).
"""

import json
from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.adapters.inbound.fhir_rest.errors import TemporarilyUnavailable
from diucs.adapters.inbound.fhir_rest.parameters import (
    PARAMETERS,
    index_parameters,
    single,
    text,
)
from diucs.adapters.inbound.fhir_rest.routes_registration import (
    NO_STORE,
    _camel,
    _task_response,
)
from diucs.application.actor import Actor
from diucs.application.idempotency import format_instant
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.geo import Geocoder
from diucs.application.ports.outbound.identity import HmacPhoneHasher
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.lookups import LookupRejected, TransientLookupError
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.registration_views import (
    QUEUE_TABS,
    ConfirmRegistrationDetails,
    DecisionView,
    GetDecision,
    GetMyRegistration,
    GetRegistrationStatus,
    GetReviewOverview,
    ListMyRegistrations,
    ListRegistrationQueue,
    RegistrationActionCommand,
    RegistrationRecord,
    RegistrationStatusView,
    RequestRegistrationReview,
    ReviewOverview,
    SendTestNotification,
    StepView,
)
from diucs.application.use_cases.review_registration import (
    NOTE_MAX_LENGTH,
    AreaDistrictsFor,
    ExplainCheck,
    ExplainCheckCommand,
    GetReviewStatus,
    StartReview,
    StartReviewCommand,
)
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.postcode import normalise_postcode

router = APIRouter()

MAX_ADDRESSES: Final = 20
"""The most addresses one lookup gives: a postcode names a few dozen homes at most, and the page
shows a list the applicant picks from."""
APPLICANT: Final = (Role.REPORTER,)
LEAD: Final = (Role.LEAD,)
APPLICANT_OR_LEAD: Final = (Role.REPORTER, Role.LEAD)
RETRY_AFTER_LOOKUP_SECONDS: Final = 30


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
    def area_districts_for(self) -> AreaDistrictsFor: ...


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


def _answer(body: dict[str, Any]) -> Response:
    return FhirJSONResponse(content=body, headers=NO_STORE)


def _at(value: Any) -> str | None:
    return None if value is None else format_instant(value)


def _camel_keys(values: dict[str, Any]) -> dict[str, Any]:
    return {_camel(name): value for name, value in values.items()}


def _step(view: StepView) -> dict[str, Any]:
    return {
        "state": view.state,
        "values": _camel_keys(view.values),
        "problems": [
            {"field": _camel(field), "message": message} for field, message in view.problems
        ],
    }


def _record(view: RegistrationRecord) -> dict[str, Any]:
    return {
        "registrationId": view.registration_id,
        "status": view.status.value,
        "serviceId": view.service_id,
        "serviceName": view.service_name,
        "submittedAt": _at(view.submitted_at),
        "lastModified": _at(view.last_modified),
        "invitationExpiresAt": _at(view.invitation_expires_at),
        "note": view.note,
        "noteFrom": view.note_from,
        "steps": {key: _step(step) for key, step in view.steps.items()},
    }


def _status(view: RegistrationStatusView) -> dict[str, Any]:
    return {
        "registrationId": view.registration_id,
        "status": view.status.value,
        "serviceName": view.service_name,
        "submittedAt": _at(view.submitted_at),
        "note": view.note,
        "noteFrom": view.note_from,
        "reason": view.reason,
        "firstPromptAt": _at(view.first_prompt_at),
        "reviewRequestedAt": view.review_requested_at,
        "testSentAt": view.test_sent_at,
        "details": {
            "spoaPhone": view.spoa_phone,
            "criteriaOwner": view.criteria_owner,
            "reportingPhoneEnding": view.reporting_phone_ending,
        },
    }


def _overview(view: ReviewOverview) -> dict[str, Any]:
    return {
        "registrationId": view.registration_id,
        "status": view.status.value,
        "serviceId": view.service_id,
        "serviceName": view.service_name,
        "category": view.category,
        "checks": [
            {
                "name": check.name,
                "passed": check.passed,
                "ok": check.ok,
                "message": check.message,
                "explainedNote": check.explained_note,
            }
            for check in view.checks
        ],
        "automaticOk": view.automatic_ok,
        "callbackConfirmed": view.callback_confirmed,
        "scope": view.scope,
        "criteriaApproved": view.criteria_approved,
        "missing": list(view.missing),
        "registeredBy": {
            "role": view.registered_by_role,
            "contactName": view.contact_name,
            "organisationName": view.organisation_name,
        },
        "applicantNumbers": [
            {"label": label, "ending": ending} for label, ending in view.applicant_numbers
        ],
        "callBack": {
            "numberToCall": None,
            "directoryName": view.directory_name,
            "pathwayName": view.pathway_name,
        },
    }


def _decision(view: DecisionView) -> dict[str, Any]:
    return {
        "registrationId": view.registration_id,
        "status": view.status.value,
        "missing": list(view.missing),
        "approvals": [
            {"key": key, "label": label, "done": done} for key, label, done in view.approvals
        ],
        "canApprove": view.can_approve,
        "test": {"sentAt": view.test_sent_at, "channel": view.test_channel},
        "timeline": [{"event": event, "at": format_instant(at)} for event, at in view.timeline],
    }


# ------------------------------------------------------------------------------ the applicant


@router.get("/registrations/{registration_id}/record")
async def read_record(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*APPLICANT))],
) -> Response:
    container = _container(request)
    view = await GetMyRegistration(container.uow_factory, container.clock).execute(
        actor, registration_id
    )
    return _answer(_record(view))


@router.get("/my/registrations")
async def read_my_registrations(
    request: Request, actor: Annotated[Actor, Depends(require_role(*APPLICANT))]
) -> Response:
    rows = await ListMyRegistrations(_container(request).uow_factory).execute(actor)
    return _answer(
        {
            "registrations": [
                {
                    "registrationId": row.registration_id,
                    "serviceId": row.service_id,
                    "serviceName": row.service_name,
                    "status": row.status.value,
                    "submittedAt": _at(row.submitted_at),
                }
                for row in rows
            ]
        }
    )


@router.get("/registrations/{registration_id}/status")
async def read_status(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*APPLICANT))],
) -> Response:
    view = await GetRegistrationStatus(_container(request).uow_factory).execute(
        actor, registration_id
    )
    return _answer(_status(view))


@router.get("/addresses")
async def look_up_addresses(
    request: Request, actor: Annotated[Actor, Depends(require_role(*APPLICANT))]
) -> Response:
    raw = request.query_params.get("postcode")
    postcode = None if raw is None else normalise_postcode(raw)
    if postcode is None:
        raise ValidationFailed("postcode", "Enter a full postcode")
    try:
        found = await _container(request).geocoder.find_addresses(postcode)
    except TransientLookupError, LookupRejected:
        # Never an empty list for a lookup that could not answer: the page says so.
        raise TemporarilyUnavailable(RETRY_AFTER_LOOKUP_SECONDS) from None
    return _answer(
        {
            "addresses": [
                {"id": item.uprn, "label": f"{item.line}, {item.town}"}
                for item in found[:MAX_ADDRESSES]
            ]
        }
    )


async def _act(
    request: Request,
    actor: Actor,
    registration_id: str,
    operation: str,
    run: Any,
) -> Response:
    key = idempotency_key(request)
    command = RegistrationActionCommand(
        idempotency_key=key, actor=actor, registration_id=registration_id
    )

    async def once() -> Response:
        return _answer(await run(_container(request), command))

    return await replay_or_run(
        request, actor, f"registration-{operation}:{registration_id}:{key}", once
    )


@router.post("/registrations/{registration_id}/test-notification")
async def send_test_notification(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*APPLICANT_OR_LEAD))],
) -> Response:
    async def run(container: _Container, command: RegistrationActionCommand) -> dict[str, Any]:
        result = await SendTestNotification(
            container.uow_factory, container.ids, container.clock, container.sealer
        ).execute(command)
        return {"sentAt": format_instant(result.sent_at), "channel": result.channel.value}

    return await _act(request, actor, registration_id, "test", run)


@router.post("/registrations/{registration_id}/review-request")
async def request_review(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*APPLICANT))],
) -> Response:
    async def run(container: _Container, command: RegistrationActionCommand) -> dict[str, Any]:
        result = await RequestRegistrationReview(container.uow_factory, container.clock).execute(
            command
        )
        return {"requestedAt": format_instant(result.requested_at)}

    return await _act(request, actor, registration_id, "review", run)


@router.post("/registrations/{registration_id}/confirm-details")
async def confirm_details(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*APPLICANT))],
) -> Response:
    async def run(container: _Container, command: RegistrationActionCommand) -> dict[str, Any]:
        result = await ConfirmRegistrationDetails(container.uow_factory, container.clock).execute(
            command
        )
        return {"status": result.status.value, "confirmedAt": format_instant(result.confirmed_at)}

    return await _act(request, actor, registration_id, "confirm", run)


# ---------------------------------------------------------------------------------- the lead


def _review_status(container: _Container) -> GetReviewStatus:
    return GetReviewStatus(
        container.uow_factory,
        HmacPhoneHasher(container.secrets),
        container.clock,
        area_districts_for=container.area_districts_for,
    )


@router.get("/registrations")
async def read_queue(
    request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    queue = await ListRegistrationQueue(_container(request).uow_factory).execute(
        actor, request.query_params.get("tab")
    )
    return _answer(
        {
            "tab": queue.tab,
            "counts": queue.counts,
            "tabs": [
                {"key": key, "label": label, "count": queue.counts[key]}
                for key, (label, _) in QUEUE_TABS.items()
            ],
            "registrations": [
                {
                    "registrationId": row.registration_id,
                    "serviceId": row.service_id,
                    "serviceName": row.service_name,
                    "category": row.category,
                    "status": row.status.value,
                    "submittedAt": _at(row.submitted_at),
                    "registeredBy": {
                        "role": row.registered_by_role,
                        "contactName": row.contact_name,
                    },
                    "reviewRequestedAt": row.review_requested_at,
                }
                for row in queue.rows
            ],
        }
    )


@router.get("/registrations/{registration_id}/overview")
async def read_overview(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*LEAD))],
) -> Response:
    container = _container(request)
    view = await GetReviewOverview(_review_status(container), container.uow_factory).execute(
        actor, registration_id
    )
    return _answer(_overview(view))


@router.get("/registrations/{registration_id}/decision")
async def read_decision(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*LEAD))],
) -> Response:
    container = _container(request)
    view = await GetDecision(_review_status(container), container.uow_factory).execute(
        actor, registration_id
    )
    return _answer(_decision(view))


@router.post("/fhir/Task/{registration_id}/$start-review")
async def start_review(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*LEAD))],
) -> Response:
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        result = await StartReview(
            container.uow_factory,
            HmacPhoneHasher(container.secrets),
            container.clock,
            area_districts_for=container.area_districts_for,
        ).execute(
            StartReviewCommand(idempotency_key=key, actor=actor, registration_id=registration_id)
        )
        return _task_response(registration_id, result.status.value)

    return await replay_or_run(request, actor, f"start-review:{registration_id}:{key}", run)


@router.post("/fhir/Task/{registration_id}/$explain-check")
async def explain_check(
    registration_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*LEAD))],
) -> Response:
    key = idempotency_key(request)
    try:
        index = index_parameters(json.loads(await request.body()))
    except ValueError:
        raise ValidationFailed(PARAMETERS, "the body is not valid JSON") from None
    check = text(single(index, "check", required=True), "check")
    note = text(single(index, "note", required=True), "note", limit=NOTE_MAX_LENGTH)
    container = _container(request)

    async def run() -> Response:
        result = await ExplainCheck(
            container.uow_factory,
            HmacPhoneHasher(container.secrets),
            container.clock,
            area_districts_for=container.area_districts_for,
        ).execute(
            ExplainCheckCommand(
                idempotency_key=key,
                actor=actor,
                registration_id=registration_id,
                check_name=check,
                note=note,
            )
        )
        return FhirJSONResponse(
            content={
                "resourceType": PARAMETERS,
                "parameter": [{"name": "automaticOk", "valueBoolean": result.automatic_ok}],
            },
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"explain-check:{registration_id}:{key}", run)


__all__ = ["router"]
