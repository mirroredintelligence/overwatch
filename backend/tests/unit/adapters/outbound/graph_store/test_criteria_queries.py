"""Unit tests for the criteria candidate and history statements (G11).

These pin the statement text and the scenario shape, and the input refusals of `candidates`, which
are decided before any transaction is touched. The database behaviour (the parity with the domain
filter, the suspension, the history order on real data) is in
tests/integration/graph_store/test_criteria_queries.py and runs in verification.
"""

import re
from enum import StrEnum
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store.criteria_repository import Neo4jCriteriaRepository
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario
from diucs.domain.codes import AgeBand, NeedCategory
from diucs.domain.errors import ValidationFailed

_TENANT_LABELS = ("HealthcareService", "ServiceCriteria", "ServiceFlag", "Concept")
_LABELLED_NODE = re.compile(r"\((\w*):(\w+)([^()]*)\)")


class _OtherEnum(StrEnum):
    """A member of another enum with the value of a need: it must not pass as a need."""

    FRAILTY = "frailty"


def _statement(query_id: str) -> Any:
    return REGISTRY.get(query_id)


def test_the_candidate_statement_is_registered_as_a_tenant_statement_with_a_scenario() -> None:
    query = _statement("Q-CRIT-FILTER")
    assert query.scope == "tenant"
    assert query.mode == "read"
    assert query.scenario is not None
    assert "$tenant" in query.cypher
    assert validate_scenario("Q-CRIT-FILTER", query.scenario) == []


def test_the_history_statement_is_registered_as_a_tenant_statement_with_a_scenario() -> None:
    query = _statement("Q-CRIT-HISTORY")
    assert query.scope == "tenant"
    assert query.mode == "read"
    assert query.scenario is not None
    assert validate_scenario("Q-CRIT-HISTORY", query.scenario) == []


@pytest.mark.parametrize("query_id", ["Q-CRIT-FILTER", "Q-CRIT-HISTORY"])
def test_every_labelled_node_names_the_tenant(query_id: str) -> None:
    cypher = _statement(query_id).cypher
    nodes = [m for m in _LABELLED_NODE.finditer(cypher) if m.group(2) in _TENANT_LABELS]
    assert nodes, "the statement matches no tenant node: the scan is not looking at it"
    for node in nodes:
        assert "tenantId: $tenant" in node.group(0), node.group(0)


def test_the_candidate_statement_reads_the_current_version_of_an_active_service() -> None:
    cypher = _statement("Q-CRIT-FILTER").cypher
    assert "(s:HealthcareService {active: true, tenantId: $tenant})" in cypher
    assert "-[:CURRENT_CRITERIA]->(c:ServiceCriteria {status: 'current', tenantId: $tenant})" in (
        cypher
    )


def test_the_candidate_statement_excludes_a_suspended_service_by_its_active_flag() -> None:
    cypher = _statement("Q-CRIT-FILTER").cypher
    assert "(f:ServiceFlag {code: 'suspended', status: 'active', tenantId: $tenant})" in cypher


def test_the_candidate_statement_uses_the_age_band_bounds_and_the_district() -> None:
    cypher = _statement("Q-CRIT-FILTER").cypher
    assert "c.ageMin <= coalesce($bandMax, 999)" in cypher
    assert "$bandMin <= c.ageMax" in cypher
    assert "$district IN c.postcodeDistricts" in cypher


def test_the_history_statement_reads_every_version_of_the_service_by_its_subject() -> None:
    # KI-180: every version whose subject is the service (a draft, a pending version, an old one),
    # with no need for a current version, newest first. It does not walk the SUPERSEDES chain.
    cypher = _statement("Q-CRIT-HISTORY").cypher
    assert "MATCH (v:ServiceCriteria {tenantId: $tenant})-[:SUBJECT]->" in cypher
    assert "(:HealthcareService {id: $serviceId, tenantId: $tenant})" in cypher
    assert "SUPERSEDES" not in cypher
    assert "status:" not in cypher
    assert "ORDER BY v.version DESC" in cypher


async def test_candidates_refuses_an_age_band_that_is_not_a_band() -> None:
    repo = Neo4jCriteriaRepository(tx=object(), store=object())  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        await repo.candidates("80+", "DT4", [NeedCategory.FRAILTY])  # type: ignore[arg-type]


async def test_candidates_refuses_a_need_that_is_not_a_need_category() -> None:
    repo = Neo4jCriteriaRepository(tx=object(), store=object())  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        await repo.candidates(AgeBand.A80_PLUS, "DT4", ["frailty"])  # type: ignore[list-item]


async def test_candidates_refuses_a_member_of_another_enum_with_the_same_value() -> None:
    repo = Neo4jCriteriaRepository(tx=object(), store=object())  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        await repo.candidates(AgeBand.A80_PLUS, "DT4", [_OtherEnum.FRAILTY])  # type: ignore[list-item]


async def test_candidates_refuses_an_empty_or_non_text_district() -> None:
    repo = Neo4jCriteriaRepository(tx=object(), store=object())  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        await repo.candidates(AgeBand.A80_PLUS, "", [NeedCategory.FRAILTY])
    with pytest.raises(ValidationFailed):
        await repo.candidates(AgeBand.A80_PLUS, None, [NeedCategory.FRAILTY])  # type: ignore[arg-type]
