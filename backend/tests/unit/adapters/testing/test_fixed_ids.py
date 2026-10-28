from typing import Any, cast

import pytest

from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.tenancy import ScopeId, ScopeInvalid
from diucs.bootstrap.container import build_for_tests


def test_default_prefix_counts_up_from_one() -> None:
    ids = SequentialIds()
    assert ids.new_id() == "id-1"
    assert ids.new_id() == "id-2"


def test_custom_prefix_is_used() -> None:
    ids = SequentialIds(prefix="booking")
    assert ids.new_id() == "booking-1"


def test_each_instance_counts_separately() -> None:
    first = SequentialIds()
    second = SequentialIds()
    first.new_id()
    assert second.new_id() == "id-1"


# TEN-003: tenant-prefixed ids


def test_a_scoped_generator_prefixes_the_scope() -> None:
    ids = SequentialIds.scoped("a1")
    assert [ids.new_id(), ids.new_id()] == ["a1-id-1", "a1-id-2"]


def test_a_scoped_generator_takes_a_prefix_after_the_scope() -> None:
    assert SequentialIds.scoped("a1", "booking").new_id() == "a1-booking-1"


def test_a_scope_id_works_as_well_as_a_string() -> None:
    assert SequentialIds.scoped(ScopeId.tenant("a1")).new_id() == "a1-id-1"
    assert SequentialIds.scoped(ScopeId.network("net-pilot")).new_id() == "net-pilot-id-1"


def test_two_tenants_never_produce_the_same_id_in_their_first_hundred() -> None:
    first = SequentialIds.scoped("a1")
    second = SequentialIds.scoped("b1")
    produced = [first.new_id() for _ in range(100)] + [second.new_id() for _ in range(100)]
    assert len(set(produced)) == 200


def test_two_generators_for_one_tenant_produce_the_same_sequence_and_do_not_share_a_counter() -> (
    None
):
    first = SequentialIds.scoped("a1")
    second = SequentialIds.scoped("a1")
    assert [first.new_id() for _ in range(3)] == ["a1-id-1", "a1-id-2", "a1-id-3"]
    assert [second.new_id() for _ in range(3)] == ["a1-id-1", "a1-id-2", "a1-id-3"]


@pytest.mark.parametrize("scope", ["A1", "a:1", "", "a b", "net-", "x"])
def test_a_scope_that_is_not_valid_is_refused(scope: str) -> None:
    with pytest.raises(ScopeInvalid):
        SequentialIds.scoped(scope)


def test_a_network_id_is_a_scope_too() -> None:
    assert SequentialIds.scoped("net-pilot").new_id() == "net-pilot-id-1"


def test_the_default_generator_is_unchanged_and_so_is_the_one_build_for_tests_uses() -> None:
    assert SequentialIds().new_id() == "id-1"
    assert SequentialIds(prefix="x").new_id() == "x-1"
    container = build_for_tests(neo4j=cast(Any, object()))
    assert container.ids.new_id() == "id-1"
    assert container.ids.new_id() == "id-2"
