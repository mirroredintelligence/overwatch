"""SetupServiceByLead: a shift lead sets up one service for the pilot (U15).

The lead gives the service, its reporter (a UK mobile for text, a role inbox for email) and a first
criteria version. One unit of work writes the service, the reporter's practitioner (reused when the
phone hash is already held in this tenant), the reporter role, the lead's owner role, the protected
contact, criteria version 1 (current), the first prompt-due job, the ServiceActivated outbox message
and the audit entry. The number goes only to the protected contact store; the graph keeps the phone
hash (DEC-057, P16). Rules: domain-rules 1.1 (service profile), 1.4 (schedule), 4.2 (criteria) and
9 (channels). Assumptions are listed in the U15 evidence fragment.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PhoneHasher, normalise_uk_mobile
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.work import WorkKind
from diucs.domain.codes import (
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    PractitionerRoleCode,
    Role,
    ServiceCategory,
)
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import ServiceActivated
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.people import (
    Practitioner,
    PractitionerRole,
    check_email_domain,
    check_staff_text,
)
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.postcode import normalise_district
from diucs.domain.rules.schedule import next_due

USE_CASE: Final = "SetupServiceByLead"
AUDIT_ACTION: Final = "C"
CRITERIA_VERSION: Final = 1
REPORTER_ROLE_CODE: Final = PractitionerRoleCode.DUTY_MANAGER
"""The post a reporter holds. The lead gives a role name, not a code, so the reporter post is one
code for every pilot service (assumption, U15 fragment)."""
OWNER_ROLE_CODE: Final = PractitionerRoleCode.CRITERIA_OWNER
CAN_EXCEED_ESTABLISHED: Final = False
"""A service set up by a lead reports within its established capacity (assumption, U15 fragment)."""
UK_COUNTRY_CODE: Final = "+44"


@dataclass(frozen=True, slots=True)
class SetupServiceCommand:
    idempotency_key: str
    actor: Actor
    name: str
    category: ServiceCategory
    measure: Measure
    unit_label: str
    established_capacity: int
    usual_range: tuple[int, int]
    cadence: Cadence
    available_times: tuple[AvailableTime, ...]
    channel: Channel
    reporter_role_name: str
    age_min: int
    districts: frozenset[str]
    accepts: frozenset[NeedCategory]
    review_by: date
    owner_role_name: str
    phone: str | None = None
    email: str | None = None
    age_max: int | None = None
    excludes: frozenset[NeedCategory] = frozenset()


@dataclass(frozen=True, slots=True)
class SetupServiceResult:
    service_id: str
    practitioner_id: str
    role_id: str
    criteria_id: str
    first_prompt_at: datetime


@dataclass(frozen=True, slots=True)
class ReporterContact:
    channel: Channel
    phone: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class _StoredSetup:
    """What the idempotency store keeps for a command key: the result and the fingerprint of the
    command that made it (DEC-104)."""

    fingerprint: str
    result: SetupServiceResult


def check_may_set_up(actor: Actor) -> str:
    """Only a shift lead acting as a named practitioner may set up a service. Returns the lead's
    practitioner id, which owns the service's criteria-owner role."""
    if actor.role is not Role.LEAD:
        raise NotAllowed("only a shift lead may set up a service")
    if actor.practitioner_id is None:
        raise NotAllowed("the lead must act as a named practitioner")
    return actor.practitioner_id


