"""Shift lead routes over HTTP (R08, U15, U16): set a service up for a reporter, and change a
reporter's number for leave or cover. Thin: each route reads the FHIR Parameters, runs one use case
and maps the result. No business rule lives here.

POST /fhir/HealthcareService/$setup              role lead; Idempotency-Key required; Parameters in;
                                                 201 HealthcareService out (SetupServiceByLead, U15)
POST /fhir/PractitionerRole/{id}/$change-number  role lead; Idempotency-Key required; Parameters in;
                                                 200 Parameters out: numberEnding and, for a cover,
                                                 coverUntil (ChangeReporterNumber, U16)

The `$setup` Parameters are: name, category, measure, unitLabel, establishedCapacity, usualMin,
usualMax, cadence, channel (text or email), mobile or email, roleName, availableFrom and availableTo
(HH:MM; the hours are needed by U15 and are not in the prompt's list, DEC-344 item 2), and the
criteria: ageMin, optional ageMax, district (repeating, at least one), accepts and excludes
(repeating), reviewBy, optional ownerRoleName (default "Criteria owner"). Parts of a `criteria`
parameter are read as top-level parameters too.

Refusals: a role other than lead is a non-revealing 404 (require_role). A missing or malformed
Idempotency-Key is a 400. A bad element is a 400 that names the element, never its value. A phone
number is never in a response, a log or an error: a bad one answers with the example
"07700 900123", and a change answers with the last four digits only.

Tenancy: the lead's tenant is bound at the REST edge from the verified token (TEN-018). Until that
lands, nothing is bound here, the use cases refuse with TenantNotBound, and the request fails
closed (500), as the wall-screen connect route does (R15). The route never reads a tenant from the
body, the query or a header.
"""

import json
from datetime import date, time
from enum import StrEnum
from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.adapters.inbound.fhir_rest.mapping import service_to_fhir, validate_outbound
from diucs.adapters.inbound.fhir_rest.routes_services import UnitOfWorkIdempotency
from diucs.application.actor import Actor
from diucs.application.idempotency import format_instant
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import HmacPhoneHasher, normalise_uk_mobile
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.change_reporter_number import (
    ChangeReporterNumber,
    ChangeReporterNumberCommand,
    CoverDuration,
)
from diucs.application.use_cases.setup_service_by_lead import (
    SetupServiceByLead,
    SetupServiceCommand,
)
from diucs.domain.codes import Cadence, Channel, Measure, NeedCategory, Role, ServiceCategory
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.service import AvailableTime

router = APIRouter(prefix="/fhir")
MOBILE_REFUSAL: Final = "Enter a UK mobile number, for example 07700 900123"
OWNER_ROLE_DEFAULT: Final = "Criteria owner"
"""The owner role name when the caller gives none. [ASSUMED] (DEC-344 item 3)."""
PILOT_CHANNELS: Final = frozenset({Channel.TEXT, Channel.EMAIL})
"""push is outside the pilot for a new service (R08): a 400."""
_VALUE_KEYS: Final = ("valueString", "valueCode", "valueInteger", "valueDate", "valueBoolean")
_PARAMETERS: Final = "Parameters"


