"""The replies the webhook could not take in, on Neo4j (DEC-1359).

One node per message sid: (:InboundReplyFailure {sid, tenantId, receivedAt, step, errorType, text,
phoneHash, status, resolvedAt, resolvedBy, resolution}). The key is (tenantId, sid) (migration
0203). The phone number is never stored, only its hash; the text is what the sender wrote, cut to
200 characters. Every statement names `tenantId: $tenant`.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from overwatch.adapters.outbound.graph_store.driver import ScopedTx, run_query
from overwatch.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from overwatch.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    TenantSeed,
)
from overwatch.domain.model.inbound_reply import (
    LIST_MAX,
    FailedStep,
    InboundReplyFailure,
    ReplyStatus,
    Resolution,
)

LABEL: Final = "InboundReplyFailure"

_RECEIVED: Final = datetime(2026, 11, 10, 10, 1, 8, tzinfo=UTC)
_HASH: Final = "a" * 64
_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "failure",
            (LABEL,),
            {
                "sid": "SM-1",
                "receivedAt": _RECEIVED,
                "step": "enqueue",
                "errorType": "ConnectionError",
                "text": Marked("Y"),
                "phoneHash": _HASH,
                "status": "open",
            },
        ),
    ),
)

_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-INREPLY-ADD": Scenario(
        "keep a reply that could not be taken in; a message that already has a record keeps it",
        seed=_SEED,
        params={
            "sid": "SM-1",
            "receivedAt": _RECEIVED + timedelta(minutes=1),
            "step": "find-sender",
            "errorType": "TimeoutError",
            "text": "N",
            "phoneHash": "c" * 64,
        },
        lookup=("sid",),
        new=("receivedAt", "step", "errorType", "text", "phoneHash"),
        expect=Expect(rows=({"made": False},)),
    ),
    "Q-INREPLY-OPEN": Scenario(
        "list the replies still waiting, newest first",
        seed=_SEED,
        params={"limit": LIST_MAX},
        new=("limit",),
        expect=Expect(rows=({"sid": "SM-1", "text": Marked("Y"), "step": "enqueue"},)),
    ),
    "Q-INREPLY-GET": Scenario(
        "one reply that could not be taken in, by its message id",
        seed=_SEED,
        params={"sid": "SM-1"},
        lookup=("sid",),
        expect=Expect(rows=({"sid": "SM-1", "text": Marked("Y"), "status": "open"},)),
    ),
    "Q-INREPLY-RESOLVE": Scenario(
        "close an open reply: handled by hand, or put on the queue again",
        seed=_SEED,
        params={
            "sid": "SM-1",
            "resolution": "handled",
            "by": "lead-1",
            "at": _RECEIVED,
        },
        lookup=("sid",),
        new=("resolution", "by", "at"),
        expect=Expect(
            rows=({"closed": 1},),
            after=(NodeSpec((LABEL,), {"sid": "SM-1", "status": "resolved"}),),
        ),
    ),
}

_PROPS = (
    "f.sid AS sid, f.receivedAt AS receivedAt, f.step AS step, f.errorType AS errorType, "
    "f.text AS text, f.phoneHash AS phoneHash, f.status AS status, f.resolvedAt AS resolvedAt, "
    "f.resolvedBy AS resolvedBy, f.resolution AS resolution"
)

_QUERIES: Final[tuple[NamedQuery, ...]] = (
    NamedQuery(
        id="Q-INREPLY-ADD",
        cypher=(
            "OPTIONAL MATCH (e:InboundReplyFailure {sid: $sid, tenantId: $tenant}) "
            "WITH e IS NULL AS made "
            "MERGE (f:InboundReplyFailure {sid: $sid, tenantId: $tenant}) "
            "ON CREATE SET f.receivedAt = $receivedAt, f.step = $step, "
            "f.errorType = $errorType, f.text = $text, f.phoneHash = $phoneHash, "
            "f.status = 'open' "
            "RETURN made"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-INREPLY-ADD"],
    ),
    NamedQuery(
        id="Q-INREPLY-OPEN",
        cypher=(
            "MATCH (f:InboundReplyFailure {tenantId: $tenant}) WHERE f.status = 'open' "
            f"RETURN {_PROPS} ORDER BY f.receivedAt DESC, f.sid LIMIT $limit"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-INREPLY-OPEN"],
    ),
    NamedQuery(
        id="Q-INREPLY-GET",
        cypher=(f"MATCH (f:InboundReplyFailure {{sid: $sid, tenantId: $tenant}}) RETURN {_PROPS}"),
        mode="read",
        scenario=_SCENARIOS["Q-INREPLY-GET"],
    ),
    NamedQuery(
        id="Q-INREPLY-RESOLVE",
        cypher=(
            "MATCH (f:InboundReplyFailure {sid: $sid, tenantId: $tenant}) "
            "WHERE f.status = 'open' "
            "SET f.status = 'resolved', f.resolution = $resolution, f.resolvedBy = $by, "
            "f.resolvedAt = $at "
            "RETURN count(f) AS closed"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-INREPLY-RESOLVE"],
    ),
)

for _query in _QUERIES:
    if _query.id not in REGISTRY.ids():
        REGISTRY.register(_query)


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    native: datetime = value.to_native() if hasattr(value, "to_native") else value
    return native.astimezone(UTC)


def _from_row(row: dict[str, Any]) -> InboundReplyFailure:
    received = _utc(row["receivedAt"])
    assert received is not None
    return InboundReplyFailure(
        sid=str(row["sid"]),
        received_at=received,
        step=FailedStep(row["step"]),
        error_type=str(row["errorType"]),
        text=str(row["text"]),
        phone_hash=str(row["phoneHash"]),
        status=ReplyStatus(row["status"]),
        resolved_at=_utc(row["resolvedAt"]),
        resolved_by=row["resolvedBy"],
        resolution=None if row["resolution"] is None else Resolution(row["resolution"]),
    )


class Neo4jInboundReplyFailures:
    """The failed replies of the bound tenant. Built per transaction (DEC-012)."""

    def __init__(self, tx: ScopedTx) -> None:
        self._tx = tx

    async def add(self, failure: InboundReplyFailure) -> bool:
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-INREPLY-ADD"),
            sid=failure.sid,
            receivedAt=failure.received_at.astimezone(UTC),
            step=failure.step.value,
            errorType=failure.error_type,
            text=failure.text,
            phoneHash=failure.phone_hash,
        )
        return bool(rows and rows[0]["made"])

    async def list_open(self) -> list[InboundReplyFailure]:
        rows = await run_query(self._tx, REGISTRY.get("Q-INREPLY-OPEN"), limit=LIST_MAX)
        return [_from_row(row) for row in rows]

    async def get(self, sid: str) -> InboundReplyFailure | None:
        rows = await run_query(self._tx, REGISTRY.get("Q-INREPLY-GET"), sid=sid)
        return _from_row(rows[0]) if rows else None

    async def mark_resolved(
        self, sid: str, *, resolution: Resolution, by: str, at: datetime
    ) -> bool:
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-INREPLY-RESOLVE"),
            sid=sid,
            resolution=resolution.value,
            by=by,
            at=at.astimezone(UTC),
        )
        return bool(rows and rows[0]["closed"])
