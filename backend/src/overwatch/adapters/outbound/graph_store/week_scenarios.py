"""The scenarios of the week summary's date-range reads (U35, DEC-142 item 5).

One scenario per statement: `Q-CASE-OPENED-BETWEEN`, `Q-CAP-BETWEEN`, `Q-BOOK-CONFIRMED-BETWEEN`
and `Q-COMM-PROMPTS-DUE-BETWEEN`. Both tenants get the same nodes with the same keys, one inside
the window and one outside it, so a statement that forgets `tenantId: $tenant` returns the other
tenant's row, which carries a different id. The window is given by two times (`start`, `end`); a
time is not a key, so it is declared new. The module is pure data: no Neo4j, no Cypher.
"""

from datetime import UTC, datetime
from typing import Final

from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)
from diucs.domain.codes import BASE_URL, code_system_url

_START: Final = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
_END: Final = datetime(2026, 10, 19, 17, 0, tzinfo=UTC)
_INSIDE: Final = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
_OUTSIDE: Final = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
_BOOKING_OUTPUT_SYSTEM: Final = code_system_url("booking-output-type")
_MESSAGE_SYSTEM: Final = f"{BASE_URL}CodeSystem/message-id"
_WARD: Final = SeedNode(
    "ward",
    ("Resource", "HealthcareService"),
    {"id": "svc-1", "key": "HealthcareService/svc-1", "name": Marked("Ward"), "active": True},
)

# Cases: a ServiceRequest with its opened time (authoredOn).
_CASE_IN: Final = SeedNode(
    "case-in",
    ("Resource", "ServiceRequest"),
    {"id": Marked("case-in"), "key": "ServiceRequest/case-in", "authoredOn": _INSIDE},
)
_CASE_OUT: Final = SeedNode(
    "case-out",
    ("Resource", "ServiceRequest"),
    {"id": Marked("case-out"), "key": "ServiceRequest/case-out", "authoredOn": _OUTSIDE},
)
_CASE_SEED: Final = TenantSeed(nodes=(_CASE_IN, _CASE_OUT))

# Capacity reports of the ward: one inside the window, one outside.
_REPORT_IN: Final = SeedNode(
    "report-in",
    ("Resource", "Observation"),
    {
        "id": Marked("obs-in"),
        "key": "Observation/obs-in",
        "effectiveDateTime": _INSIDE,
        "ext_reportType": "number",
    },
)
_REPORT_OUT: Final = SeedNode(
    "report-out",
    ("Resource", "Observation"),
    {
        "id": Marked("obs-out"),
        "key": "Observation/obs-out",
        "effectiveDateTime": _OUTSIDE,
        "ext_reportType": "number",
    },
)
_REPORT_SEED: Final = TenantSeed(
    nodes=(_WARD, _REPORT_IN, _REPORT_OUT),
    rels=(SeedRel("report-in", "FOCUS", "ward"), SeedRel("report-out", "FOCUS", "ward")),
)

# Confirmed bookings: a Task with a confirmed-at output inside the window and one outside it.
_CONFIRMED_AT: Final = "confirmed-at"
_OUTPUT_CONCEPT: Final = SeedNode(
    "output-concept",
    ("Concept",),
    {
        "key": f"Concept|{_BOOKING_OUTPUT_SYSTEM}|{_CONFIRMED_AT}",
        "system": _BOOKING_OUTPUT_SYSTEM,
        "code": _CONFIRMED_AT,
    },
)
_BOOK_IN: Final = SeedNode(
    "book-in",
    ("Resource", "Task"),
    {"id": Marked("bk-in"), "key": "Task/bk-in", "businessStatus": "confirmed"},
)
_BOOK_OUT: Final = SeedNode(
    "book-out",
    ("Resource", "Task"),
    {"id": Marked("bk-out"), "key": "Task/bk-out", "businessStatus": "confirmed"},
)
_OUT_IN: Final = SeedNode(
    "out-in", ("Task_Output",), {"key": "Task/bk-in#output[0]", "valueDateTime": _INSIDE}
)
_OUT_OUT: Final = SeedNode(
    "out-out", ("Task_Output",), {"key": "Task/bk-out#output[0]", "valueDateTime": _OUTSIDE}
)
_BOOKING_SEED: Final = TenantSeed(
    nodes=(_WARD, _OUTPUT_CONCEPT, _BOOK_IN, _BOOK_OUT, _OUT_IN, _OUT_OUT),
    rels=(
        SeedRel("book-in", "HAS_OUTPUT", "out-in"),
        SeedRel("book-out", "HAS_OUTPUT", "out-out"),
        SeedRel("out-in", "TYPE", "output-concept"),
        SeedRel("out-out", "TYPE", "output-concept"),
    ),
)