def check_role_name(field: str, value: str) -> None:
    """A role name is staff text: not blank, and never a postcode or a long number (DEC-065)."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(field, "must not be blank")
    check_staff_text(field, value)


def _role_inbox(value: object) -> str:
    refused = ValidationFailed("email", "must be a role inbox address")
    if not isinstance(value, str):
        raise refused
    address = value.strip()
    local, separator, domain = address.partition("@")
    if not separator or not local or "@" in domain or any(c.isspace() for c in address):
        raise refused
    domain = domain.lower()
    try:
        check_email_domain(domain)
    except ValidationFailed:
        raise refused from None
    return f"{local}@{domain}"


def reporter_contact(channel: Channel, phone: str | None, email: str | None) -> ReporterContact:
    """The reporter's contact for the service's channel. Text takes a UK mobile (kept as eleven
    digits from 07); email takes a role inbox. Push is outside the MVP, so it is refused."""
    if channel is Channel.TEXT:
        return ReporterContact(channel=channel, phone=normalise_uk_mobile(phone or ""), email=None)
    if channel is Channel.EMAIL:
        return ReporterContact(channel=channel, phone=None, email=_role_inbox(email))
    raise ValidationFailed("channel", "text or email only; other channels are outside the MVP")


def international(national: str) -> str:
    """The stored form of a UK mobile: +44 and the subscriber digits, with no trunk zero."""
    return UK_COUNTRY_CODE + national[1:]


def _check_member(field: str, value: object, enum_cls: type[Enum]) -> None:
    # isinstance on the enum class, never the bare value (lessons L3 and L38).
    if not isinstance(value, enum_cls):
        raise ValidationFailed(field, f"must be a {enum_cls.__name__} code")


def build_profile(command: SetupServiceCommand, service_id: str) -> ServiceProfile:
    """The service's reporting profile. ServiceProfile checks the numbers, the ranges and the
    times; the enum fields are checked here, by class."""
    _check_member("category", command.category, ServiceCategory)
    _check_member("measure", command.measure, Measure)
    _check_member("cadence", command.cadence, Cadence)
    _check_member("channel", command.channel, Channel)
    return ServiceProfile(
        id=service_id,
        name=command.name,
        category=command.category,
        measure=command.measure,
        unit_label=command.unit_label,
        established_capacity=command.established_capacity,
        can_exceed_established=CAN_EXCEED_ESTABLISHED,
        usual_range=command.usual_range,
        cadence=command.cadence,
        available_times=command.available_times,
        channel=command.channel,
    )


def _districts(value: object) -> frozenset[str]:
    if not isinstance(value, set | frozenset) or not value:
        raise ValidationFailed("districts", "at least one district code is required")
    normalised: set[str] = set()
    for item in value:
        district = normalise_district(item) if isinstance(item, str) else None
        if district is None:
            raise ValidationFailed("districts", "must be district codes such as DT4")
        normalised.add(district)
    return frozenset(normalised)


def build_criteria(
    command: SetupServiceCommand, criteria_id: str, service_id: str, owner_role_id: str
) -> ServiceCriteria:
    """Criteria version 1, current. ServiceCriteria checks the ages and the need sets; this adds the
    district rule, the review date rule and the rule that a service accepts at least one need."""
    if not isinstance(command.review_by, date) or isinstance(command.review_by, datetime):
        raise ValidationFailed("review_by", "must be a calendar date")
    if not isinstance(command.accepts, frozenset) or not command.accepts:
        raise ValidationFailed("accepts", "at least one accepted need is required")
    return ServiceCriteria(
        id=criteria_id,
        service_id=service_id,
        version=CRITERIA_VERSION,
        status=CriteriaStatus.CURRENT,
        age_min=command.age_min,
        age_max=command.age_max,
        districts=_districts(command.districts),
        accepts=command.accepts,
        excludes=command.excludes,
        review_by=command.review_by,
        owner_role_id=owner_role_id,
    )


def first_prompt_at(profile: ServiceProfile, now: datetime) -> datetime:
    """The first prompt: the next due instant strictly after now (D04 next_due)."""
    due = next_due(profile, now)
    if due is None:
        raise ValidationFailed("available_times", "no prompt falls in the next eight days")
    return due


def _plain(value: object) -> Any:
    """JSON-ready data in a fixed form, so that two equal commands give one fingerprint."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, AvailableTime):
        return {
            "days": sorted(value.days),
            "all_day": value.all_day,
            "start": _plain(value.start),
            "end": _plain(value.end),
        }
    if isinstance(value, set | frozenset):
        return sorted((_plain(item) for item in value), key=str)
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def command_fingerprint(command: SetupServiceCommand, contact_key: str) -> str:
    """The command body, the actor and the reporter's contact key (the phone hash, or a digest of
    the address), so a replay with another body is refused (DEC-104). No number is in it."""
    body = _plain(
        {
            "use_case": USE_CASE,
            "name": command.name,
            "category": command.category,
            "measure": command.measure,
            "unit_label": command.unit_label,
            "established_capacity": command.established_capacity,
            "usual_range": command.usual_range,
            "cadence": command.cadence,
            "available_times": command.available_times,
            "channel": command.channel,
            "reporter_role_name": command.reporter_role_name,
            "age_min": command.age_min,
            "age_max": command.age_max,
            "districts": command.districts,
            "accepts": command.accepts,
            "excludes": command.excludes,
            "review_by": command.review_by,
            "owner_role_name": command.owner_role_name,
            "contact": contact_key,
            "actor": {
                "role": command.actor.role,
                "practitioner_id": command.actor.practitioner_id,
            },
        }
    )
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def setup_snapshot(
    command: SetupServiceCommand,
    *,
    service_id: str,
    practitioner_id: str,
    role_id: str,
    owner_role_id: str,
    criteria_id: str,
    first_prompt: datetime,
) -> dict[str, Any]:
    """What the audit entry keeps. Never a phone number or an address."""
    return {
        "service_id": service_id,
        "practitioner_id": practitioner_id,
        "role_id": role_id,
        "owner_role_id": owner_role_id,
        "criteria_id": criteria_id,
        "criteria_version": CRITERIA_VERSION,
        "channel": command.channel.value,
        "reporter_role_name": command.reporter_role_name,
        "owner_role_name": command.owner_role_name,
        "first_prompt_at": first_prompt,
    }


def _replay(stored: _StoredSetup, fingerprint: str) -> SetupServiceResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different set-up")
    return stored.result


