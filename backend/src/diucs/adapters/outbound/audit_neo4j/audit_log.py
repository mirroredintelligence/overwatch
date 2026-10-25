"""Neo4j audit log and provenance on one hash chain (P05, DEC-054). STUB (red commit, DEC-010)."""

from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry, AuditRecord
from diucs.domain.codes import Role


class AuditHeadMissing(RuntimeError):
    """The chain head does not exist. Call ensure_audit_head at startup."""


async def ensure_audit_head(driver: Any) -> None:
    raise NotImplementedError("P05 stub")


class Neo4jAuditLog:
    def __init__(self, tx: AsyncManagedTransaction, ids: Any = None, clock: Any = None) -> None:
        raise NotImplementedError("P05 stub")

    async def append(self, entry: AuditEntry) -> AuditRecord:
        raise NotImplementedError("P05 stub")

    async def records(self, since: str | None = None) -> list[AuditRecord]:
        raise NotImplementedError("P05 stub")

    async def verify_chain(self) -> bool:
        raise NotImplementedError("P05 stub")

    async def append_provenance(
        self,
        target_type: str,
        target_id: str,
        activity: str,
        agent_id: str,
        agent_role: Role,
        source_communication_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        raise NotImplementedError("P05 stub")
