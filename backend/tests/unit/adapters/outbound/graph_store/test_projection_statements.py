"""The projection statements of the network scope (TEN-053, DEC-542, DEC-132 item 4, DEC-134
items 6 and 7).

Nineteen statements, all network-only and all registered with a scenario. Fourteen write, and every
one of them passes the allowlist's own statement check (`check_network_write_statement`: no map
assignment, no label assignment, no delete, no property or relationship outside the allowlist). An
upsert matches the active `ProjectionSource` of its kind and takes its lock first, so a projection
that races a leave or a grant end writes nothing; it orders by the source's version, so a replay is
idempotent and an older message never replaces a newer one (hazard H-N06). Checked on the text and
the scenarios, without Neo4j; the generated test (TEN-060) runs each statement on a real database
in three scopes.
"""

import re

import pytest

from diucs.adapters.outbound.graph_store import projection_repository  # noqa: F401
from diucs.adapters.outbound.graph_store.projection_scenarios import PROJECTION_SCENARIOS
from diucs.adapters.outbound.graph_store.queries import NETWORK_KINDS, REGISTRY, statement_labels
from diucs.adapters.outbound.graph_store.scenario import Marked, validate_scenario
from diucs.application.projection import check_network_write_statement
from diucs.domain.messages.privacy_guard import find_forbidden_keys
from diucs.domain.rules import projection as allowlist

READS = (
    "Q-PROJ-SOURCE-GET",
    "Q-PROJ-SOURCES",
    "Q-NETVIEW-SERVICES",
    "Q-NETVIEW-CAPACITIES",
    "Q-NETVIEW-CRITERIA",
)
WRITES = (
    "Q-PROJ-SOURCE-OPEN",
    "Q-PROJ-SOURCE-END",
    "Q-PROJ-SERVICE-UPSERT",
    "Q-PROJ-LOCATION-UPSERT",
    "Q-PROJ-LOCATION-END",
    "Q-PROJ-HOUR-UPSERT",
    "Q-PROJ-HOURS-END",
    "Q-PROJ-CAPACITY-UPSERT",
    "Q-PROJ-CRITERIA-UPSERT",
    "Q-PROJ-MARK-SERVICE",
    "Q-PROJ-MARK-LOCATION",
    "Q-PROJ-MARK-HOUR",
    "Q-PROJ-MARK-CAPACITY",
    "Q-PROJ-MARK-CRITERIA",
)
ALL = (*READS, *WRITES)
# The statements that list a whole scope: they name no member.
LIST_ALL = ("Q-PROJ-SOURCES", "Q-NETVIEW-SERVICES", "Q-NETVIEW-CAPACITIES", "Q-NETVIEW-CRITERIA")
BY_MEMBER = tuple(query_id for query_id in ALL if query_id not in LIST_ALL)
# The kind of grant scope whose source an upsert needs to be active.
KIND = {
    "Q-PROJ-SERVICE-UPSERT": "directory",
    "Q-PROJ-LOCATION-UPSERT": "directory",
    "Q-PROJ-HOUR-UPSERT": "directory",
    "Q-PROJ-CAPACITY-UPSERT": "capacity",
    "Q-PROJ-CRITERIA-UPSERT": "criteria",
}
LABEL = {
    "Q-PROJ-SERVICE-UPSERT": "ProjectedService",
    "Q-PROJ-LOCATION-UPSERT": "ProjectedLocation",
    "Q-PROJ-HOUR-UPSERT": "ProjectedOpeningHour",
    "Q-PROJ-CAPACITY-UPSERT": "ProjectedCapacity",
    "Q-PROJ-CRITERIA-UPSERT": "ProjectedCriteria",
}
STAMPS = {"sourceTenant", "projectedAt", "grantId", "grantVersion"}


def _params(query_id: str) -> set[str]:
    return set(re.findall(r"\$(\w+)", REGISTRY.get(query_id).cypher)) - {"tenant"}


