"""Local FHIR code systems: one definition of every code, system URL and display word.

Every local code in the product is defined here once. Other modules import the enums; none
keeps its own copy of a code.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from diucs.domain.errors import ValidationFailed

BASE_URL = "https://diucs.example/"
"""Placeholder. Identifiers cannot change once minted, so this stays in this one constant."""


class Status(StrEnum):
    ACCEPTING = "accepting"
    LIMITED = "limited"
    NOT_ACCEPTING = "not-accepting"
    OVER_CAPACITY = "over-capacity"
    NOT_UPDATED = "not-updated"
    OUT_OF_HOURS = "out-of-hours"


class Measure(StrEnum):
    FREE_SLOTS = "free-slots"
    FREE_BEDS = "free-beds"
    REFERRALS_ACCEPTABLE = "referrals-acceptable"
    OCCUPIED_PATIENTS = "occupied-patients"
    PACKAGES_FREE = "packages-free"
    OTHER = "other"
    # A service that counts something none of the others name: read like any other count, with the
    # generic unit "places" (W7B A3).


class ReportSource(StrEnum):
    TEXT = "text"
    LINK = "link"
    APP = "app"
    EMAIL = "email"
    ADVISOR_PHONED = "advisor-phoned"
    FEED = "feed"


class ReportType(StrEnum):
    NUMBER = "number"
    CONFIRMED = "confirmed"


class ServiceCategory(StrEnum):
    URGENT_COMMUNITY_RESPONSE = "urgent-community-response"
    SAME_DAY_EMERGENCY_CARE = "same-day-emergency-care"
    INPATIENT_BEDS = "inpatient-beds"
    HOSPITAL_AT_HOME_OR_VIRTUAL_WARD = "hospital-at-home-or-virtual-ward"
    REABLEMENT = "reablement"
    URGENT_TREATMENT = "urgent-treatment"
    MENTAL_HEALTH_CRISIS = "mental-health-crisis"
    OTHER = "other"


class NeedCategory(StrEnum):
    FALL_NO_INJURY = "fall-no-injury"
    FRAILTY = "frailty"
    WOUND_CARE = "wound-care"
    IV_THERAPY = "iv-therapy"
    PALLIATIVE = "palliative"
    DEMENTIA = "dementia"
    SUSPECTED_FRACTURE = "suspected-fracture"
    HEAD_INJURY_ANTICOAGULANTS = "head-injury-anticoagulants"
    INFECTION_ISOLATION = "infection-isolation"


class Urgency(StrEnum):
    WITHIN_2_HRS = "within-2-hrs"
    TODAY = "today"
    PLANNED = "planned"


class AgeBand(StrEnum):
    A0_15 = "0-15"
    A16_64 = "16-64"
    A65_79 = "65-79"
    A80_PLUS = "80+"


class AcuityMethod(StrEnum):
    PATHWAYS_DX = "pathways-dx"
    AMBULANCE_CATEGORY = "ambulance-category"
    MANCHESTER = "manchester"
    NEWS2 = "news2"
    CFS = "cfs"


class BookingStatus(StrEnum):
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED_BEFORE = "cancelled-before"
    CANCELLED_AFTER = "cancelled-after"
    WITHDRAWN = "withdrawn"
    NOT_REACHED = "not-reached"
    COMPLETED = "completed"


class DeclineReason(StrEnum):
    FULL = "full"
    OUTSIDE_CRITERIA = "outside-criteria"
    STAFFING_OR_TRANSPORT = "staffing-or-transport"
    OTHER = "other"


class WithdrawReason(StrEnum):
    NOW_FULL = "now-full"
    STAFFING = "staffing"
    CANNOT_REACH_PATIENT = "cannot-reach-patient"
    OTHER = "other"


class NotReachedReason(StrEnum):
    NOT_AT_ADDRESS = "not-at-address"
    NO_ANSWER = "no-answer"
    GONE_TO_HOSPITAL = "gone-to-hospital"
    OTHER = "other"


class CancelReason(StrEnum):
    CALLER_DECLINED = "caller-declined"
    NO_LONGER_NEEDED = "no-longer-needed"
    OTHER_ROUTE_FOUND = "other-route-found"
    ENTERED_IN_ERROR = "entered-in-error"


class RegistrationStatus(StrEnum):
    INVITED = "invited"
    DRAFT = "draft"
    SUBMITTED = "submitted"
    IN_REVIEW = "in-review"
    NEEDS_CHANGES = "needs-changes"
    APPROVED = "approved"
    LIVE = "live"
    NOT_APPROVED = "not-approved"
    PAUSED = "paused"
    REVERIFY = "reverify"


class CriteriaStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending-approval"
    CURRENT = "current"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class Channel(StrEnum):
    TEXT = "text"
    EMAIL = "email"
    PUSH = "push"


class AlertKind(StrEnum):
    SERVICE_CLOSED = "service-closed"
    OVER_CAPACITY = "over-capacity"
    NOT_UPDATED = "not-updated"
    SYSTEM_PRESSURE = "system-pressure"


class Cadence(StrEnum):
    EVERY_2_HRS = "every-2-hrs"
    TWICE_A_DAY = "twice-a-day"
    ONCE_A_DAY = "once-a-day"


class Role(StrEnum):
    REPORTER = "reporter"
    ADVISOR = "advisor"
    CLINICAL = "clinical"
    LEAD = "lead"
    OWNER = "owner"
    EXEC = "exec"
    WALL = "wall"
    ANONYMOUS_LINK = "anonymous-link"
    SUPPORT = "support"
    AUDIT = "audit"
    # Administration (DEC-134 item 4). A tenant administrator runs one tenant; a network
    # administrator runs the sharing of one network; the platform operator runs tenant lifecycle
    # only and has no data access.
    TENANT_ADMIN = "tenant-admin"
    NETWORK_ADMIN = "network-admin"
    PLATFORM_OPERATOR = "platform-operator"


class ScopeFlag(StrEnum):
    IN_PILOT = "in-pilot"
    LATER = "later"
    OUT_OF_SCOPE = "out-of-scope"


class ReportFlagReason(StrEnum):
    OUT_OF_RANGE_TWICE = "out-of-range-twice"
    MANY_CHANGES = "many-changes"
    DIFFERS_FROM_PHONED = "differs-from-phoned"


class Outcome(StrEnum):
    ACCEPTED_AND_BOOKED = "accepted-and-booked"
    DECLINED = "declined"
    REDIRECTED = "redirected"
    CALLER_CANCELLED = "caller-cancelled"
    NO_SERVICE_FITS = "no-service-fits"
    OUT_OF_AREA = "out-of-area"


class AdviceChoice(StrEnum):
    """What a clinical advisor advised on a request (U40)."""

    GO_AHEAD = "go-ahead"
    USE_ANOTHER_SERVICE = "use-another-service"
    CLINICAL_CALL_TO_REFERRER = "clinical-call-to-referrer"
    EMERGENCY_ROUTE = "emergency-route"


class BestFitNotUsedReason(StrEnum):
    FULL = "full"
    DECLINED = "declined"
    DATA_TOO_OLD = "data-too-old"
    CALLER_PREFERENCE = "caller-preference"
    CLINICAL_OVERRIDE = "clinical-override"


class ReferrerType(StrEnum):
    AMBULANCE_CREW = "ambulance-crew"
    CARE_HOME = "care-home"
    GP = "gp"
    NHS_111 = "nhs-111"
    OTHER = "other"


class PractitionerRoleCode(StrEnum):
    DUTY_MANAGER = "duty-manager"
    COORDINATOR = "coordinator"
    CRITERIA_OWNER = "criteria-owner"
    CLINICAL_LEAD = "clinical-lead"
    SHIFT_LEAD = "shift-lead"
    REVIEWER = "reviewer"


_NAMES: dict[type[StrEnum], str] = {
    Status: "status",
    Measure: "capacity-measure",
    ReportSource: "report-source",
    ReportType: "report-type",
    ServiceCategory: "service-category",
    NeedCategory: "need-category",
    Urgency: "urgency",
    AgeBand: "age-band",
    AcuityMethod: "acuity-method",
    BookingStatus: "booking-business-status",
    DeclineReason: "decline-reason",
    WithdrawReason: "withdraw-reason",
    NotReachedReason: "not-reached-reason",
    CancelReason: "cancel-reason",
    RegistrationStatus: "registration-status",
    CriteriaStatus: "criteria-status",
    Channel: "channel",
    AlertKind: "alert-kind",
    Cadence: "report-cadence",
    Role: "role",
    ScopeFlag: "scope-flag",
    ReportFlagReason: "report-flag-reason",
    Outcome: "case-outcome",
    BestFitNotUsedReason: "best-fit-not-used",
    ReferrerType: "referrer-type",
    PractitionerRoleCode: "practitioner-role",
}

CODE_SYSTEM_NAMES: Mapping[type[StrEnum], str] = MappingProxyType(_NAMES)
"""The local code system name of each enum. Every local enum appears here exactly once."""

# Display words that sentence case of the code would get wrong. Keyed by (enum class, code)
# rather than by member, because StrEnum members compare equal to their string value across
# enums (ServiceCategory.OTHER == ReferrerType.OTHER).
_EXPLICIT_DISPLAY: Mapping[tuple[type[StrEnum], str], str] = MappingProxyType(
    {
        (NeedCategory, "fall-no-injury"): "Fall, no injury",
        (NeedCategory, "iv-therapy"): "IV therapy",
        (NeedCategory, "head-injury-anticoagulants"): "Head injury on anticoagulants",
        (AgeBand, "0-15"): "0-15",
        (AgeBand, "16-64"): "16-64",
        (AgeBand, "65-79"): "65-79",
        (AgeBand, "80+"): "80+",
        (AcuityMethod, "pathways-dx"): "Pathways Dx",
        (AcuityMethod, "news2"): "NEWS2",
        (AcuityMethod, "cfs"): "Clinical frailty scale",
        (ReferrerType, "gp"): "GP",
        (ReferrerType, "nhs-111"): "NHS 111",
    }
)


def code_system_url(name: str) -> str:
    return f"{BASE_URL}CodeSystem/{name}"


@dataclass(frozen=True, slots=True)
class Coding:
    system: str
    code: str
    display: str


def display(member: StrEnum) -> str:
    """The word shown to people. Explicit where sentence case would be wrong, else sentence case."""
    explicit = _EXPLICIT_DISPLAY.get((type(member), member.value))
    if explicit is not None:
        return explicit
    words = member.value.replace("-", " ")
    return words[:1].upper() + words[1:]


def coding_for(member: StrEnum) -> Coding:
    return Coding(
        system=code_system_url(CODE_SYSTEM_NAMES[type(member)]),
        code=member.value,
        display=display(member),
    )


def parse_code[E: StrEnum](enum_cls: type[E], code: str) -> E:
    """Return the member for a code, or raise ValidationFailed. The input is never echoed."""
    try:
        return enum_cls(code)
    except ValueError:
        name = CODE_SYSTEM_NAMES.get(enum_cls, enum_cls.__name__)
        raise ValidationFailed("code", f"not a known {name} code") from None
