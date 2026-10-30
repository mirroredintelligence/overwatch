"""The projection allowlist, its DTOs and their builders (TEN-052, reworks D17).

This module is the only definition of what may leave a tenant for the network (DEC-132 items 4 and
7): capacity status inputs and figures with the as-of time, the service name, category, location,
district coverage, opening hours and service-level contact, and the current criteria version. A
projection never carries a reporter's name, phone, device, PIN or link token, a communication, a
booking, a case, an audit entry or any free text about a service or a person. The allowlist is
enforced in three places: here (a DTO that holds nothing else and checks every field), in
`application/projection.py` (the row and body forms, and a check of the statements that write the
network scope), and in the privacy guard (`domain/messages/privacy_guard.py`, D17).

The projection stores the inputs of a status and never the status itself (DEC-134 item 6): the
network read recomputes it at read time with the same `compute_status`, so a service that stops
reporting reads "Not updated" with no new event (hazard H-N07).

Pure: no I/O and no clock. Fail closed: a DTO that fails a check is never built, an enum is
checked by exact type (lesson L3), and no refusal repeats a value.

Changing the allowlist (a field added, renamed or retyped) needs a new
`PROJECTION_ALLOWLIST_VERSION`, a new digest in
`tests/unit/application/test_projection_allowlist.py`, a decision and, for a widening, a new
agreement version for the grants. Status: prepared, not externally certified.
"""