@pytest.mark.parametrize("query_id", ALL)
def test_every_statement_is_registered_network_only_with_a_scenario_that_validates(
    query_id: str,
) -> None:
    query = REGISTRY.get(query_id)
    assert query.scope == "tenant"
    assert query.scope_kinds == NETWORK_KINDS
    assert query.mode == ("write" if query_id in WRITES else "read")
    assert query.scenario is not None
    assert query.scenario is PROJECTION_SCENARIOS[query_id]
    assert validate_scenario(query_id, query.scenario) == []


def test_the_scenarios_are_exactly_these_nineteen() -> None:
    assert set(PROJECTION_SCENARIOS) == set(ALL)
    assert len(ALL) == 19


@pytest.mark.parametrize("query_id", ALL)
def test_a_scenario_tells_two_networks_apart_and_collides_on_the_source_and_the_service(
    query_id: str,
) -> None:
    scenario = PROJECTION_SCENARIOS[query_id]
    marked = [
        value
        for node in scenario.seed.nodes
        for value in node.props.values()
        if isinstance(value, Marked)
    ]
    assert marked, "the seed has a value that differs between the scopes"
    assert all(
        set(node.labels) <= (set(allowlist.ALLOWLIST) | {"ProjectionSource", "ProjectionCursor"})
        for node in scenario.seed.nodes
    )
    if query_id in BY_MEMBER:
        assert scenario.params["sourceTenant"] == "tenant-x"
        assert "sourceTenant" in scenario.lookup


@pytest.mark.parametrize("query_id", ALL)
def test_a_statement_names_network_labels_the_scope_and_the_source_tenant(query_id: str) -> None:
    text = REGISTRY.get(query_id).cypher
    assert set(statement_labels(text)) <= set(allowlist.ALLOWLIST) | {
        "ProjectionSource",
        "ProjectionCursor",
    }
    assert "tenantId: $tenant" in text
    assert ("$sourceTenant" in text) == (query_id in BY_MEMBER)
    # The source tenant is a value of a row, never the predicate that picks the scope.
    assert re.search(r"tenantId: \$sourceTenant", text) is None


@pytest.mark.parametrize("query_id", WRITES)
def test_a_write_passes_the_allowlists_own_statement_check(query_id: str) -> None:
    assert check_network_write_statement(REGISTRY.get(query_id).cypher) == []


@pytest.mark.parametrize("query_id", WRITES)
def test_no_write_deletes_assigns_a_map_or_a_label_or_calls_a_procedure(query_id: str) -> None:
    text = REGISTRY.get(query_id).cypher
    assert re.search(r"\b(DELETE|DETACH|REMOVE|CALL|FOREACH|LOAD)\b", text, re.IGNORECASE) is None
    assert "+=" not in text
    assert re.search(r"\bSET\s+\w+\s*:", text) is None


def test_the_relationships_a_network_write_may_create_are_these_two() -> None:
    assert frozenset({"HAS_LOCATION", "HAS_OPENING_HOUR"}) == allowlist.NETWORK_RELATIONSHIPS
    for query_id in ("Q-PROJ-LOCATION-UPSERT", "Q-PROJ-HOUR-UPSERT"):
        text = REGISTRY.get(query_id).cypher
        assert re.search(r"MERGE \(p\)-\[:HAS_(LOCATION|OPENING_HOUR)\]->", text)


def test_a_child_is_keyed_by_its_service_and_the_stamps_include_that_key() -> None:
    for label in ("ProjectedLocation", "ProjectedOpeningHour"):
        assert "sourceServiceId" in allowlist.SYSTEM_PROPERTIES[label]
        assert "sourceServiceId" not in {spec.prop for spec in allowlist.ALLOWLIST[label]}


@pytest.mark.parametrize("query_id", sorted(KIND))
def test_an_upsert_matches_the_active_source_of_its_kind_and_takes_its_lock_first(
    query_id: str,
) -> None:
    text = REGISTRY.get(query_id).cypher
    source = (
        "MATCH (s:ProjectionSource {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        f"kind: '{KIND[query_id]}', status: 'active'}}) SET s.status = s.status "
    )
    assert text.startswith(source)


