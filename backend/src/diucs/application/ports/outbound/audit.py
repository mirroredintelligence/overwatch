"""Outbound port: the append-only audit log with a hash chain (P05, DEC-054).

Every audit entry and every provenance record is a link in one chain:

    chain_hash = sha256((previous_hash + canonical_json(entry)).encode()).hexdigest()

The first link's previous_hash is GENESIS_HASH. Canonical JSON: sorted keys, no spaces, ASCII kept,
datetimes as ISO 8601 UTC ending in Z, enums as their values, sets as sorted lists, tuples as lists.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from diucs.application.actor import Actor
from diucs.domain.errors import ValidationFailed

GENESIS_HASH = "0" * 64
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    action: str
    use_case: str
    actor: Actor
    entity_ids: tuple[str, ...]
    snapshot: dict[str, Any] | None
    at: datetime


@dataclass(frozen=True, slots=True)
class AuditRecord:
    id: str
    entry: AuditEntry
    chain_hash: str
    previous_hash: str


def _sort_key(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _plain(value: object, path: str) -> Any:
    """Turn a value into JSON-ready data in canonical form, or refuse it."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValidationFailed(path or "value", "must be a timezone-aware datetime")
        return value.astimezone(UTC).strftime(TIME_FORMAT)
    if isinstance(value, dict):
        return {str(key): _plain(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, set | frozenset):
        return sorted((_plain(item, path) for item in value), key=_sort_key)
    if isinstance(value, list | tuple):
        return [_plain(item, path) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise ValidationFailed(path or "value", "has no canonical JSON form")


def canonical_json(value: object) -> str:
    """The canonical text of a value (see the module docstring)."""
    return json.dumps(_plain(value, ""), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_entry_json(entry: AuditEntry) -> str:
    if entry.at.utcoffset() is None:
        raise ValidationFailed("at", "must be a timezone-aware datetime")
    return canonical_json(
        {
            "action": entry.action,
            "use_case": entry.use_case,
            "actor": {
                "role": entry.actor.role,
                "practitioner_id": entry.actor.practitioner_id,
                "device_id": entry.actor.device_id,
                "channel": entry.actor.channel,
                "service_ids": entry.actor.service_ids,
            },
            "entity_ids": entry.entity_ids,
            "snapshot": entry.snapshot,
            "at": entry.at,
        }
    )


def chain_hash_over(previous_hash: str, canonical_text: str) -> str:
    """The chain link for a canonical text, given the link before it."""
    return hashlib.sha256((previous_hash + canonical_text).encode()).hexdigest()


def chain_hash_for(previous_hash: str, entry: AuditEntry) -> str:
    return chain_hash_over(previous_hash, canonical_entry_json(entry))


class AuditLog(Protocol):
    """Append-only. There is no update, delete or remove."""

    async def append(self, entry: AuditEntry) -> AuditRecord: ...

    async def records(self, since: str | None = None) -> list[AuditRecord]: ...

    async def verify_chain(self) -> bool: ...
