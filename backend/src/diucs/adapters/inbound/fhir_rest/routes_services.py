"""HealthcareService and capacity Observation endpoints over FHIR (R04).

GET  /fhir/HealthcareService            search (active, service-category, organization, paging)
GET  /fhir/HealthcareService/{id}       one service with an ETag
POST /fhir/Observation                  one capacity report (ReportCapacity, U01)
GET  /fhir/Observation?focus=...        the latest report of a service
GET  /fhir/Observation/{id}             one report (where Location points)
PUT, PATCH, DELETE /fhir/Observation/{id}   405: reports are never edited

The routes hold no business rule. A report goes through the ReportCapacity use case, which decides
the range, back-dating, flags, audit, outbox and replay; the route never writes the store. What the
routes decide is the shape of the request: which elements and parameters are accepted, who may call,
and which answer an id that is not the caller's gets (the same 404 as an unknown id).

Tenancy: no tenant is read, passed or accepted here. The tenant is the scope the unit of work was
bound to by the edge from the verified token (`auth.current_actor`, TEN-018).
The one place a route looks at the scope is the `organization` search parameter, which matches only
the caller's own organisation (DEC-168 item 4).
"""

import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, Final
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest import capability
from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import (
    current_actor,
    ensure_can_act_for,
    ensure_screen_live,
    require_role,
)
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.concurrency import (
    idempotency_key,
    replay_or_run,
    versioned_response,
)
from diucs.adapters.inbound.fhir_rest.errors import operation_outcome
from diucs.adapters.inbound.fhir_rest.mapping import (
    FHIR_ID_PATTERN,
    ReportRequest,
    report_request_from_fhir,
    report_to_fhir,
    search_bundle,
    service_to_fhir,
    ucum_unit,
    validate_outbound,
)
from diucs.adapters.inbound.fhir_rest.routes_board import BOARD_ROLES
from diucs.adapters.inbound.fhir_rest.validation import validated_body
from diucs.application.actor import Actor
from diucs.application.ports.outbound.terminology import profile_url
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind
from diucs.application.tenant_settings import DirectoryZones
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.domain.codes import (
    BASE_URL,
    CODE_SYSTEM_NAMES,
    Role,
    ServiceCategory,
    code_system_url,
    parse_code,
)
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile

SERVICES_PATH: Final = "/fhir/HealthcareService"
OBSERVATION_PATH: Final = "/fhir/Observation"
DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100
"""A page of services is at most this many. The directory holds tens of services, so a page of 100
is the whole list for any realistic tenant, and the cap keeps one request bounded."""
MAX_OFFSET: Final = 10**6
REPORT_WRITE_ROLES: Final = (Role.REPORTER, Role.LEAD)
REPORT_READ_ROLES: Final = (*BOARD_ROLES, Role.REPORTER)
NOT_EDITED_TEXT: Final = "Reports are not edited. Send a new report."

_ID: Final = re.compile(FHIR_ID_PATTERN)
_NUMBER: Final = re.compile(r"[0-9]{1,7}")
_SERVICE_PARAMS: Final = frozenset(
    {"active", "service-category", "organization", "_count", "_offset"}
)
_OBSERVATION_PARAMS: Final = frozenset({"focus", "_sort", "_count"})
_CATEGORY_SYSTEM: Final = code_system_url(CODE_SYSTEM_NAMES[ServiceCategory])
_ORGANIZATION_PREFIX: Final = "Organization/"
_SERVICE_PREFIX: Final = "HealthcareService/"
# What a ReportCapacity refusal names, as the FHIR element the caller sent.
_REPORT_ELEMENTS: Final = {
    "value": "Observation.valueQuantity.value",
    "effective_at": "Observation.effectiveDateTime",
}

router = APIRouter(prefix="/fhir")


