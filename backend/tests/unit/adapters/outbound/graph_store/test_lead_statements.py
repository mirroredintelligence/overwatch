"""The stored form of what the shift lead's pages read (W7B C): a suspension keeps the number of
requests it expired, and the invitation and device lists are registered statements that name the
tenant on every node. Pure: no Neo4j (the two-tenant run is the integration test)."""

from datetime import UTC, datetime

import pytest

from diucs.adapters.outbound.graph_store.flag_repository import (
    service_flag_from_fhir,
    service_flag_to_fhir,
)
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.flags import ServiceFlag

AT = datetime(2026, 10, 30, 8, 12, tzinfo=UTC)


def _flag(**changes: object) -> ServiceFlag:
    values: dict[str, object] = {
        "service_id": "svc-1",
        "code": "suspended",
        "active": True,
        "reason": "closed-unexpectedly",
        "actor_id": "prac-lead",
        "at": AT,
    }
    values.update(changes)
    return ServiceFlag(**values)  # type: ignore[arg-type]


def test_a_suspension_keeps_how_many_requests_it_expired() -> None:
    resource = service_flag_to_fhir(_flag(expired_count=2))

    assert resource["expiredCount"] == 2
    assert service_flag_from_fhir({**resource, "meta": {"versionId": "1"}}).expired_count == 2


def test_a_flag_with_no_count_stores_none_and_reads_none() -> None:
    resource = service_flag_to_fhir(_flag())

    assert "expiredCount" not in resource
    assert service_flag_from_fhir({**resource, "meta": {"versionId": "1"}}).expired_count is None


@pytest.mark.parametrize("bad", [-1, True, 1.5, "2"])
def test_a_count_that_is_not_a_whole_number_of_zero_or_more_is_refused(bad: object) -> None:
    with pytest.raises(ValidationFailed) as refusal:
        _flag(expired_count=bad)
    assert refusal.value.field == "expired_count"


@pytest.mark.parametrize("statement", ["Q-REG-INVITATIONS", "Q-DEVICE-LIST"])
def test_each_new_statement_is_registered_and_names_the_tenant_on_every_node(
    statement: str,
) -> None:
    query = REGISTRY.get(statement)

    assert query.mode == "read"
    assert query.cypher.count("tenantId: $tenant") >= 2
    assert query.scenario.expect.rows
