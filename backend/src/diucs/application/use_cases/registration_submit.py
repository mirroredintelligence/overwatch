"""Registration persistence: a submitted draft becomes draft FHIR resources in one transaction.

Task U27.

Submit (U26) stores the applicant's answers as a draft. This module turns a complete draft into a
FHIR `transaction` Bundle (Organization, Location, HealthcareService and the first ServiceCriteria
as Basic), asks the ODS terminology and the geocoder what they know, and writes the bundle with the
audit entry and the outbox message in one unit of work: all of it commits or none of it does.

Everything is a draft. `Organization.active` and `HealthcareService.active` are false, the Location
is inactive, and criteria version 1 is `pending-approval`; nothing is live until approval (U29). The
service already exists as the inactive placeholder the scope list made (DEC-082 item 4), so its
entry is a PUT onto that id; the others are POSTs. The reporter's phone or email is in no resource:
it stays in the protected contact store. The criteria owner needs a post for the criteria's author,
so a practitioner, a criteria-owner post and the owner's email (protected) are written with it.

The ODS result and the address result are kept on the registration as the `lookups` step of its
draft, for the review (U28). An ODS code that is not found does not stop the registration.
Decisions: DEC-313 to DEC-315 (U27).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.geo import AddressCandidate, Geocoder
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.terminology import Terminology
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import current_tenant
from diucs.application.use_cases.registration_draft import (
    LocationStep,
    OrganisationStep,
    RegistrationDraft,
    ReportingStep,
    ServiceStep,
    read_draft,
)
from diucs.domain.codes import (
    BASE_URL,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    PractitionerRoleCode,
    RegistrationStatus,
    Role,
    ServiceCategory,
    code_system_url,
    coding_for,
    parse_code,
)
from diucs.domain.errors import InvalidTransition, NotFound, ValidationFailed
from diucs.domain.events import RegistrationPersisted
from diucs.domain.model.people import (
    Practitioner,
    PractitionerRole,
    check_email_domain,
    check_staff_text,
)
from diucs.domain.model.registration import (
    DISTRICT_TYPE_CODE,
    LOCATION_TYPE_SYSTEM,
    Registration,
)
from diucs.domain.model.service import ESTABLISHED_CAPACITY_MIN, LIMITED_LEVEL_PERCENT_DEFAULT
from diucs.domain.rules.postcode import normalise_district, normalise_postcode, postcode_district

ODS_ORG_SYSTEM: Final = "https://fhir.nhs.uk/Id/ods-organization-code"
"""The system the mapper copies to the Organization's `odsCode` (a test pins the two as equal)."""
UPRN_SYSTEM: Final = "https://diucs.example/uprn"
GEOCODE_SOURCE: Final = "os-places"
LOOKUPS_STEP: Final = "lookups"
"""The key of the lookup record in a registration's draft. It is not a wizard step: `read_draft`
ignores it and a save of a step keeps it."""
PHYSICAL_TYPE_SYSTEM: Final = "http://terminology.hl7.org/CodeSystem/location-physical-type"
BUILDING: Final = "bu"
AREA: Final = "ar"
UNIT_LABELS: Final[Mapping[Measure, str]] = {
    Measure.FREE_SLOTS: "slots",
    Measure.FREE_BEDS: "beds",
    Measure.REFERRALS_ACCEPTABLE: "referrals",
    Measure.OCCUPIED_PATIENTS: "patients",
    Measure.PACKAGES_FREE: "packages",
    Measure.OTHER: "places",
}
"""The words shown after a figure, by measure [ASSUMED]: the draft does not ask for them."""
CAN_EXCEED_ESTABLISHED: Final = False
"""A service registered through the wizard reports within its established capacity [ASSUMED]."""
CRITERIA_VERSION: Final = 1
OWNER_POST_CODE: Final = PractitionerRoleCode.CRITERIA_OWNER
OWNER_FALLBACK_NAME: Final = "Criteria owner"
PERSIST_USE_CASE: Final = "PersistRegistration"
AUDIT_ACTION: Final = "C"
PERSISTABLE: Final = frozenset({RegistrationStatus.SUBMITTED, RegistrationStatus.IN_REVIEW})
DAY_ORDER: Final = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_LOOKUP_NAMES: Final = frozenset(
    {
        "ods_found",
        "ods_active",
        "ods_name",
        "ods_type",
        "address_found",
        "address_district",
        "checked_at",
    }
)
_PUNCTUATION: Final = re.compile(r"[^a-z0-9]+")