def register_capabilities() -> None:
    """Advertise the two resources in the CapabilityStatement, once per process: building the app
    again (every test does) finds them registered and leaves them."""
    registrations = (
        (
            "HealthcareService",
            ("read", "search-type"),
            (
                f"{BASE_URL}OperationDefinition/board",
                f"{BASE_URL}OperationDefinition/confirm-capacity",
            ),
        ),
        ("Observation", ("read", "create", "search-type"), ()),
    )
    for resource_type, interactions, operations in registrations:
        if not capability.is_registered(resource_type):
            capability.register_resource(resource_type, interactions, operations)


# Search parameters


def _search_params(request: Request, allowed: frozenset[str]) -> dict[str, str]:
    """The query parameters, each at most once, and only those this search supports. An unknown
    parameter is refused rather than ignored, because ignoring a filter would return a wider answer
    than the caller asked for. Its name is not echoed."""
    values: dict[str, str] = {}
    for name, value in request.query_params.multi_items():
        if name not in allowed:
            raise ValidationFailed("parameters", "a search parameter is not supported")
        if name in values:
            raise ValidationFailed(name, "may be given once")
        values[name] = value
    return values


def _number(name: str, text: str, *, least: int, most: int) -> int:
    if _NUMBER.fullmatch(text) is None or not least <= int(text) <= most:
        raise ValidationFailed(name, f"must be a whole number from {least} to {most}")
    return int(text)


def _service_id_of(value: str, name: str) -> str:
    service_id = value[len(_SERVICE_PREFIX) :] if value.startswith(_SERVICE_PREFIX) else value
    if _ID.fullmatch(service_id) is None:
        raise ValidationFailed(name, "is not a valid service reference")
    return service_id


@dataclass(frozen=True, slots=True)
class _ServiceSearch:
    active_given: bool
    category: ServiceCategory | None
    organization: str | None
    count: int
    count_given: bool
    offset: int
    offset_given: bool

    def filters(self) -> list[tuple[str, str]]:
        parts: list[tuple[str, str]] = []
        if self.active_given:
            parts.append(("active", "true"))
        if self.category is not None:
            parts.append(("service-category", self.category.value))
        if self.organization is not None:
            parts.append(("organization", self.organization))
        return parts


def _services_url(parts: list[tuple[str, str]]) -> str:
    return f"{SERVICES_PATH}?{urlencode(parts)}" if parts else SERVICES_PATH


def _parse_category(text: str) -> ServiceCategory:
    system, bar, code = text.rpartition("|")
    if bar and system != _CATEGORY_SYSTEM:
        raise ValidationFailed("service-category", "is not a known service category")
    try:
        return parse_code(ServiceCategory, code)
    except ValidationFailed:
        raise ValidationFailed("service-category", "is not a known service category") from None


def _parse_organization(text: str) -> str:
    organization = text.removeprefix(_ORGANIZATION_PREFIX)
    if _ID.fullmatch(organization) is None:
        raise ValidationFailed("organization", "is not a valid organization reference")
    return organization


def _parse_services(params: dict[str, str]) -> _ServiceSearch:
    if "active" in params and params["active"] != "true":
        # Only active services can be listed: the port has no list of the others, and a service
        # that has not registered has no profile to show.
        raise ValidationFailed("active", "only active services are listed: use active=true")
    category = _parse_category(params["service-category"]) if "service-category" in params else None
    organization = _parse_organization(params["organization"]) if "organization" in params else None
    count = (
        _number("_count", params["_count"], least=1, most=MAX_PAGE_SIZE)
        if "_count" in params
        else DEFAULT_PAGE_SIZE
    )
    offset = (
        _number("_offset", params["_offset"], least=0, most=MAX_OFFSET)
        if "_offset" in params
        else 0
    )
    return _ServiceSearch(
        active_given="active" in params,
        category=category,
        organization=organization,
        count=count,
        count_given="_count" in params,
        offset=offset,
        offset_given="_offset" in params,
    )


# Reading a service


async def _profile(uow: UnitOfWork, service_id: str) -> ServiceProfile | None:
    """The service's profile, or None for an unknown service and for one with no profile yet (a
    scope-list entry that has not registered reads as not found, lesson L104)."""
    found = await _versioned(uow, service_id)
    return None if found is None else found[0]


async def _versioned(uow: UnitOfWork, service_id: str) -> tuple[ServiceProfile, int] | None:
    try:
        return await uow.services.get_versioned(service_id)
    except ValidationFailed:
        return None


@router.get("/HealthcareService")
async def search_services(
    request: Request, actor: Annotated[Actor, Depends(current_actor)]
) -> Response:
    await ensure_screen_live(request, actor)
    search = _parse_services(_search_params(request, _SERVICE_PARAMS))
    async with get_container(request).uow_factory() as uow:
        profiles = await uow.services.list_active()
        scope = uow.unit_scope
    # The organisation is the tenant (DEC-132 item 1): `organization` matches the caller's own
    # scope and nothing else. Another organisation, or no scope bound, matches no service.
    own_organization = (
        scope is not None and scope.kind is ScopeKind.TENANT and scope.value == search.organization
    )
    if search.organization is not None and not own_organization:
        profiles = []
    if search.category is not None:
        profiles = [p for p in profiles if p.category is search.category]
    page = profiles[search.offset : search.offset + search.count]
    own = search.filters()
    if search.count_given:
        own.append(("_count", str(search.count)))
    if search.offset_given:
        own.append(("_offset", str(search.offset)))
    next_offset = search.offset + search.count
    next_url = (
        _services_url(
            [*search.filters(), ("_count", str(search.count)), ("_offset", str(next_offset))]
        )
        if next_offset < len(profiles)
        else None
    )
    bundle = search_bundle(
        [service_to_fhir(profile) for profile in page],
        total=len(profiles),
        self_url=_services_url(own),
        next_url=next_url,
    )
    return FhirJSONResponse(content=validate_outbound(bundle))


@router.get("/HealthcareService/{service_id}")
async def read_service(
    service_id: str, request: Request, actor: Annotated[Actor, Depends(current_actor)]
) -> Response:
    await ensure_screen_live(request, actor)
    found = None
    if _ID.fullmatch(service_id) is not None:
        async with get_container(request).uow_factory() as uow:
            found = await _versioned(uow, service_id)
    if found is None:
        raise NotFound("no service with this id")
    profile, version = found
    return versioned_response(validate_outbound(service_to_fhir(profile)), version_id=version)


# Reading reports


def _may_read_capacity(actor: Actor, service_id: str) -> None:
    # The board roles read any service's figures. A reporter reads only their own services.
    if actor.role is Role.REPORTER:
        ensure_can_act_for(actor, service_id)


@router.get("/Observation")
async def search_reports(
    request: Request, actor: Annotated[Actor, Depends(require_role(*REPORT_READ_ROLES))]
) -> Response:
    params = _search_params(request, _OBSERVATION_PARAMS)
    if "focus" not in params:
        raise ValidationFailed("focus", "is required: name the service")
    service_id = _service_id_of(params["focus"], "focus")
    if params.get("_sort", "-date") != "-date":
        raise ValidationFailed("_sort", "only the newest first is supported: use _sort=-date")
    if params.get("_count", "1") != "1":
        raise ValidationFailed("_count", "only the latest report is returned: use _count=1")
    _may_read_capacity(actor, service_id)
    async with get_container(request).uow_factory() as uow:
        profile = await _profile(uow, service_id)
        if profile is None:
            raise NotFound("no service with this id")
        report = await uow.capacity.latest(service_id)
    bundle = search_bundle(
        [] if report is None else [report_to_fhir(report)],
        total=0 if report is None else 1,
        self_url=f"{OBSERVATION_PATH}?focus={_SERVICE_PREFIX}{service_id}&_sort=-date&_count=1",
    )
    return FhirJSONResponse(
        content=validate_outbound(bundle), headers={"Cache-Control": "no-store"}
    )


