"""Outbound port: the append-only audit log with a hash chain (P05, DEC-055).

Every audit entry and every provenance record is a link in one chain:

    chain_hash = sha256((previous_hash + canonical_json(entry)).encode()).hexdigest()

The first link's previous_hash is the genesis of its scope: GENESIS_HASH for the default tenant (the
chain the development data holds), and a hash of the scope id for every other tenant or network
scope (genesis_hash_for, TEN-017). Each scope has its own chain and its own head.

Canonical JSON: sorted keys, no spaces, ASCII kept, datetimes as ISO 8601 UTC ending in Z, enums as
their values, sets as sorted lists, tuples as lists.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from diucs.application.actor import Actor
from diucs.application.tenancy import DEFAULT_TENANT_ID
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed

GENESIS_HASH = "0" * 64
GENESIS_LABEL = "diucs-genesis|"
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


def genesis_hash_for(scope: str) -> str:
    """The hash the chain of one scope starts from (TEN-017, audit A section 3.2).

    The default tenant keeps GENESIS_HASH, so the chain the development data was written on still
    verifies unchanged. Every other scope starts from the SHA-256 of its own id, so a chain cannot
    be grafted onto another scope's head, and a link hashed under one genesis never verifies under
    another. The hashed text of every link is unchanged: the tenant is the chain's, not the entry's.
    """
    if scope == DEFAULT_TENANT_ID:
        return GENESIS_HASH
    return hashlib.sha256((GENESIS_LABEL + scope).encode()).hexdigest()


def chain_hash_over(previous_hash: str, canonical_text: str) -> str:
    """The chain link for a canonical text, given the link before it."""
    return hashlib.sha256((previous_hash + canonical_text).encode()).hexdigest()


def chain_hash_for(previous_hash: str, entry: AuditEntry) -> str:
    return chain_hash_over(previous_hash, canonical_entry_json(entry))


class AuditLog(Protocol):
    """Append-only. There is no update, delete or remove."""

    async def append(self, entry: AuditEntry) -> AuditRecord: ...

    async def append_provenance(
        self,
        target_type: str,
        target_id: str,
        activity: str,
        agent_id: str,
        agent_role: Role,
        source_communication_id: str | None = None,
        extra: dict[str, Any] | None = None,
        agent_type: str = "Practitioner",
    ) -> str:
        """Append a Provenance record to the chain: who did what to which record, with a few small
        facts in `extra` (names of letters and digits, values text, whole numbers or flags). It is
        linked to its target and its agent. Returns the record's id. Never a patient value, and
        never a phone number (U28 puts the number in the contact store and its keyed hash here)."""
        ...

    async def records(self, since: str | None = None) -> list[AuditRecord]: ...

    async def records_for(self, entity_id: str) -> list[AuditRecord]:
        """Audit entries (not provenance) that name this entity id, in chain order (U42). Reads
        the bound tenant's chain only."""
        ...

    async def verify_chain(self) -> bool: ...
