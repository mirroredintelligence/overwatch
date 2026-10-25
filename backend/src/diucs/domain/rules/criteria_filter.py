"""Hard criteria filter: may a case be offered to a service? A filter, never a ranking (D20).

Fails closed. A need, age band or criteria value that is not a known code excludes the service
with a reason, and never passes it. Reasons are fixed text: no case value is echoed.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from diucs.domain.codes import AgeBand, CriteriaStatus, NeedCategory
from diucs.domain.model.criteria import ServiceCriteria

AGE_BAND_BOUNDS: dict[AgeBand, tuple[int, int | None]] = {
    AgeBand.A0_15: (0, 15),
    AgeBand.A16_64: (16, 64),
    AgeBand.A65_79: (65, 79),
    AgeBand.A80_PLUS: (80, None),
}
"""Inclusive age bounds of each band. None is no upper limit."""

AGE_OVERLAP_WARNING: Final = "Check age: band overlaps the service's age limits"
"""[ASSUMED] shown when a band overlaps the service's age limits only in part (domain-rules 4.1)."""


@dataclass(frozen=True, slots=True)
class FilterResult:
    passes: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def _age_reasons(
    criteria: ServiceCriteria, age_band: object, reasons: list[str], warnings: list[str]
) -> None:
    # Exact member check first: a plain string such as "80+" is not a band.
    if type(age_band) is not AgeBand:
        reasons.append("Age not recognised")
        return
    band_min, band_max = AGE_BAND_BOUNDS[age_band]
    age_min, age_max = criteria.age_min, criteria.age_max
    fully_inside = band_min >= age_min and (
        age_max is None or (band_max is not None and band_max <= age_max)
    )
    if fully_inside:
        return
    overlaps = (age_max is None or band_min <= age_max) and (
        band_max is None or band_max >= age_min
    )
    if overlaps:
        warnings.append(AGE_OVERLAP_WARNING)
        return
    limit = "no limit" if age_max is None else str(age_max)
    reasons.append(f"Age {age_band.value} outside {age_min} to {limit}")


def check_hard_criteria(
    criteria: ServiceCriteria,
    age_band: AgeBand,
    district: str,
    needs: Iterable[NeedCategory],
) -> FilterResult:
    reasons: list[str] = []
    warnings: list[str] = []

    if criteria.status is not CriteriaStatus.CURRENT:
        reasons.append("Criteria not current")
    if not isinstance(district, str) or district not in criteria.districts:
        reasons.append(f"Does not cover {district}")

    # Checked in three passes, so the reasons come out in the stated order.
    needs_seen = tuple(needs)
    for need in needs_seen:
        if type(need) is not NeedCategory:
            reasons.append("Need not recognised")
    known = [need for need in needs_seen if type(need) is NeedCategory]
    for need in known:
        if need in criteria.excludes:
            reasons.append(f"Does not accept {need.value}")
    for need in known:
        if need not in criteria.excludes and need not in criteria.accepts:
            reasons.append(f"Does not take {need.value}")

    _age_reasons(criteria, age_band, reasons, warnings)

    return FilterResult(
        passes=not reasons,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )
