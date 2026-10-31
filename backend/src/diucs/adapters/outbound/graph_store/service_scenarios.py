"""The scenarios of the service, capacity, booking and case statements (TEN-010, DEC-142 item 5).

One scenario per statement of `service_repository.py`, `capacity_repository.py`,
`booking_repository.py` and `case_repository.py`. The generated two-tenant test
(`tests/integration/graph_store/test_tenant_isolation.py`) runs each one as tenant A and as tenant B
on a private container: both tenants get the same nodes with the same keys, so a statement that
forgets `tenantId: $tenant` finds the other tenant's node by key, and the text that should differ is
`Marked`, so a row that came from the wrong tenant looks different.

The seeds are written the way the resource store writes them: `Resource` roots carry an `id` and a
`key` of the form `<Type>/<id>`, an Observation focuses on its service, a Task owns its service and
has its output (a `Task_Output` typed by a `Concept` of the booking output system), a case is a
ServiceRequest and its Patient stub. This module is pure data: no Neo4j, no tenant, no Cypher.
"""

from datetime import UTC, datetime
from typing import Final

from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)
from diucs.domain.codes import code_system_url

_BOOKING_OUTPUT_SYSTEM: Final = code_system_url("booking-output-type")
_CONFIRMED_AT: Final = "confirmed-at"
_AT_0715: Final = datetime(2026, 10, 25, 7, 15, tzinfo=UTC)
_AT_0912: Final = datetime(2026, 10, 25, 9, 12, tzinfo=UTC)
_AT_1030: Final = datetime(2026, 10, 25, 10, 30, tzinfo=UTC)
_SINCE_0800: Final = datetime(2026, 10, 25, 8, 0, tzinfo=UTC)
_WARD_KEY: Final = "HealthcareService/svc-1"
_HUB_KEY: Final = "HealthcareService/svc-3"

# Services. svc-1 and svc-3 are active; svc-2 is not, so no statement lists it.
_WARD: Final = SeedNode(
    "ward",
    ("Resource", "HealthcareService"),
    {"id": "svc-1", "key": _WARD_KEY, "name": Marked("Ward"), "active": True},
)
_CLINIC: Final = SeedNode(
    "clinic",
    ("Resource", "HealthcareService"),
    {"id": "svc-2", "key": "HealthcareService/svc-2", "name": Marked("Clinic"), "active": False},
)
_HUB: Final = SeedNode(
    "hub",
    ("Resource", "HealthcareService"),
    {"id": "svc-3", "key": _HUB_KEY, "name": Marked("Hub"), "active": True},
)

# Capacity reports of svc-1: two numbers, then a confirmation. The latest is obs-3.
_OBS_0715: Final = SeedNode(
    "obs-0715",
    ("Resource", "Observation"),
    {
        "id": "obs-1",
        "key": "Observation/obs-1",
        "effectiveDateTime": _AT_0715,
        "ext_reportType": "number",
    },
)
_OBS_0912: Final = SeedNode(
    "obs-0912",
    ("Resource", "Observation"),
    {
        "id": "obs-2",
        "key": "Observation/obs-2",
        "effectiveDateTime": _AT_0912,
        "ext_reportType": "number",
    },
)
_OBS_1030: Final = SeedNode(
    "obs-1030",
    ("Resource", "Observation"),
    {
        "id": Marked("obs-3"),
        "key": "Observation/obs-3",
        "effectiveDateTime": _AT_1030,
        "ext_reportType": "confirmed",
    },
)
_CAPACITY_SEED: Final = TenantSeed(
    nodes=(_WARD, _CLINIC, _HUB, _OBS_0715, _OBS_0912, _OBS_1030),
    rels=(
        SeedRel("obs-0715", "FOCUS", "ward"),
        SeedRel("obs-0912", "FOCUS", "ward"),
        SeedRel("obs-1030", "FOCUS", "ward"),
    ),
)

