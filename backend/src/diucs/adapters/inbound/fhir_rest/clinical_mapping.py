"""A clinical advice request as a FHIR Task, for the advisor who asked and for the clinical advisors
(R13, W7A). Pure: no store, no clock.

The Task names the case, the urgency and the reason, and carries the case's glance: its number, age
band, needs, urgency and NEWS2. It carries no postcode, no district, no practitioner and no
identifier of anyone: the requester's id, the taker's id and the handle of the note stay out. Each
input or output that is not a FHIR element is an extension under the `task-input` code system.

    case-reference  the four-digit case number          age-band     the case's age band
    need            one per need (repeats)               case-urgency the case's urgency
    news2           the case's NEWS2 score               urgency      now or within-15-min
    why             the reason it was asked              returns-at   when a held lock ends
    advice-choice, advice-reason, advice-note, advised-at   the advice, once given
"""

from typing import Any, Final

from diucs.application.idempotency import format_instant
from diucs.application.use_cases.clinical_advice import ClinicalRequestView
from diucs.domain.codes import code_system_url

CLINICAL_CODE: Final = "clinical-advice"
REQUESTED: Final = "requested"
IN_PROGRESS: Final = "in-progress"
COMPLETED: Final = "completed"
TASK_CODE_SYSTEM: Final = code_system_url("task-code")
TASK_INPUT: Final = "task-input"


def input_url(name: str) -> str:
    return code_system_url(f"{TASK_INPUT}/{name}")


def _item(name: str, value_key: str, value: object) -> dict[str, Any]:
    return {"url": input_url(name), value_key: value}


def task_status(view: ClinicalRequestView) -> str:
    request = view.record.request
    if request.advised_at is not None:
        return COMPLETED
    if request.taken_by is not None:
        return IN_PROGRESS
    return REQUESTED


def clinical_task(view: ClinicalRequestView) -> dict[str, Any]:
    record = view.record
    request = record.request
    extensions: list[dict[str, Any]] = [
        _item("urgency", "valueCode", request.urgency),
        _item("why", "valueCode", record.why),
    ]
    glance = view.case
    if glance is not None:
        extensions.append(_item("case-reference", "valueString", glance.reference))
        if glance.age_band is not None:
            extensions.append(_item("age-band", "valueCode", glance.age_band.value))
        extensions.extend(_item("need", "valueCode", need.value) for need in glance.needs)
        if glance.urgency is not None:
            extensions.append(_item("case-urgency", "valueCode", glance.urgency.value))
        if glance.news2 is not None:
            extensions.append(_item("news2", "valueInteger", glance.news2))
    if view.returns_at is not None:
        extensions.append(_item("returns-at", "valueDateTime", format_instant(view.returns_at)))
    advice = record.advice
    if advice is not None:
        extensions.append(_item("advice-choice", "valueCode", advice.choice))
        if advice.reason is not None:
            extensions.append(_item("advice-reason", "valueCode", advice.reason))
        if view.note is not None:
            extensions.append(_item("advice-note", "valueString", view.note))
        extensions.append(_item("advised-at", "valueDateTime", format_instant(advice.at)))
    return {
        "resourceType": "Task",
        "id": request.id,
        "status": task_status(view),
        "code": {"coding": [{"system": TASK_CODE_SYSTEM, "code": CLINICAL_CODE}]},
        "focus": {"reference": f"ServiceRequest/{request.case_id}"},
        "authoredOn": format_instant(request.requested_at),
        "extension": extensions,
    }
