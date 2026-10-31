"""The tenant configuration records (TEN-026): composite uniqueness for each, expand only.

Migration 0055 (the first id of the block 0055 to 0059 given to this task) makes the key of each
record unique within its tenant: a configuration version by its number, a setting by its version
and key, a contact by its kind, a channel by its id, a retention rule by its data class, a directory
binding by its directory and a role mapping by its group. A racing second write of one key then
waits and matches, or is refused, instead of creating a second node (lessons L90 and L122); the
adapter turns the refusal of a second version number into `Conflict`.

One schema statement each (lesson L8: a schema statement runs in its own transaction), idempotent
(`IF NOT EXISTS`), fixed text written out in full (DEC-142 item 1). Nothing is dropped and no data
is written: the labels are new, so no old single-property constraint is superseded.
"""

from typing import Final

from diucs.adapters.outbound.graph_store.migration_types import Migration

TENANT_CONFIG_MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(
        "0055_tenant_config_records",
        statements=(
            "CREATE CONSTRAINT tenant_config_version IF NOT EXISTS FOR (n:TenantConfigVersion) "
            "REQUIRE (n.tenantId, n.version) IS UNIQUE",
            "CREATE CONSTRAINT tenant_setting_key IF NOT EXISTS FOR (n:TenantSetting) "
            "REQUIRE (n.tenantId, n.configVersion, n.key) IS UNIQUE",
            "CREATE CONSTRAINT tenant_contact_kind IF NOT EXISTS FOR (n:TenantContact) "
            "REQUIRE (n.tenantId, n.kind) IS UNIQUE",
            "CREATE CONSTRAINT tenant_channel_id IF NOT EXISTS FOR (n:TenantChannel) "
            "REQUIRE (n.tenantId, n.id) IS UNIQUE",
            "CREATE CONSTRAINT tenant_retention_class IF NOT EXISTS FOR (n:TenantRetention) "
            "REQUIRE (n.tenantId, n.dataClass) IS UNIQUE",
            "CREATE CONSTRAINT tenant_entra_binding IF NOT EXISTS FOR (n:TenantEntraBinding) "
            "REQUIRE (n.tenantId, n.directoryId) IS UNIQUE",
            "CREATE CONSTRAINT tenant_role_mapping IF NOT EXISTS FOR (n:TenantRoleMapping) "
            "REQUIRE (n.tenantId, n.groupObjectId) IS UNIQUE",
        ),
    ),
)
