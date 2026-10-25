"""Referrer scores: validated value objects (D18). Scores are recorded as given, never calculated.

Stub for the red commit (DEC-010): names and signatures only, no behaviour yet.
"""

from dataclasses import dataclass

from diucs.domain.codes import AcuityMethod


@dataclass(frozen=True, slots=True)
class News2:
    value: int

    def __post_init__(self) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ClinicalFrailty:
    value: int

    def __post_init__(self) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class AmbulanceCategory:
    value: int

    def __post_init__(self) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ManchesterTriage:
    level: str

    def __post_init__(self) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class PathwaysDx:
    code: str

    def __post_init__(self) -> None:
        raise NotImplementedError


Score = News2 | ClinicalFrailty | AmbulanceCategory | ManchesterTriage | PathwaysDx


def method_of(score: Score) -> AcuityMethod:
    raise NotImplementedError