# Bookings. bk-1 is requested for svc-1; bk-2 is confirmed for svc-1, with its confirmed-at output.
_BOOKING_REQUESTED: Final = SeedNode(
    "booking-requested",
    ("Resource", "Task"),
    {"id": "bk-1", "key": "Task/bk-1", "businessStatus": "requested", "reference": "4821"},
)
_BOOKING_CONFIRMED: Final = SeedNode(
    "booking-confirmed",
    ("Resource", "Task"),
    {"id": Marked("bk-2"), "key": "Task/bk-2", "businessStatus": "confirmed", "reference": "4822"},
)
_CONFIRMED_OUTPUT: Final = SeedNode(
    "output",
    ("Task_Output",),
    {"key": "Task/bk-2#output[0]", "valueDateTime": _AT_1030},
)
_CONFIRMED_CONCEPT: Final = SeedNode(
    "concept",
    ("Concept",),
    {
        "key": f"Concept|{_BOOKING_OUTPUT_SYSTEM}|{_CONFIRMED_AT}",
        "system": _BOOKING_OUTPUT_SYSTEM,
        "code": _CONFIRMED_AT,
    },
)
# The latest booking of each service (U22): the requested booking is the newer one, the confirmed
# booking the older, so the query must name bk-1 for svc-1.
_DATED_REQUESTED: Final = SeedNode(
    "booking-requested",
    ("Resource", "Task"),
    {
        "id": Marked("bk-1"),
        "key": "Task/bk-1",
        "businessStatus": "requested",
        "reference": "4821",
        "authoredOn": "2026-10-29T14:16:00Z",
    },
)
_DATED_CONFIRMED: Final = SeedNode(
    "booking-confirmed",
    ("Resource", "Task"),
    {
        "id": Marked("bk-2"),
        "key": "Task/bk-2",
        "businessStatus": "confirmed",
        "reference": "4822",
        "authoredOn": "2026-10-29T10:00:00Z",
    },
)
_LATEST_SEED: Final = TenantSeed(
    nodes=(_WARD, _HUB, _DATED_REQUESTED, _DATED_CONFIRMED),
    rels=(
        SeedRel("booking-requested", "OWNER", "ward"),
        SeedRel("booking-confirmed", "OWNER", "ward"),
    ),
)
# The bookings of a case (WB4). bk-c1 and bk-c2 focus on case-1, bk-c2 is the newer; bk-c3
# focuses on another case. Booking Tasks carry a reference.
_CASE_REQUEST: Final = SeedNode(
    "case-request",
    ("Resource", "ServiceRequest"),
    {"id": "case-1", "key": "ServiceRequest/case-1", "reference": "4801"},
)
_OTHER_REQUEST: Final = SeedNode(
    "other-request",
    ("Resource", "ServiceRequest"),
    {"id": "case-2", "key": "ServiceRequest/case-2", "reference": "4802"},
)
_CASE_OLDER: Final = SeedNode(
    "case-older",
    ("Resource", "Task"),
    {
        "id": Marked("bk-c1"),
        "key": "Task/bk-c1",
        "businessStatus": "requested",
        "reference": "4841",
        "authoredOn": "2026-10-29T14:16:00Z",
    },
)
_CASE_NEWER: Final = SeedNode(
    "case-newer",
    ("Resource", "Task"),
    {
        "id": Marked("bk-c2"),
        "key": "Task/bk-c2",
        "businessStatus": "declined",
        "reference": "4842",
        "authoredOn": "2026-10-29T14:30:00Z",
    },
)
_CASE_OTHER: Final = SeedNode(
    "case-other",
    ("Resource", "Task"),
    {
        "id": Marked("bk-c3"),
        "key": "Task/bk-c3",
        "businessStatus": "requested",
        "reference": "4843",
        "authoredOn": "2026-10-29T14:40:00Z",
    },
)
_CASE_BOOKINGS_SEED: Final = TenantSeed(
    nodes=(_CASE_REQUEST, _OTHER_REQUEST, _CASE_OLDER, _CASE_NEWER, _CASE_OTHER),
    rels=(
        SeedRel("case-older", "FOCUS", "case-request"),
        SeedRel("case-newer", "FOCUS", "case-request"),
        SeedRel("case-other", "FOCUS", "other-request"),
    ),
)

