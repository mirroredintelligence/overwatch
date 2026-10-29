"""Registration drafting and submission (U26, docs/spec/domain-rules.md section 6).

The applicant fills five steps (organisation, location, service, reporting, API). Each save stores
the step as typed fields on the registration's draft, saves even when the step has errors, and
reports them, so the form can show its error summary. Submit needs every step complete and the
registration in draft or needs-changes; it then moves to submitted and records the time.

Contact numbers and addresses for reporting never enter the draft: they are written to the protected
contact store (P16) for the registration's requester role. Decisions: DEC-243.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from datetime import date
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId
from diucs.domain.codes import Cadence, Measure, NeedCategory, RegistrationStatus, ServiceCategory
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import RegistrationSubmitted
from diucs.domain.model.registration import Registration
from diucs.domain.rules.postcode import normalise_district, normalise_postcode
from diucs.domain.rules.registration import invitation_valid, transition_registration

AUDIT_ACTION: Final = "U"
ORGANISATION_TYPES: Final = frozenset(
    {"nhs-trust", "gp-practice", "local-authority", "voluntary-or-independent", "other"}
)
SITE_TYPES: Final = frozenset({"ward", "community-hospital", "hub-or-base", "clinic", "other"})
REFERRAL_METHODS: Final = frozenset({"phone", "systmone", "email", "e-referral"})
DAYS: Final = frozenset({"mon", "tue", "wed", "thu", "fri", "sat", "sun"})
CHANNELS: Final = frozenset({"text", "email", "push"})
MAX_USUAL: Final = 999
_TIME: Final = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
_EMAIL: Final = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_ODS: Final = re.compile(r"[A-Z0-9]{3,6}")
_PHONE_CHARACTERS: Final = re.compile(r"[\s-]")
_PHONE_MESSAGE: Final = "Enter a full phone number, for example 01305 123456"
_MOBILE_MESSAGE: Final = "Enter a mobile number for text messages"


@dataclass(frozen=True, slots=True)
class FieldError:
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class OrganisationStep:
    name: str
    ods_code: str
    org_type: str
    contact_name: str
    contact_email: str = ""
    contact_phone: str = ""


@dataclass(frozen=True, slots=True)
class LocationStep:
    fixed_site: bool
    postcode: str = ""
    address: str = ""
    site_name: str = ""
    site_type: str = ""
    open_24h: bool = False
    opening_days: str = ""
    opening_start: str = ""
    opening_end: str = ""


@dataclass(frozen=True, slots=True)
class ServiceStep:
    service_name: str
    category: str
    referral_methods: str
    spoa_phone: str
    accepting_days: str
    accepting_start: str
    accepting_end: str
    needs: str
    age_min: int | None
    age_max: int | None = None
    no_age_limit: bool = False
    excluded_needs: str = ""
    no_exclusions: bool = False
    owner_role: str = ""
    owner_email: str = ""
    review_by: date | None = None
    districts: str = ""


@dataclass(frozen=True, slots=True)
class ReportingStep:
    measure: str
    usual_low: int | None
    usual_high: int | None
    cadence: str
    channel: str
    holder_name: str = ""
    contact_mobile: str = ""
    contact_email: str = ""


@dataclass(frozen=True, slots=True)
class ApiStep:
    wanted: bool
    name: str = ""
    address: str = ""
    connection: str = ""
    data_type: str = ""


Step = OrganisationStep | LocationStep | ServiceStep | ReportingStep | ApiStep

_KEY_OF: Final[Mapping[type[Any], str]] = {
    OrganisationStep: "organisation",
    LocationStep: "location",
    ServiceStep: "service",
    ReportingStep: "reporting",
    ApiStep: "api",
}
_STEP_OF_KIND: Final[Mapping[str, type[Any]]] = {cls.__name__: cls for cls in _KEY_OF}
_STEP_TYPES: Final[tuple[type[Any], ...]] = tuple(_KEY_OF)
_CONTACT_FIELDS: Final[Mapping[type[Any], frozenset[str]]] = {
    ReportingStep: frozenset({"contact_mobile", "contact_email"}),
}
_DATE_FIELDS: Final = frozenset({"review_by"})


@dataclass(frozen=True, slots=True)
class RegistrationDraft:
    registration_id: str
    organisation: OrganisationStep | None = None
    location: LocationStep | None = None
    service: ServiceStep | None = None
    reporting: ReportingStep | None = None
    api: ApiStep | None = None


def is_full_uk_phone(text: str) -> bool:
    """A full UK number: eleven digits starting 0, or +44 followed by the ten digits after the 0.
    Spaces and hyphens do not count. A short, long, foreign or non-numeric number is refused."""
    compact = _PHONE_CHARACTERS.sub("", text)
    national = "0" + compact[3:] if compact.startswith("+44") else compact
    return re.fullmatch(r"0[0-9]{10}", national) is not None


def _valid_email(text: str) -> bool:
    return _EMAIL.fullmatch(text) is not None


def _set(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _subset(text: str, allowed: frozenset[str] | set[str]) -> bool:
    items = _set(text)
    return bool(items) and all(item in allowed for item in items)


def _enum_values(enum: type[Any]) -> frozenset[str]:
    return frozenset(member.value for member in enum)


def _hours_ok(days: str, start: str, end: str) -> bool:
    if not _subset(days, DAYS):
        return False
    if _TIME.fullmatch(start) is None or _TIME.fullmatch(end) is None:
        return False
    return start != end


def _organisation(step: OrganisationStep) -> list[FieldError]:
    errors: list[FieldError] = []
    if not step.name.strip():
        errors.append(FieldError("name", "Enter the organisation name"))
    if _ODS.fullmatch(step.ods_code) is None:
        errors.append(FieldError("ods_code", "Enter the ODS code"))
    if step.org_type not in ORGANISATION_TYPES:
        errors.append(FieldError("org_type", "Choose an organisation type"))
    if not step.contact_name.strip():
        errors.append(FieldError("contact_name", "Enter a contact name"))
    if not step.contact_email and not step.contact_phone:
        errors.append(FieldError("contact", "Enter a contact email or phone number"))
    if step.contact_email and not _valid_email(step.contact_email):
        errors.append(FieldError("contact_email", "Enter an email address"))
    if step.contact_phone and not is_full_uk_phone(step.contact_phone):
        errors.append(FieldError("contact_phone", _PHONE_MESSAGE))
    return errors


def _location(step: LocationStep) -> list[FieldError]:
    if not step.fixed_site:
        return []
    errors: list[FieldError] = []
    if normalise_postcode(step.postcode) is None:
        errors.append(FieldError("postcode", "Enter a full postcode"))
    if not step.address.strip():
        errors.append(FieldError("address", "Choose an address"))
    if not step.site_name.strip():
        errors.append(FieldError("site_name", "Enter the site name"))
    if step.site_type not in SITE_TYPES:
        errors.append(FieldError("site_type", "Choose a site type"))
    if not step.open_24h and not _hours_ok(step.opening_days, step.opening_start, step.opening_end):
        errors.append(FieldError("opening", "Enter the opening days and times, or choose 24 hours"))
    return errors


def _service(step: ServiceStep, fixed_site: bool | None) -> list[FieldError]:
    errors: list[FieldError] = []
    if step.category not in _enum_values(ServiceCategory):
        errors.append(FieldError("category", "Choose a category"))
    if not _subset(step.referral_methods, REFERRAL_METHODS):
        errors.append(FieldError("referral_methods", "Choose at least one referral method"))
    if not step.spoa_phone.strip():
        errors.append(FieldError("spoa_phone", "Enter a phone number the SPOA can call"))
    elif not is_full_uk_phone(step.spoa_phone):
        errors.append(FieldError("spoa_phone", _PHONE_MESSAGE))
    if not _hours_ok(step.accepting_days, step.accepting_start, step.accepting_end):
        errors.append(FieldError("accepting", "Enter the accepting days and times"))
    if not _subset(step.needs, _enum_values(NeedCategory)):
        errors.append(FieldError("needs", "Choose at least one accepted need"))
    if type(step.age_min) is not int or step.age_min < 0:
        errors.append(FieldError("age_min", "Enter the youngest age"))
    if step.no_age_limit:
        if step.age_max is not None:
            errors.append(FieldError("age_max", "Choose no limit or enter an age, not both"))
    elif type(step.age_max) is not int or (
        type(step.age_min) is int and step.age_max < step.age_min
    ):
        errors.append(FieldError("age_max", "Enter the oldest age, or choose no limit"))
    if step.no_exclusions:
        if step.excluded_needs:
            errors.append(FieldError("excluded_needs", "Choose excluded needs or no exclusions"))
    elif not _subset(step.excluded_needs, _enum_values(NeedCategory)):
        errors.append(FieldError("excluded_needs", "Choose excluded needs, or no exclusions"))
    if not step.owner_role.strip():
        errors.append(FieldError("owner_role", "Enter who owns the criteria"))
    if not _valid_email(step.owner_email):
        errors.append(FieldError("owner_email", "Enter an email address for the criteria owner"))
    if step.review_by is None:
        errors.append(FieldError("review_by", "Enter a review-by date"))
    districts = _set(step.districts)
    if fixed_site is False and not districts:
        errors.append(FieldError("districts", "Enter at least one postcode district"))
    elif any(normalise_district(d) != d for d in districts):
        errors.append(FieldError("districts", "Enter postcode districts, for example DT4"))
    return errors


def _reporting(step: ReportingStep) -> list[FieldError]:
    errors: list[FieldError] = []
    if step.measure not in _enum_values(Measure):
        errors.append(FieldError("measure", "Choose what you will report"))
    low, high = step.usual_low, step.usual_high
    if type(low) is not int or not 0 <= low <= MAX_USUAL:
        errors.append(FieldError("usual_low", "Enter the lowest usual number"))
    if type(high) is not int or not 0 <= high <= MAX_USUAL:
        errors.append(FieldError("usual_high", "Enter the highest usual number"))
    elif type(low) is int and low > high:
        errors.append(FieldError("usual_high", "The highest usual number is below the lowest"))
    if step.cadence not in _enum_values(Cadence):
        errors.append(FieldError("cadence", "Choose how often you will report"))
    if step.channel not in CHANNELS:
        errors.append(FieldError("channel", "Choose how you will report"))
    if not step.holder_name.strip():
        errors.append(FieldError("holder_name", "Enter who holds the phone"))
    if step.channel in ("text", "push") and not is_full_uk_phone(step.contact_mobile):
        errors.append(FieldError("contact_mobile", _MOBILE_MESSAGE))
    if step.channel == "email" and not _valid_email(step.contact_email):
        errors.append(FieldError("contact_email", "Enter an email address for reports"))
    return errors


def _api(step: ApiStep) -> list[FieldError]:
    if not step.wanted:
        return []
    errors: list[FieldError] = []
    if not step.name.strip():
        errors.append(FieldError("name", "Enter the API name"))
    if not step.address.startswith("https://") or len(step.address) <= len("https://"):
        errors.append(FieldError("address", "Enter an https address"))
    if not step.connection.strip():
        errors.append(FieldError("connection", "Choose a connection type"))
    if not step.data_type.strip():
        errors.append(FieldError("data_type", "Choose a data type"))
    return errors


def validate_step(step: object, *, fixed_site: bool | None = None) -> list[FieldError]:
    """The field errors of one step, in screen order. `fixed_site` is the location's answer: a
    visiting service must name postcode districts. Pure: nothing is stored or read."""
    if isinstance(step, OrganisationStep):
        return _organisation(step)
    if isinstance(step, LocationStep):
        return _location(step)
    if isinstance(step, ServiceStep):
        return _service(step, fixed_site)
    if isinstance(step, ReportingStep):
        return _reporting(step)
    if isinstance(step, ApiStep):
        return _api(step)
    raise ValidationFailed("step", "is not a registration step")


def encode_step(step: object) -> dict[str, Any]:
    """The typed fields of a step for the draft: text, whole numbers and flags, with an unset value
    left out (the store keeps no null, lesson L74). Contact numbers and addresses are left out too:
    they go to the protected contact store (DEC-001, P16)."""
    if not isinstance(step, _STEP_TYPES):
        raise ValidationFailed("step", "is not a registration step")
    skip = _CONTACT_FIELDS.get(type(step), frozenset())
    values: dict[str, Any] = {}
    for item in fields(step):
        if item.name in skip:
            continue
        value = getattr(step, item.name)
        if value is None:
            continue
        values[item.name] = value.isoformat() if isinstance(value, date) else value
    return values


def decode_step(kind: str, values: Mapping[str, Any]) -> Step:
    """The step a stored draft holds. `kind` is the step's class name. A field the step does not
    have, or a value of the wrong type, is refused (fail closed)."""
    cls = _STEP_OF_KIND.get(kind)
    if cls is None:
        raise ValidationFailed("step", "is not a registration step")
    known = {item.name for item in fields(cls)}
    if set(values) - known:
        raise ValidationFailed("draft", "holds a field the step does not have")
    kwargs: dict[str, Any] = {}
    for name, value in values.items():
        if name in _DATE_FIELDS:
            if not isinstance(value, str):
                raise ValidationFailed(name, "must be a calendar date")
            kwargs[name] = date.fromisoformat(value)
        elif isinstance(value, str | int | bool):
            kwargs[name] = value
        else:
            raise ValidationFailed("draft", "a field must be text, a whole number or a flag")
    step: Step = cls(**kwargs)
    return step


def read_draft(registration: Registration) -> RegistrationDraft:
    """The steps a registration's draft holds, decoded. A step that is not there is None."""
    found: dict[str, Any] = {}
    for kind, key in _KEY_OF.items():
        values = registration.draft.get(key)
        if values is not None:
            found[key] = decode_step(kind.__name__, values)
    return RegistrationDraft(
        registration_id=registration.id,
        organisation=found.get("organisation"),
        location=found.get("location"),
        service=found.get("service"),
        reporting=found.get("reporting"),
        api=found.get("api"),
    )


