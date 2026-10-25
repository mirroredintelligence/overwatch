"""Grouped prompts for a phone that reports for several services, and the phone load limit (D28).

domain-rules 2.4 and the D28 prompt. Due times are aware instants; they are compared and subtracted
in UTC (lessons L52 and L53). Domain functions take every time as an argument.

DEC-048 records the choices the prompt leaves open.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.schedule import reply_by

# [ASSUMED] domain-rules 2.4: the 10-minute grouping window. Owner-pending: the clinical safety
# officer must confirm it with the other [ASSUMED] values. Not a settled rule-book value.
GROUP_WINDOW: Final = timedelta(minutes=10)
MAX_SERVICES_PER_PHONE: Final = 3
# From the D28 prompt and DEC-048 item 6. NOT a rule-book value: it is the number of letters A to Z.
MAX_LETTERED_ITEMS: Final = 26


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


def _utc_instant(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed("due", "must be a timezone-aware instant")
    return value.astimezone(UTC)


def letters_for(names: Sequence[str]) -> dict[str, str]:
    if len(names) > MAX_LETTERED_ITEMS:
        raise ValidationFailed("names", "at most 26 items can be lettered")
    if len(set(names)) != len(names):
        raise ValidationFailed("names", "names must be unique within a group")
    return {name: chr(ord("A") + index) for index, name in enumerate(sorted(names))}


def group_due(due: Sequence[tuple[str, str, datetime]]) -> list[PromptGroup]:
    seen_ids: set[str] = set()
    entries: list[tuple[datetime, str, str]] = []
    for service_id, name, when in due:
        if service_id in seen_ids:
            raise ValidationFailed("service_id", "a service may appear once in a phone's prompts")
        seen_ids.add(service_id)
        entries.append((_utc_instant(when), name, service_id))
    entries.sort()

    batches: list[list[tuple[datetime, str, str]]] = []
    for entry in entries:
        if batches and entry[0] < batches[-1][0][0] + GROUP_WINDOW:
            batches[-1].append(entry)
        else:
            batches.append([entry])

    groups: list[PromptGroup] = []
    for batch in batches:
        if len(batch) > MAX_LETTERED_ITEMS:
            raise ValidationFailed("items", "at most 26 items can be prompted together")
        names = [name for _, name, _ in batch]
        letters = letters_for(names) if len(batch) > 1 else None
        items = tuple(
            GroupedItem(
                service_id=service_id,
                name=name,
                due=when,
                letter=letters[name] if letters is not None else None,
            )
            for when, name, service_id in batch
        )
        first_due = batch[0][0]
        groups.append(PromptGroup(items=items, due=first_due, reply_by=reply_by(first_due)))
    return groups


def phone_overloaded(count: int) -> bool:
    if count < 0:
        raise ValidationFailed("count", "must not be negative")
    return count > MAX_SERVICES_PER_PHONE
