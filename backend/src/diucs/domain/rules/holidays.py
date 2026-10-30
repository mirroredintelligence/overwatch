"""Bank holidays and service closures (TEN-066, H-T21). Stub (red): not yet implemented."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

REGIONS: Final = frozenset({"england-and-wales", "scotland", "northern-ireland"})


@dataclass(frozen=True, slots=True)
class ClosurePeriod:
    """A service's closure, as inclusive local dates."""

    first: date
    last: date


def bank_holidays(region: str) -> frozenset[date]:
    raise NotImplementedError


def closed_on(region: str, closures: Sequence[ClosurePeriod] = ()) -> Callable[[date], bool]:
    raise NotImplementedError
