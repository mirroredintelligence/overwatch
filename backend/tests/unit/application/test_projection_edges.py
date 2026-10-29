"""The edges of the rows, bodies and the statement check (TEN-052): arguments that are not what
they should be, and statement shapes the parser must read or refuse. Every case is invented."""

from dataclasses import replace
from datetime import time
from typing import Any

import pytest

from diucs.application import projection as projection_module
from diucs.application.projection import (
    check_network_write_statement,
    format_window,
    from_body,
    parse_window,
    to_body,
    to_rows,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.network import GrantScope
from diucs.domain.rules import projection as domain_projection
from tests.support.projection_samples import (
    sample_capacity_projection,
    sample_criteria_projection,
    sample_service_projection,
)

_S = "MATCH (s:ProjectedService {tenantId: $tenant}) "


def test_rows_and_bodies_refuse_what_is_not_a_projection() -> None:
    for bad in (None, "service", {"a": 1}, object()):
        with pytest.raises(ValidationFailed):
            to_rows(bad)  # type: ignore[arg-type]
        with pytest.raises(ValidationFailed):
            to_body(bad)  # type: ignore[arg-type]


def test_a_window_that_is_timed_but_has_no_times_cannot_be_formatted() -> None:
    hour = sample_service_projection().opening_hours[0]
    object.__setattr__(hour, "start", None)

    with pytest.raises(ValidationFailed):
        format_window(hour)


def test_a_window_that_is_not_text_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        parse_window(5, 0)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["2026-13-45T09:00:00Z", "2026-10-29T25:61:61Z"])
def test_an_instant_that_looks_right_but_is_not_a_time_is_refused(bad: str) -> None:
    body = {**to_body(sample_capacity_projection()), "reported_at": bad}

    with pytest.raises(ValidationFailed):
        from_body(GrantScope.CAPACITY, body)


@pytest.mark.parametrize("bad", ["2027-13-45", "27-04-29", 20270429, "2027-04-29T00:00:00"])
def test_a_review_date_that_is_not_a_date_is_refused(bad: object) -> None:
    body = {**to_body(sample_criteria_projection()), "review_by": bad}

    with pytest.raises(ValidationFailed):
        from_body(GrantScope.CRITERIA, body)


def test_a_projection_kind_must_be_a_grant_scope() -> None:
    with pytest.raises(ValidationFailed):
        projection_module.body_keys("capacity")  # type: ignore[arg-type]


def test_a_non_text_key_in_a_body_is_refused() -> None:
    body: dict[Any, Any] = {**to_body(sample_service_projection()), 5: "x"}

    with pytest.raises(ValidationFailed):
        from_body(GrantScope.DIRECTORY, body)


def test_a_dto_built_from_a_body_is_validated_again_for_the_hours() -> None:
    body = {**to_body(sample_service_projection()), "opening_hours": ("0,1|08:00:00|08:00:00",)}

    with pytest.raises(ValidationFailed):
        from_body(GrantScope.DIRECTORY, body)
    assert replace(
        sample_service_projection(), opening_hours=sample_service_projection().opening_hours
    )


# ---------------------------------------------------------------- statement shapes


@pytest.mark.parametrize(
    "statement",
    [
        _S + "SET s.serviceName = 'it\\'s fine'",
        _S + 'SET s.serviceName = "say \\"hi\\""',
        _S + "SET s.serviceName = $n;",
        "OPTIONAL MATCH (s:ProjectedService {tenantId: $tenant}) SET s.serviceName = $n",
        _S + "SET s.serviceName = $n RETURN s.serviceName ORDER BY s.serviceName SKIP 1 LIMIT 2",
        _S + "WITH s ORDER BY s.sourceVersion DESC SET s.sourceVersion = 1",
        "UNWIND $rows AS row " + _S + "WITH s, row AS r SET s.sourceVersion = r.version",
        "MATCH (a:ProjectedService {tenantId: $tenant}) MATCH p = shortestPath((a)-[*1..3]-(b)) "
        "SET a.sourceVersion = 1",
        _S + "MATCH (s)-[:HAS_LOCATION*1..2]->(l) SET s.sourceVersion = 1",
        "MATCH (s:ProjectedService {tenantId: $tenant}) UNION MATCH (s:ProjectedService "
        "{tenantId: $tenant}) SET s.sourceVersion = 1",
        _S + "SET s.sourceVersion = 1.5, s.serviceName = $n",
        "MATCH (s:ProjectedService {}) SET s.sourceVersion = 1",
    ],
)
def test_a_statement_the_parser_reads_has_no_problems(statement: str) -> None:
    assert check_network_write_statement(statement) == []


@pytest.mark.parametrize(
    "statement",
    [
        _S + "SET s.serviceName = $",
        _S + "SET s.serviceName = @x",
        _S + "SET s.serviceName = [1, 2)",
        _S + "SET s.serviceName = 'a'; SET s.sourceVersion = 1",
        _S + "SET s",
        _S + "SET s.serviceName + 1",
        _S + "SET s + 1",
        _S + "SET s.serviceName $p",
        "MATCH (s:ProjectedService foo) SET s.sourceVersion = 1",
        "MATCH (s:ProjectedService {a}) SET s.sourceVersion = 1",
        "MERGE (s:ProjectedService {tenantId: $tenant}) UNWIND $rows",
        "`",
        5,
    ],
)
def test_a_statement_the_parser_cannot_read_is_unparseable(statement: Any) -> None:
    assert check_network_write_statement(statement) == ["unparseable"]


def test_an_anonymous_node_in_a_create_is_refused() -> None:
    assert "unlabelled-node" in check_network_write_statement("CREATE ()")


def test_a_relationship_variable_in_a_create_is_tracked_and_may_not_be_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(domain_projection, "NETWORK_RELATIONSHIPS", frozenset({"HAS_LOCATION"}))
    statement = (
        "MATCH (s:ProjectedService {tenantId: $tenant}), (l:ProjectedLocation {tenantId: $tenant}) "
        "MERGE (s)-[r:HAS_LOCATION]->(l) SET r.x = 1"
    )

    assert check_network_write_statement(statement) == ["relationship-properties"]


def test_a_with_alias_keeps_the_label_of_the_variable_it_renames() -> None:
    statement = _S + "WITH s AS t SET t.comment = $c"

    assert check_network_write_statement(statement) == [
        "property-not-allowed:ProjectedService.comment"
    ]


def test_matching_a_bracket_that_never_closes_is_unparseable() -> None:
    tokens, _ = projection_module._lex("(a")

    with pytest.raises(projection_module._Unparseable):
        projection_module._matching(tokens, 0)


def test_a_window_time_with_a_fraction_is_not_a_window() -> None:
    assert parse_window("0|08:00:00|18:00:00", 0).start == time(8, 0)
    with pytest.raises(ValidationFailed):
        parse_window("0|08:00:00.5|18:00:00", 0)


def test_a_location_with_no_coordinates_round_trips() -> None:
    from tests.support.projection_samples import sample_location

    location = replace(sample_location(), latitude=None, longitude=None)
    dto = sample_service_projection(location=location)

    assert from_body(GrantScope.DIRECTORY, to_body(dto)) == dto
