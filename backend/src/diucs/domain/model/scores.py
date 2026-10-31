"""Referrer scores: validated value objects (D18). Scores are recorded as given, never calculated.

Each score is checked once, when it is built. A failure raises ValidationFailed naming the field.
The message never echoes the value: a score is clinical data, and errors can reach logs.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

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

# [ASSUMED] The shape of a Pathways Dx code (DEC-1170, KI-816): two to twelve letters of either case
# and digits. The codes of the list begin "Dx" (the pilot's own sample is "DxSAMPLE01"), so the
# upper-case-only shape of domain-rules.md section 4 refused every one of them. The shape only keeps
# stray text out; what makes a code acceptable is that it is on the list (the Terminology port,
# H-85), and the list file is refused at load when it holds a code of another shape.
PATHWAYS_DX_PATTERN: Final = re.compile(r"[A-Za-z0-9]{2,12}")


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


class ScoreCorrectionReason(StrEnum):
    """Why a recorded score was changed (Q7, DEC-1100, DEC-1171). A closed set of codes, never free
    text: a reason can reach the audit trail, which must not hold anything a person typed."""

    TYPING_ERROR = "typing-error"
    REFERRER_CORRECTED = "referrer-corrected"
    RESCORED = "rescored"


@dataclass(frozen=True, slots=True)
class ScoreMerge:
    """The recorded scores after a write, in order: the recorded methods (with a corrected value
    where one was given), then the methods added. `corrected` holds (was, now) per method
    changed."""

    scores: tuple[Score, ...]
    corrected: tuple[tuple[Score, Score], ...]
    added: tuple[Score, ...]


def merge_scores(recorded: tuple[Score, ...], given: tuple[Score, ...]) -> ScoreMerge:
    """Merge the scores of a write into the recorded ones, by method (DEC-1171). A method not yet
    recorded is added; a method recorded with another value is a correction; a recorded method not
    mentioned stays as it is. Nothing is calculated or judged."""
    given_by_method: dict[AcuityMethod, Score] = {}
    for score in given:
        method = method_of(score)
        if method in given_by_method:
            raise ValidationFailed("scores", "at most one score per method")
        given_by_method[method] = score
    kept: list[Score] = []
    corrected: list[tuple[Score, Score]] = []
    for was in recorded:
        now = given_by_method.pop(method_of(was), was)
        if now != was:
            corrected.append((was, now))
        kept.append(now)
    added = tuple(given_by_method.values())
    return ScoreMerge(tuple(kept) + added, tuple(corrected), added)


def score_record(score: Score) -> dict[str, Any]:
    """A score as the audit keeps it: the method and the value, nothing else."""
    method = method_of(score).value
    match score:
        case News2() | ClinicalFrailty() | AmbulanceCategory():
            return {"method": method, "value": score.value}
        case ManchesterTriage():
            return {"method": method, "value": score.level}
        case PathwaysDx():
            return {"method": method, "value": score.code}


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
