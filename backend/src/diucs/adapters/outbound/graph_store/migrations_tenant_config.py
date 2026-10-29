"""Migration of the tenant configuration records (TEN-026). Stub for the red commit."""

from typing import Final

from diucs.adapters.outbound.graph_store.migration_types import Migration

TENANT_CONFIG_MIGRATIONS: Final[tuple[Migration, ...]] = ()
