"""The advice on a clinical Task, as a FHIR read shows it (KI-232, KI-768).

The advice is `Task.output` (a typed output per part), so a FHIR read of the Task shows it; the
extensions the screens read today stay beside it until they read the outputs. The service the
advisor was considering is a task input, named by its name now and never by its id. Pure.
"""

from datetime import UTC, datetime
from typing import Any

from diucs.adapters.inbound.fhir_rest.clinical_mapping import (
    TASK_OUTPUT_SYSTEM,
    clinical_task,
    input_url,
)
from diucs.application.use_cases.clinical_advice import CaseGlance, ClinicalRequestView
from diucs.domain.codes import AgeBand, NeedCategory, Urgency
from diucs.domain.model.clinical import ClinicalAdvice, ClinicalRequestRecord
from diucs.domain.rules.clinical_queue import ClinicalRequest

REQUESTED = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
TAKEN = datetime(2026, 10, 23, 13, 14, tzinfo=UTC)
ADVISED = datetime(2026, 10, 23, 13, 20, tzinfo=UTC)
GLANCE = CaseGlance("4821", AgeBand.A80_PLUS, (NeedCategory.FRAILTY,), Urgency.WITHIN_2_HRS, 2)


def view(*, advised: bool, service_name: str | None = None, note: str | None = None) -> Any:
    request = ClinicalRequest(
        id="req-1",
        case_id="case-1",
        urgency="now",
        requested_at=REQUESTED,
        taken_by="clin-1",
        taken_at=TAKEN,
        advised_at=ADVISED if advised else None,
    )
    advice = (
        ClinicalAdvice("go-ahead", "safer-alternative", "h-1" if note else None, "clin-1", ADVISED)
        if advised
        else None
    )
    record = ClinicalRequestRecord(
        request=request,
        requester_id="adv-1",
        why="borderline-criteria",
        snapshot_ref=None,
        advice=advice,
        service_id="svc-1" if service_name else None,
    )
    return ClinicalRequestView(
        record=record, case=GLANCE, note=note, returns_at=None, service_name=service_name
    )


def outputs(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["type"]["coding"][0]["code"]: item for item in task.get("output", [])}


def test_an_advised_task_shows_its_advice_as_typed_outputs() -> None:
    task = clinical_task(view(advised=True, note="Phone first"))

    found = outputs(task)
    assert found["advice-choice"]["valueCode"] == "go-ahead"
    assert found["advice-reason"]["valueCode"] == "safer-alternative"
    assert found["advice-note"]["valueString"] == "Phone first"
    assert found["advised-at"]["valueDateTime"] == "2026-10-23T13:20:00Z"
    assert all(item["type"]["coding"][0]["system"] == TASK_OUTPUT_SYSTEM for item in task["output"])


def test_the_extensions_the_screens_read_today_stay_beside_the_outputs() -> None:
    task = clinical_task(view(advised=True))

    urls = {item["url"] for item in task["extension"]}
    assert input_url("advice-choice") in urls
    assert input_url("advised-at") in urls


def test_a_reason_or_note_that_was_not_given_has_no_output() -> None:
    task = clinical_task(view(advised=True))

    assert set(outputs(task)) == {"advice-choice", "advice-reason", "advised-at"}


def test_a_task_not_yet_advised_has_no_output_element() -> None:
    assert "output" not in clinical_task(view(advised=False))


def test_the_service_the_advisor_was_considering_is_named_by_its_name() -> None:
    task = clinical_task(view(advised=False, service_name="UCR West"))

    items = [i for i in task["extension"] if i["url"] == input_url("service")]
    assert items == [{"url": input_url("service"), "valueString": "UCR West"}]
    assert "svc-1" not in repr(task)


def test_no_service_considered_has_no_service_input() -> None:
    task = clinical_task(view(advised=False))

    assert all(i["url"] != input_url("service") for i in task["extension"])
