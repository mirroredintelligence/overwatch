"""Tests for diucs.domain.codes: local FHIR code systems and the Coding value object.

The expected values below are copied from docs/spec/contracts.md ("diucs/domain/codes.py (F07)")
and must match it exactly.
"""

import dataclasses
from enum import StrEnum

import pytest

from diucs.domain import codes
from diucs.domain.codes import (
    AcuityMethod,
    AgeBand,
    AlertKind,
    BestFitNotUsedReason,
    BookingStatus,
    Cadence,
    CancelReason,
    Channel,
    Coding,
    CriteriaStatus,
    DeclineReason,
    Measure,
    NeedCategory,
    NotReachedReason,
    Outcome,
    PractitionerRoleCode,
    ReferrerType,
    RegistrationStatus,
    ReportFlagReason,
    ReportSource,
    ReportType,
    Role,
    ScopeFlag,
    ServiceCategory,
    Status,
    Urgency,
    WithdrawReason,
    code_system_url,
    coding_for,
    display,
    parse_code,
)
from diucs.domain.errors import DomainError, ValidationFailed

# Enum class -> (code system name, values in contracts.md order)
SPEC: dict[type[StrEnum], tuple[str, tuple[str, ...]]] = {
    Status: (
        "status",
        ("accepting", "limited", "not-accepting", "over-capacity", "not-updated", "out-of-hours"),
    ),
    Measure: (
        "capacity-measure",
        (
            "free-slots",
            "free-beds",
            "referrals-acceptable",
            "occupied-patients",
            "packages-free",
            "other",
        ),
    ),
    ReportSource: (
        "report-source",
        ("text", "link", "app", "email", "advisor-phoned", "feed"),
    ),
    ReportType: ("report-type", ("number", "confirmed")),
    ServiceCategory: (
        "service-category",
        (
            "urgent-community-response",
            "same-day-emergency-care",
            "inpatient-beds",
            "hospital-at-home-or-virtual-ward",
            "reablement",
            "urgent-treatment",
            "mental-health-crisis",
            "other",
        ),
    ),
    NeedCategory: (
        "need-category",
        (
            "fall-no-injury",
            "frailty",
            "wound-care",
            "iv-therapy",
            "palliative",
            "dementia",
            "suspected-fracture",
            "head-injury-anticoagulants",
            "infection-isolation",
        ),
    ),
    Urgency: ("urgency", ("within-2-hrs", "today", "planned")),
    AgeBand: ("age-band", ("0-15", "16-64", "65-79", "80+")),
    AcuityMethod: (
        "acuity-method",
        ("pathways-dx", "ambulance-category", "manchester", "news2", "cfs"),
    ),
    BookingStatus: (
        "booking-business-status",
        (
            "requested",
            "confirmed",
            "declined",
            "expired",
            "cancelled-before",
            "cancelled-after",
            "withdrawn",
            "not-reached",
            "completed",
        ),
    ),
    DeclineReason: (
        "decline-reason",
        ("full", "outside-criteria", "staffing-or-transport", "other"),
    ),
    WithdrawReason: (
        "withdraw-reason",
        ("now-full", "staffing", "cannot-reach-patient", "other"),
    ),
    NotReachedReason: (
        "not-reached-reason",
        ("not-at-address", "no-answer", "gone-to-hospital", "other"),
    ),
    CancelReason: (
        "cancel-reason",
        ("caller-declined", "no-longer-needed", "other-route-found", "entered-in-error"),
    ),
    RegistrationStatus: (
        "registration-status",
        (
            "invited",
            "draft",
            "submitted",
            "in-review",
            "needs-changes",
            "approved",
            "live",
            "not-approved",
            "paused",
            "reverify",
        ),
    ),
    CriteriaStatus: (
        "criteria-status",
        ("draft", "pending-approval", "current", "superseded", "retired"),
    ),
    Channel: ("channel", ("text", "email", "push")),
    AlertKind: (
        "alert-kind",
        ("service-closed", "over-capacity", "not-updated", "system-pressure"),
    ),
    Cadence: ("report-cadence", ("every-2-hrs", "twice-a-day", "once-a-day")),
    Role: (
        "role",
        (
            "reporter",
            "advisor",
            "clinical",
            "lead",
            "owner",
            "exec",
            "wall",
            "anonymous-link",
            "support",
            "audit",
            "tenant-admin",
            "network-admin",
            "platform-operator",
        ),
    ),
    ScopeFlag: ("scope-flag", ("in-pilot", "later", "out-of-scope")),
    ReportFlagReason: (
        "report-flag-reason",
        ("out-of-range-twice", "many-changes", "differs-from-phoned"),
    ),
    Outcome: (
        "case-outcome",
        (
            "accepted-and-booked",
            "declined",
            "redirected",
            "caller-cancelled",
            "no-service-fits",
            "out-of-area",
        ),
    ),
    BestFitNotUsedReason: (
        "best-fit-not-used",
        ("full", "declined", "data-too-old", "caller-preference", "clinical-override"),
    ),
    ReferrerType: (
        "referrer-type",
        ("ambulance-crew", "care-home", "gp", "nhs-111", "other"),
    ),
    PractitionerRoleCode: (
        "practitioner-role",
        (
            "duty-manager",
            "coordinator",
            "criteria-owner",
            "clinical-lead",
            "shift-lead",
            "reviewer",
        ),
    ),
}

