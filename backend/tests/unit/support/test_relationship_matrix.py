"""The relationship matrix is complete and says what each entry point does (TEN-029).

The matrix lists every relationship type the graph store writes by name, and what an entry point
does when the caller names a record that belongs to another tenant. These are the checks that need
no database: that no written type is missing from the matrix, that no entry is stale, and that
every entry the integration matrix must exercise has a case, and no other entry has one.
"""

import pytest

from tests.support import relationship_matrix as matrix
from tests.support.relationship_matrix import Handling


def test_every_relationship_type_the_store_writes_is_classified() -> None:
    classified = {entry.type for entry in matrix.RELATIONSHIPS}

    assert matrix.written_types() - classified == frozenset()


def test_no_literal_entry_is_stale() -> None:
    literal = {entry.type for entry in matrix.RELATIONSHIPS if entry.literal}

    assert literal - matrix.written_types() == frozenset()


def test_the_scan_finds_the_relationships_of_the_graph_store() -> None:
    written = matrix.written_types()

    assert {"FOCUS", "COVERED_BY", "HAS_VERSION", "SHARED_VIA", "USED_BY"} <= written
    assert "Practitioner" not in written


def test_a_type_is_classified_once() -> None:
    types = [entry.type for entry in matrix.RELATIONSHIPS]

    assert len(types) == len(set(types))


def test_every_checked_entry_names_a_case_and_no_other_entry_does() -> None:
    for entry in matrix.RELATIONSHIPS:
        if entry.handling is Handling.CHECKED:
            assert entry.cases, entry.type
        else:
            assert entry.cases == (), entry.type


def test_a_case_names_one_relationship_and_one_entry_point() -> None:
    cases = matrix.checked_cases()

    assert cases
    assert all(name.count(".") == 2 for name in cases)
    assert set(cases.values()) == {
        entry.type for entry in matrix.RELATIONSHIPS if entry.handling is Handling.CHECKED
    }


def test_a_case_name_is_listed_once() -> None:
    names = [name for entry in matrix.RELATIONSHIPS for name in entry.cases]

    assert len(names) == len(set(names))


def test_a_placeholder_entry_names_the_entry_point_that_creates_it() -> None:
    placeholders = [e for e in matrix.RELATIONSHIPS if e.handling is Handling.PLACEHOLDER]

    assert placeholders
    assert all(entry.note for entry in placeholders)


@pytest.mark.parametrize("handling", [Handling.SHARED, Handling.REGISTRY])
def test_a_shared_or_registry_entry_says_why(handling: Handling) -> None:
    entries = [e for e in matrix.RELATIONSHIPS if e.handling is handling]

    assert entries
    assert all(entry.note for entry in entries)


def test_only_concept_valued_relationships_are_shared() -> None:
    shared = {e.type for e in matrix.RELATIONSHIPS if e.handling is Handling.SHARED}

    assert shared == {"ACCEPTS_NEED", "EXCLUDES_NEED", "CHANNEL", "CODE", "MEDIUM", "TOPIC", "TYPE"}


def test_shape_replaces_the_ids_and_nothing_else() -> None:
    from diucs.domain.errors import NotFound

    error = NotFound("HealthcareService/svc-9 is not here")

    assert matrix.shape(error, "svc-9") == "HealthcareService/<id> is not here"
    assert matrix.shape(NotFound("practitioner"), "svc-9") == "practitioner"


def test_shape_replaces_every_id_longest_first() -> None:
    from diucs.domain.errors import NotFound

    error = NotFound("svc-1 and svc-12")

    assert matrix.shape(error, "svc-1", "svc-12") == "<id> and <id>"


def test_the_integration_matrix_runs_every_case_of_the_matrix_and_no_other() -> None:
    from tests.integration.graph_store import test_cross_tenant_references as integration

    assert set(integration.CASES) == set(matrix.checked_cases())
