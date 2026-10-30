"""Migration ids are unique, and P05's audit migrations sit after P07's (DEC-055 item 16, L68).

TEN-005: the list is assembled from per-area modules, the 26 core entries are pinned by a digest so
an applied migration cannot be edited, and the tenant migrations follow the last core id.
"""

import hashlib
import json

import pytest

from diucs.adapters.outbound.graph_store.migration_types import Migration
from diucs.adapters.outbound.graph_store.migrations import (
    CORE_MIGRATIONS,
    MIGRATIONS,
    assemble_migrations,
)
from diucs.adapters.outbound.graph_store.migrations_network import NETWORK_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_protected import PROTECTED_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_safety import SAFETY_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_support import SUPPORT_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_tenant import TENANT_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_tenant_config import TENANT_CONFIG_MIGRATIONS

CORE_IDS = [
    "0001_resource_id",
    "0002_identifier_key",
    "0003_concept_key",
    "0004_obs_by_service",
    "0005_task_by_status",
    "0006_svc_active",
    "0007_phone_hash",
    "0008_location_position",
    "0009_scheduled_work_id",
    "0014_communication_id",
    "0015_communication_provider_id",
    "0016_audit_event_id",
    "0017_audit_head_id",
    "0018_audit_ref_id",
    "0019_provenance_id",
    "0020_chain_seq",
    "0021_link_token_hash",
    "0022_case_reference_id",
    "0023_device_id",
    "0024_protected_contact_role_id",
    "0025_protected_contact_key",
    "0026_credential_device_id",
    "0027_report_flag_id",
    "0028_outbox_message_id",
    "0029_idempotency_key",
    "0030_processed_key",
]
# The SHA-256 of the canonical text of the 26 core entries, computed from main (a95fa3c) before
# TEN-005 touched migrations.py. Applied migrations are never edited: any change to an id or a
# statement changes this digest.
CORE_DIGEST = "662d3c728a8bd66c701e2d0c7d65d504d3dac73bb100c35b2ff96d28e148b702"
TENANT_IDS = [
    "0031_tenant_composites",
    "0032_backfill_default_tenant",
    "0033_case_open_reference",
    "0034_tenant_registry",
    "0035_default_tenant_record",
]

AUDIT_MIGRATION_IDS = [
    "0016_audit_event_id",
    "0017_audit_head_id",
    "0018_audit_ref_id",
    "0019_provenance_id",
    "0020_chain_seq",
]


def test_every_migration_id_is_unique() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert len(ids) == len(set(ids))


def test_no_two_migrations_share_a_numeric_prefix() -> None:
    prefixes = [migration.id.split("_", 1)[0] for migration in MIGRATIONS]
    assert len(prefixes) == len(set(prefixes))


def test_the_audit_migrations_are_numbered_0016_to_0020_in_order_after_p07() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    start = ids.index("0016_audit_event_id")
    assert ids[start : start + 5] == AUDIT_MIGRATION_IDS
    assert ids.index("0015_communication_provider_id") < start


def test_the_link_token_migration_is_0021_after_the_audit_migrations() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert ids.count("0021_link_token_hash") == 1
    assert ids.index("0021_link_token_hash") > ids.index("0020_chain_seq")


def test_the_case_reference_migration_is_0022_after_the_link_token_migration() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert ids.count("0022_case_reference_id") == 1
    assert ids.index("0022_case_reference_id") > ids.index("0021_link_token_hash")


def test_the_device_and_contact_migrations_are_0023_and_0024_after_the_case_reference() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert ids.count("0023_device_id") == 1
    assert ids.count("0024_protected_contact_role_id") == 1
    assert ids.index("0023_device_id") > ids.index("0022_case_reference_id")
    assert ids.index("0024_protected_contact_role_id") > ids.index("0023_device_id")


def test_the_protected_contact_key_migration_is_0025_after_the_contact_index() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert ids.count("0025_protected_contact_key") == 1
    assert ids.index("0025_protected_contact_key") > ids.index("0024_protected_contact_role_id")


def test_the_credential_device_migration_is_0026_after_the_contact_key() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert ids.count("0026_credential_device_id") == 1
    assert ids.index("0026_credential_device_id") > ids.index("0025_protected_contact_key")


