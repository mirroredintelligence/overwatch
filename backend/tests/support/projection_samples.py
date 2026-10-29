"""Sample sources for the projection tests (TEN-052).

Every value is invented: `UCR West`, `DT4 8XX`, `Sampletown`, `tenant-a`. No real organisation,
person or place."""

from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import Any

from diucs.domain.codes import (
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    ReportSource,
    ReportType,
    ServiceCategory,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.network import DirectorySource
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules.projection import (
    CapacityProjection,
    CriteriaProjection,
    LocationInputs,
    ServiceContactInputs,
    ServiceProjection,
    build_capacity_projection,
    build_criteria_projection,
    build_service_projection,
)

REPORTED_AT = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
SERVICE_ID = "svc-1"


def sample_profile(**overrides: Any) -> ServiceProfile:
    fields: dict[str, Any] = {
        "id": SERVICE_ID,
        "name": "UCR West",
        "category": ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        "measure": Measure.REFERRALS_ACCEPTABLE,
        "unit_label": "referrals in the next 2 hrs",
        "established_capacity": 10,
        "can_exceed_established": False,
        "usual_range": (0, 10),
        "cadence": Cadence.EVERY_2_HRS,
        "available_times": (
            AvailableTime.weekdays(time(8, 0), time(18, 0)),
            AvailableTime(days=frozenset({5, 6}), all_day=True, start=None, end=None),
        ),
        "channel": Channel.TEXT,
        "limited_level_percent": 80,
        "active": True,
        "suspended": False,
        "comment": "Both women only",
    }
    fields.update(overrides)
    return ServiceProfile(**fields)


def sample_report(**overrides: Any) -> CapacityReport:
    fields: dict[str, Any] = {
        "id": "rep-1",
        "service_id": SERVICE_ID,
        "value": 4,
        "measure": Measure.REFERRALS_ACCEPTABLE,
        "effective_at": REPORTED_AT,
        "source": ReportSource.TEXT,
        "report_type": ReportType.NUMBER,
        "performer_role_id": "role-1",
    }
    fields.update(overrides)
    return CapacityReport(**fields)


def sample_criteria(**overrides: Any) -> ServiceCriteria:
    fields: dict[str, Any] = {
        "id": "crit-1",
        "service_id": SERVICE_ID,
        "version": 3,
        "status": CriteriaStatus.CURRENT,
        "age_min": 18,
        "age_max": None,
        "districts": frozenset({"DT4", "DT1"}),
        "accepts": frozenset({NeedCategory.FRAILTY, NeedCategory.FALL_NO_INJURY}),
        "excludes": frozenset({NeedCategory.IV_THERAPY}),
        "review_by": date(2027, 4, 29),
        "owner_role_id": "role-2",
        "change_reason": "Added frailty",
        "supersedes_id": "crit-0",
    }
    fields.update(overrides)
    return ServiceCriteria(**fields)


def sample_location() -> LocationInputs:
    return LocationInputs(
        name="UCR West base", postcode="DT4 8XX", city="Sampletown", latitude=52.0, longitude=-1.5
    )


def sample_contact() -> ServiceContactInputs:
    return ServiceContactInputs(label="Duty desk", phone="0300 123 4567")


def sample_policy(**overrides: Any) -> TenantPolicy:
    return replace(DEFAULT_POLICY, **overrides)


def sample_service_projection(**overrides: Any) -> ServiceProjection:
    profile = overrides.pop("profile", None) or sample_profile()
    arguments: dict[str, Any] = {
        "source_version": 2,
        "location": sample_location(),
        "contact": sample_contact(),
    }
    arguments.update(overrides)
    return build_service_projection(profile, **arguments)


def sample_capacity_projection(**overrides: Any) -> CapacityProjection:
    profile = overrides.pop("profile", None) or sample_profile()
    arguments: dict[str, Any] = {
        "latest": sample_report(),
        "confirmed_since": 1,
        "policy": DEFAULT_POLICY,
        "source_version": 1_793_000_000_000,
        "valid_until": datetime(2026, 10, 29, 10, 30, tzinfo=UTC),
    }
    arguments.update(overrides)
    latest = arguments.pop("latest")
    return build_capacity_projection(profile, latest, **arguments)


def sample_criteria_projection(**overrides: Any) -> CriteriaProjection:
    return build_criteria_projection(overrides.pop("criteria", None) or sample_criteria())


def sample_directory_source() -> DirectorySource:
    return DirectorySource.MANUAL
