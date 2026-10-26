"""Migration ids are unique, and P05's audit migrations sit after P07's (DEC-055 item 16, L68)."""

from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS

AUDIT_MIGRATION_IDS = [
    "0016_audit_event_id",
    "0017_audit_head_id",
    "0018_audit_ref_id",
    "0019_provenance_id",
    "0020_chain_seq",
]


def test_every_migration_id_is_unique() -> None:
    ids = [migration_id for migration_id, _ in MIGRATIONS]
    assert len(ids) == len(set(ids))


def test_no_two_migrations_share_a_numeric_prefix() -> None:
    prefixes = [migration_id.split("_", 1)[0] for migration_id, _ in MIGRATIONS]
    assert len(prefixes) == len(set(prefixes))


def test_the_audit_migrations_are_numbered_0016_to_0020_in_order_after_p07() -> None:
    ids = [migration_id for migration_id, _ in MIGRATIONS]
    start = ids.index("0016_audit_event_id")
    assert ids[start : start + 5] == AUDIT_MIGRATION_IDS
    assert ids.index("0015_communication_provider_id") < start


def test_the_link_token_migration_is_0021_after_the_audit_migrations() -> None:
    ids = [migration_id for migration_id, _ in MIGRATIONS]
    assert ids.count("0021_link_token_hash") == 1
    assert ids.index("0021_link_token_hash") > ids.index("0020_chain_seq")


def test_the_case_reference_migration_is_0022_after_the_link_token_migration() -> None:
    ids = [migration_id for migration_id, _ in MIGRATIONS]
    assert ids.count("0022_case_reference_id") == 1
    assert ids.index("0022_case_reference_id") > ids.index("0021_link_token_hash")


def test_the_device_and_contact_migrations_are_0023_and_0024_after_the_case_reference() -> None:
    ids = [migration_id for migration_id, _ in MIGRATIONS]
    assert ids.count("0023_device_id") == 1
    assert ids.count("0024_protected_contact_role_id") == 1
    assert ids.index("0023_device_id") > ids.index("0022_case_reference_id")
    assert ids.index("0024_protected_contact_role_id") > ids.index("0023_device_id")


def test_the_protected_contact_key_migration_is_0025_after_the_contact_index() -> None:
    ids = [migration_id for migration_id, _ in MIGRATIONS]
    assert ids.count("0025_protected_contact_key") == 1
    assert ids.index("0025_protected_contact_key") > ids.index("0024_protected_contact_role_id")


def test_the_credential_device_migration_is_0026_after_the_contact_key() -> None:
    ids = [migration_id for migration_id, _ in MIGRATIONS]
    assert ids.count("0026_credential_device_id") == 1
    assert ids.index("0026_credential_device_id") > ids.index("0025_protected_contact_key")


def test_the_report_flag_id_migration_is_0027_after_the_credential_migration() -> None:
    ids = [migration_id for migration_id, _ in MIGRATIONS]
    assert ids.count("0027_report_flag_id") == 1
    assert ids.index("0027_report_flag_id") > ids.index("0026_credential_device_id")


def test_the_outbox_message_id_migration_is_0028_after_the_report_flag_migration() -> None:
    ids = [migration_id for migration_id, _ in MIGRATIONS]
    assert ids.count("0028_outbox_message_id") == 1
    assert ids.index("0028_outbox_message_id") > ids.index("0027_report_flag_id")
