"""The expand step of the tenant schema (TEN-005): stub."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.migration_types import Migration

REGISTRY_LABELS: Final[tuple[str, ...]] = ()


@dataclass(frozen=True, slots=True)
class CompositeConstraint:
    name: str
    label: str
    properties: tuple[str, ...]
    replaces: str | None


@dataclass(frozen=True, slots=True)
class CompositeIndex:
    name: str
    label: str
    properties: tuple[str, ...]
    replaces: str


COMPOSITE_CONSTRAINTS: Final[tuple[CompositeConstraint, ...]] = ()
COMPOSITE_INDEXES: Final[tuple[CompositeIndex, ...]] = ()
SUPERSEDED_CONSTRAINTS: Final[frozenset[str]] = frozenset()
SUPERSEDED_INDEXES: Final[frozenset[str]] = frozenset()
STAMP_DEFAULT_TENANT: Final = ""
OPEN_REFERENCE_BACKFILL: Final = ""
UNSTAMPED_NODES_QUERY: Final = ""
CROSS_SCOPE_RELATIONSHIPS_QUERY: Final = ""
ROLLBACK_0031: Final[tuple[str, ...]] = ()
TENANT_MIGRATIONS: Final[tuple[Migration, ...]] = ()


async def backfill_default_tenant(driver: AsyncDriver, *, batch: int = 10_000) -> int:
    raise NotImplementedError


async def invariant_violations(driver: AsyncDriver) -> Mapping[str, list[dict[str, Any]]]:
    raise NotImplementedError
