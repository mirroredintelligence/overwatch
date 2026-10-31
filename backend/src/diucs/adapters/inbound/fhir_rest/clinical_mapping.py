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
    service         the name of the service the advisor was considering, when one was named
    advice-choice, advice-reason, advice-note, advised-at   the advice, once given

The advice is also `Task.output` (KI-232): one typed output per part, under the `task-output` code
system, so a FHIR read of the Task shows it. The extensions stay beside the outputs until the
screens read the outputs.
"""

from typing import Any, Final

from diucs.application.idempotency import format_instant
from diucs.application.use_cases.clinical_advice import ClinicalRequestView
from diucs.application.use_cases.clinical_context import AdvisorContact, WhatAdvisorSaw
from diucs.domain.codes import code_system_url

CLINICAL_CODE: Final = "clinical-advice"
REQUESTED: Final = "requested"
IN_PROGRESS: Final = "in-progress"
COMPLETED: Final = "completed"
TASK_CODE_SYSTEM: Final = code_system_url("task-code")
TASK_OUTPUT_SYSTEM: Final = code_system_url("task-output")
TASK_INPUT: Final = "task-input"


def input_url(name: str) -> str:
    return code_system_url(f"{TASK_INPUT}/{name}")


def _item(name: str, value_key: str, value: object) -> dict[str, Any]:
    return {"url": input_url(name), value_key: value}


def _output(code: str, value_key: str, value: object) -> dict[str, Any]:
    return {
        "type": {"coding": [{"system": TASK_OUTPUT_SYSTEM, "code": code}]},
        value_key: value,
    }


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
    if view.service_name is not None:
        extensions.append(_item("service", "valueString", view.service_name))
    if view.returns_at is not None:
        extensions.append(_item("returns-at", "valueDateTime", format_instant(view.returns_at)))
    advice = record.advice
    outputs: list[dict[str, Any]] = []
    if advice is not None:
        extensions.append(_item("advice-choice", "valueCode", advice.choice))
        outputs.append(_output("advice-choice", "valueCode", advice.choice))
        if advice.reason is not None:
            extensions.append(_item("advice-reason", "valueCode", advice.reason))
            outputs.append(_output("advice-reason", "valueCode", advice.reason))
        if view.note is not None:
            extensions.append(_item("advice-note", "valueString", view.note))
            outputs.append(_output("advice-note", "valueString", view.note))
        advised_at = format_instant(advice.at)
        extensions.append(_item("advised-at", "valueDateTime", advised_at))
        outputs.append(_output("advised-at", "valueDateTime", advised_at))
    task: dict[str, Any] = {
        "resourceType": "Task",
        "id": request.id,
        "status": task_status(view),
        "code": {"coding": [{"system": TASK_CODE_SYSTEM, "code": CLINICAL_CODE}]},
        "focus": {"reference": f"ServiceRequest/{request.case_id}"},
        "authoredOn": format_instant(request.requested_at),
        "extension": extensions,
    }
    if outputs:
        task["output"] = outputs
    return task


def seen_json(saw: WhatAdvisorSaw) -> dict[str, Any]:
    """What the advisor saw, for the clinician who holds the request (W9G). One line per service of
    the display: its name, how it was shown, its status, its figure (what it could take, "+n" when
    over capacity, or none), the age of the figure, whether that is past the stale limit, why it was
    not suitable, and the criteria version. No postcode, no district, no identifier of a service or
    a person: the lines are in the order the display showed them."""
    return {
        "state": saw.state,
        "shownAt": None if saw.shown_at is None else format_instant(saw.shown_at),
        "options": saw.options,
        "noneFitted": saw.state == "shown" and saw.options == 0,
        "lines": [
            {
                "service": line.service,
                "shownAs": line.shown_as,
                "status": line.status,
                "statusText": line.status_text,
                "figure": line.figure,
                "age": line.age,
                "stale": line.stale,
                "why": line.why,
                "criteriaVersion": line.criteria_version,
            }
            for line in saw.lines
        ],
    }


def contact_json(contact: AdvisorContact) -> dict[str, Any]:
    """The way to reach the advisor, for the clinician who holds the request (W9G). The number is
    whole here and nowhere else; with none, `available` is false and every other field is null."""
    return {
        "available": contact.phone is not None,
        "via": contact.via,
        "phone": contact.phone,
        "name": contact.name,
    }
