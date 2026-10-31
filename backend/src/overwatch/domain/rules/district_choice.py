"""The districts offered as chips when a postcode cannot be used (W50, W9H DEC-1045, DEC-1046).

When the locator does not know the case's district, or no service covers it, the advisor can choose
one of the districts the tenant's services DO cover and run the options again. This orders those
districts and keeps the list short. Pure: places in, an ordered tuple out, no I/O.

- With a place for the patient (the district is known but uncovered): the nearest districts first.
- With none (the district is not known): the districts of the same postcode area as the case's
  first (DT before BH), then the rest, each in natural order (DT2 before DT10).

A district a service covers is the service's configuration, never a person's; the case's own
district is never offered back. Nothing is logged and no value is echoed in a refusal.
"""

import math
import re
from collections.abc import Mapping
from typing import Final

from diucs.domain.errors import ValidationFailed

MAX_DISTRICT_CHOICES: Final = 12
"""[ASSUMED] How many chips the screen is given: enough to cover the neighbours of any one district,
few enough to read on a phone without scrolling a wall of buttons."""

_DISTRICT: Final = re.compile(r"([A-Z]{1,2})([0-9])([A-Z0-9]?)")
_NATURAL: Final = re.compile(r"([A-Z]+)([0-9]+)([A-Z]*)")


def _area(district: str) -> str:
    match = _DISTRICT.fullmatch(district)
    return "" if match is None else match.group(1)


def _natural(district: str) -> tuple[str, int, str]:
    """DT2 before DT10: the letters, then the number as a number, then any trailing letter."""
    match = _NATURAL.fullmatch(district)
    if match is None:
        return (district, 0, "")
    return (match.group(1), int(match.group(2)), match.group(3))


def _check(district: object) -> str:
    if type(district) is not str or _DISTRICT.fullmatch(district) is None:
        raise ValidationFailed("districts", "must be upper-case postcode districts")
    return district


def _place(value: object) -> tuple[float, float]:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or not all(isinstance(part, (int, float)) and not isinstance(part, bool) for part in value)
    ):
        raise ValidationFailed("districts", "each district needs a place as two numbers")
    return (float(value[0]), float(value[1]))


def _distance_squared(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Squared flat-earth distance in degrees, with the longitude narrowed by the latitude. Only the
    order is used, so the scale does not matter."""
    mean = math.radians((a[0] + b[0]) / 2)
    dy = a[0] - b[0]
    dx = (a[1] - b[1]) * math.cos(mean)
    return dx * dx + dy * dy


def candidate_districts(
    places: Mapping[str, tuple[float, float]],
    *,
    origin: tuple[float, float] | None,
    case_district: str | None,
    limit: int = MAX_DISTRICT_CHOICES,
) -> tuple[str, ...]:
    """The districts to offer, in the order to show them, at most `limit`. `places` maps each
    candidate district to its centre; `origin` is the patient's place when it is known."""
    checked = {_check(district): _place(place) for district, place in places.items()}
    checked.pop(case_district or "", None)
    if origin is not None:
        start = _place(origin)
        ordered = sorted(checked, key=lambda d: (_distance_squared(checked[d], start), _natural(d)))
    else:
        area = _area(case_district) if case_district is not None else ""
        ordered = sorted(checked, key=lambda d: (area == "" or _area(d) != area, _natural(d)))
    return tuple(ordered[:limit])