@router.get("/Observation/{report_id}")
async def read_report(
    report_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*REPORT_READ_ROLES))],
) -> Response:
    report: CapacityReport | None = None
    if _ID.fullmatch(report_id) is not None:
        async with get_container(request).uow_factory() as uow:
            report = await uow.capacity.get(report_id)
    if report is None:
        raise NotFound("no report with this id")
    _may_read_capacity(actor, report.service_id)
    return FhirJSONResponse(
        content=validate_outbound(report_to_fhir(report)), headers={"Cache-Control": "no-store"}
    )


@router.api_route("/Observation/{report_id}", methods=["PUT", "PATCH", "DELETE"])
async def refuse_edit() -> Response:
    return operation_outcome(405, "not-supported", NOT_EDITED_TEXT, headers={"Allow": "GET, HEAD"})


# Creating a report


class UnitOfWorkIdempotency:
    """The idempotency store for ReportCapacity's early replay check, on the application's own
    unit of work, so this adapter needs no outbound adapter. The authoritative check and the write
    of the key are inside the use case's unit of work. (The same small class is in routes_board.)"""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, key: str) -> object | None:
        async with self._uow_factory() as uow:
            return await uow.idempotency.get(key)

    async def put(self, key: str, result: object) -> None:
        async with self._uow_factory() as uow:
            await uow.idempotency.put(key, result)
            await uow.commit()


def _check_matches_service(request: ReportRequest, profile: ServiceProfile) -> None:
    """The use case stamps the service's own measure on the report, so a sender who names another
    measure or unit would be told one thing and have another stored. Refuse the mismatch."""
    if request.measure is not profile.measure:
        raise ValidationFailed("Observation.code", "is not the measure this service reports")
    if request.unit != ucum_unit(profile.measure):
        raise ValidationFailed(
            "Observation.valueQuantity.code", "is not the unit of this service's measure"
        )


async def _json_object(request: Request) -> Any:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise ValidationFailed("Observation", "the body is not valid JSON") from None


@router.post("/Observation")
async def create_report(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*REPORT_WRITE_ROLES))],
    _conforming: Annotated[
        dict[str, Any],
        Depends(validated_body(profile_url("DiucsCapacityReport"), "Observation")),
    ],
) -> Response:
    # The body conforms to the capacity profile (R14) before anything else. The key and the body
    # are checked before the service is looked at, so a refusal here never depends on which
    # services exist.
    key = idempotency_key(request)
    report_request = report_request_from_fhir(await _json_object(request), actor, key)
    command = report_request.command
    ensure_can_act_for(actor, command.service_id)
    container = get_container(request)

    async def run() -> Response:
        async with container.uow_factory() as uow:
            profile = await _profile(uow, command.service_id)
        if profile is None:
            raise NotFound("no service with this id")
        _check_matches_service(report_request, profile)
        use_case = ReportCapacity(
            container.uow_factory,
            container.clock,
            container.ids,
            UnitOfWorkIdempotency(container.uow_factory),
            zones=DirectoryZones(container.tenants),
        )
        try:
            result = await use_case.execute(command)
        except ValidationFailed as refused:
            raise ValidationFailed(
                _REPORT_ELEMENTS.get(refused.field, "Observation"), refused.message
            ) from None
        async with container.uow_factory() as uow:
            stored = await uow.capacity.get(result.report_id)
        if stored is None:
            raise RuntimeError("the report that was just stored cannot be read")
        return FhirJSONResponse(
            content=validate_outbound(report_to_fhir(stored)),
            status_code=201,
            headers={"Location": f"{OBSERVATION_PATH}/{stored.id}"},
        )

    # The cache name carries the operation, so one key sent to another operation is not answered
    # from this one's response; the use case then refuses it as a Conflict.
    return await replay_or_run(request, actor, f"observation:{key}", run)
