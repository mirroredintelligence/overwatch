"""Outbound port: the append-only audit log with a hash chain (P05, DEC-054).

STUB (red commit, DEC-010): the behaviour is not written yet.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from diucs.application.actor import Actor

GENESIS_HASH = "0" * 64


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


def canonical_json(value: object) -> str:
    raise NotImplementedError("P05 stub")


def canonical_entry_json(entry: AuditEntry) -> str:
    raise NotImplementedError("P05 stub")


def chain_hash_for(previous_hash: str, entry: AuditEntry) -> str:
    raise NotImplementedError("P05 stub")


class AuditLog(Protocol):
    async def append(self, entry: AuditEntry) -> AuditRecord: ...

    async def records(self, since: str | None = None) -> list[AuditRecord]: ...

    async def verify_chain(self) -> bool: ...