__all__ = [
    "DISTRICT_TYPE_CODE",
    "GEOCODE_SOURCE",
    "LOOKUPS_STEP",
    "ODS_ORG_SYSTEM",
    "UNIT_LABELS",
    "Lookups",
    "PersistRegistration",
    "PersistRegistrationCommand",
    "PersistRegistrationResult",
    "build_registration_bundle",
    "choose_address",
    "decode_lookups",
    "encode_lookups",
    "lookups_of",
    "unit_label",
]


@dataclass(frozen=True, slots=True)
class Lookups:
    """What the ODS directory and the geocoder said when the registration was persisted, kept for
    the review. A name or district that was not found is None."""

    ods_found: bool
    ods_active: bool
    ods_name: str | None
    ods_type: str | None
    address_found: bool
    address_district: str | None
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class PersistRegistrationCommand:
    registration_id: str


@dataclass(frozen=True, slots=True)
class PersistRegistrationResult:
    persisted: bool
    """False when the registration had already been persisted: nothing was written."""
    service_id: str


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def encode_lookups(lookups: Lookups) -> dict[str, Any]:
    """The lookup record as draft fields: text, whole numbers and flags, with a value that was not
    found left out (the store keeps no null, lesson L74)."""
    values: dict[str, Any] = {
        "ods_found": lookups.ods_found,
        "ods_active": lookups.ods_active,
        "address_found": lookups.address_found,
        "checked_at": _iso(lookups.checked_at),
    }
    for name, value in (
        ("ods_name", lookups.ods_name),
        ("ods_type", lookups.ods_type),
        ("address_district", lookups.address_district),
    ):
        if value is not None:
            values[name] = value
    return values


def decode_lookups(values: Mapping[str, Any]) -> Lookups:
    """The lookup record a draft holds. A field it does not have, or a value of the wrong type, is
    refused (fail closed)."""
    if set(values) - _LOOKUP_NAMES:
        raise ValidationFailed("draft", "the lookup record holds a field it does not have")
    flags = {}
    for name in ("ods_found", "ods_active", "address_found"):
        value = values.get(name)
        if not isinstance(value, bool):
            raise ValidationFailed(name, "must be a flag")
        flags[name] = value
    texts: dict[str, str | None] = {}
    for name in ("ods_name", "ods_type", "address_district"):
        value = values.get(name)
        if value is not None and not isinstance(value, str):
            raise ValidationFailed(name, "must be text")
        texts[name] = value
    checked = values.get("checked_at")
    if not isinstance(checked, str):
        raise ValidationFailed("checked_at", "must be a datetime")
    try:
        checked_at = datetime.fromisoformat(checked)
    except ValueError:
        raise ValidationFailed("checked_at", "not a datetime") from None
    if checked_at.tzinfo is None:
        raise ValidationFailed("checked_at", "must carry a UTC offset")
    return Lookups(
        ods_found=flags["ods_found"],
        ods_active=flags["ods_active"],
        ods_name=texts["ods_name"],
        ods_type=texts["ods_type"],
        address_found=flags["address_found"],
        address_district=texts["address_district"],
        checked_at=checked_at.astimezone(UTC),
    )


def lookups_of(registration: Registration) -> Lookups | None:
    """The lookup record of a registration, or None when it has not been persisted."""
    values = registration.draft.get(LOOKUPS_STEP)
    return None if values is None else decode_lookups(values)


def _normal(text: str) -> str:
    return _PUNCTUATION.sub(" ", text.lower()).strip()