import hashlib
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from diucs.domain.codes import (
    Cadence,
    CriteriaStatus,
    Measure,
    NeedCategory,
    ServiceCategory,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.network import DirectorySource
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import (
    REPLY_WINDOW_MAX,
    REPLY_WINDOW_MIN,
    STALE_WARNING_MAX,
    STALE_WARNING_MIN,
    TenantPolicy,
    require_policy,
)
from diucs.domain.rules.postcode import normalise_district, normalise_postcode, postcode_district

PROJECTION_ALLOWLIST_VERSION: Final = 1

# ---------------------------------------------------------------- the allowlist


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One allowed field: the DTO field, the property stored in the network scope, and the
    property or attribute it comes from in the member's scope today."""

    dto_field: str
    prop: str
    source: str


def _specs(*rows: tuple[str, str, str]) -> tuple[FieldSpec, ...]:
    return tuple(FieldSpec(*row) for row in rows)


# Keyed by network label. The order of each tuple is the order of the keys in a row and of the
# fields in the DTO; the digest below covers every name and every source.
ALLOWLIST: Final[Mapping[str, tuple[FieldSpec, ...]]] = MappingProxyType(
    {
        "ProjectedService": _specs(
            ("source_service_id", "sourceServiceId", "HealthcareService.id (ServiceProfile.id)"),
            ("source_version", "sourceVersion", "HealthcareService versionId"),
            ("service_name", "serviceName", "HealthcareService.name (ServiceProfile.name)"),
            ("category", "categoryCode", "CATEGORY Concept code (ServiceProfile.category)"),
            ("active", "active", "HealthcareService.active"),
            ("source", "source", "constant manual today (ServiceDirectoryChanged.source)"),
            (
                "contact_label",
                "serviceContactLabel",
                "the service's own ContactPoint (HAS_TELECOM), never ProtectedContact",
            ),
            ("contact_phone", "serviceContactPhone", "the same ContactPoint value"),
        ),
        "ProjectedLocation": _specs(
            ("location_name", "locationName", "Location.name"),
            (
                "postal_district",
                "postalDistrict",
                "the Address postcode reduced to its district; no street, no full postcode",
            ),
            ("city", "city", "the Address child city"),
            ("latitude", "latitude", "Location.positionLatitude"),
            ("longitude", "longitude", "Location.positionLongitude"),
        ),
        "ProjectedOpeningHour": _specs(
            ("position", "position", "index in ServiceProfile.available_times"),
            ("days", "days", "HealthcareService_AvailableTime day codes"),
            ("all_day", "allDay", "HealthcareService_AvailableTime allDay"),
            ("start", "start", "availableStartTime (London local)"),
            ("end", "end", "availableEndTime (London local)"),
        ),
        "ProjectedCapacity": _specs(
            ("source_service_id", "sourceServiceId", "the FOCUS target HealthcareService.id"),
            (
                "source_version",
                "sourceVersion",
                "milliseconds since 1970 UTC at which the producer read the source",
            ),
            ("measure", "measureCode", "Observation.measureCode (ServiceProfile.measure)"),
            ("unit_label", "unitLabel", "HealthcareService.ext_unitLabel"),
            ("established_capacity", "establishedCapacity", "ext_establishedCapacity"),
            ("can_exceed_established", "canExceedEstablished", "ext_canExceedEstablished"),
            ("limited_level_percent", "limitedLevelPercent", "ext_limitedLevelPercent"),
            ("cadence", "cadenceCode", "ext_reportCadence"),
            ("suspended", "suspended", "the active suspended flag (flag only, never its reason)"),
            ("report_id", "sourceReportId", "Observation.id"),
            ("reported_at", "effectiveDateTime", "Observation.effectiveDateTime (the as-of time)"),
            ("value", "value", "Observation.valueQuantity_value"),
            (
                "confirmed_since",
                "confirmedSince",
                "BookingRepository.confirmed_since (a count only)",
            ),
            ("reply_window_minutes", "replyWindowMinutes", "TenantPolicy.reply_window in minutes"),
            (
                "stale_warning_hours",
                "staleWarningHours",
                "TenantPolicy.stale_warning_after in hours",
            ),
            ("valid_until", "validUntil", "supplied by the producer (TEN-056)"),
        ),
        "ProjectedCriteria": _specs(
            ("source_criteria_id", "sourceCriteriaId", "Basic.id"),
            ("source_service_id", "sourceServiceId", "the SUBJECT target id"),
            ("version", "version", "Basic.version (the ordering value)"),
            ("age_min", "ageMin", "Basic.ageMin"),
            ("age_max", "ageMax", "Basic.ageMax"),
            ("districts", "postcodeDistricts", "Basic.postcodeDistricts"),
            ("accepts", "acceptsNeedCodes", "ACCEPTS_NEED Concept codes, copied as text"),
            ("excludes", "excludesNeedCodes", "EXCLUDES_NEED Concept codes, copied as text"),
            ("review_by", "reviewBy", "Basic.reviewBy"),
        ),
    }
)

_STAMPED: Final = frozenset(
    {"tenantId", "sourceTenantId", "projectedAt", "grantId", "grantVersion", "endedAt", "endReason"}
)

# Properties the repository statements stamp that are not DTO fields (TEN-053 may extend this
# table, with a test; it may not touch ALLOWLIST).
SYSTEM_PROPERTIES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        **dict.fromkeys(ALLOWLIST, _STAMPED),
        # A location and an opening window are keyed by their service (TEN-053): the service id is
        # a key the statement stamps, not a field of the child's DTO. It is the id the service
        # row already carries, so nothing new crosses.
        "ProjectedLocation": _STAMPED | {"sourceServiceId"},
        "ProjectedOpeningHour": _STAMPED | {"sourceServiceId"},
        "ProjectionSource": frozenset(
            {"tenantId", "sourceTenantId", "kind", "status", "endedAt", "endReason", "grantId"}
        ),
        "ProjectionCursor": frozenset({"tenantId", "sourceTenantId", "kind", "watermark"}),
    }
)

# Relationship types a network write may create: a service to its location and to each of its
# opening windows (TEN-053), each with a test. A relationship carries no property.
NETWORK_RELATIONSHIPS: Final[frozenset[str]] = frozenset({"HAS_LOCATION", "HAS_OPENING_HOUR"})

# What is never copied. The sentinel test and TEN-062's scan of the network scope iterate this
# list: a name added here adds a check everywhere.
NEVER_SHARED: Final[tuple[str, ...]] = (
    "reporter-name",
    "reporter-phone",
    "device",
    "pin",
    "token",
    "communication",
    "booking",
    "case",
    "audit-entry",
    "service-comment",
    "flag-reason",
    "criteria-change-reason",
    "role-reference",
    "role-contact",
    "report-channel",
    "report-range",
    "next-due",
    "pending-bookings",
)