# The withdrawals and not-reached reports nobody has acknowledged (WB4). bk-w1 and bk-n1 are open
# (bk-n1 the newer), bk-w2 is withdrawn and acknowledged, bk-r1 is only requested.
_ACKNOWLEDGED_AT: Final = "acknowledged-at"
_ALERT_WITHDRAWN: Final = SeedNode(
    "alert-withdrawn",
    ("Resource", "Task"),
    {
        "id": Marked("bk-w1"),
        "key": "Task/bk-w1",
        "businessStatus": "withdrawn",
        "reference": "4851",
        "authoredOn": "2026-10-29T14:16:00Z",
    },
)
_ALERT_ACKNOWLEDGED: Final = SeedNode(
    "alert-acknowledged",
    ("Resource", "Task"),
    {
        "id": Marked("bk-w2"),
        "key": "Task/bk-w2",
        "businessStatus": "withdrawn",
        "reference": "4852",
        "authoredOn": "2026-10-29T14:20:00Z",
    },
)
_ALERT_NOT_REACHED: Final = SeedNode(
    "alert-not-reached",
    ("Resource", "Task"),
    {
        "id": Marked("bk-n1"),
        "key": "Task/bk-n1",
        "businessStatus": "not-reached",
        "reference": "4853",
        "authoredOn": "2026-10-29T14:30:00Z",
    },
)
_ALERT_REQUESTED: Final = SeedNode(
    "alert-requested",
    ("Resource", "Task"),
    {
        "id": Marked("bk-r1"),
        "key": "Task/bk-r1",
        "businessStatus": "requested",
        "reference": "4854",
        "authoredOn": "2026-10-29T14:40:00Z",
    },
)
_ALERT_ACK_OUTPUT: Final = SeedNode(
    "alert-ack-output",
    ("Task_Output",),
    {"key": "Task/bk-w2#output[0]", "valueDateTime": _AT_1030},
)
_ALERT_ACK_CONCEPT: Final = SeedNode(
    "alert-ack-concept",
    ("Concept",),
    {
        "key": f"Concept|{_BOOKING_OUTPUT_SYSTEM}|{_ACKNOWLEDGED_AT}",
        "system": _BOOKING_OUTPUT_SYSTEM,
        "code": _ACKNOWLEDGED_AT,
    },
)
_ALERTS_SEED: Final = TenantSeed(
    nodes=(
        _ALERT_WITHDRAWN,
        _ALERT_ACKNOWLEDGED,
        _ALERT_NOT_REACHED,
        _ALERT_REQUESTED,
        _ALERT_ACK_OUTPUT,
        _ALERT_ACK_CONCEPT,
    ),
    rels=(
        SeedRel("alert-acknowledged", "HAS_OUTPUT", "alert-ack-output"),
        SeedRel("alert-ack-output", "TYPE", "alert-ack-concept"),
    ),
)
_BOOKING_SEED: Final = TenantSeed(
    nodes=(
        _WARD,
        _HUB,
        _BOOKING_REQUESTED,
        _BOOKING_CONFIRMED,
        _CONFIRMED_OUTPUT,
        _CONFIRMED_CONCEPT,
    ),
    rels=(
        SeedRel("booking-requested", "OWNER", "ward"),
        SeedRel("booking-confirmed", "OWNER", "ward"),
        SeedRel("booking-confirmed", "HAS_OUTPUT", "output"),
        SeedRel("output", "TYPE", "concept"),
    ),
)

# A case: a ServiceRequest with its reference, and the Patient stub with a postcode.
_REQUEST: Final = SeedNode(
    "request",
    ("Resource", "ServiceRequest"),
    {
        "id": "case-1",
        "key": "ServiceRequest/case-1",
        "reference": "4821",
        "openReference": "4821",
    },
)
_PATIENT: Final = SeedNode(
    "patient",
    ("Resource", "Patient"),
    {"id": "pat-1", "key": "Patient/pat-1", "postalCode": Marked("Post")},
)
_CASE_SEED: Final = TenantSeed(nodes=(_REQUEST, _PATIENT))

