"""Practitioners and their posts (P03). Red stub: fields only, behaviour not yet written."""

from dataclasses import dataclass
from datetime import datetime

from diucs.domain.codes import Channel, PractitionerRoleCode

REPORTER_ROLE_CODES: frozenset[PractitionerRoleCode] = frozenset(
    {PractitionerRoleCode.DUTY_MANAGER, PractitionerRoleCode.COORDINATOR}
)


@dataclass(frozen=True, slots=True)
class Practitioner:
    id: str
    active: bool
    display_name: str
    phone_hash: str | None
    email_domain: str | None = None


@dataclass(frozen=True, slots=True)
class PractitionerRole:
    id: str
    practitioner_id: str
    service_id: str | None
    code: PractitionerRoleCode
    active: bool
    channel: Channel | None
    period_start: datetime
    period_end: datetime | None = None
    covered_by_practitioner_id: str | None = None
    covered_until: datetime | None = None


def role_holder(role: PractitionerRole, now: datetime) -> str:
    raise NotImplementedError


def is_in_effect(role: PractitionerRole, now: datetime) -> bool:
    raise NotImplementedError
