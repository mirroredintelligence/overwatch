"""The mirror seed and the snapshots of the generated two-tenant test (TEN-004, DEC-150).

STUB (DEC-010, red commit): the names exist, the functions raise NotImplementedError.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.scenario import Slot, TenantSeed

# Labels a node may carry without a tenantId: the migration record and the registry nodes of the
# network design (DEC-132).
UNSTAMPED_OK: Final = frozenset({"Migration"})


@dataclass(frozen=True, slots=True)
class Node:
    labels: tuple[str, ...]
    props: Mapping[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, slots=True)
class Rel:
    start: Node
    type: str
    end: Node
    props: Mapping[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, slots=True)
class Snapshot:
    nodes: tuple[Node, ...] = ()
    rels: tuple[Rel, ...] = ()


def canonical(value: Any) -> str:
    raise NotImplementedError


def seed_statement(seed: TenantSeed, slot: Slot) -> tuple[str, dict[str, Any]]:
    raise NotImplementedError


async def seed_tenant(driver: AsyncDriver, tenant: str, slot: Slot, seed: TenantSeed) -> None:
    raise NotImplementedError


def digest(snapshot: Snapshot) -> str:
    raise NotImplementedError