def choose_address(candidates: Sequence[AddressCandidate], text: str) -> AddressCandidate | None:
    """The candidate whose line, or line and town, is the address the applicant chose, ignoring
    case, spacing and punctuation. None when none matches or more than one does: no address is
    guessed, so a wrong position never reaches a service."""
    wanted = _normal(text)
    if not wanted:
        return None
    found = [
        candidate
        for candidate in candidates
        if wanted in {_normal(candidate.line), _normal(f"{candidate.line}, {candidate.town}")}
    ]
    return found[0] if len(found) == 1 else None


def unit_label(measure: Measure) -> str:
    return UNIT_LABELS[measure]


def _items(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _concept(system: str, code: str) -> dict[str, Any]:
    return {"coding": [{"system": system, "code": code}]}


def _coded(member: Any) -> dict[str, Any]:
    coding = coding_for(member)
    return {"coding": [{"system": coding.system, "code": coding.code, "display": coding.display}]}


def _extension_url(short_name: str) -> str:
    """The URL of a registered extension (extensions.py: the StructureDefinition of its name)."""
    return f"{BASE_URL}StructureDefinition/{short_name}"


def _urn(resource_id: str) -> str:
    return f"urn:uuid:{resource_id}"


def _post(resource: dict[str, Any]) -> dict[str, Any]:
    return {
        "fullUrl": _urn(resource["id"]),
        "resource": resource,
        "request": {"method": "POST", "url": resource["resourceType"]},
    }


def _put(resource: dict[str, Any]) -> dict[str, Any]:
    return {
        "fullUrl": _urn(resource["id"]),
        "resource": resource,
        "request": {"method": "PUT", "url": f"{resource['resourceType']}/{resource['id']}"},
    }


def _required[T](step: T | None, name: str) -> T:
    if step is None:
        raise ValidationFailed(name, "the draft has no such step")
    return step


def _organisation(resource_id: str, step: OrganisationStep) -> dict[str, Any]:
    telecom: list[dict[str, Any]] = []
    if step.contact_email:
        telecom.append({"system": "email", "value": step.contact_email.strip()})
    if step.contact_phone:
        telecom.append({"system": "phone", "value": step.contact_phone.strip()})
    return {
        "resourceType": "Organization",
        "id": resource_id,
        "active": False,
        "name": step.name.strip(),
        "identifier": [{"system": ODS_ORG_SYSTEM, "value": step.ods_code}],
        "type": [_concept(code_system_url("organization-type"), step.org_type)],
        "telecom": telecom,
    }


def _opening_hours(step: LocationStep) -> list[dict[str, Any]]:
    if step.open_24h:
        return [{"daysOfWeek": list(DAY_ORDER), "allDay": True}]
    days = set(_items(step.opening_days))
    return [
        {
            "daysOfWeek": [day for day in DAY_ORDER if day in days],
            "allDay": False,
            "openingTime": f"{step.opening_start}:00",
            "closingTime": f"{step.opening_end}:00",
        }
    ]


def _site(
    resource_id: str,
    step: LocationStep,
    organisation_id: str,
    address: AddressCandidate | None,
    now: datetime,
) -> dict[str, Any]:
    postcode = normalise_postcode(address.postcode if address is not None else step.postcode)
    location: dict[str, Any] = {
        "resourceType": "Location",
        "id": resource_id,
        "status": "inactive",
        "name": step.site_name.strip(),
        "mode": "instance",
        "type": [_concept(LOCATION_TYPE_SYSTEM, step.site_type)],
        "physicalType": _concept(PHYSICAL_TYPE_SYSTEM, BUILDING),
        "managingOrganization": {"reference": _urn(organisation_id)},
        "hoursOfOperation": _opening_hours(step),
    }
    postal: dict[str, Any] = {
        "line": [address.line if address is not None else step.address.strip()]
    }
    if address is not None:
        postal["city"] = address.town
    if postcode is not None:
        postal["postalCode"] = postcode
        postal["district"] = postcode_district(postcode)
    postal["country"] = "GB"
    location["address"] = postal
    if address is not None:
        location["position"] = {
            "latitude": address.position.lat,
            "longitude": address.position.lon,
        }
        location["identifier"] = [{"system": UPRN_SYSTEM, "value": address.uprn}]
        location["extension"] = [
            {"url": _extension_url("geocodeSource"), "valueString": GEOCODE_SOURCE},
            {"url": _extension_url("geocodedAt"), "valueDateTime": _iso(now)},
        ]
    return location


def _window(step: ServiceStep) -> dict[str, Any]:
    days = set(_items(step.accepting_days))
    return {
        "daysOfWeek": [day for day in DAY_ORDER if day in days],
        "allDay": False,
        "availableStartTime": f"{step.accepting_start}:00",
        "availableEndTime": f"{step.accepting_end}:00",
    }


def _service(
    service_id: str,
    step: ServiceStep,
    reporting: ReportingStep,
    organisation_id: str,
    locations: list[dict[str, str]],
    *,
    visiting: bool,
) -> dict[str, Any]:
    low, high = _usual(reporting)
    measure = parse_code(Measure, reporting.measure)
    extensions: list[tuple[str, str, Any]] = [
        ("establishedCapacity", "valueInteger", max(high, ESTABLISHED_CAPACITY_MIN)),
        ("canExceedEstablished", "valueBoolean", CAN_EXCEED_ESTABLISHED),
        ("usualRangeMin", "valueInteger", low),
        ("usualRangeMax", "valueInteger", high),
        ("reportCadence", "valueString", reporting.cadence),
        ("limitedLevelPercent", "valueInteger", LIMITED_LEVEL_PERCENT_DEFAULT),
        ("smsShortName", "valueString", step.service_name.strip()),
        ("measure", "valueString", measure.value),
        ("unitLabel", "valueString", unit_label(measure)),
        ("channel", "valueString", parse_code(Channel, reporting.channel).value),
    ]
    service: dict[str, Any] = {
        "resourceType": "HealthcareService",
        "id": service_id,
        "active": False,
        "name": step.service_name.strip(),
        "category": [_coded(parse_code(ServiceCategory, step.category))],
        "providedBy": {"reference": _urn(organisation_id)},
        "referralMethod": [
            _concept(code_system_url("referral-method"), method)
            for method in _items(step.referral_methods)
        ],
        "telecom": [{"system": "phone", "value": step.spoa_phone.strip(), "use": "work"}],
        "availableTime": [_window(step)],
        "extension": [{"url": _extension_url(name), key: value} for name, key, value in extensions],
    }
    service["coverageArea" if visiting else "location"] = locations
    return service


def _usual(reporting: ReportingStep) -> tuple[int, int]:
    low, high = reporting.usual_low, reporting.usual_high
    if type(low) is not int or type(high) is not int:
        raise ValidationFailed("usual_high", "the usual range is not a whole-number pair")
    return low, high


def _area(resource_id: str, district: str, organisation_id: str) -> dict[str, Any]:
    return {
        "resourceType": "Location",
        "id": resource_id,
        "status": "inactive",
        "name": district,
        "mode": "kind",
        "type": [_concept(LOCATION_TYPE_SYSTEM, DISTRICT_TYPE_CODE)],
        "physicalType": _concept(PHYSICAL_TYPE_SYSTEM, AREA),
        "managingOrganization": {"reference": _urn(organisation_id)},
    }


def _criteria_districts(service: ServiceStep, location: LocationStep) -> list[str]:
    named = sorted(
        {d for d in (normalise_district(item) for item in _items(service.districts)) if d}
    )
    if named:
        return named
    postcode = normalise_postcode(location.postcode)
    return [] if postcode is None else [postcode_district(postcode)]


def _needs(text: str) -> list[dict[str, Any]]:
    members = sorted({parse_code(NeedCategory, item) for item in _items(text)})
    return [_coded(member) for member in members]


def _criteria(
    criteria_id: str,
    service_id: str,
    owner_role_id: str,
    step: ServiceStep,
    location: LocationStep,
) -> dict[str, Any]:
    if step.review_by is None:
        raise ValidationFailed("review_by", "the draft has no review-by date")
    if type(step.age_min) is not int:
        raise ValidationFailed("age_min", "the draft has no youngest age")
    criteria: dict[str, Any] = {
        "resourceType": "Basic",
        "id": criteria_id,
        "subject": {"reference": f"HealthcareService/{service_id}"},
        "author": {"reference": f"PractitionerRole/{owner_role_id}"},
        "version": CRITERIA_VERSION,
        "status": CriteriaStatus.PENDING_APPROVAL.value,
        "ageMin": step.age_min,
        "reviewBy": step.review_by.isoformat(),
    }
    if not step.no_age_limit and step.age_max is not None:
        criteria["ageMax"] = step.age_max
    districts = _criteria_districts(step, location)
    if districts:
        criteria["postcodeDistricts"] = districts
    criteria["acceptsNeed"] = _needs(step.needs)
    if not step.no_exclusions and step.excluded_needs:
        criteria["excludesNeed"] = _needs(step.excluded_needs)
    return criteria


def build_registration_bundle(
    draft: RegistrationDraft,
    ids: IdGenerator,
    now: datetime,
    address: AddressCandidate | None,
    *,
    service_id: str,
    owner_role_id: str,
    existing_districts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The FHIR transaction Bundle of a complete draft, in dependency order. Pure: it reads no
    store and no clock; `ids` gives the new resources their ids and `now` stamps the geocode.

    `service_id` is the placeholder the scope list made, replaced by a PUT. `owner_role_id` is the
    criteria owner's post, which the criteria Basic names as its author. `existing_districts` maps
    a postcode district to the id of its Location when one exists: a visiting service reuses it
    instead of writing another. A fixed site's address is the chosen candidate (its position, UPRN
    and geocode record) or None (no position is guessed)."""
    organisation = _required(draft.organisation, "organisation")
    location = _required(draft.location, "location")
    service = _required(draft.service, "service")
    reporting = _required(draft.reporting, "reporting")
    known = existing_districts or {}

    organisation_id = ids.new_id()
    entries: list[dict[str, Any]] = [_post(_organisation(organisation_id, organisation))]
    placed: list[dict[str, str]] = []
    if location.fixed_site:
        site_id = ids.new_id()
        entries.append(_post(_site(site_id, location, organisation_id, address, now)))
        placed.append({"reference": _urn(site_id)})
    else:
        for district in sorted(
            {d for d in (normalise_district(i) for i in _items(service.districts)) if d}
        ):
            if district in known:
                placed.append({"reference": f"Location/{known[district]}"})
                continue
            area_id = ids.new_id()
            entries.append(_post(_area(area_id, district, organisation_id)))
            placed.append({"reference": _urn(area_id)})
    entries.append(
        _put(
            _service(
                service_id,
                service,
                reporting,
                organisation_id,
                placed,
                visiting=not location.fixed_site,
            )
        )
    )
    entries.append(_post(_criteria(ids.new_id(), service_id, owner_role_id, service, location)))
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def _check_state(registration: Registration) -> None:
    if registration.status not in PERSISTABLE:
        raise InvalidTransition(
            f"a registration in {registration.status.value} has not been submitted to write"
        )


def _owner_name(role: str) -> str:
    name = " ".join(role.split())
    try:
        check_staff_text("owner_role", name)
    except ValidationFailed:
        return OWNER_FALLBACK_NAME
    return name or OWNER_FALLBACK_NAME


def _email_domain(address: str) -> str | None:
    domain = address.partition("@")[2].strip().lower()
    try:
        check_email_domain(domain)
    except ValidationFailed:
        return None
    return domain


class PersistRegistration:
    """Write a submitted registration's draft resources, once. The lookups (ODS, geocoder) run
    outside any unit of work, so no lock is held while an external service answers; the write is
    one unit: the owner's post, the bundle, the lookup record, the audit entry and the outbox
    message commit together or not at all. A second call finds the lookup record and writes
    nothing."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        geocoder: Geocoder,
        terminology: Terminology,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._geocoder = geocoder
        self._terminology = terminology
        self._ids = ids
        self._clock = clock

    async def persist_registration(self, registration_id: str) -> PersistRegistrationResult:
        """The call SubmitRegistration makes (its port is `RegistrationPersister`)."""
        return await self.execute(PersistRegistrationCommand(registration_id))

    async def execute(self, command: PersistRegistrationCommand) -> PersistRegistrationResult:
        async with self._uow_factory() as uow:
            registration = await _load(uow, command.registration_id)
            if lookups_of(registration) is not None:
                return PersistRegistrationResult(False, registration.service_id)
            _check_state(registration)
            draft = read_draft(registration)
        organisation = _required(draft.organisation, "organisation")
        location = _required(draft.location, "location")
        ods = await self._terminology.ods_lookup(organisation.ods_code)
        chosen: AddressCandidate | None = None
        if location.fixed_site:
            candidates = await self._geocoder.find_addresses(location.postcode)
            chosen = choose_address(candidates, location.address)

        now = self._clock.now()
        async with self._uow_factory() as uow:
            registration = await _load(uow, command.registration_id)
            if lookups_of(registration) is not None:
                return PersistRegistrationResult(False, registration.service_id)
            _check_state(registration)
            draft = read_draft(registration)
            service = _required(draft.service, "service")
            service_id = registration.service_id
            known: Mapping[str, str] = {}
            if not location.fixed_site:
                wanted = [
                    d for d in (normalise_district(i) for i in _items(service.districts)) if d
                ]
                known = await uow.registrations.district_locations(wanted)
            owner_role_id = await self._write_owner(uow, service, service_id, now)
            bundle = build_registration_bundle(
                draft,
                self._ids,
                now,
                chosen,
                service_id=service_id,
                owner_role_id=owner_role_id,
                existing_districts=known,
            )
            written = await uow.registrations.write_bundle(bundle)
            lookups = Lookups(
                ods_found=ods is not None,
                ods_active=ods is not None and ods.active,
                ods_name=None if ods is None else ods.name,
                ods_type=None if ods is None else ods.org_type,
                address_found=chosen is not None,
                address_district=_district_of(chosen),
                checked_at=now,
            )
            await uow.registrations.save(
                replace(
                    registration,
                    draft={**registration.draft, LOOKUPS_STEP: encode_lookups(lookups)},
                    last_modified=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=PERSIST_USE_CASE,
                    actor=Actor(
                        role=Role.OWNER,
                        practitioner_id=None,
                        device_id=None,
                        channel="system",
                        service_ids=frozenset({service_id}),
                        tenant_id=current_tenant(),
                    ),
                    entity_ids=(
                        registration.id,
                        service_id,
                        *(target.partition("/")[2] for target in written.values()),
                    ),
                    snapshot={
                        "registration_id": registration.id,
                        "service_id": service_id,
                        "resources": len(written),
                        "ods_found": lookups.ods_found,
                        "address_found": lookups.address_found,
                    },
                    at=now,
                )
            )
            await uow.outbox.add(
                outbox_message_for(
                    RegistrationPersisted(
                        registration_id=registration.id, service_id=service_id, at=now
                    ),
                    id=self._ids.new_id(),
                    now=now,
                )
            )
            await uow.commit()
        return PersistRegistrationResult(True, service_id)

    async def _write_owner(
        self, uow: UnitOfWork, service: ServiceStep, service_id: str, now: datetime
    ) -> str:
        """The criteria owner's practitioner and post, and the owner's email in the protected
        contact store. The criteria Basic names the post as its author."""
        practitioner_id = self._ids.new_id()
        role_id = self._ids.new_id()
        await uow.people.save_practitioner(
            Practitioner(
                id=practitioner_id,
                active=True,
                display_name=_owner_name(service.owner_role),
                phone_hash=None,
                email_domain=_email_domain(service.owner_email),
            )
        )
        await uow.people.save_role(
            PractitionerRole(
                id=role_id,
                practitioner_id=practitioner_id,
                service_id=service_id,
                code=OWNER_POST_CODE,
                active=True,
                channel=Channel.EMAIL,
                period_start=now,
            )
        )
        await uow.contacts.put_email(role_id, service.owner_email)
        return role_id


async def _load(uow: UnitOfWork, registration_id: str) -> Registration:
    registration = await uow.registrations.get(registration_id)
    if registration is None:
        raise NotFound("no registration with this id")
    return registration


def _district_of(address: AddressCandidate | None) -> str | None:
    if address is None:
        return None
    postcode = normalise_postcode(address.postcode)
    return None if postcode is None else postcode_district(postcode)
