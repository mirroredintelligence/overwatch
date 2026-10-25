"""Referrer scores: validated value objects (D18). Scores are recorded as given, never calculated.

Each score is checked once, when it is built. A failure raises ValidationFailed naming the field.
The message never echoes the value: a score is clinical data, and errors can reach logs.
"""

import re
from dataclasses import dataclass
from typing import Final

from diucs.domain.codes import AcuityMethod
from diucs.domain.errors import ValidationFailed

NEWS2_MIN: Final = 0
NEWS2_MAX: Final = 20
CLINICAL_FRAILTY_MIN: Final = 1
CLINICAL_FRAILTY_MAX: Final = 9
AMBULANCE_CATEGORY_MIN: Final = 1
AMBULANCE_CATEGORY_MAX: Final = 4

MANCHESTER_LEVELS: Final[frozenset[str]] = frozenset(
    {"immediate", "very-urgent", "urgent", "standard", "non-urgent"}
)

# [ASSUMED] domain-rules.md section 4: a Pathways Dx code is validated for format only, from a
# list the service provides. Two to ten upper-case letters or digits.
PATHWAYS_DX_PATTERN: Final = re.compile(r"[A-Z0-9]{2,10}")


def _whole_number(field: str, value: object, low: int, high: int) -> None:
    # bool is a subclass of int, so it is refused explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationFailed(field, "must be a whole number")
    if not low <= value <= high:
        raise ValidationFailed(field, f"must be from {low} to {high}")


@dataclass(frozen=True, slots=True)
class News2:
    value: int

    def __post_init__(self) -> None:
        _whole_number("news2", self.value, NEWS2_MIN, NEWS2_MAX)


@dataclass(frozen=True, slots=True)
class ClinicalFrailty:
    value: int

    def __post_init__(self) -> None:
        _whole_number("clinical_frailty", self.value, CLINICAL_FRAILTY_MIN, CLINICAL_FRAILTY_MAX)


@dataclass(frozen=True, slots=True)
class AmbulanceCategory:
    value: int

    def __post_init__(self) -> None:
        _whole_number(
            "ambulance_category", self.value, AMBULANCE_CATEGORY_MIN, AMBULANCE_CATEGORY_MAX
        )


@dataclass(frozen=True, slots=True)
class ManchesterTriage:
    level: str

    def __post_init__(self) -> None:
        if not isinstance(self.level, str) or self.level not in MANCHESTER_LEVELS:
            raise ValidationFailed("manchester_triage", "not a listed Manchester triage level")


@dataclass(frozen=True, slots=True)
class PathwaysDx:
    code: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or PATHWAYS_DX_PATTERN.fullmatch(self.code) is None:
            raise ValidationFailed("pathways_dx", "not a valid Pathways Dx code format")


Score = News2 | ClinicalFrailty | AmbulanceCategory | ManchesterTriage | PathwaysDx


def method_of(score: Score) -> AcuityMethod:
    match score:
        case News2():
            return AcuityMethod.NEWS2
        case ClinicalFrailty():
            return AcuityMethod.CFS
        case AmbulanceCategory():
            return AcuityMethod.AMBULANCE_CATEGORY
        case ManchesterTriage():
            return AcuityMethod.MANCHESTER
        case PathwaysDx():
            return AcuityMethod.PATHWAYS_DX