def _command_key(scope: ScopeId | None, key: str) -> str:
    """The replay key with the tenant in it (lesson L160): two tenants that use one key are two
    commands until the replay store is tenant-scoped."""
    return f"registration:{scope}:{key}"


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _Stored:
    """What the idempotency store keeps for a command key: the result and the fingerprint of the
    command that made it (DEC-104)."""

    fingerprint: str
    result: object


def _replay(stored: object, fingerprint: str) -> object | None:
    if stored is None:
        return None
    if not isinstance(stored, _Stored) or stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different registration command")
    return stored.result


@dataclass(frozen=True, slots=True)
class SaveRegistrationStepCommand:
    idempotency_key: str
    actor: Actor
    registration_id: str
    step: OrganisationStep | LocationStep | ServiceStep | ReportingStep | ApiStep


@dataclass(frozen=True, slots=True)
class SaveStepResult:
    errors: tuple[FieldError, ...]
    status: RegistrationStatus
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class SubmitRegistrationCommand:
    idempotency_key: str
    actor: Actor
    registration_id: str


@dataclass(frozen=True, slots=True)
class SubmitResult:
    status: RegistrationStatus
    errors: tuple[FieldError, ...]
    replayed: bool = False


async def _check_applicant(uow: UnitOfWork, actor: Actor, registration: Registration) -> None:
    """The invited applicant is the practitioner who holds the registration's requester role."""
    if actor.practitioner_id is None:
        raise NotAllowed("a named applicant is needed for this registration")
    roles = await uow.people.roles_for_practitioner(actor.practitioner_id)
    if not any(role.id == registration.requester_role_id for role in roles):
        raise NotAllowed("only the invited applicant may complete this registration")


