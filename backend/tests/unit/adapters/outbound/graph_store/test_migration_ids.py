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
    assert ids[-5:] == AUDIT_MIGRATION_IDS
    assert ids.index("0015_communication_provider_id") < ids.index("0016_audit_event_id")
