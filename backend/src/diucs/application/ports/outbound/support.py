"""Outbound port: the support-access records (O06, docs/spec/fhir-data-model.md "Platform nodes").

A `UiSession` is pseudonymous. The only link from a session to a person is a `SupportCode` the
person creates, and only the keyed hash of the code is stored. Every open of a session is a
`SupportAccess`, written in the same unit of work as its audit entry, and shown to the person.
Adapter: Neo4jSupportRepository (graph_store/support_repository.py). Every record is tenant-scoped:
the adapter writes and matches `tenantId` from the unit of work, never from a caller.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SupportCodeRecord:
    code_hash: str
    session_id: str
    practitioner_id: str
    created_at: datetime
    expires_at: datetime
    stopped_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SupportAccessRecord:
    id: str
    session_id: str
    practitioner_id: str
    reason: str
    opened_at: datetime
    expires_at: datetime


class SupportRepository(Protocol):
    async def ensure_session(
        self,
        session_id: str,
        device_type: str,
        app_mode: str,
        release: str,
        started_at: datetime,
    ) -> None:
        """Create the pseudonymous session if it does not exist. Never links it to a person."""
        ...

    async def session_exists(self, session_id: str) -> bool: ...

    async def session_shared_by(self, session_id: str, practitioner_id: str) -> bool:
        """True when the practitioner created a support code for this session."""
        ...

    async def add_code(self, record: SupportCodeRecord) -> bool:
        """Store a code's hash and its links. False when the session or the practitioner is not in
        this tenant, so nothing was written."""
        ...

    async def code_by_hash(self, code_hash: str) -> SupportCodeRecord | None: ...

    async def stop_codes(self, session_id: str, practitioner_id: str, at: datetime) -> int:
        """Expire the practitioner's live codes for the session at once. Returns how many."""
        ...

    async def end_accesses(self, session_id: str, at: datetime) -> int:
        """End the opens of the session still in progress, at once. Returns how many."""
        ...

    async def add_access(self, record: SupportAccessRecord) -> bool:
        """Store one open. False when the session or the opening practitioner is not in this
        tenant, so nothing was written."""
        ...

    async def accesses_of(self, session_id: str) -> list[SupportAccessRecord]: ...
