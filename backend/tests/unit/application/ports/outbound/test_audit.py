"""Pure tests of the audit chain functions (P05, DEC-055): canonical JSON and the chain hash."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import (
    GENESIS_HASH,
    AuditEntry,
    canonical_entry_json,
    canonical_json,
    chain_hash_for,
    chain_hash_over,
    genesis_hash_for,
)
from diucs.application.tenancy import DEFAULT_TENANT_ID
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed

ENTRY = AuditEntry(
    action="report-capacity",
    use_case="ReportCapacity",
    actor=Actor(
        role=Role.REPORTER,
        practitioner_id=None,
        device_id="dev-sms-1",
        channel="text",
        service_ids=frozenset({"svc-ucr-west"}),
    ),
    entity_ids=("obs-1",),
    snapshot=None,
    at=datetime(2026, 10, 25, 9, 0, tzinfo=UTC),
)

# Written out by hand: keys sorted at every level, no spaces, the instant ends with Z.
HAND_CANONICAL = (
    '{"action":"report-capacity",'
    '"actor":{"channel":"text","device_id":"dev-sms-1","practitioner_id":null,'
    '"role":"reporter","service_ids":["svc-ucr-west"]},'
    '"at":"2026-10-25T09:00:00.000000Z",'
    '"entity_ids":["obs-1"],"snapshot":null,"use_case":"ReportCapacity"}'
)


def test_the_genesis_hash_is_sixty_four_zeros() -> None:
    assert GENESIS_HASH == "0" * 64


def test_canonical_entry_json_is_the_hand_written_text() -> None:
    assert canonical_entry_json(ENTRY) == HAND_CANONICAL


def test_chain_hash_equals_sha256_of_previous_hash_and_canonical_text() -> None:
    expected = hashlib.sha256((GENESIS_HASH + HAND_CANONICAL).encode()).hexdigest()
    assert chain_hash_for(GENESIS_HASH, ENTRY) == expected


def test_canonical_json_ignores_dict_insertion_order() -> None:
    first = replace(ENTRY, snapshot={"b": 1, "a": {"y": 2, "x": 3}})
    second = replace(ENTRY, snapshot={"a": {"x": 3, "y": 2}, "b": 1})
    assert canonical_entry_json(first) == canonical_entry_json(second)


def test_a_frozenset_serialises_as_a_sorted_list() -> None:
    assert canonical_json(frozenset({"svc-ucr-west"})) == '["svc-ucr-west"]'
    assert canonical_json(frozenset({"svc-b", "svc-a"})) == '["svc-a","svc-b"]'


def test_a_tuple_serialises_as_a_list() -> None:
    assert canonical_json(("obs-1", "obs-2")) == '["obs-1","obs-2"]'


def test_a_naive_datetime_is_refused_in_the_entry() -> None:
    entry = replace(ENTRY, at=datetime(2026, 10, 25, 9, 0))
    with pytest.raises(ValidationFailed, match="at"):
        canonical_entry_json(entry)


# The genesis of each scope's chain (TEN-017): the default tenant keeps the original genesis, every
# other scope starts from a hash of its own id.


def test_the_default_tenant_keeps_the_genesis_of_the_chain_the_development_data_holds() -> None:
    assert genesis_hash_for(DEFAULT_TENANT_ID) == GENESIS_HASH


def test_another_tenant_starts_from_a_hash_of_its_own_id() -> None:
    expected = hashlib.sha256(b"diucs-genesis|acme-icb").hexdigest()
    assert genesis_hash_for("acme-icb") == expected
    assert genesis_hash_for("acme-icb") != GENESIS_HASH


def test_a_network_scope_has_its_own_genesis() -> None:
    assert genesis_hash_for("net-nw1") != genesis_hash_for("acme-icb")
    assert len(genesis_hash_for("net-nw1")) == 64


def test_no_two_scopes_share_a_genesis_and_each_is_a_hex_digest() -> None:
    scopes = [DEFAULT_TENANT_ID, "acme-icb", "acme-icb-2", "bridge-ccg", "net-nw1"]
    genesis = [genesis_hash_for(scope) for scope in scopes]
    assert len(set(genesis)) == len(scopes)
    for value in genesis:
        assert len(value) == 64
        int(value, 16)


def test_a_link_hashed_from_one_scopes_genesis_does_not_verify_from_anothers() -> None:
    text = canonical_entry_json(ENTRY)
    from_a = chain_hash_over(genesis_hash_for("acme-icb"), text)
    assert from_a != chain_hash_over(genesis_hash_for("bridge-ccg"), text)
    assert from_a != chain_hash_over(GENESIS_HASH, text)