def allowlist_digest() -> str:
    """A SHA-256 over the version and every label, DTO field, property and source, in order. It
    does not cover `SYSTEM_PROPERTIES`: those are stamped by statements, not copied from a DTO."""
    lines = [f"version={PROJECTION_ALLOWLIST_VERSION}"]
    for label in sorted(ALLOWLIST):
        lines.extend(
            f"{label}|{spec.dto_field}|{spec.prop}|{spec.source}" for spec in ALLOWLIST[label]
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def supersedes(stored: int | None, incoming: int) -> bool:
    """True when a write with source version `incoming` may replace one with `stored`: always for
    the first write, and for an equal version, so a replay is idempotent. An older version never
    replaces a newer one (hazard H-N06)."""
    if stored is not None:
        _count("stored", stored, 1)
    _count("incoming", incoming, 1)
    return stored is None or incoming >= stored


# ---------------------------------------------------------------- field checks

TEXT_MESSAGE: Final = "must be plain text of the right length"
ID_MESSAGE: Final = "is not a valid id"
TYPE_MESSAGE: Final = "has the wrong type"
RANGE_MESSAGE: Final = "is outside the allowed range"
AWARE_MESSAGE: Final = "must be a timezone-aware datetime"
TOGETHER_MESSAGE: Final = "must be all present or all absent"

# The characters a projected text may hold: letters, digits, space and the plain punctuation of a
# name. No control character, no `<`, `>` or `@`, so no markup, no placeholder and no e-mail.
_TEXT: Final = re.compile(r"[\w &'()./,:+·-]+")
_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
_PHONE: Final = re.compile(r"\+?[0-9][0-9 ]{6,15}[0-9]")

NAME_MAX: Final = 120
CITY_MAX: Final = 60
CONTACT_LABEL_MAX: Final = 60
UNIT_LABEL_MAX: Final = 40
LATITUDE_LIMIT: Final = 90.0
LONGITUDE_LIMIT: Final = 180.0
MAX_PERCENT: Final = 100
DAYS_IN_WEEK: Final = 7


def check_projection_text(field: str, value: object, maximum: int = NAME_MAX) -> str:
    """The value, when it is exactly a `str` of 1 to `maximum` characters from the projection's
    character list that has no patient-data shape (D17). The refusal names the field only."""
    if (
        type(value) is not str
        or not 1 <= len(value) <= maximum
        or _TEXT.fullmatch(value) is None
        or find_patient_data(value)
    ):
        raise ValidationFailed(field, TEXT_MESSAGE)
    return value


def _optional_text(field: str, value: object, maximum: int) -> None:
    if value is not None:
        check_projection_text(field, value, maximum)


def check_projection_id(field: str, value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None or find_patient_data(value):
        raise ValidationFailed(field, ID_MESSAGE)
    return value


def _optional_id(field: str, value: object) -> None:
    if value is not None:
        check_projection_id(field, value)


def _count(field: str, value: object, minimum: int, maximum: int | None = None) -> int:
    if type(value) is not int:
        raise ValidationFailed(field, TYPE_MESSAGE)
    if value < minimum or (maximum is not None and value > maximum):
        raise ValidationFailed(field, RANGE_MESSAGE)
    return value


def _flag(field: str, value: object) -> None:
    if type(value) is not bool:
        raise ValidationFailed(field, TYPE_MESSAGE)


def _enum(field: str, value: object, enum_type: type[StrEnum]) -> None:
    if type(value) is not enum_type:
        raise ValidationFailed(field, TYPE_MESSAGE)


def _coordinate(field: str, value: object, limit: float) -> None:
    if type(value) is not float or not math.isfinite(value):
        raise ValidationFailed(field, TYPE_MESSAGE)
    if not -limit <= value <= limit:
        raise ValidationFailed(field, RANGE_MESSAGE)


def _utc(value: object, field: str) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise ValidationFailed(field, AWARE_MESSAGE)
    return value.astimezone(UTC)


def _set_utc(holder: object, field: str, value: object) -> None:
    if value is not None:
        object.__setattr__(holder, field, _utc(value, field))


def _local_time(field: str, value: object) -> None:
    if type(value) is not time or value.tzinfo is not None:
        raise ValidationFailed(field, "must be a local time of day without a timezone")


def _sequence(field: str, value: object) -> list[object]:
    """The items of a list, tuple or set. A string is iterable and must not pass as a list of
    codes (lesson L51), and a mapping is not a sequence."""
    if not isinstance(value, list | tuple | set | frozenset):
        raise ValidationFailed(field, TYPE_MESSAGE)
    return list(value)


def _sorted_tuple(
    field: str, value: object, check: Callable[[object], None], key: Callable[[Any], Any]
) -> tuple[Any, ...]:
    """The distinct items of a sequence, each checked, as a sorted tuple (a list is copied, so
    no DTO holds a mutable value)."""
    items = _sequence(field, value)
    for item in items:
        check(item)
    unique: list[object] = []
    for item in items:
        if item not in unique:
            unique.append(item)
    return tuple(sorted(unique, key=key))


def _check_district(field: str) -> Callable[[object], None]:
    def check(item: object) -> None:
        if type(item) is not str or normalise_district(item) != item:
            raise ValidationFailed(field, "must be upper-case district codes")

    return check


def _check_need(field: str) -> Callable[[object], None]:
    def check(item: object) -> None:
        if type(item) is not NeedCategory:
            raise ValidationFailed(field, "must be need categories")

    return check


def _check_day(item: object) -> None:
    if type(item) is not int or not 0 <= item < DAYS_IN_WEEK:
        raise ValidationFailed("days", "day numbers run from 0 (Monday) to 6 (Sunday)")


# ---------------------------------------------------------------- inputs the builders accept


@dataclass(frozen=True, slots=True)
class LocationInputs:
    """The place of a service as the member's scope holds it. The street lines are not an input:
    the street address is not shared (the postcode is reduced to its district by the builder)."""

    name: str
    postcode: str | None
    city: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True, slots=True)
class ServiceContactInputs:
    """The service's own contact point: a switchboard or role number, never a person. That it is a
    role number and not a person's cannot be enforced by shape: it is a point for the person who
    registers the service, recorded in the decision of TEN-052."""

    label: str | None
    phone: str | None


# ---------------------------------------------------------------- the DTOs


@dataclass(frozen=True, slots=True)
class LocationProjection:
    label: ClassVar[str] = "ProjectedLocation"

    location_name: str
    postal_district: str | None
    city: str | None
    latitude: float | None
    longitude: float | None

    def __post_init__(self) -> None:
        check_projection_text("location_name", self.location_name, NAME_MAX)
        if self.postal_district is not None and (
            type(self.postal_district) is not str
            or normalise_district(self.postal_district) != self.postal_district
        ):
            raise ValidationFailed("postal_district", "must be an upper-case district code")
        _optional_text("city", self.city, CITY_MAX)
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationFailed("latitude", TOGETHER_MESSAGE)
        if self.latitude is not None:
            _coordinate("latitude", self.latitude, LATITUDE_LIMIT)
            _coordinate("longitude", self.longitude, LONGITUDE_LIMIT)


@dataclass(frozen=True, slots=True)
class OpeningHourProjection:
    label: ClassVar[str] = "ProjectedOpeningHour"

    position: int
    days: tuple[int, ...]
    all_day: bool
    start: time | None
    end: time | None

    def __post_init__(self) -> None:
        _count("position", self.position, 0)
        days = _sorted_tuple("days", self.days, _check_day, key=int)
        if not days:
            raise ValidationFailed("days", "at least one day is required")
        object.__setattr__(self, "days", days)
        _flag("all_day", self.all_day)
        if self.all_day:
            if self.start is not None or self.end is not None:
                raise ValidationFailed("start", "an all-day window has no start or end time")
            return
        _local_time("start", self.start)
        _local_time("end", self.end)
        if self.start == self.end:
            raise ValidationFailed("end", "the end must differ from the start")


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

    def __post_init__(self) -> None:
        check_projection_id("source_service_id", self.source_service_id)
        _count("source_version", self.source_version, 1)
        check_projection_text("service_name", self.service_name, NAME_MAX)
        _enum("category", self.category, ServiceCategory)
        _flag("active", self.active)
        _enum("source", self.source, DirectorySource)
        _optional_text("contact_label", self.contact_label, CONTACT_LABEL_MAX)
        if self.contact_phone is not None and (
            type(self.contact_phone) is not str
            or _PHONE.fullmatch(self.contact_phone) is None
            or find_patient_data(self.contact_phone)
        ):
            raise ValidationFailed("contact_phone", "is not a telephone number")
        if self.location is not None and type(self.location) is not LocationProjection:
            raise ValidationFailed("location", TYPE_MESSAGE)
        hours = tuple(_sequence("opening_hours", self.opening_hours))
        if not hours or any(type(hour) is not OpeningHourProjection for hour in hours):
            raise ValidationFailed("opening_hours", "at least one opening hour is required")
        if [hour.position for hour in hours] != list(range(len(hours))):  # type: ignore[attr-defined]
            raise ValidationFailed("opening_hours", "the positions must run from 0 in order")
        object.__setattr__(self, "opening_hours", hours)


@dataclass(frozen=True, slots=True)
class CapacityProjection:
    """The inputs of a status, not the status (DEC-134 item 6)."""

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

    def __post_init__(self) -> None:
        check_projection_id("source_service_id", self.source_service_id)
        _count("source_version", self.source_version, 1)
        _enum("measure", self.measure, Measure)
        check_projection_text("unit_label", self.unit_label, UNIT_LABEL_MAX)
        _count("established_capacity", self.established_capacity, 1)
        _flag("can_exceed_established", self.can_exceed_established)
        _count("limited_level_percent", self.limited_level_percent, 1, MAX_PERCENT)
        _enum("cadence", self.cadence, Cadence)
        _flag("suspended", self.suspended)
        _optional_id("report_id", self.report_id)
        _set_utc(self, "reported_at", self.reported_at)
        if self.value is not None:
            _count("value", self.value, 0)
        present = [self.report_id, self.reported_at, self.value]
        if any(item is None for item in present) and any(item is not None for item in present):
            raise ValidationFailed("report_id", TOGETHER_MESSAGE)
        _count("confirmed_since", self.confirmed_since, 0)
        _count(
            "reply_window_minutes",
            self.reply_window_minutes,
            REPLY_WINDOW_MIN // timedelta(minutes=1),
            REPLY_WINDOW_MAX // timedelta(minutes=1),
        )
        _count(
            "stale_warning_hours",
            self.stale_warning_hours,
            STALE_WARNING_MIN // timedelta(hours=1),
            STALE_WARNING_MAX // timedelta(hours=1),
        )
        _set_utc(self, "valid_until", self.valid_until)


@dataclass(frozen=True, slots=True)
class CriteriaProjection:
    """Only a current version: its structured needs, districts and ages, never the workflow."""

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

    def __post_init__(self) -> None:
        check_projection_id("source_criteria_id", self.source_criteria_id)
        check_projection_id("source_service_id", self.source_service_id)
        _count("version", self.version, 1)
        _count("age_min", self.age_min, 0)
        if self.age_max is not None:
            _count("age_max", self.age_max, self.age_min)
        object.__setattr__(
            self,
            "districts",
            _sorted_tuple("districts", self.districts, _check_district("districts"), key=str),
        )
        accepts = _sorted_tuple(
            "accepts", self.accepts, _check_need("accepts"), key=lambda need: need.value
        )
        excludes = _sorted_tuple(
            "excludes", self.excludes, _check_need("excludes"), key=lambda need: need.value
        )
        if set(accepts) & set(excludes):
            raise ValidationFailed("excludes", "a need cannot be both accepted and excluded")
        object.__setattr__(self, "accepts", accepts)
        object.__setattr__(self, "excludes", excludes)
        if type(self.review_by) is not date:
            raise ValidationFailed("review_by", "must be a date")


# ---------------------------------------------------------------- builders


def _district_of(postcode: object) -> str | None:
    """The district of a full postcode or of a bare district. Anything else gives None, and the
    raw text is never copied."""
    if postcode is None:
        return None
    if type(postcode) is not str:
        raise ValidationFailed("postcode", TYPE_MESSAGE)
    full = normalise_postcode(postcode)
    if full is not None:
        return postcode_district(full)
    return normalise_district(postcode)


def _location(location: LocationInputs | None) -> LocationProjection | None:
    if location is None:
        return None
    if type(location) is not LocationInputs:
        raise ValidationFailed("location", TYPE_MESSAGE)
    return LocationProjection(
        location_name=location.name,
        postal_district=_district_of(location.postcode),
        city=location.city,
        latitude=location.latitude,
        longitude=location.longitude,
    )


def build_service_projection(
    profile: ServiceProfile,
    *,
    source_version: int,
    location: LocationInputs | None,
    contact: ServiceContactInputs | None,
    source: DirectorySource = DirectorySource.MANUAL,
) -> ServiceProjection:
    """The directory projection of a service. The comment, the channel and the usual range of the
    profile are not read. The street address is not an input and the postcode becomes a district."""
    if type(profile) is not ServiceProfile:
        raise ValidationFailed("profile", TYPE_MESSAGE)
    if contact is not None and type(contact) is not ServiceContactInputs:
        raise ValidationFailed("contact", TYPE_MESSAGE)
    hours = tuple(
        OpeningHourProjection(
            position=position,
            days=tuple(sorted(window.days)),
            all_day=window.all_day,
            start=window.start,
            end=window.end,
        )
        for position, window in enumerate(profile.available_times)
    )
    return ServiceProjection(
        source_service_id=profile.id,
        source_version=source_version,
        service_name=profile.name,
        category=profile.category,
        active=profile.active,
        source=source,
        contact_label=None if contact is None else contact.label,
        contact_phone=None if contact is None else contact.phone,
        location=_location(location),
        opening_hours=hours,
    )


def _whole(delta: timedelta, unit: timedelta, field: str) -> int:
    if type(delta) is not timedelta or delta % unit != timedelta(0):
        raise ValidationFailed(field, "must be a whole number of its unit")
    return delta // unit


def build_capacity_projection(
    profile: ServiceProfile,
    latest: CapacityReport | None,
    *,
    confirmed_since: int,
    policy: TenantPolicy,
    source_version: int,
    valid_until: datetime | None,
) -> CapacityProjection:
    """The status inputs of a service: the profile subset, the latest report, how many bookings
    were confirmed since it (a count and nothing else) and the tenant's reply window and stale
    limit. The report of another service or measure is refused, as `compute_status` refuses it."""
    if type(profile) is not ServiceProfile:
        raise ValidationFailed("profile", TYPE_MESSAGE)
    try:
        policy = require_policy(policy)
    except TypeError:
        raise ValidationFailed("policy", "a tenant policy is required") from None
    if latest is not None:
        if type(latest) is not CapacityReport:
            raise ValidationFailed("latest", TYPE_MESSAGE)
        if latest.service_id != profile.id or latest.measure is not profile.measure:
            raise ValidationFailed("latest", "the report does not belong to this service")
    return CapacityProjection(
        source_service_id=profile.id,
        source_version=source_version,
        measure=profile.measure,
        unit_label=profile.unit_label,
        established_capacity=profile.established_capacity,
        can_exceed_established=profile.can_exceed_established,
        limited_level_percent=profile.limited_level_percent,
        cadence=profile.cadence,
        suspended=profile.suspended,
        report_id=None if latest is None else latest.id,
        reported_at=None if latest is None else latest.effective_at,
        value=None if latest is None else latest.value,
        confirmed_since=confirmed_since,
        reply_window_minutes=_whole(policy.reply_window, timedelta(minutes=1), "reply_window"),
        stale_warning_hours=_whole(
            policy.stale_warning_after, timedelta(hours=1), "stale_warning_after"
        ),
        valid_until=valid_until,
    )


def build_criteria_projection(criteria: ServiceCriteria) -> CriteriaProjection:
    """The projection of a current criteria version. A version in any other status is refused
    (identity check, lesson L38), and the reason, the owner and the history are not read."""
    if type(criteria) is not ServiceCriteria:
        raise ValidationFailed("criteria", TYPE_MESSAGE)
    if criteria.status is not CriteriaStatus.CURRENT:
        raise ValidationFailed("status", "only a current version is projected")
    return CriteriaProjection(
        source_criteria_id=criteria.id,
        source_service_id=criteria.service_id,
        version=criteria.version,
        age_min=criteria.age_min,
        age_max=criteria.age_max,
        districts=tuple(criteria.districts),
        accepts=tuple(criteria.accepts),
        excludes=tuple(criteria.excludes),
        review_by=criteria.review_by,
    )
