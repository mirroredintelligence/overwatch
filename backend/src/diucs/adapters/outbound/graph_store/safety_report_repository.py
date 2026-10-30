"""Safety concerns and problem reports on Neo4j (U41).

A report is a Task with code `safety-concern` or `problem-report` (fhir-data-model.md, Safety
concern). It holds its requester, its category, its focus (a case or a service, when one was given),
its reference and the handle of its text in the protected store. It never holds the text.

The concern reference comes from a per-tenant counter node, (:SafetyCounter {tenantId, counterId}),
advanced by one statement in the caller's unit of work, so two concerns in two units get SC-0001 and
SC-0002. The counter's (tenantId, counterId) pair is unique (migration 0070).

The Task statements carry no FHIR relationships yet: the requester, the owner and the focus are
properties (a known issue of U41).
"""

from datetime import UTC, datetime
from typing import Any, Final

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    TenantSeed,
)
from diucs.domain.errors import Conflict
from diucs.domain.model.safety import SafetyReport
from diucs.domain.rules.safety_report import SAFETY_CONCERN_CODE, safety_reference

COUNTER_ID: Final = SAFETY_CONCERN_CODE
_CREATED: Final = datetime(2026, 10, 29, 14, 20, tzinfo=UTC)

# Scenarios (DEC-150). Both tenants hold the counter and the report `rep-1`: the keys are shared, so
# only the tenant stamp keeps the two apart.
_NODE_SERVICE: Final = SeedNode(
    "svc",
    ("Resource", "HealthcareService"),
    {
        "id": "svc-ucr-east",
        "key": "HealthcareService/svc-ucr-east",
        "active": True,
        "name": Marked("UCR East"),
    },
)
_NODE_COUNTER: Final = SeedNode(
    "counter",
    ("SafetyCounter",),
    {"counterId": COUNTER_ID, "value": 4, "label": Marked("concern")},
)
_NODE_REPORT: Final = SeedNode(
    "report",
    ("Task",),
    {
        "id": "rep-1",
        "code": "problem-report",
        "category": "screen-slow",
        "requesterId": Marked("prac-1"),
        "sessionShared": True,
    },
)
_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-SAFETY-NEXT-REF": Scenario(
        "advance the concern counter and return its new value",
        seed=TenantSeed(nodes=(_NODE_COUNTER,)),
        params={"counterId": COUNTER_ID},
        lookup=("counterId",),
        expect=Expect(
            rows=({"value": 5, "label": Marked("concern")},),
            after=(NodeSpec(("SafetyCounter",), {"counterId": COUNTER_ID, "value": 5}),),
        ),
    ),
    "Q-SAFETY-ADD": Scenario(
        "store a new safety concern or problem report as a Task",
        seed=TenantSeed(nodes=(_NODE_SERVICE,)),
        params={
            "id": "rep-new",
            "key": "Task/rep-new",
            "code": "safety-concern",
            "category": "wrong-status-on-board",
            "requesterId": "prac-1",
            "createdAt": _CREATED,
            "reference": "SC-0001",
            "focusId": None,
            "textHandle": "h-new",
            "ownerRoleId": "clinical-safety-officer",
            "sessionShared": None,
        },
        new=(
            "id",
            "key",
            "code",
            "category",
            "requesterId",
            "createdAt",
            "reference",
            "focusId",
            "textHandle",
            "ownerRoleId",
            "sessionShared",
        ),
        expect=Expect(rows=({"stored": 1},), nodes={"Task": 1}),
    ),
    "Q-SAFETY-GET": Scenario(
        "read a safety concern or problem report by its id in the bound tenant",
        seed=TenantSeed(nodes=(_NODE_REPORT,)),
        params={"id": "rep-1"},
        lookup=("id",),
        expect=Expect(
            rows=({"id": "rep-1", "requesterId": Marked("prac-1"), "sessionShared": True},),
        ),
    ),
}

_QUERIES: Final[tuple[NamedQuery, ...]] = (
    NamedQuery(
        id="Q-SAFETY-NEXT-REF",
        cypher=(
            "MERGE (c:SafetyCounter {tenantId: $tenant, counterId: $counterId}) "
            "ON CREATE SET c.value = 0 "
            "SET c.value = c.value + 1 "
            "RETURN c.value AS value, c.label AS label"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-SAFETY-NEXT-REF"],
    ),
    NamedQuery(
        id="Q-SAFETY-ADD",
        cypher=(
            "CREATE (t:Task {id: $id, key: $key, tenantId: $tenant, code: $code, "
            "category: $category, requesterId: $requesterId, createdAt: $createdAt, "
            "reference: $reference, focusId: $focusId, textHandle: $textHandle, "
            "ownerRoleId: $ownerRoleId, sessionShared: $sessionShared}) "
            "RETURN count(t) AS stored"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-SAFETY-ADD"],
    ),
    NamedQuery(
        id="Q-SAFETY-GET",
        cypher=(
            "MATCH (t:Task {id: $id, tenantId: $tenant}) "
            "WHERE t.code IN ['safety-concern', 'problem-report'] "
            "RETURN t.id AS id, t.code AS code, t.category AS category, "
            "t.requesterId AS requesterId, t.createdAt AS createdAt, t.reference AS reference, "
            "t.focusId AS focusId, t.textHandle AS textHandle, "
            "t.ownerRoleId AS ownerRoleId, t.sessionShared AS sessionShared"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-SAFETY-GET"],
    ),
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


for _query in _QUERIES:
    _register(_query)


def _utc(value: Any) -> datetime:
    """A stored instant as UTC; the driver returns its own datetime type, converted here."""
    native: datetime = value.to_native() if hasattr(value, "to_native") else value
    return native.astimezone(UTC)


class Neo4jSafetyReportRepository:
    """Safety reports on the unit of work's transaction (built per unit, DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def next_concern_reference(self) -> str:
        rows = await run_query(self._tx, REGISTRY.get("Q-SAFETY-NEXT-REF"), counterId=COUNTER_ID)
        return safety_reference(int(rows[0]["value"]))

    async def add(self, report: SafetyReport) -> None:
        if await self.get(report.id) is not None:
            raise Conflict("a safety report with this id is already stored")
        await run_query(
            self._tx,
            REGISTRY.get("Q-SAFETY-ADD"),
            id=report.id,
            key=f"Task/{report.id}",
            code=report.code,
            category=report.category,
            requesterId=report.requester_id,
            createdAt=report.created_at,
            reference=report.reference,
            focusId=report.focus_id,
            textHandle=report.text_handle,
            ownerRoleId=report.owner_role_id,
            sessionShared=report.session_shared,
        )

    async def get(self, report_id: str) -> SafetyReport | None:
        rows = await run_query(self._tx, REGISTRY.get("Q-SAFETY-GET"), id=report_id)
        if not rows:
            return None
        row = rows[0]
        return SafetyReport(
            id=str(row["id"]),
            code=str(row["code"]),
            requester_id=str(row["requesterId"]),
            category=str(row["category"]),
            created_at=_utc(row["createdAt"]),
            reference=None if row["reference"] is None else str(row["reference"]),
            focus_id=None if row["focusId"] is None else str(row["focusId"]),
            text_handle=None if row["textHandle"] is None else str(row["textHandle"]),
            owner_role_id=None if row["ownerRoleId"] is None else str(row["ownerRoleId"]),
            session_shared=row["sessionShared"],
        )
