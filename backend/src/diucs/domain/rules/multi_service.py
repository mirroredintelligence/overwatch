"""Grouped prompts for a phone that reports for several services, and the phone load limit (D28).

domain-rules 2.4 and the D28 prompt. Due times are aware instants; they are compared and subtracted
in UTC (lessons L52 and L53). Domain functions take every time as an argument.

DEC-048 records the choices the prompt leaves open.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

GROUP_WINDOW: Final = timedelta(minutes=10)
MAX_SERVICES_PER_PHONE: Final = 3


@dataclass(frozen=True, slots=True)
class GroupedItem:
    service_id: str
    name: str
    due: datetime
    letter: str | None


@dataclass(frozen=True, slots=True)
class PromptGroup:
    items: tuple[GroupedItem, ...]
    due: datetime
    reply_by: datetime


def group_due(due: Sequence[tuple[str, str, datetime]]) -> list[PromptGroup]:
    raise NotImplementedError


def letters_for(names: Sequence[str]) -> dict[str, str]:
    raise NotImplementedError


def phone_overloaded(count: int) -> bool:
    raise NotImplementedError
