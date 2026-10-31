"""Outbound ports of a tenant's offboarding, export and purge (TEN-074, DEC-136 item 10, audit F
section 2.4, DEC-960 to DEC-966).

Three small ports, each a door the operator's use cases take and a tenant's own code never holds:

- `TenantDataReader` reads the bound tenant's scope for the export package and the purge's dry run:
  how many nodes of each label set there are, one page of the nodes of one label set, one page of
  the relationships, and the head of the audit chain. It reads in the scope bound now and in no
  other, and it only reads.
- `ExportStorage` holds the export package: a file at a time, and it answers with the SHA-256 of
  what it stored, so the manifest's hashes are the storage's own and not the writer's claim. The
  production adapter is the object store of the tenant's choice (not built here, a human decision);
  the recording fake in `adapters/testing/memory_export_storage.py` is the only implementation.
- `TenantPurger` deletes the bound tenant's scope in batches: the data first, the audit chain
  last, so a purge that stops half way still has the record of what the tenant did. A batch is its
  own transaction and `delete_*` answers how many nodes it removed, so the caller loops until it
  answers zero.
- `ScopeCachePurger` removes every cache key, lock, fence and channel of one scope.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from diucs.application.tenancy import ScopeId


@dataclass(frozen=True, slots=True)
class LabelCount:
    """How many nodes of the bound scope carry exactly this label set."""

    labels: tuple[str, ...]
    count: int


@dataclass(frozen=True, slots=True)
class ExportedNode:
    ref: str
    """A reference that is stable inside one export, so the relationship file can name its ends."""
    properties: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ExportedRelationship:
    ref: str
    type: str
    start: str
    end: str
    properties: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AuditHeadState:
    last_hash: str
    last_seq: int


class TenantDataReader(Protocol):
    async def node_counts(self) -> Sequence[LabelCount]: ...

    async def nodes(
        self, labels: tuple[str, ...], *, after: str | None, limit: int
    ) -> Sequence[ExportedNode]:
        """Up to `limit` nodes that carry exactly these labels, in ref order, after `after`."""
        ...

    async def relationships(
        self, *, after: str | None, limit: int
    ) -> Sequence[ExportedRelationship]: ...

    async def audit_head(self) -> AuditHeadState | None: ...


class ExportStorage(Protocol):
    async def put(self, tenant_id: str, package_id: str, name: str, content: bytes) -> str:
        """Store one file of a package and return the SHA-256 (hex) of the bytes stored."""
        ...

    async def has_package(self, tenant_id: str, manifest_hash: str) -> bool:
        """True when this tenant has a stored package whose manifest has this hash."""
        ...


class TenantPurger(Protocol):
    async def delete_data_batch(self, limit: int) -> int:
        """Delete up to `limit` nodes of the bound scope that are not the audit chain, with their
        relationships. The number deleted."""
        ...

    async def delete_audit_batch(self, limit: int) -> int:
        """As `delete_data_batch`, for the audit chain: refused (answers 0) while any other node of
        the scope is left, so the chain always goes last."""
        ...


class ScopeCachePurger(Protocol):
    async def purge_scope(self, scope: ScopeId) -> int:
        """Remove every key of the scope; the number removed."""
        ...
