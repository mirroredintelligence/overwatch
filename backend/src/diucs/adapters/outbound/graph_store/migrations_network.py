"""Migrations of the network registry and projections (TEN-051, TEN-053 add theirs here)."""

from dataclasses import dataclass
from typing import Final

from diucs.adapters.outbound.graph_store.migration_types import Migration


@dataclass(frozen=True, slots=True)
class RegistryConstraint:
    name: str
    label: str
    properties: tuple[str, ...]


NETWORK_REGISTRY_CONSTRAINTS: Final[tuple[RegistryConstraint, ...]] = ()
NETWORK_MIGRATIONS: Final[tuple[Migration, ...]] = ()