def test_the_report_flag_id_migration_is_0027_after_the_credential_migration() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert ids.count("0027_report_flag_id") == 1
    assert ids.index("0027_report_flag_id") > ids.index("0026_credential_device_id")


def test_the_outbox_message_id_migration_is_0028_after_the_report_flag_migration() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert ids.count("0028_outbox_message_id") == 1
    assert ids.index("0028_outbox_message_id") > ids.index("0027_report_flag_id")


def test_the_idempotency_migrations_are_0029_and_0030_after_the_outbox_migration() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert ids.count("0029_idempotency_key") == 1
    assert ids.count("0030_processed_key") == 1
    assert ids.index("0029_idempotency_key") > ids.index("0028_outbox_message_id")
    assert ids.index("0030_processed_key") > ids.index("0029_idempotency_key")


def test_the_list_is_sorted_by_id() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert ids == sorted(ids)


def test_the_core_ids_are_the_twenty_six_of_main() -> None:
    assert [migration.id for migration in CORE_MIGRATIONS] == CORE_IDS


def test_each_core_entry_is_one_schema_statement_with_no_loop_and_no_parameter() -> None:
    for migration in CORE_MIGRATIONS:
        assert len(migration.statements) == 1, migration.id
        assert migration.loops == (), migration.id
        assert dict(migration.params) == {}, migration.id


def test_the_core_entries_are_unchanged_since_main() -> None:
    canonical = json.dumps(
        [[migration.id, list(migration.statements)] for migration in CORE_MIGRATIONS],
        separators=(",", ":"),
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == CORE_DIGEST


def test_the_tenant_migrations_follow_the_last_core_id_in_order() -> None:
    assert [migration.id for migration in TENANT_MIGRATIONS] == TENANT_IDS
    ids = [migration.id for migration in MIGRATIONS]
    start = ids.index("0030_processed_key") + 1
    assert ids[start : start + len(TENANT_IDS)] == TENANT_IDS


def test_the_assembled_list_is_the_core_the_tenant_and_the_network_lists_together() -> None:
    assert len(CORE_MIGRATIONS) == 26
    assert len(MIGRATIONS) == (
        len(CORE_MIGRATIONS)
        + len(TENANT_MIGRATIONS)
        + len(TENANT_CONFIG_MIGRATIONS)
        + len(NETWORK_MIGRATIONS)
        + len(PROTECTED_MIGRATIONS)
        + len(SUPPORT_MIGRATIONS)
        + len(SAFETY_MIGRATIONS)
    )
    assert {m.id for m in MIGRATIONS} == (
        {m.id for m in CORE_MIGRATIONS}
        | {m.id for m in TENANT_MIGRATIONS}
        | {m.id for m in TENANT_CONFIG_MIGRATIONS}
        | {m.id for m in NETWORK_MIGRATIONS}
        | {m.id for m in PROTECTED_MIGRATIONS}
        | {m.id for m in SUPPORT_MIGRATIONS}
        | {m.id for m in SAFETY_MIGRATIONS}
    )


def test_assembly_sorts_by_id_whatever_the_order_of_the_areas() -> None:
    late = (Migration("0040_x"), Migration("0041_y"))
    early = (Migration("0010_a"), Migration("0050_z"))
    assert [m.id for m in assemble_migrations(late, early)] == [
        "0010_a",
        "0040_x",
        "0041_y",
        "0050_z",
    ]


def test_a_duplicate_id_across_two_areas_is_refused() -> None:
    with pytest.raises(ValueError, match="0040_x"):
        assemble_migrations((Migration("0040_x"),), (Migration("0040_x", ("S",)),))


def test_a_duplicate_id_inside_one_area_is_refused() -> None:
    with pytest.raises(ValueError, match="0040_x"):
        assemble_migrations((Migration("0040_x"), Migration("0040_x")))


def test_a_migration_batch_must_be_positive() -> None:
    with pytest.raises(ValueError, match="batch"):
        Migration("0099_x", batch=0)


def test_a_migration_holds_its_parameters_read_only() -> None:
    migration = Migration("0099_x", params={"a": 1})
    assert migration.params["a"] == 1
    with pytest.raises(TypeError):
        migration.params["b"] = 2  # type: ignore[index]