class SaveRegistrationStep:
    """Save one step of the wizard. Saves even when the step has errors, and reports them."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock

    async def execute(self, command: SaveRegistrationStepCommand) -> SaveStepResult:
        kind = type(command.step)
        if kind not in _KEY_OF:
            raise ValidationFailed("step", "is not a registration step")
        fingerprint = _fingerprint(
            "save", command.registration_id, repr(command.step), command.actor.practitioner_id
        )
        now = self._clock.now()
        async with self._uow_factory() as uow:
            key = _command_key(uow.unit_scope, command.idempotency_key)
            stored = _replay(await uow.idempotency.get(key), fingerprint)
            if isinstance(stored, SaveStepResult):
                return replace(stored, replayed=True)
            registration = await uow.registrations.get(command.registration_id)
            if registration is None:
                raise NotFound("no registration with this id")
            await _check_applicant(uow, command.actor, registration)
            if registration.status is RegistrationStatus.INVITED:
                if not invitation_valid(registration.created_at, now):
                    raise NotAllowed("this invitation has expired")
                status = transition_registration(
                    RegistrationStatus.INVITED, RegistrationStatus.DRAFT
                )
            elif registration.status in (
                RegistrationStatus.DRAFT,
                RegistrationStatus.NEEDS_CHANGES,
            ):
                status = registration.status
            else:
                raise InvalidTransition(
                    f"a registration in {registration.status.value} cannot be edited"
                )
            fixed_site: bool | None = None
            if isinstance(command.step, ServiceStep):
                entry = await uow.scope.get_entry(registration.service_id)
                if entry is None:
                    raise NotFound("this service is not on the scope list")
                if command.step.service_name != entry.name:
                    raise ValidationFailed("service_name", "is fixed by the invitation")
                location = read_draft(registration).location
                fixed_site = None if location is None else location.fixed_site
            errors = validate_step(command.step, fixed_site=fixed_site)
            if isinstance(command.step, ReportingStep) and not errors:
                await _store_contacts(uow, registration.requester_role_id, command.step)
            draft = dict(registration.draft)
            draft[_KEY_OF[kind]] = encode_step(command.step)
            updated = replace(registration, status=status, draft=draft, last_modified=now)
            await uow.registrations.save(updated)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case="SaveRegistrationStep",
                    actor=command.actor,
                    entity_ids=(registration.id, registration.service_id),
                    snapshot={"step": _KEY_OF[kind], "errors": len(errors), "status": status.value},
                    at=now,
                )
            )
            result = SaveStepResult(errors=tuple(errors), status=status)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


async def _store_contacts(uow: UnitOfWork, role_id: str | None, step: ReportingStep) -> None:
    if role_id is None:
        raise ValidationFailed("requester_role_id", "the registration has no requester role")
    if step.contact_mobile:
        await uow.contacts.put_phone(role_id, step.contact_mobile)
    if step.contact_email:
        await uow.contacts.put_email(role_id, step.contact_email)


async def _completeness(uow: UnitOfWork, registration: Registration) -> list[FieldError]:
    """Every step complete, as the screens require at submit. The API step is optional: missing
    means not wanted. The reporting contact is read from the protected store, not the draft."""
    draft = read_draft(registration)
    errors: list[FieldError] = []
    steps: tuple[tuple[str, object], ...] = (
        ("organisation", draft.organisation),
        ("location", draft.location),
        ("service", draft.service),
        ("reporting", draft.reporting),
    )
    for key, step in steps:
        if step is None:
            errors.append(FieldError(key, "Complete this step"))
    fixed = None if draft.location is None else draft.location.fixed_site
    if draft.service is not None:
        errors.extend(validate_step(draft.service, fixed_site=fixed))
    for step in (draft.organisation, draft.location, draft.reporting):
        if step is not None:
            errors.extend(validate_step(step))
    if draft.reporting is not None and registration.requester_role_id is not None:
        channel = draft.reporting.channel
        if (
            channel in ("text", "push")
            and await uow.contacts.get_phone(registration.requester_role_id) is None
        ):
            errors.append(FieldError("contact_mobile", _MOBILE_MESSAGE))
        if (
            channel == "email"
            and await uow.contacts.get_email(registration.requester_role_id) is None
        ):
            errors.append(FieldError("contact_email", "Enter an email address for reports"))
    return errors


class SubmitRegistration:
    """Submit a complete registration for approval. Only from draft or needs-changes."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock

    async def execute(self, command: SubmitRegistrationCommand) -> SubmitResult:
        fingerprint = _fingerprint("submit", command.registration_id, command.actor.practitioner_id)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            key = _command_key(uow.unit_scope, command.idempotency_key)
            stored = _replay(await uow.idempotency.get(key), fingerprint)
            if isinstance(stored, SubmitResult):
                return replace(stored, replayed=True)
            registration = await uow.registrations.get(command.registration_id)
            if registration is None:
                raise NotFound("no registration with this id")
            await _check_applicant(uow, command.actor, registration)
            transition_registration(registration.status, RegistrationStatus.SUBMITTED)
            errors = await _completeness(uow, registration)
            if errors:
                result = SubmitResult(status=registration.status, errors=tuple(errors))
                await uow.idempotency.put(key, _Stored(fingerprint, result))
                await uow.commit()
                return result
            submitted = replace(
                registration,
                status=RegistrationStatus.SUBMITTED,
                submitted_at=now,
                last_modified=now,
            )
            await uow.registrations.save(submitted)
            await uow.outbox.add(
                outbox_message_for(
                    RegistrationSubmitted(registration_id=registration.id, at=now),
                    id=self._ids.new_id(),
                    now=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case="SubmitRegistration",
                    actor=command.actor,
                    entity_ids=(registration.id, registration.service_id),
                    snapshot={"status": RegistrationStatus.SUBMITTED.value},
                    at=now,
                )
            )
            result = SubmitResult(status=RegistrationStatus.SUBMITTED, errors=())
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result