ENUM_CLASSES = list(SPEC)
ALL_MEMBERS = [member for cls in ENUM_CLASSES for member in cls]


def test_base_url_is_the_placeholder_constant() -> None:
    assert codes.BASE_URL == "https://diucs.example/"


def test_code_system_url_builds_local_url() -> None:
    assert code_system_url("status") == "https://diucs.example/CodeSystem/status"


def test_coding_for_status_limited() -> None:
    assert coding_for(Status.LIMITED) == Coding(
        "https://diucs.example/CodeSystem/status", "limited", "Limited"
    )


def test_coding_is_frozen() -> None:
    coding = coding_for(Status.LIMITED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        coding.code = "accepting"  # type: ignore[misc]


@pytest.mark.parametrize("enum_cls", ENUM_CLASSES, ids=lambda c: c.__name__)
def test_every_spec_enum_is_in_the_code_system_mapping(enum_cls: type[StrEnum]) -> None:
    assert enum_cls in codes.CODE_SYSTEM_NAMES


@pytest.mark.parametrize("enum_cls", ENUM_CLASSES, ids=lambda c: c.__name__)
def test_code_system_name_matches_spec(enum_cls: type[StrEnum]) -> None:
    assert codes.CODE_SYSTEM_NAMES[enum_cls] == SPEC[enum_cls][0]


def test_mapping_has_no_enum_beyond_the_spec() -> None:
    assert set(codes.CODE_SYSTEM_NAMES) == set(ENUM_CLASSES)


def test_code_system_names_are_unique() -> None:
    names = list(codes.CODE_SYSTEM_NAMES.values())
    assert len(names) == len(set(names))


@pytest.mark.parametrize("enum_cls", ENUM_CLASSES, ids=lambda c: c.__name__)
def test_enum_has_members(enum_cls: type[StrEnum]) -> None:
    assert len(list(enum_cls)) > 0


@pytest.mark.parametrize("member", ALL_MEMBERS, ids=str)
def test_every_member_has_a_non_empty_display(member: StrEnum) -> None:
    assert isinstance(display(member), str)
    assert display(member).strip() != ""


@pytest.mark.parametrize("member", ALL_MEMBERS, ids=str)
def test_coding_for_every_member_uses_its_own_system_and_code(member: StrEnum) -> None:
    coding = coding_for(member)
    assert coding.system == code_system_url(SPEC[type(member)][0])
    assert coding.code == member.value
    assert coding.display == display(member)


@pytest.mark.parametrize("enum_cls", ENUM_CLASSES, ids=lambda c: c.__name__)
def test_values_match_contracts_exactly(enum_cls: type[StrEnum]) -> None:
    assert tuple(member.value for member in enum_cls) == SPEC[enum_cls][1]


def test_status_values_in_contract_order() -> None:
    assert [m.value for m in Status] == [
        "accepting",
        "limited",
        "not-accepting",
        "over-capacity",
        "not-updated",
        "out-of-hours",
    ]


def test_booking_status_values_in_contract_order() -> None:
    assert [m.value for m in BookingStatus] == [
        "requested",
        "confirmed",
        "declined",
        "expired",
        "cancelled-before",
        "cancelled-after",
        "withdrawn",
        "not-reached",
        "completed",
    ]


@pytest.mark.parametrize(
    "member",
    [m for cls in ENUM_CLASSES if cls is not AgeBand for m in cls],
    ids=str,
)
def test_member_names_are_upper_snake_case_of_value(member: StrEnum) -> None:
    assert member.name == member.value.upper().replace("-", "_")


def test_age_band_member_names() -> None:
    assert AgeBand.A0_15.value == "0-15"
    assert AgeBand.A16_64.value == "16-64"
    assert AgeBand.A65_79.value == "65-79"
    assert AgeBand.A80_PLUS.value == "80+"


def test_age_band_lookup_by_value() -> None:
    assert AgeBand("80+") is AgeBand.A80_PLUS


def test_booking_status_lookup_by_value() -> None:
    assert BookingStatus("cancelled-before") is BookingStatus.CANCELLED_BEFORE


def test_display_words_for_need_and_urgency() -> None:
    assert display(NeedCategory.FALL_NO_INJURY) == "Fall, no injury"
    assert display(Urgency.WITHIN_2_HRS) == "Within 2 hrs"


def test_display_words_that_sentence_case_would_get_wrong() -> None:
    assert display(NeedCategory.IV_THERAPY) == "IV therapy"
    assert display(NeedCategory.HEAD_INJURY_ANTICOAGULANTS) == "Head injury on anticoagulants"
    assert display(AgeBand.A0_15) == "0-15"
    assert display(AgeBand.A80_PLUS) == "80+"
    assert display(ReferrerType.GP) == "GP"
    assert display(ReferrerType.NHS_111) == "NHS 111"


def test_display_is_sentence_case_with_hyphens_as_spaces_by_default() -> None:
    assert display(Status.NOT_ACCEPTING) == "Not accepting"
    assert display(Status.OUT_OF_HOURS) == "Out of hours"
    assert display(Cadence.EVERY_2_HRS) == "Every 2 hrs"


def test_same_value_in_two_enums_keeps_its_own_coding() -> None:
    # StrEnum members compare equal to their string value, so ServiceCategory.OTHER and
    # ReferrerType.OTHER are equal. The coding must still come from each member's own class.
    assert ServiceCategory.OTHER == ReferrerType.OTHER
    assert coding_for(ReferrerType.OTHER).system == code_system_url("referrer-type")
    assert coding_for(ServiceCategory.OTHER).system == code_system_url("service-category")
    assert display(ServiceCategory.OTHER) == "Other"


def test_parse_code_returns_member() -> None:
    assert parse_code(Status, "limited") is Status.LIMITED


def test_parse_code_rejects_unknown_code_with_validation_failed() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        parse_code(Status, "closed")
    assert excinfo.value.field == "code"
    assert isinstance(excinfo.value, DomainError)


def test_parse_code_error_does_not_echo_the_input() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        parse_code(Status, "not-a-code-xyz123")
    assert "xyz123" not in excinfo.value.message
    assert "not-a-code-xyz123" not in str(excinfo.value)


def test_explicit_display_is_scoped_to_its_enum_class(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two enums share the code "other". An explicit word registered for ReferrerType must not
    # leak onto ServiceCategory.OTHER, which has the same value.
    table = {(ReferrerType, "other"): "Other referrer"}
    monkeypatch.setattr(codes, "_EXPLICIT_DISPLAY", table)
    assert display(ReferrerType.OTHER) == "Other referrer"
    assert display(ServiceCategory.OTHER) == "Other"
