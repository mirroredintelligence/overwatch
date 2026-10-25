"""Neo4j store for link tokens (P10, DEC-004, DEC-057). Only the token hash is stored.

Layout: (:LinkToken {id, tokenHash, phoneHash, purpose, aboutId, expiresAt, usedAt}). The id is
the token hash, so the node has no second identifier to keep in step. tokenHash is unique
(migration 0021). Times are written in UTC and read back in UTC.
"""

from datetime import UTC, datetime
from typing import Any, Literal

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.domain.errors import Conflict
from diucs.domain.rules.tokens import LinkTokenRecord, check_phone_hash

_QUERIES: dict[str, tuple[str, Literal["read", "write"]]] = {
    "Q-LINK-ADD": (
        "CREATE (t:LinkToken {id: $id, tokenHash: $tokenHash, phoneHash: $phoneHash, "
        "purpose: $purpose, aboutId: $aboutId, expiresAt: $expiresAt, usedAt: $usedAt}) "
        "RETURN count(t) AS written",
        "write",
    ),
    "Q-LINK-GET": (
        "MATCH (t:LinkToken {tokenHash: $tokenHash}) RETURN properties(t) AS props",
        "read",
    ),
    # Lock first, then read. A MATCH ... WHERE usedAt IS NULL ... SET reads usedAt before any
    # write lock is held, so concurrent callers all see it unset (measured: 8 of 8, then 16 of 16,
    # won). Setting a property that does not exist (usedAt) to null is a no-op that takes no lock,
    # so the lock is taken on tokenHash, which always exists, and the WHERE then reads usedAt.
    "Q-LINK-MARK-USED": (
        "MATCH (t:LinkToken {tokenHash: $tokenHash}) "
        "SET t.tokenHash = t.tokenHash "
        "WITH t WHERE t.usedAt IS NULL "
        "SET t.usedAt = $at, t.burnKey = $key RETURN count(t) AS n",
        "write",
    ),
    "Q-LINK-BURN-KEY": (
        "MATCH (t:LinkToken {tokenHash: $tokenHash}) RETURN t.burnKey AS key",
        "read",
    ),
}

for _query_id, (_cypher, _mode) in _QUERIES.items():
    REGISTRY.register(NamedQuery(id=_query_id, cypher=_cypher, mode=_mode))


def _utc(value: Any) -> datetime:
    native: datetime = value.to_native()
    return native.astimezone(UTC)


def _from_props(props: dict[str, Any]) -> LinkTokenRecord:
    used = props.get("usedAt")
    return LinkTokenRecord(
        token_hash=str(props["tokenHash"]),
        purpose=str(props["purpose"]),
        about_id=str(props["aboutId"]),
        phone_hash=props.get("phoneHash"),
        expires_at=_utc(props["expiresAt"]),
        used_at=_utc(used) if used is not None else None,
    )


class Neo4jLinkTokenRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def add(self, record: LinkTokenRecord) -> None:
        """Store one token hash. A phone field that is not a hash is refused, and a second add of
        the same hash is Conflict; both are decided before the write, so a refused add leaves no
        node (DEC-053 item 16, H-09)."""
        check_phone_hash(record.phone_hash)
        if await self.get_by_hash(record.token_hash) is not None:
            raise Conflict("link token already exists")
        try:
            await self._run(
                "Q-LINK-ADD",
                id=record.token_hash,
                tokenHash=record.token_hash,
                phoneHash=record.phone_hash,
                purpose=record.purpose,
                aboutId=record.about_id,
                expiresAt=record.expires_at.astimezone(UTC),
                usedAt=None if record.used_at is None else record.used_at.astimezone(UTC),
            )
        except ConstraintError as error:
            raise Conflict("link token already exists") from error

    async def get_by_hash(self, token_hash: str) -> LinkTokenRecord | None:
        rows = await self._run("Q-LINK-GET", tokenHash=token_hash)
        return _from_props(rows[0]["props"]) if rows else None

    async def mark_used(self, token_hash: str, at: datetime, key: str) -> bool:
        """Set usedAt and the burn key once. True only for the caller whose write set it."""
        rows = await self._run(
            "Q-LINK-MARK-USED", tokenHash=token_hash, at=at.astimezone(UTC), key=key
        )
        return int(rows[0]["n"]) == 1

    async def burn_key(self, token_hash: str) -> str | None:
        """The key of the attempt that burned the link, or None if it is unused or unknown."""
        rows = await self._run("Q-LINK-BURN-KEY", tokenHash=token_hash)
        return rows[0]["key"] if rows else None

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, query_id, **params)
