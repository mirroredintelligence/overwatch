"""Pure tests of the clinical request store (P18): the Task mapping, the advice properties, the
queue order and the statement shape. Neo4j behaviour is in
tests/integration/graph_store/test_clinical_request_repository.py.
"""

import re
from datetime import UTC, datetime

import pytest

from diucs.adapters.outbound.graph_store import clinical_request_repository  # noqa: F401
from diucs.adapters.outbound.graph_store.clinical_request_repository import (
    clinical_record_from_fhir,
    clinical_record_to_fhir,
    clinical_record_to_props,
)
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario
from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED
from diucs.domain.codes import code_system_url
from diucs.domain.model.clinical import ClinicalAdvice, ClinicalRequestRecord
from diucs.domain.rules.clinical_queue import ClinicalRequest, give_advice, take

REQUESTED = datetime(2026, 10, 25, 13, 13, tzinfo=UTC)
TAKEN = datetime(2026, 10, 25, 13, 14, tzinfo=UTC)
ADVISED = datetime(2026, 10, 25, 13, 16, tzinfo=UTC)
TASK_CODE = code_system_url("task-code")


def _record(
    request: ClinicalRequest, advice: ClinicalAdvice | None = None
) -> ClinicalRequestRecord:
    return ClinicalRequestRecord(
        request=request,
        requester_id="adv-1",
        why="borderline criteria",
        snapshot_ref="audit-1",
        advice=advice,
    )


WAITING = _record(
    ClinicalRequest(id="req-1", case_id="case-1", urgency="now", requested_at=REQUESTED)
)
TAKEN_BY_CLIN = _record(take(WAITING.request, "clin-1", TAKEN))
ADVICE = ClinicalAdvice(
    choice="go-ahead",
    reason="within-criteria",
    note_handle="h-123",
    clinician_id="clin-1",
    at=ADVISED,
)
ADVISED_RECORD = _record(give_advice(TAKEN_BY_CLIN.request, "clin-1", ADVISED), advice=ADVICE)


def _props_of(record: ClinicalRequestRecord) -> dict[str, object]:
    return clinical_record_to_props(record)


@pytest.mark.parametrize("record", [WAITING, TAKEN_BY_CLIN, ADVISED_RECORD])
def test_a_request_round_trips_through_its_task_and_its_advice_properties(
    record: ClinicalRequestRecord,
) -> None:
    resource = clinical_record_to_fhir(record)

    assert clinical_record_from_fhir(resource, _props_of(record)) == record


def test_a_request_is_a_task_with_the_clinical_code() -> None:
    resource = clinical_record_to_fhir(WAITING)

    assert resource["resourceType"] == "Task"
    assert resource["code"]["coding"][0] == {
        "system": TASK_CODE,
        "code": "clinical-advice-request",
    }
    assert resource["focus"] == {"reference": "ServiceRequest/case-1"}
    assert resource["requester"] == {"reference": "Practitioner/adv-1"}


@pytest.mark.parametrize(("urgency", "priority"), [("now", "stat"), ("within-15-min", "asap")])
def test_urgency_is_the_task_priority(urgency: str, priority: str) -> None:
    record = _record(
        ClinicalRequest(id="req-2", case_id="case-1", urgency=urgency, requested_at=REQUESTED)
    )

    assert clinical_record_to_fhir(record)["priority"] == priority


def test_the_taker_is_the_owner_once_taken() -> None:
    assert "owner" not in clinical_record_to_fhir(WAITING)
    assert clinical_record_to_fhir(TAKEN_BY_CLIN)["owner"] == {"reference": "Practitioner/clin-1"}


@pytest.mark.parametrize(
    ("record", "status"),
    [(WAITING, "waiting"), (TAKEN_BY_CLIN, "taken"), (ADVISED_RECORD, "advised")],
)
def test_the_business_status_follows_the_request(
    record: ClinicalRequestRecord, status: str
) -> None:
    assert clinical_record_to_fhir(record)["businessStatus"]["coding"][0]["code"] == status


def test_the_advice_properties_hold_the_handle_and_never_the_note_text() -> None:
    props = _props_of(ADVISED_RECORD)

    assert props["noteHandle"] == "h-123"
    assert props["adviceChoice"] == "go-ahead"
    assert props["adviceReason"] == "within-criteria"
    assert props["advisedAt"] == ADVISED
    assert props["businessStatus"] == "advised"


def test_no_advice_properties_are_set_before_advice() -> None:
    props = _props_of(WAITING)

    assert props["adviceChoice"] is None
    assert props["noteHandle"] is None
    assert props["advisedAt"] is None


def test_the_clinical_statements_are_registered() -> None:
    assert {"Q-CLIN-SET-PROPS", "Q-CLIN-WAITING", "Q-CLIN-TAKEN-BY"} <= set(REGISTRY.ids())


def test_every_clinical_statement_names_its_tenant_and_carries_a_valid_scenario() -> None:
    pattern = re.compile(r"\((?:\w+)?(?::\w+)+\s*(\{[^}]*\})?\)")
    ids = [q for q in REGISTRY.ids() if q.startswith("Q-CLIN")]
    assert ids
    for query_id in ids:
        query = REGISTRY.get(query_id)
        for match in pattern.finditer(query.cypher):
            assert match.group(1) is not None and "tenantId: $tenant" in match.group(1), query_id
        assert query.scenario is not None, query_id
        assert validate_scenario(query_id, query.scenario) == [], query_id
        assert query_id not in UNCONVERTED


def test_the_queue_statement_orders_nothing_it_does_not_need_to() -> None:
    # The queue order is applied in Python by queue_order (D23): the statement returns ids only.
    assert "note" not in REGISTRY.get("Q-CLIN-WAITING").cypher.lower()
