"""The scenarios of the flag statements of `flag_repository.py` (TEN-012, DEC-142 item 5).

One scenario per statement. The generated two-tenant test runs each one as tenant A and as tenant B
on a private container (DEC-150, DEC-159): both tenants get the same service, report, report flag
and service flag, with the same ids and keys, so a statement that forgets `tenantId: $tenant` finds
the other tenant's node by key or id. The text that should differ between the tenants is `Marked`.

The seeds follow the stores: a report flag is a `ReportFlag` node with an `ON` link to its
Observation, which focuses on its service; a service flag is a `Basic` Resource labelled
`ServiceFlag`, whose `SUBJECT` is its service. The unflagged Basic of the label scenario is a
`Basic` with no flag label.

This module is pure data: no Neo4j, no tenant, no Cypher.
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

_AT_0912: Final = datetime(2026, 10, 25, 9, 12, tzinfo=UTC)
_AT_1030: Final = datetime(2026, 10, 25, 10, 30, tzinfo=UTC)
_AT_1100: Final = datetime(2026, 10, 25, 11, 0, tzinfo=UTC)
_SERVICE_FLAG_KEY: Final = "Basic/svc-1.suspended"
_UNFLAGGED_KEY: Final = "Basic/svc-1.criteria-overdue"

_SERVICE: Final = SeedNode(
    "service",
    ("Resource", "HealthcareService"),
    {"id": "svc-1", "key": "HealthcareService/svc-1", "name": Marked("Ward"), "active": True},
)
_REPORT: Final = SeedNode(
    "report",
    ("Resource", "Observation"),
    {
        "id": "obs-1",
        "key": "Observation/obs-1",
        "effectiveDateTime": _AT_0912,
        "ext_reportType": "number",
    },
)
_REPORT_FLAG: Final = SeedNode(
    "report-flag",
    ("ReportFlag",),
    {
        "id": "rf-1",
        "reason": "out-of-range-twice",
        "status": "open",
        "createdAt": _AT_1030,
        "serviceId": "svc-1",
    },
)
_SERVICE_FLAG: Final = SeedNode(
    "service-flag",
    ("Resource", "Basic", "ServiceFlag"),
    {
        "id": "svc-1.suspended",
        "key": _SERVICE_FLAG_KEY,
        "status": "active",
        "code": "suspended",
        "reason": Marked("Duty manager"),
        "actor": "prac-1",
        "at": "2026-10-25T10:30:00Z",
    },
)
_UNFLAGGED: Final = SeedNode(
    "unflagged",
    ("Resource", "Basic"),
    {
        "id": "svc-1.criteria-overdue",
        "key": _UNFLAGGED_KEY,
        "status": "inactive",
        "code": "criteria-overdue",
        "reason": Marked("Review due"),
        "actor": "prac-1",
        "at": "2026-10-25T11:00:00Z",
    },
)

_SEED: Final = TenantSeed(
    nodes=(_SERVICE, _REPORT, _REPORT_FLAG, _SERVICE_FLAG, _UNFLAGGED),
    rels=(
        SeedRel("report", "FOCUS", "service"),
        SeedRel("report-flag", "ON", "report"),
        SeedRel("service-flag", "SUBJECT", "service"),
        SeedRel("unflagged", "SUBJECT", "service"),
    ),
)

OBS_LOCK_SCENARIO: Final = Scenario(
    "lock the report that a flag is raised on",
    seed=_SEED,
    params={"key": "Observation/obs-1"},
    lookup=("key",),
    expect=Expect(rows=({"locked": 1},)),
)
OBS_SERVICE_SCENARIO: Final = Scenario(
    "read the service a report is about",
    seed=_SEED,
    params={"key": "Observation/obs-1"},
    lookup=("key",),
    expect=Expect(rows=({"serviceId": "svc-1"},)),
)
REPORT_EXISTS_SCENARIO: Final = Scenario(
    "count the report flags with an id",
    seed=_SEED,
    params={"id": "rf-1"},
    lookup=("id",),
    expect=Expect(rows=({"found": 1},)),
)
REPORT_ADD_SCENARIO: Final = Scenario(
    "raise a report flag on a report",
    seed=_SEED,
    params={
        "key": "Observation/obs-1",
        "props": {
            "id": "rf-2",
            "reason": "many-changes",
            "status": "open",
            "createdAt": _AT_1100,
            "serviceId": "svc-1",
        },
    },
    lookup=("key",),
    new=("props",),
    expect=Expect(
        rows=({"created": 1},),
        nodes={"ReportFlag": 1},
        rels={"ON": 1},
        after=(NodeSpec(("ReportFlag",), {"id": "rf-2", "reason": "many-changes"}),),
    ),
)
REPORT_LOCK_SCENARIO: Final = Scenario(
    "lock a report flag before it is resolved",
    seed=_SEED,
    params={"id": "rf-1"},
    lookup=("id",),
    expect=Expect(rows=({"locked": 1},)),
)
REPORT_GET_SCENARIO: Final = Scenario(
    "read a report flag and the report it is on",
    seed=_SEED,
    params={"id": "rf-1"},
    lookup=("id",),
    expect=Expect(
        rows=(
            {
                "props": {"reason": "out-of-range-twice", "status": "open", "serviceId": "svc-1"},
                "reportId": "obs-1",
            },
        )
    ),
)
REPORT_SAVE_SCENARIO: Final = Scenario(
    "resolve a report flag",
    seed=_SEED,
    params={
        "id": "rf-1",
        "status": "checked",
        "outcome": "confirmed",
        "resolvedAt": _AT_1100,
        # The statement sets resolvedBy, so the probe must pass it: a missing parameter is a
        # ClientError, which the generated test reports as a probe error.
        "resolvedBy": "role-1",
    },
    lookup=("id",),
    new=("status", "outcome", "resolvedAt", "resolvedBy"),
    expect=Expect(
        rows=({"saved": 1},),
        after=(
            NodeSpec(("ReportFlag",), {"id": "rf-1", "status": "checked", "resolvedBy": "role-1"}),
        ),
    ),
)
REPORT_OPEN_SCENARIO: Final = Scenario(
    "list the open report flags of a service",
    seed=_SEED,
    params={"status": "open", "serviceId": "svc-1"},
    lookup=("serviceId",),
    expect=Expect(
        rows=(
            {
                "props": {"id": "rf-1", "status": "open", "serviceId": "svc-1"},
                "reportId": "obs-1",
            },
        )
    ),
)
SERVICE_LOCK_SCENARIO: Final = Scenario(
    "lock a service before its flag is set",
    seed=_SEED,
    params={"serviceId": "svc-1"},
    lookup=("serviceId",),
    expect=Expect(rows=({"locked": 1},)),
)
BASIC_STATE_SCENARIO: Final = Scenario(
    "read whether a Basic is a service flag",
    seed=_SEED,
    params={"key": _SERVICE_FLAG_KEY},
    lookup=("key",),
    expect=Expect(rows=({"flagged": True},)),
)
LABEL_SCENARIO: Final = Scenario(
    "label an unflagged Basic as a service flag",
    seed=_SEED,
    params={"key": _UNFLAGGED_KEY},
    lookup=("key",),
    expect=Expect(
        rows=({"labelled": 1},),
        nodes={"ServiceFlag": 1},
        after=(NodeSpec(("ServiceFlag",), {"id": "svc-1.criteria-overdue"}),),
    ),
)
SERVICE_ACTIVE_SCENARIO: Final = Scenario(
    "list the active service flags of a service",
    seed=_SEED,
    params={"active": "active", "serviceId": "svc-1"},
    lookup=("serviceId",),
    expect=Expect(rows=({"key": _SERVICE_FLAG_KEY},)),
)
# The statement returns DISTINCT service ids, so two tenants holding one service id would collapse
# to one row and hide a leak: the service id differs between the tenants here.
_FLAGGED_SERVICE: Final = SeedNode(
    "service",
    ("Resource", "HealthcareService"),
    {"id": Marked("svc"), "key": "HealthcareService/svc-1", "name": Marked("Ward"), "active": True},
)
SERVICES_WITH_SCENARIO: Final = Scenario(
    "list the services that hold an active flag of a code",
    seed=TenantSeed(
        nodes=(_FLAGGED_SERVICE, _SERVICE_FLAG),
        rels=(SeedRel("service-flag", "SUBJECT", "service"),),
    ),
    params={"active": "active", "code": "suspended"},
    lookup=("code",),
    expect=Expect(rows=({"serviceId": Marked("svc")},)),
)

FLAG_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-FLAG-OBS-LOCK": OBS_LOCK_SCENARIO,
    "Q-FLAG-OBS-SERVICE": OBS_SERVICE_SCENARIO,
    "Q-FLAG-REPORT-EXISTS": REPORT_EXISTS_SCENARIO,
    "Q-FLAG-REPORT-ADD": REPORT_ADD_SCENARIO,
    "Q-FLAG-REPORT-LOCK": REPORT_LOCK_SCENARIO,
    "Q-FLAG-REPORT-GET": REPORT_GET_SCENARIO,
    "Q-FLAG-REPORT-SAVE": REPORT_SAVE_SCENARIO,
    "Q-FLAG-REPORT-OPEN": REPORT_OPEN_SCENARIO,
    "Q-FLAG-SERVICE-LOCK": SERVICE_LOCK_SCENARIO,
    "Q-FLAG-BASIC-STATE": BASIC_STATE_SCENARIO,
    "Q-FLAG-LABEL": LABEL_SCENARIO,
    "Q-FLAG-SERVICE-ACTIVE": SERVICE_ACTIVE_SCENARIO,
    "Q-FLAG-SERVICES-WITH": SERVICES_WITH_SCENARIO,
}