def _json_body(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        raise ValidationFailed(_PARAMETERS, "the body is not valid JSON") from None


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...
    @property
    def ids(self) -> IdGenerator: ...
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...
    @property
    def secrets(self) -> SecretStore: ...


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


def _index(body: object) -> dict[str, list[dict[str, Any]]]:
    """The parameters by name, with the parts of a `criteria` parameter read as top-level ones."""
    if not isinstance(body, dict) or body.get("resourceType") != _PARAMETERS:
        raise ValidationFailed(_PARAMETERS, "the body must be a FHIR Parameters resource")
    index: dict[str, list[dict[str, Any]]] = {}
    for item in body.get("parameter") or []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValidationFailed("parameter", "every parameter needs a name")
        index.setdefault(item["name"], []).append(item)
        if item["name"] == "criteria":
            for part in item.get("part") or []:
                if isinstance(part, dict) and isinstance(part.get("name"), str):
                    index.setdefault(part["name"], []).append(part)
    return index


def _single(index: dict[str, list[dict[str, Any]]], name: str, *, required: bool) -> object:
    items = index.get(name, [])
    if not items:
        if required:
            raise ValidationFailed(name, "is required")
        return None
    if len(items) > 1:
        raise ValidationFailed(name, "is given once")
    for key in _VALUE_KEYS:
        if key in items[0]:
            return items[0][key]
    raise ValidationFailed(name, "has no value")


def _repeated(index: dict[str, list[dict[str, Any]]], name: str) -> list[object]:
    values: list[object] = []
    for item in index.get(name, []):
        for key in _VALUE_KEYS:
            if key in item:
                values.append(item[key])
                break
        else:
            raise ValidationFailed(name, "has no value")
    return values


def _enum[E: StrEnum](enum_cls: type[E], value: object, name: str) -> E:
    try:
        return enum_cls(str(value))
    except ValueError:
        raise ValidationFailed(name, f"is not a known {name}") from None


def _whole(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValidationFailed(name, "must be a whole number")
    return value


def _clock_time(value: object, name: str) -> time:
    if isinstance(value, str):
        try:
            return time.fromisoformat(value)
        except ValueError:
            pass
    raise ValidationFailed(name, "must be a time as HH:MM")


def _day(value: object, name: str) -> date:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValidationFailed(name, "must be a date as YYYY-MM-DD")


def _national_mobile(value: object) -> str:
    """The national form of a UK mobile, or the example refusal. The input is never repeated."""
    try:
        if not isinstance(value, str):
            raise ValidationFailed("mobile", MOBILE_REFUSAL)
        return normalise_uk_mobile(value)
    except ValidationFailed:
        raise ValidationFailed("mobile", MOBILE_REFUSAL) from None


def setup_command(body: object, actor: Actor, key: str) -> SetupServiceCommand:
    """The use case command for one $setup body. Channel and the phone are checked first, so a
    refusal of either does not depend on the rest of the body."""
    index = _index(body)
    channel = _enum(Channel, _single(index, "channel", required=True), "channel")
    if channel not in PILOT_CHANNELS:
        raise ValidationFailed("channel", "must be text or email: push is outside the pilot")
    mobile_value = _single(index, "mobile", required=False)
    email_value = _single(index, "email", required=False)
    if channel is Channel.TEXT and mobile_value is None:
        raise ValidationFailed("mobile", "is required for a text channel")
    if channel is Channel.EMAIL and email_value is None:
        raise ValidationFailed("email", "is required for an email channel")
    phone = None if mobile_value is None else _national_mobile(mobile_value)
    email = None if email_value is None else str(email_value)
    category = _enum(ServiceCategory, _single(index, "category", required=True), "category")
    measure = _enum(Measure, _single(index, "measure", required=True), "measure")
    cadence = _enum(Cadence, _single(index, "cadence", required=True), "cadence")
    districts = frozenset(str(value) for value in _repeated(index, "district"))
    if not districts:
        raise ValidationFailed("district", "is required")
    start = _clock_time(_single(index, "availableFrom", required=True), "availableFrom")
    end = _clock_time(_single(index, "availableTo", required=True), "availableTo")
    max_age = _single(index, "ageMax", required=False)
    owner = _single(index, "ownerRoleName", required=False)
    return SetupServiceCommand(
        idempotency_key=key,
        actor=actor,
        name=str(_single(index, "name", required=True)),
        category=category,
        measure=measure,
        unit_label=str(_single(index, "unitLabel", required=True)),
        established_capacity=_whole(
            _single(index, "establishedCapacity", required=True), "establishedCapacity"
        ),
        usual_range=(
            _whole(_single(index, "usualMin", required=True), "usualMin"),
            _whole(_single(index, "usualMax", required=True), "usualMax"),
        ),
        cadence=cadence,
        available_times=(AvailableTime.every_day(start, end),),
        channel=channel,
        reporter_role_name=str(_single(index, "roleName", required=True)),
        age_min=_whole(_single(index, "ageMin", required=True), "ageMin"),
        districts=districts,
        accepts=frozenset(_enum(NeedCategory, v, "accepts") for v in _repeated(index, "accepts")),
        excludes=frozenset(
            _enum(NeedCategory, v, "excludes") for v in _repeated(index, "excludes")
        ),
        review_by=_day(_single(index, "reviewBy", required=True), "reviewBy"),
        owner_role_name=OWNER_ROLE_DEFAULT if owner is None else str(owner),
        phone=phone,
        email=email,
        age_max=None if max_age is None else _whole(max_age, "ageMax"),
    )


def change_parameters(body: object) -> tuple[str, CoverDuration]:
    """The new national mobile and the cover duration of one $change-number body."""
    index = _index(body)
    mobile = _national_mobile(_single(index, "mobile", required=True))
    duration = _enum(CoverDuration, _single(index, "duration", required=True), "duration")
    return mobile, duration


def number_ending(mobile: str) -> str:
    """The last four digits of a UK mobile, for a response (R08: never the whole number)."""
    return normalise_uk_mobile(mobile)[-4:]


async def _body(request: Request) -> object:
    return _json_body(await request.body())


@router.post("/HealthcareService/$setup", status_code=201)
async def set_up_service(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    key = idempotency_key(request)
    command = setup_command(await _body(request), actor, key)
    container = _container(request)

    async def run() -> Response:
        use_case = SetupServiceByLead(
            container.uow_factory,
            container.clock,
            container.ids,
            UnitOfWorkIdempotency(container.uow_factory),
            HmacPhoneHasher(container.secrets),
        )
        result = await use_case.execute(command)
        async with container.uow_factory() as uow:
            profile = await uow.services.get(result.service_id)
        if profile is None:
            raise RuntimeError("the service that was just stored cannot be read")
        return FhirJSONResponse(
            content=validate_outbound(service_to_fhir(profile)),
            status_code=201,
            headers={"Location": f"/fhir/HealthcareService/{profile.id}"},
        )

    return await replay_or_run(request, actor, f"lead-setup:{key}", run)


@router.post("/PractitionerRole/{role_id}/$change-number")
async def change_reporter_number(
    role_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    key = idempotency_key(request)
    mobile, duration = change_parameters(await _body(request))
    container = _container(request)

    async def run() -> Response:
        async with container.uow_factory() as uow:
            role = await uow.people.get_role(role_id)
        if role is None or role.service_id is None:
            raise NotFound("no reporter role with this id")
        result = await ChangeReporterNumber(
            container.uow_factory,
            container.clock,
            container.ids,
            UnitOfWorkIdempotency(container.uow_factory),
            HmacPhoneHasher(container.secrets),
        ).execute(
            ChangeReporterNumberCommand(
                idempotency_key=key,
                actor=actor,
                service_id=role.service_id,
                new_mobile=mobile,
                duration=duration,
            )
        )
        parameters: list[dict[str, Any]] = [
            {"name": "numberEnding", "valueString": number_ending(mobile)}
        ]
        if result.covered_until is not None:
            parameters.append(
                {"name": "coverUntil", "valueDateTime": format_instant(result.covered_until)}
            )
        return FhirJSONResponse(
            content={"resourceType": _PARAMETERS, "parameter": parameters},
            headers={"Cache-Control": "no-store"},
        )

    return await replay_or_run(request, actor, f"lead-change:{key}", run)


__all__ = [
    "change_parameters",
    "change_reporter_number",
    "number_ending",
    "router",
    "set_up_service",
    "setup_command",
]