# Positions (U12). svc-1 has a Location with coordinates; svc-2 has none, so it is left out.
_POSITION_LOCATION: Final = SeedNode(
    "location",
    ("Resource", "Location"),
    {
        "id": "loc-1",
        "key": "Location/loc-1",
        "name": Marked("Site"),
        "positionLatitude": 50.7,
        "positionLongitude": -2.4,
    },
)
_POSITION_SEED: Final = TenantSeed(
    nodes=(_WARD, _CLINIC, _POSITION_LOCATION),
    rels=(SeedRel("ward", "LOCATION", "location"),),
)

SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-SVC-POSITIONS": Scenario(
        "the site position of each of the tenant's services that has one",
        seed=_POSITION_SEED,
        params={"ids": ["svc-1", "svc-2"]},
        expect=Expect(rows=({"id": "svc-1", "name": Marked("Ward"), "lat": 50.7, "lon": -2.4},)),
    ),
    "Q-SVC-LIST-ACTIVE": Scenario(
        "list the tenant's active services by name",
        seed=_CAPACITY_SEED,
        expect=Expect(rows=({"id": "svc-1"}, {"id": "svc-3"})),
    ),
    "Q-SVC-LAST-REPORT": Scenario(
        "the latest report time of each of the tenant's active services",
        seed=_CAPACITY_SEED,
        expect=Expect(rows=({"id": "svc-1", "last": _AT_1030}, {"id": "svc-3", "last": None})),
    ),
    "Q-CAP-LATEST": Scenario(
        "the latest report of one of the tenant's services",
        seed=_CAPACITY_SEED,
        params={"key": _WARD_KEY},
        lookup=("key",),
        expect=Expect(rows=({"obs": Marked("obs-3")},)),
    ),
    "Q-CAP-LATEST-FOR": Scenario(
        "the latest report of each of the tenant's services in a list",
        seed=_CAPACITY_SEED,
        params={"keys": [_WARD_KEY, _HUB_KEY]},
        expect=Expect(rows=({"service": "svc-1", "obs": Marked("obs-3")},)),
    ),
    "Q-CAP-SINCE": Scenario(
        "the reports of one service since a time, earliest first",
        seed=_CAPACITY_SEED,
        params={"key": _WARD_KEY, "since": _SINCE_0800},
        lookup=("key",),
        new=("since",),
        expect=Expect(rows=({"obs": "obs-2"}, {"obs": Marked("obs-3")})),
    ),
    "Q-CAP-LOCK-SERVICE": Scenario(
        "lock one of the tenant's services for the rest of the transaction",
        seed=_CAPACITY_SEED,
        params={"key": _WARD_KEY},
        lookup=("key",),
        expect=Expect(rows=({"locked": 1},)),
    ),
    "Q-CAP-LATEST-CONFIRMED-AT": Scenario(
        "the time of the latest confirmation of one of the tenant's services",
        seed=_CAPACITY_SEED,
        params={"key": _WARD_KEY},
        lookup=("key",),
        expect=Expect(rows=({"obs": Marked("obs-3"), "at": _AT_1030},)),
    ),
    "Q-CAP-TRAILING-CONFIRMS": Scenario(
        "the confirmations that trail the reports of one of the tenant's services",
        seed=_CAPACITY_SEED,
        params={"key": _WARD_KEY},
        lookup=("key",),
        expect=Expect(rows=({"trailing": 1},)),
    ),
    "Q-BOOK-PENDING": Scenario(
        "count the requested bookings of one of the tenant's services",
        seed=_BOOKING_SEED,
        params={"id": "svc-1"},
        lookup=("id",),
        expect=Expect(rows=({"pending": 1},)),
    ),
    "Q-BOOK-OPEN-FOR": Scenario(
        "the requested bookings of a list of the tenant's services",
        seed=_BOOKING_SEED,
        params={"ids": ["svc-1"]},
        expect=Expect(rows=({"serviceId": "svc-1", "id": "bk-1"},)),
    ),
    "Q-BOOK-LATEST-FOR": Scenario(
        "the most recent booking of each of a list of the tenant's services",
        seed=_LATEST_SEED,
        params={"ids": ["svc-1"]},
        expect=Expect(rows=({"serviceId": "svc-1", "id": Marked("bk-1")},)),
    ),
    "Q-BOOK-CONFIRMED-SINCE": Scenario(
        "the confirmed bookings of one of the tenant's services",
        seed=_BOOKING_SEED,
        params={"id": "svc-1"},
        lookup=("id",),
        expect=Expect(rows=({"id": Marked("bk-2")},)),
    ),
    "Q-BOOK-CONFIRMED-FOR": Scenario(
        "the confirmed-at outputs of the confirmed bookings of a list of services",
        seed=_BOOKING_SEED,
        params={"ids": ["svc-1"], "code": _CONFIRMED_AT, "system": _BOOKING_OUTPUT_SYSTEM},
        expect=Expect(rows=({"serviceId": "svc-1", "confirmedAt": _AT_1030},)),
    ),
    "Q-BOOK-BY-REF": Scenario(
        "the booking of the tenant that holds a reference",
        seed=_BOOKING_SEED,
        params={"reference": "4822"},
        lookup=("reference",),
        expect=Expect(rows=({"id": Marked("bk-2")},)),
    ),
    "Q-BOOK-FOR-CASE": Scenario(
        "the bookings of one of the tenant's cases, newest first",
        seed=_CASE_BOOKINGS_SEED,
        params={"id": "case-1"},
        lookup=("id",),
        expect=Expect(rows=({"id": Marked("bk-c2")}, {"id": Marked("bk-c1")})),
    ),
    "Q-BOOK-UNACKNOWLEDGED": Scenario(
        "the tenant's withdrawn or not-reached bookings that no advisor has acknowledged",
        seed=_ALERTS_SEED,
        params={"code": _ACKNOWLEDGED_AT, "system": _BOOKING_OUTPUT_SYSTEM},
        expect=Expect(rows=({"id": Marked("bk-n1")}, {"id": Marked("bk-w1")})),
    ),
    "Q-BOOK-SET-PROPS": Scenario(
        "set the status and the reference of one of the tenant's bookings",
        seed=_BOOKING_SEED,
        params={"key": "Task/bk-1", "businessStatus": "declined", "reference": "4830"},
        lookup=("key",),
        new=("businessStatus", "reference"),
        expect=Expect(
            rows=({"set": 1},),
            after=(
                NodeSpec(
                    ("Task",),
                    {"id": "bk-1", "businessStatus": "declined", "reference": "4830"},
                ),
            ),
        ),
    ),
    "Q-CASE-BY-REF": Scenario(
        "the case of the tenant that holds a reference",
        seed=_CASE_SEED,
        params={"reference": "4821"},
        lookup=("reference",),
        expect=Expect(rows=({"id": "case-1"},)),
    ),
    "Q-CASE-SET-POSTCODE": Scenario(
        "set the postcode on one of the tenant's patient stubs",
        seed=_CASE_SEED,
        params={"key": "Patient/pat-1", "postalCode": "DT4 8XX"},
        lookup=("key",),
        new=("postalCode",),
        expect=Expect(
            rows=({"set": 1},),
            after=(NodeSpec(("Patient",), {"id": "pat-1", "postalCode": "DT4 8XX"}),),
        ),
    ),
    "Q-CASE-READ-POSTCODE": Scenario(
        "read the postcode of one of the tenant's patient stubs",
        seed=_CASE_SEED,
        params={"key": "Patient/pat-1"},
        lookup=("key",),
        expect=Expect(rows=({"postalCode": Marked("Post")},)),
    ),
    "Q-CASE-SET-REFERENCE": Scenario(
        "set the reference and the open reference of one of the tenant's requests",
        seed=_CASE_SEED,
        params={"key": "ServiceRequest/case-1", "reference": "4822", "openReference": "4822"},
        lookup=("key",),
        new=("reference", "openReference"),
        expect=Expect(
            rows=({"set": 1},),
            after=(
                NodeSpec(
                    ("ServiceRequest",),
                    {"id": "case-1", "reference": "4822", "openReference": "4822"},
                ),
            ),
        ),
    ),
}
