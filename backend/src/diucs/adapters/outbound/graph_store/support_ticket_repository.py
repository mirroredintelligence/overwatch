"""Neo4j store for support tickets (R18, under O06).

(:SupportTicket {id, tenantId, state, requestedBy, approvedBy, requestedAt, approvedAt})
(:SupportTicket)-[:FOR_SESSION]->(:UiSession)

Every statement writes `tenantId: $tenant` on each node it matches, merges or creates (DEC-130,
DEC-132). Times are UTC instants. Uniqueness of a ticket id within the tenant is not yet a
constraint (no migration in this build); add_ checks before it writes, and the known-issues
entry records the gap.
"""

from datetime import UTC, datetime
from typing import Any, Final, Literal

from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)
from diucs.application.ports.outbound.support_tickets import SupportTicketRecord

_NOW: Final = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)

_SEED: Final = TenantSeed(
    nodes=(
        SeedNode("session", ("UiSession",), {"id": "ui-1", "deviceType": Marked("device")}),
        SeedNode(
            "ticket",
            ("SupportTicket",),
            {
                "id": "TKT-1",
                "state": "pending",
                "requestedBy": "p-seed-requester",
                "approvedBy": None,
                "requestedAt": _NOW,
                "approvedAt": None,
            },
        ),
    ),
    rels=(SeedRel("ticket", "FOR_SESSION", "session"),),
)

_ADD: Final = Scenario(
    "store a pending ticket for the tenant's session, beside the tenant's own ticket",
    seed=_SEED,
    params={
        "id": "TKT-2",
        "sessionId": "ui-1",
        "requestedBy": "p-support",
        "at": _NOW,
    },
    lookup=("sessionId",),
    new=("id", "requestedBy", "at"),
    expect=Expect(
        rows=({"written": 1},),
        nodes={"SupportTicket": 1},
        rels={"FOR_SESSION": 1},
        after=(NodeSpec(("SupportTicket",), {"id": "TKT-2", "state": "pending"}),),
    ),
)
_GET: Final = Scenario(
    "read the tenant's ticket and the session it is for",
    seed=_SEED,
    params={"id": "TKT-1"},
    lookup=("id",),
    expect=Expect(rows=({"state": "pending", "requestedBy": "p-seed-requester"},)),
)
_APPROVE: Final = Scenario(
    "approve the tenant's pending ticket",
    seed=_SEED,
    params={"id": "TKT-1", "approvedBy": "p-lead", "at": _NOW},
    lookup=("id",),
    new=("approvedBy", "at"),
    expect=Expect(
        rows=({"n": 1},),
        after=(NodeSpec(("SupportTicket",), {"id": "TKT-1", "state": "approved"}),),
    ),
)

_CYPHER: Final[dict[str, tuple[str, Literal["read", "write"], Scenario]]] = {
    "Q-TICKET-ADD": (
        "MATCH (s:UiSession {id: $sessionId, tenantId: $tenant}) "
        "CREATE (t:SupportTicket {id: $id, tenantId: $tenant, state: 'pending', "
        "requestedBy: $requestedBy, approvedBy: null, requestedAt: $at, approvedAt: null}) "
        "CREATE (t)-[:FOR_SESSION]->(s) "
        "RETURN count(t) AS written",
        "write",
        _ADD,
    ),
    "Q-TICKET-GET": (
        "MATCH (t:SupportTicket {id: $id, tenantId: $tenant}) "
        "OPTIONAL MATCH (t)-[:FOR_SESSION]->(s:UiSession {tenantId: $tenant}) "
        "RETURN t.state AS state, t.requestedBy AS requestedBy, t.approvedBy AS approvedBy, "
        "t.requestedAt AS requestedAt, t.approvedAt AS approvedAt, s.id AS sessionId",
        "read",
        _GET,
    ),
    "Q-TICKET-APPROVE": (
        "MATCH (t:SupportTicket {id: $id, tenantId: $tenant, state: 'pending'}) "
        "SET t.state = 'approved', t.approvedBy = $approvedBy, t.approvedAt = $at "
        "RETURN count(t) AS n",
        "write",
        _APPROVE,
    ),
}

for _query_id, (_text, _mode, _scenario) in _CYPHER.items():
    REGISTRY.register(NamedQuery(id=_query_id, cypher=_text, mode=_mode, scenario=_scenario))


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    native: datetime = value.to_native()
    return native.astimezone(UTC)


class Neo4jSupportTicketRepository:
    def __init__(self, tx: ScopedTx) -> None:
        self._tx = tx

    async def add(self, record: SupportTicketRecord) -> bool:
        rows = await self._run(
            "Q-TICKET-ADD",
            sessionId=record.session_id,
            id=record.id,
            requestedBy=record.requested_by,
            at=record.requested_at.astimezone(UTC),
        )
        return bool(rows) and int(rows[0]["written"]) == 1

    async def get(self, ticket_id: str) -> SupportTicketRecord | None:
        rows = await self._run("Q-TICKET-GET", id=ticket_id)
        if not rows or rows[0]["sessionId"] is None:
            return None
        row = rows[0]
        state: Literal["pending", "approved"] = (
            "approved" if row["state"] == "approved" else "pending"
        )
        return SupportTicketRecord(
            id=ticket_id,
            session_id=str(row["sessionId"]),
            requested_by=str(row["requestedBy"]),
            state=state,
            approved_by=None if row["approvedBy"] is None else str(row["approvedBy"]),
            requested_at=_utc(row["requestedAt"]) or _NOW,
            approved_at=_utc(row["approvedAt"]),
        )

    async def approve(self, ticket_id: str, approved_by: str, at: datetime) -> bool:
        rows = await self._run(
            "Q-TICKET-APPROVE", id=ticket_id, approvedBy=approved_by, at=at.astimezone(UTC)
        )
        return bool(rows) and int(rows[0]["n"]) == 1

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        query: NamedQuery = REGISTRY.get(query_id)
        return await run_query(self._tx, query, **params)
