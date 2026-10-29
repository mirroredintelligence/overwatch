"""Neo4j store for support access (O06, docs/spec/fhir-data-model.md "Platform nodes").

Layout (every node carries tenantId, and every statement writes `tenantId: $tenant` on each node it
matches, merges or creates):

    (:UiSession {id, tenantId, deviceType, appMode, release, startedAt})
    (:UiSession)-[:SHARED_VIA]->(:SupportCode {codeHash, tenantId, createdAt, expiresAt, stoppedAt})
    (:SupportCode)-[:SHARED_BY]->(:Practitioner)
    (:SupportAccess {id, tenantId, reason, openedAt, expiresAt})-[:OPENED]->(:UiSession)
    (:SupportAccess)-[:OPENED_BY]->(:Practitioner)

A UiSession has no link to a person. The only link is the SupportCode, which the person creates, and
only its keyed hash is stored. Times are written in UTC and read back in UTC. A statement that
cannot
find the tenant's node matches nothing, so another tenant's session or code is not found, stopped or
read (DEC-130, DEC-132).

Uniqueness is composite (tenantId plus the key). The constraints are migrations 0045 (the session
id) and 0046 (the code hash), in migrations_support.py. add_code checks before it writes, and a
racing second write that the constraint refuses is raised as Conflict too.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

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
from diucs.application.ports.outbound.support import SupportAccessRecord, SupportCodeRecord
from diucs.domain.errors import Conflict

_NOW: Final = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
_LATER: Final = _NOW + timedelta(hours=4)
_END: Final = _NOW + timedelta(hours=1)

# Scenarios (DEC-142 item 5): the same plain ids are held by both tenants, and each tenant's own
# values differ (`Marked`), so a row read from the other tenant shows its marker. Lookups use the
# plain ids, so they collide across the tenants.
_SESSION_SEED: Final = TenantSeed(
    nodes=(
        SeedNode("session", ("UiSession",), {"id": "ui-1", "deviceType": Marked("device")}),
        SeedNode("prac", ("Practitioner",), {"id": "p-1", "active": True}),
        SeedNode(
            "code",
            ("SupportCode",),
            {
                "codeHash": Marked("hash"),
                "createdAt": _NOW,
                "expiresAt": _LATER,
                "stoppedAt": None,
            },
        ),
    ),
    rels=(
        SeedRel("session", "SHARED_VIA", "code"),
        SeedRel("code", "SHARED_BY", "prac"),
    ),
)
_ACCESS_SEED: Final = TenantSeed(
    nodes=(
        SeedNode("session", ("UiSession",), {"id": "ui-1", "deviceType": Marked("device")}),
        SeedNode("prac", ("Practitioner",), {"id": "p-1", "active": True}),
        SeedNode(
            "access",
            ("SupportAccess",),
            {"id": Marked("acc"), "reason": "ticket", "openedAt": _NOW, "expiresAt": _END},
        ),
    ),
    rels=(
        SeedRel("access", "OPENED", "session"),
        SeedRel("access", "OPENED_BY", "prac"),
    ),
)

_ENSURE: Final = Scenario(
    "create the tenant's session once, and a second session beside it",
    seed=_SESSION_SEED,
    params={
        "id": "ui-2",
        "deviceType": "tablet",
        "appMode": "browser",
        "release": "2026.10.29",
        "startedAt": _NOW,
    },
    new=("id", "deviceType", "appMode", "release"),
    expect=Expect(
        rows=({"n": 1},),
        # `nodes` is the net change: the seed holds one session, so a second is +1.
        nodes={"UiSession": 1},
        after=(NodeSpec(("UiSession",), {"id": "ui-2", "deviceType": "tablet"}),),
    ),
)
_EXISTS: Final = Scenario(
    "find the tenant's session by its id",
    seed=_SESSION_SEED,
    params={"id": "ui-1"},
    lookup=("id",),
    expect=Expect(rows=({"n": 1},)),
)
_SHARED_BY: Final = Scenario(
    "find the code this practitioner made for the tenant's session",
    seed=_SESSION_SEED,
    params={"sessionId": "ui-1", "practitionerId": "p-1"},
    lookup=("sessionId", "practitionerId"),
    expect=Expect(rows=({"n": 1},)),
)
_CODE_ADD: Final = Scenario(
    "store a code for the tenant's session and practitioner, beside its own",
    seed=_SESSION_SEED,
    params={
        "sessionId": "ui-1",
        "practitionerId": "p-1",
        "codeHash": "hash-new",
        "createdAt": _NOW,
        "expiresAt": _LATER,
    },
    lookup=("sessionId", "practitionerId"),
    new=("codeHash",),
    expect=Expect(
        rows=({"written": 1},),
        # Net change: one new code, joined to the session and to the practitioner.
        nodes={"SupportCode": 1},
        rels={"SHARED_VIA": 1, "SHARED_BY": 1},
        after=(NodeSpec(("SupportCode",), {"codeHash": "hash-new"}),),
    ),
)
# The code's hash is the same text in both tenants (it is the lookup), and the session it links to
# differs, so a row read from the other tenant shows the other tenant's session.
_CODE_SEED: Final = TenantSeed(
    nodes=(
        SeedNode("session", ("UiSession",), {"id": Marked("ui")}),
        SeedNode("prac", ("Practitioner",), {"id": "p-1", "active": True}),
        SeedNode(
            "code",
            ("SupportCode",),
            {"codeHash": "hash-1", "createdAt": _NOW, "expiresAt": _LATER, "stoppedAt": None},
        ),
    ),
    rels=(
        SeedRel("session", "SHARED_VIA", "code"),
        SeedRel("code", "SHARED_BY", "prac"),
    ),
)
_CODE_GET: Final = Scenario(
    "read the code with this hash, and the session and practitioner it links to",
    seed=_CODE_SEED,
    params={"codeHash": "hash-1"},
    lookup=("codeHash",),
    expect=Expect(rows=({"sessionId": Marked("ui"), "practitionerId": "p-1"},)),
)
_CODES_STOP: Final = Scenario(
    "stop the tenant's live codes for the session at once",
    seed=_SESSION_SEED,
    params={"sessionId": "ui-1", "practitionerId": "p-1", "at": _NOW},
    lookup=("sessionId", "practitionerId"),
    expect=Expect(
        rows=({"n": 1},),
        after=(NodeSpec(("SupportCode",), {"codeHash": Marked("hash"), "stoppedAt": _NOW}),),
    ),
)
_ACCESSES_END: Final = Scenario(
    "end the tenant's opens in progress for the session",
    seed=_ACCESS_SEED,
    params={"sessionId": "ui-1", "at": _NOW},
    lookup=("sessionId",),
    expect=Expect(
        rows=({"n": 1},),
        after=(NodeSpec(("SupportAccess",), {"id": Marked("acc"), "expiresAt": _NOW}),),
    ),
)
_ACCESS_ADD: Final = Scenario(
    "record a new open of the tenant's session by the tenant's practitioner",
    seed=_SESSION_SEED,
    params={
        "id": "acc-new",
        "sessionId": "ui-1",
        "practitionerId": "p-1",
        "reason": "code",
        "openedAt": _NOW,
        "expiresAt": _END,
    },
    lookup=("sessionId", "practitionerId"),
    new=("id", "reason"),
    expect=Expect(
        rows=({"written": 1},),
        # Net change: one new open, joined to the session and to the practitioner.
        nodes={"SupportAccess": 1},
        rels={"OPENED": 1, "OPENED_BY": 1},
        after=(NodeSpec(("SupportAccess",), {"id": "acc-new", "reason": "code"}),),
    ),
)
_ACCESS_LIST: Final = Scenario(
    "list the tenant's opens of the session, with the practitioner who opened each",
    seed=_ACCESS_SEED,
    params={"sessionId": "ui-1"},
    lookup=("sessionId",),
    expect=Expect(rows=({"id": Marked("acc"), "reason": "ticket"},)),
)

_QUERIES: Final[dict[str, tuple[str, Literal["read", "write"], Scenario]]] = {
    "Q-SUPPORT-SESSION-ENSURE": (
        "MERGE (s:UiSession {id: $id, tenantId: $tenant}) "
        "ON CREATE SET s.deviceType = $deviceType, s.appMode = $appMode, "
        "s.release = $release, s.startedAt = $startedAt "
        "RETURN count(s) AS n",
        "write",
        _ENSURE,
    ),
    "Q-SUPPORT-SESSION-EXISTS": (
        "MATCH (s:UiSession {id: $id, tenantId: $tenant}) RETURN count(s) AS n",
        "read",
        _EXISTS,
    ),
    "Q-SUPPORT-SESSION-SHARED-BY": (
        "MATCH (s:UiSession {id: $sessionId, tenantId: $tenant})"
        "-[:SHARED_VIA]->(c:SupportCode {tenantId: $tenant})"
        "-[:SHARED_BY]->(p:Practitioner {id: $practitionerId, tenantId: $tenant}) "
        "RETURN count(c) AS n",
        "read",
        _SHARED_BY,
    ),
    "Q-SUPPORT-CODE-ADD": (
        "MATCH (s:UiSession {id: $sessionId, tenantId: $tenant}) "
        "MATCH (p:Practitioner {id: $practitionerId, tenantId: $tenant}) "
        "CREATE (c:SupportCode {codeHash: $codeHash, tenantId: $tenant, createdAt: $createdAt, "
        "expiresAt: $expiresAt, stoppedAt: null}) "
        "CREATE (s)-[:SHARED_VIA]->(c) "
        "CREATE (c)-[:SHARED_BY]->(p) "
        "RETURN count(c) AS written",
        "write",
        _CODE_ADD,
    ),
    "Q-SUPPORT-CODE-GET": (
        "MATCH (c:SupportCode {codeHash: $codeHash, tenantId: $tenant}) "
        "OPTIONAL MATCH (s:UiSession {tenantId: $tenant})-[:SHARED_VIA]->(c) "
        "OPTIONAL MATCH (c)-[:SHARED_BY]->(p:Practitioner {tenantId: $tenant}) "
        "RETURN c.createdAt AS createdAt, c.expiresAt AS expiresAt, c.stoppedAt AS stoppedAt, "
        "s.id AS sessionId, p.id AS practitionerId",
        "read",
        _CODE_GET,
    ),
    "Q-SUPPORT-CODES-STOP": (
        "MATCH (s:UiSession {id: $sessionId, tenantId: $tenant})"
        "-[:SHARED_VIA]->(c:SupportCode {tenantId: $tenant})"
        "-[:SHARED_BY]->(p:Practitioner {id: $practitionerId, tenantId: $tenant}) "
        "WHERE c.expiresAt > $at "
        "SET c.expiresAt = $at, c.stoppedAt = $at "
        "RETURN count(c) AS n",
        "write",
        _CODES_STOP,
    ),
    "Q-SUPPORT-ACCESSES-END": (
        "MATCH (a:SupportAccess {tenantId: $tenant})"
        "-[:OPENED]->(s:UiSession {id: $sessionId, tenantId: $tenant}) "
        "WHERE a.expiresAt > $at "
        "SET a.expiresAt = $at "
        "RETURN count(a) AS n",
        "write",
        _ACCESSES_END,
    ),
    "Q-SUPPORT-ACCESS-ADD": (
        "MATCH (s:UiSession {id: $sessionId, tenantId: $tenant}) "
        "MATCH (p:Practitioner {id: $practitionerId, tenantId: $tenant}) "
        "CREATE (a:SupportAccess {id: $id, tenantId: $tenant, reason: $reason, "
        "openedAt: $openedAt, expiresAt: $expiresAt}) "
        "CREATE (a)-[:OPENED_BY]->(p) "
        "CREATE (a)-[:OPENED]->(s) "
        "RETURN count(a) AS written",
        "write",
        _ACCESS_ADD,
    ),
    "Q-SUPPORT-ACCESS-LIST": (
        "MATCH (a:SupportAccess {tenantId: $tenant})"
        "-[:OPENED]->(s:UiSession {id: $sessionId, tenantId: $tenant}) "
        "OPTIONAL MATCH (a)-[:OPENED_BY]->(p:Practitioner {tenantId: $tenant}) "
        "RETURN a.id AS id, a.reason AS reason, a.openedAt AS openedAt, "
        "a.expiresAt AS expiresAt, p.id AS practitionerId "
        "ORDER BY a.openedAt",
        "read",
        _ACCESS_LIST,
    ),
}

for _query_id, (_cypher, _mode, _scenario) in _QUERIES.items():
    REGISTRY.register(NamedQuery(id=_query_id, cypher=_cypher, mode=_mode, scenario=_scenario))


def _utc(value: Any) -> datetime:
    native: datetime = value.to_native()
    return native.astimezone(UTC)


def _optional_utc(value: Any) -> datetime | None:
    return None if value is None else _utc(value)


class Neo4jSupportRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def ensure_session(
        self,
        session_id: str,
        device_type: str,
        app_mode: str,
        release: str,
        started_at: datetime,
    ) -> None:
        await self._run(
            "Q-SUPPORT-SESSION-ENSURE",
            id=session_id,
            deviceType=device_type,
            appMode=app_mode,
            release=release,
            startedAt=started_at.astimezone(UTC),
        )

    async def session_exists(self, session_id: str) -> bool:
        rows = await self._run("Q-SUPPORT-SESSION-EXISTS", id=session_id)
        return int(rows[0]["n"]) == 1

    async def session_shared_by(self, session_id: str, practitioner_id: str) -> bool:
        rows = await self._run(
            "Q-SUPPORT-SESSION-SHARED-BY", sessionId=session_id, practitionerId=practitioner_id
        )
        return int(rows[0]["n"]) > 0

    async def add_code(self, record: SupportCodeRecord) -> bool:
        """Store the hash and its two links. A hash already held in this tenant is Conflict, raised
        before the write. False when the session or the practitioner is not in this tenant."""
        if await self.code_by_hash(record.code_hash) is not None:
            raise Conflict("support code already exists")
        try:
            rows = await self._run(
                "Q-SUPPORT-CODE-ADD",
                sessionId=record.session_id,
                practitionerId=record.practitioner_id,
                codeHash=record.code_hash,
                createdAt=record.created_at.astimezone(UTC),
                expiresAt=record.expires_at.astimezone(UTC),
            )
        except ConstraintError as error:
            raise Conflict("support code already exists") from error
        return int(rows[0]["written"]) == 1

    async def code_by_hash(self, code_hash: str) -> SupportCodeRecord | None:
        rows = await self._run("Q-SUPPORT-CODE-GET", codeHash=code_hash)
        if not rows:
            return None
        row = rows[0]
        if row["sessionId"] is None or row["practitionerId"] is None:
            return None
        return SupportCodeRecord(
            code_hash=code_hash,
            session_id=str(row["sessionId"]),
            practitioner_id=str(row["practitionerId"]),
            created_at=_utc(row["createdAt"]),
            expires_at=_utc(row["expiresAt"]),
            stopped_at=_optional_utc(row["stoppedAt"]),
        )

    async def stop_codes(self, session_id: str, practitioner_id: str, at: datetime) -> int:
        rows = await self._run(
            "Q-SUPPORT-CODES-STOP",
            sessionId=session_id,
            practitionerId=practitioner_id,
            at=at.astimezone(UTC),
        )
        return int(rows[0]["n"])

    async def end_accesses(self, session_id: str, at: datetime) -> int:
        rows = await self._run(
            "Q-SUPPORT-ACCESSES-END", sessionId=session_id, at=at.astimezone(UTC)
        )
        return int(rows[0]["n"])

    async def add_access(self, record: SupportAccessRecord) -> bool:
        rows = await self._run(
            "Q-SUPPORT-ACCESS-ADD",
            id=record.id,
            sessionId=record.session_id,
            practitionerId=record.practitioner_id,
            reason=record.reason,
            openedAt=record.opened_at.astimezone(UTC),
            expiresAt=record.expires_at.astimezone(UTC),
        )
        return int(rows[0]["written"]) == 1

    async def accesses_of(self, session_id: str) -> list[SupportAccessRecord]:
        rows = await self._run("Q-SUPPORT-ACCESS-LIST", sessionId=session_id)
        return [
            SupportAccessRecord(
                id=str(row["id"]),
                session_id=session_id,
                practitioner_id=str(row["practitionerId"]),
                reason=str(row["reason"]),
                opened_at=_utc(row["openedAt"]),
                expires_at=_utc(row["expiresAt"]),
            )
            for row in rows
        ]

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        query: NamedQuery = REGISTRY.get(query_id)
        return await run_query(self._tx, query, **params)
