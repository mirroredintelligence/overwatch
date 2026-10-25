"""Hard criteria filter: may a case be offered to a service? A filter, never a ranking (D20).

DEC-010 red stub: the types exist with their signatures; the rule is not written yet.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from diucs.domain.codes import AgeBand, NeedCategory
from diucs.domain.model.criteria import ServiceCriteria

AGE_BAND_BOUNDS: dict[AgeBand, tuple[int, int | None]] = {}


@dataclass(frozen=True, slots=True)
class FilterResult:
    passes: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def check_hard_criteria(
    criteria: ServiceCriteria,
    age_band: AgeBand,
    district: str,
    needs: Iterable[NeedCategory],
) -> FilterResult:
    raise NotImplementedError("D20 red stub: check_hard_criteria is not implemented yet")
