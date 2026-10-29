"""The projection allowlist, its DTOs and their builders (TEN-052). Stub for the red commit."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import ClassVar, Final

from diucs.domain.codes import Cadence, Measure, NeedCategory, ServiceCategory
from diucs.domain.messages.privacy_guard import find_patient_data  # noqa: F401
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.network import DirectorySource
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import TenantPolicy

PROJECTION_ALLOWLIST_VERSION: Final = 0


@dataclass(frozen=True, slots=True)
class FieldSpec:
    dto_field: str
    prop: str
    source: str


ALLOWLIST: Final[Mapping[str, tuple[FieldSpec, ...]]] = {}
SYSTEM_PROPERTIES: Final[Mapping[str, frozenset[str]]] = {}
NETWORK_RELATIONSHIPS: Final[frozenset[str]] = frozenset()
NEVER_SHARED: Final[tuple[str, ...]] = ()


def allowlist_digest() -> str:
    raise NotImplementedError


def supersedes(stored: int | None, incoming: int) -> bool:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class LocationInputs:
    name: str
    postcode: str | None
    city: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True, slots=True)
class ServiceContactInputs:
    label: str | None
    phone: str | None


@dataclass(frozen=True, slots=True)
class LocationProjection:
    label: ClassVar[str] = "ProjectedLocation"
    location_name: str
    postal_district: str | None
    city: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True, slots=True)
class OpeningHourProjection:
    label: ClassVar[str] = "ProjectedOpeningHour"
    position: int
    days: tuple[int, ...]
    all_day: bool
    start: time | None
    end: time | None


@dataclass(frozen=True, slots=True)
class ServiceProjection:
    label: ClassVar[str] = "ProjectedService"
    source_service_id: str
    source_version: int
    service_name: str
    category: ServiceCategory
    active: bool
    source: DirectorySource
    contact_label: str | None
    contact_phone: str | None
    location: LocationProjection | None
    opening_hours: tuple[OpeningHourProjection, ...]


@dataclass(frozen=True, slots=True)
class CapacityProjection:
    label: ClassVar[str] = "ProjectedCapacity"
    source_service_id: str
    source_version: int
    measure: Measure
    unit_label: str
    established_capacity: int
    can_exceed_established: bool
    limited_level_percent: int
    cadence: Cadence
    suspended: bool
    report_id: str | None
    reported_at: datetime | None
    value: int | None
    confirmed_since: int
    reply_window_minutes: int
    stale_warning_hours: int
    valid_until: datetime | None


@dataclass(frozen=True, slots=True)
class CriteriaProjection:
    label: ClassVar[str] = "ProjectedCriteria"
    source_criteria_id: str
    source_service_id: str
    version: int
    age_min: int
    age_max: int | None
    districts: tuple[str, ...]
    accepts: tuple[NeedCategory, ...]
    excludes: tuple[NeedCategory, ...]
    review_by: date


def build_service_projection(
    profile: ServiceProfile,
    *,
    source_version: int,
    location: LocationInputs | None,
    contact: ServiceContactInputs | None,
    source: DirectorySource = DirectorySource.MANUAL,
) -> ServiceProjection:
    raise NotImplementedError


def build_capacity_projection(
    profile: ServiceProfile,
    latest: CapacityReport | None,
    *,
    confirmed_since: int,
    policy: TenantPolicy,
    source_version: int,
    valid_until: datetime | None,
) -> CapacityProjection:
    raise NotImplementedError


def build_criteria_projection(criteria: ServiceCriteria) -> CriteriaProjection:
    raise NotImplementedError