@pytest.mark.parametrize("query_id", ["Q-PROJ-SERVICE-UPSERT", "Q-PROJ-CAPACITY-UPSERT"])
def test_a_service_and_a_capacity_row_are_ordered_by_the_source_version(query_id: str) -> None:
    text = REGISTRY.get(query_id).cypher
    assert "WITH p WHERE p.sourceVersion IS NULL OR p.sourceVersion <= $sourceVersion " in text


def test_a_criteria_row_is_ordered_by_its_version() -> None:
    text = REGISTRY.get("Q-PROJ-CRITERIA-UPSERT").cypher
    assert "WITH p WHERE p.version IS NULL OR p.version <= $version " in text


@pytest.mark.parametrize("query_id", ["Q-PROJ-LOCATION-UPSERT", "Q-PROJ-HOUR-UPSERT"])
def test_a_child_is_written_only_for_the_version_of_its_service_that_was_just_written(
    query_id: str,
) -> None:
    assert "p.sourceVersion = $sourceVersion" in REGISTRY.get(query_id).cypher


@pytest.mark.parametrize("query_id", sorted(KIND))
def test_an_upsert_writes_every_allowlisted_property_of_its_label_and_nothing_else(
    query_id: str,
) -> None:
    label = LABEL[query_id]
    stored = {spec.prop for spec in allowlist.ALLOWLIST[label]}
    expected = stored | STAMPS
    if label in ("ProjectedLocation", "ProjectedOpeningHour"):
        expected |= {"sourceServiceId", "sourceVersion"}
    if label == "ProjectedCriteria":
        expected -= {"sourceVersion"}
    assert _params(query_id) == expected


@pytest.mark.parametrize("query_id", WRITES)
def test_no_parameter_of_any_statement_has_the_form_of_a_personal_field(query_id: str) -> None:
    names = _params(query_id)
    assert find_forbidden_keys({name: 1 for name in names}) == []


def test_the_stamped_properties_of_a_row_are_the_scope_the_source_the_time_and_the_grant() -> None:
    for query_id in KIND:
        text = REGISTRY.get(query_id).cypher
        for fragment in ("projectedAt = $projectedAt", "grantId = $grantId", "endedAt = null"):
            assert fragment in text, (query_id, fragment)


@pytest.mark.parametrize(
    ("query_id", "label"),
    [
        ("Q-PROJ-MARK-SERVICE", "ProjectedService"),
        ("Q-PROJ-MARK-LOCATION", "ProjectedLocation"),
        ("Q-PROJ-MARK-HOUR", "ProjectedOpeningHour"),
        ("Q-PROJ-MARK-CAPACITY", "ProjectedCapacity"),
        ("Q-PROJ-MARK-CRITERIA", "ProjectedCriteria"),
    ],
)
def test_a_mark_ended_statement_marks_the_live_rows_of_one_member_and_deletes_none(
    query_id: str, label: str
) -> None:
    text = REGISTRY.get(query_id).cypher
    assert f":{label} {{tenantId: $tenant, sourceTenantId: $sourceTenant}}" in text
    assert "endedAt IS NULL" in text
    assert "endedAt = $endedAt" in text
    assert "endReason = $endReason" in text


def test_ending_a_source_is_a_move_from_active_and_a_second_end_changes_nothing() -> None:
    text = REGISTRY.get("Q-PROJ-SOURCE-END").cypher
    assert "status: 'active'" in text
    assert "s.status = 'ended'" in text


def test_opening_a_source_reopens_an_ended_one_and_clears_its_end() -> None:
    text = REGISTRY.get("Q-PROJ-SOURCE-OPEN").cypher
    assert text.startswith("MERGE (s:ProjectionSource {tenantId: $tenant, sourceTenantId: ")
    assert "ON MATCH SET s.status = 'active'" in text
    assert "s.endedAt = null" in text