class SetupServiceByLead:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        phone_hasher: PhoneHasher,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency
        self._phone_hasher = phone_hasher

    def _contact_key(self, contact: ReporterContact) -> str:
        if contact.phone is not None:
            return "phone:" + self._phone_hasher.hash(contact.phone)
        address = contact.email or ""
        return "email:" + hashlib.sha256(address.encode("utf-8")).hexdigest()

    async def execute(self, command: SetupServiceCommand) -> SetupServiceResult:
        lead_id = check_may_set_up(command.actor)
        check_role_name("reporter_role_name", command.reporter_role_name)
        check_role_name("owner_role_name", command.owner_role_name)
        contact = reporter_contact(command.channel, command.phone, command.email)
        fingerprint = command_fingerprint(command, self._contact_key(contact))
        # An early read outside the unit of work. The authoritative replay check is inside it.
        early = await self._idempotency.get(command.idempotency_key)
        if isinstance(early, _StoredSetup):
            return _replay(early, fingerprint)

        now = self._clock.now()
        service_id = self._ids.new_id()
        profile = build_profile(command, service_id)
        first = first_prompt_at(profile, now)
        reporter_role_id = self._ids.new_id()
        owner_role_id = self._ids.new_id()
        criteria_id = self._ids.new_id()
        criteria = build_criteria(command, criteria_id, service_id, owner_role_id)

        async with self._uow_factory() as uow:
            stored = await uow.idempotency.get(command.idempotency_key)
            if isinstance(stored, _StoredSetup):
                return _replay(stored, fingerprint)

            lead = await uow.people.get_practitioner(lead_id)
            if lead is None:
                raise NotFound("the lead is not a practitioner of this organisation")

            practitioner_id = await self._reporter_practitioner(uow, contact, command, now)
            await uow.services.save(profile)
            await uow.people.save_role(
                PractitionerRole(
                    id=reporter_role_id,
                    practitioner_id=practitioner_id,
                    service_id=service_id,
                    code=REPORTER_ROLE_CODE,
                    active=True,
                    channel=command.channel,
                    period_start=now,
                )
            )
            await uow.people.save_role(
                PractitionerRole(
                    id=owner_role_id,
                    practitioner_id=lead_id,
                    service_id=service_id,
                    code=OWNER_ROLE_CODE,
                    active=True,
                    channel=None,
                    period_start=now,
                )
            )
            if contact.phone is not None:
                await uow.contacts.put_phone(reporter_role_id, international(contact.phone))
            elif contact.email is not None:
                await uow.contacts.put_email(reporter_role_id, contact.email)
            await uow.criteria.add(criteria)
            await schedule_work(
                uow,
                self._ids,
                kind=WorkKind.PROMPT_DUE,
                about_id=service_id,
                due_at=first,
                now=now,
            )
            await uow.outbox.add(
                outbox_message_for(
                    ServiceActivated(service_id=service_id, at=now),
                    id=self._ids.new_id(),
                    now=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=command.actor,
                    entity_ids=(
                        service_id,
                        practitioner_id,
                        reporter_role_id,
                        owner_role_id,
                        criteria_id,
                    ),
                    snapshot=setup_snapshot(
                        command,
                        service_id=service_id,
                        practitioner_id=practitioner_id,
                        role_id=reporter_role_id,
                        owner_role_id=owner_role_id,
                        criteria_id=criteria_id,
                        first_prompt=first,
                    ),
                    at=now,
                )
            )
            result = SetupServiceResult(
                service_id=service_id,
                practitioner_id=practitioner_id,
                role_id=reporter_role_id,
                criteria_id=criteria_id,
                first_prompt_at=first,
            )
            await uow.idempotency.put(command.idempotency_key, _StoredSetup(fingerprint, result))
            await uow.commit()
        return result

    async def _reporter_practitioner(
        self,
        uow: UnitOfWork,
        contact: ReporterContact,
        command: SetupServiceCommand,
        now: datetime,
    ) -> str:
        """The practitioner who receives this service's prompts. A phone already held in this
        tenant is reused, and nothing is stored for it; otherwise a new practitioner is stored."""
        if contact.phone is not None:
            phone_hash = self._phone_hasher.hash(contact.phone)
            existing = await uow.people.find_by_phone_hash(phone_hash)
            if existing is not None:
                return existing.id
            practitioner_id = self._ids.new_id()
            await uow.people.save_practitioner(
                Practitioner(
                    id=practitioner_id,
                    active=True,
                    display_name=command.reporter_role_name,
                    phone_hash=phone_hash,
                )
            )
            return practitioner_id
        address = contact.email or ""
        practitioner_id = self._ids.new_id()
        await uow.people.save_practitioner(
            Practitioner(
                id=practitioner_id,
                active=True,
                display_name=command.reporter_role_name,
                phone_hash=None,
                email_domain=address.partition("@")[2],
            )
        )
        return practitioner_id
