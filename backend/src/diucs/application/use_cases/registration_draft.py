"""Registration drafting and submission (U26). Stub for the red commit (DEC-010): the step types
exist, every function raises NotImplementedError."""

from dataclasses import dataclass
from datetime import date
from typing import Any


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


@dataclass(frozen=True, slots=True)
class RegistrationDraft:
    registration_id: str
    organisation: OrganisationStep | None = None
    location: LocationStep | None = None
    service: ServiceStep | None = None
    reporting: ReportingStep | None = None
    api: ApiStep | None = None


def validate_step(step: object, *, fixed_site: bool | None = None) -> list[FieldError]:
    raise NotImplementedError


def is_full_uk_phone(text: str) -> bool:
    raise NotImplementedError


def encode_step(step: object) -> dict[str, Any]:
    raise NotImplementedError


def decode_step(key: str, fields: dict[str, Any]) -> object:
    raise NotImplementedError