# Prompts: a prompt communication sent inside the window, and one outside, each about the ward.
_PROMPT_TOPIC: Final = SeedNode(
    "topic-c1",
    ("Concept",),
    {"key": f"Concept|{_MESSAGE_SYSTEM}|C1", "system": _MESSAGE_SYSTEM, "code": "C1"},
)
_PROMPT_TOPIC_GROUPED: Final = SeedNode(
    "topic-c9",
    ("Concept",),
    {"key": f"Concept|{_MESSAGE_SYSTEM}|C9", "system": _MESSAGE_SYSTEM, "code": "C9"},
)
_PROMPT_IN: Final = SeedNode(
    "prompt-in",
    ("Communication",),
    {"id": Marked("comm-in"), "sent": _INSIDE, "deliveryStatus": "sent"},
)
_PROMPT_OUT: Final = SeedNode(
    "prompt-out",
    ("Communication",),
    {"id": Marked("comm-out"), "sent": _OUTSIDE, "deliveryStatus": "sent"},
)
_PROMPT_SEED: Final = TenantSeed(
    nodes=(_WARD, _PROMPT_TOPIC, _PROMPT_TOPIC_GROUPED, _PROMPT_IN, _PROMPT_OUT),
    rels=(
        SeedRel("prompt-in", "TOPIC", "topic-c1"),
        SeedRel("prompt-out", "TOPIC", "topic-c1"),
        SeedRel("prompt-in", "ABOUT", "ward"),
        SeedRel("prompt-out", "ABOUT", "ward"),
    ),
)

_WINDOW: Final = {"start": _START, "end": _END}

WEEK_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-CASE-OPENED-BETWEEN": Scenario(
        "the cases opened inside a week, and none opened after it",
        seed=_CASE_SEED,
        params=dict(_WINDOW),
        new=("start", "end"),
        expect=Expect(rows=({"id": Marked("case-in")},)),
    ),
    "Q-CAP-BETWEEN": Scenario(
        "the capacity reports inside a week, and none after it",
        seed=_REPORT_SEED,
        params=dict(_WINDOW),
        new=("start", "end"),
        expect=Expect(rows=({"obs": Marked("obs-in")},)),
    ),
    "Q-BOOK-CONFIRMED-BETWEEN": Scenario(
        "the bookings confirmed inside a week, and none confirmed after it",
        seed=_BOOKING_SEED,
        params={**_WINDOW, "code": _CONFIRMED_AT, "system": _BOOKING_OUTPUT_SYSTEM},
        new=("start", "end"),
        expect=Expect(rows=({"id": Marked("bk-in")},)),
    ),
    "Q-COMM-PROMPTS-DUE-BETWEEN": Scenario(
        "the prompts sent inside a week, with the service each is about, and none after it",
        seed=_PROMPT_SEED,
        params={**_WINDOW, "messageSystem": _MESSAGE_SYSTEM, "messageIds": ["C1", "C9"]},
        new=("start", "end"),
        expect=Expect(rows=({"serviceId": "svc-1", "dueAt": _INSIDE},)),
    ),
}
