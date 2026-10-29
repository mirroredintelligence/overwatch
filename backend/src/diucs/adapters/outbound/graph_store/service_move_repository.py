"""Service moves on Neo4j (P20, U38).

A move is a platform node (:ServiceMove {moveId, serviceId, fromPractitionerId, toPhoneHash, until,
codeVerifiedAt, callbackAt, completedAt, cancelledAt, tenantId}) with -[:FOR]->(:HealthcareService)
and -[:FROM]->(:Practitioner). Only the phone hash is stored, never the number.

The move's id is the property moveId, under the composite constraint (tenantId, moveId) of migration
0041.

At most one open move per service: add takes the service's write lock first (lesson L73), then
reads the open moves, then writes, so two adds for one service serialise and the second is refused
with Conflict.
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
    SeedRel,
    TenantSeed,
)
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.service_move import ServiceMove

_UNTIL: Final = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)
_DONE: Final = datetime(2026, 10, 25, 18, 30, tzinfo=UTC)
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
_NODE_PRACTITIONER: Final = SeedNode(
    "p1",
    ("Resource", "Practitioner"),
    {"id": "p-1", "key": "Practitioner/p-1", "active": True},
)
_NODE_MOVE: Final = SeedNode(
    "move",
    ("ServiceMove",),
    {
        "moveId": "move-1",
        "serviceId": "svc-ucr-east",
        "fromPractitionerId": "p-1",
        "toPhoneHash": "h9",
        "until": _UNTIL,
    },
)
# A move's FROM relationship is not in the seed: the seeder writes relationship types as plain
# names, and FROM is a keyword. The statements that read the move use its properties.
_SERVICE_SEED: Final = TenantSeed(nodes=(_NODE_SERVICE, _NODE_PRACTITIONER))
_MOVE_SEED: Final = TenantSeed(
    nodes=(_NODE_SERVICE, _NODE_PRACTITIONER, _NODE_MOVE),
    rels=(SeedRel("move", "FOR", "svc"),),
)
_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-MOVE-LOCK-SERVICE": Scenario(
        "lock the service before a move is added for it",
        seed=_SERVICE_SEED,
        params={"serviceId": "svc-ucr-east"},
        lookup=("serviceId",),
        expect=Expect(rows=({"locked": 1},)),
    ),
    "Q-MOVE-OPEN-FOR": Scenario(
        "list the open moves of a service",
        seed=_MOVE_SEED,
        params={"serviceId": "svc-ucr-east"},
        lookup=("serviceId",),
        expect=Expect(rows=({"id": "move-1"},)),
    ),
    "Q-MOVE-GET": Scenario(
        "read a service move by its id",
        seed=_MOVE_SEED,
        params={"id": "move-1"},
        lookup=("id",),
        expect=Expect(rows=({"serviceId": "svc-ucr-east", "toPhoneHash": "h9"},)),
    ),
    "Q-MOVE-ADD": Scenario(
        "add a service move for a service and a practitioner",
        seed=_SERVICE_SEED,
        params={
            "id": "move-1",
            "serviceId": "svc-ucr-east",
            "fromPractitionerId": "p-1",
            "toPhoneHash": "h9",
            "until": _UNTIL,
            "codeVerifiedAt": None,
            "callbackAt": None,
            "completedAt": None,
            "cancelledAt": None,
        },
        lookup=("serviceId", "fromPractitionerId"),
        new=(
            "id",
            "toPhoneHash",
            "until",
            "codeVerifiedAt",
            "callbackAt",
            "completedAt",
            "cancelledAt",
        ),
        expect=Expect(
            rows=({"added": 1},),
            nodes={"ServiceMove": 1},
            rels={"FOR": 1, "FROM": 1},
        ),
    ),
    "Q-MOVE-SAVE": Scenario(
        "record the completion of a service move",
        seed=_MOVE_SEED,
        params={
            "id": "move-1",
            "until": _UNTIL,
            "codeVerifiedAt": None,
            "callbackAt": None,
            "completedAt": _DONE,
            "cancelledAt": None,
        },
        lookup=("id",),
        new=("until", "completedAt"),
        expect=Expect(
            rows=({"saved": 1},),
            after=(NodeSpec(("ServiceMove",), {"moveId": "move-1", "completedAt": _DONE}),),
        ),
    ),
}

_QUERIES: Final[tuple[NamedQuery, ...]] = (
    NamedQuery(
        id="Q-MOVE-LOCK-SERVICE",
        cypher=(
            "MATCH (s:HealthcareService {id: $serviceId, tenantId: $tenant}) "
            "SET s.id = s.id RETURN count(s) AS locked"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-MOVE-LOCK-SERVICE"],
    ),
    NamedQuery(
        id="Q-MOVE-OPEN-FOR",
        cypher=(
            "MATCH (m:ServiceMove {serviceId: $serviceId, tenantId: $tenant}) "
            "WHERE m.completedAt IS NULL AND m.cancelledAt IS NULL "
            "RETURN m.moveId AS id ORDER BY m.moveId"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-MOVE-OPEN-FOR"],
    ),
    NamedQuery(
        id="Q-MOVE-GET",
        cypher=(
            "MATCH (m:ServiceMove {moveId: $id, tenantId: $tenant}) "
            "RETURN m.moveId AS id, m.serviceId AS serviceId, "
            "m.fromPractitionerId AS fromPractitionerId, m.toPhoneHash AS toPhoneHash, "
            "m.until AS until, m.codeVerifiedAt AS codeVerifiedAt, "
            "m.callbackAt AS callbackAt, m.completedAt AS completedAt, "
            "m.cancelledAt AS cancelledAt"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-MOVE-GET"],
    ),
    NamedQuery(
        id="Q-MOVE-ADD",
        cypher=(
            "MATCH (s:HealthcareService {id: $serviceId, tenantId: $tenant}), "
            "(p:Practitioner {id: $fromPractitionerId, tenantId: $tenant}) "
            "CREATE (m:ServiceMove {moveId: $id, serviceId: $serviceId, "
            "fromPractitionerId: $fromPractitionerId, toPhoneHash: $toPhoneHash, "
            "until: $until, codeVerifiedAt: $codeVerifiedAt, callbackAt: $callbackAt, "
            "completedAt: $completedAt, cancelledAt: $cancelledAt, tenantId: $tenant})"
            "-[:FOR]->(s), (m)-[:`FROM`]->(p) "
            "RETURN count(m) AS added"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-MOVE-ADD"],
    ),
    NamedQuery(
        id="Q-MOVE-SAVE",
        cypher=(
            "MATCH (m:ServiceMove {moveId: $id, tenantId: $tenant}) "
            "SET m.until = $until, m.codeVerifiedAt = $codeVerifiedAt, "
            "m.callbackAt = $callbackAt, m.completedAt = $completedAt, "
            "m.cancelledAt = $cancelledAt "
            "RETURN count(m) AS saved"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-MOVE-SAVE"],
    ),
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


for _query in _QUERIES:
    _register(_query)


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    native: datetime = value.to_native() if hasattr(value, "to_native") else value
    return native.astimezone(UTC)


def _params(move: ServiceMove) -> dict[str, Any]:
    return {
        "id": move.id,
        "serviceId": move.service_id,
        "fromPractitionerId": move.from_practitioner_id,
        "toPhoneHash": move.to_phone_hash,
        "until": _utc(move.until),
        "codeVerifiedAt": _utc(move.code_verified_at),
        "callbackAt": _utc(move.callback_at),
        "completedAt": _utc(move.completed_at),
        "cancelledAt": _utc(move.cancelled_at),
    }


def _from_row(row: dict[str, Any]) -> ServiceMove:
    return ServiceMove(
        id=str(row["id"]),
        service_id=str(row["serviceId"]),
        from_practitioner_id=str(row["fromPractitionerId"]),
        to_phone_hash=str(row["toPhoneHash"]),
        until=_utc(row["until"]),
        code_verified_at=_utc(row["codeVerifiedAt"]),
        callback_at=_utc(row["callbackAt"]),
        completed_at=_utc(row["completedAt"]),
        cancelled_at=_utc(row["cancelledAt"]),
    )


class Neo4jServiceMoveRepository:
    """Service moves. Built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def add(self, move: ServiceMove) -> None:
        # The service's write lock first, then the check, then the write (lesson L73).
        await run_query(self._tx, REGISTRY.get("Q-MOVE-LOCK-SERVICE"), serviceId=move.service_id)
        open_rows = await run_query(
            self._tx, REGISTRY.get("Q-MOVE-OPEN-FOR"), serviceId=move.service_id
        )
        if open_rows:
            raise Conflict("this service already has an open move")
        if await self.get(move.id) is not None:
            raise Conflict("a service move with this id exists")
        rows = await run_query(self._tx, REGISTRY.get("Q-MOVE-ADD"), **_params(move))
        if not rows or rows[0]["added"] == 0:
            raise NotFound("service or practitioner")

    async def get(self, move_id: str) -> ServiceMove | None:
        rows = await run_query(self._tx, REGISTRY.get("Q-MOVE-GET"), id=move_id)
        return _from_row(rows[0]) if rows else None

    async def save(self, move: ServiceMove) -> None:
        current = await self.get(move.id)
        if current is None:
            raise NotFound("service move")
        unchanged = (
            current.service_id == move.service_id
            and current.from_practitioner_id == move.from_practitioner_id
            and current.to_phone_hash == move.to_phone_hash
        )
        if not unchanged:
            raise ValidationFailed(
                "service_move", "its service, practitioner and phone cannot change"
            )
        params = _params(move)
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-MOVE-SAVE"),
            id=move.id,
            until=params["until"],
            codeVerifiedAt=params["codeVerifiedAt"],
            callbackAt=params["callbackAt"],
            completedAt=params["completedAt"],
            cancelledAt=params["cancelledAt"],
        )
        if not rows or rows[0]["saved"] == 0:
            raise NotFound("service move")

    async def open_for_service(self, service_id: str) -> list[ServiceMove]:
        rows = await run_query(self._tx, REGISTRY.get("Q-MOVE-OPEN-FOR"), serviceId=service_id)
        found: list[ServiceMove] = []
        for row in rows:
            move = await self.get(str(row["id"]))
            if move is not None:
                found.append(move)
        return found
