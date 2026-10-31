"""The platform audit chain on Neo4j (TEN-075, TEN-084, DEC-528, DEC-529, audit F section 2.4).

A tenant's audit chain records what happened in that tenant and the tenant can read it. The
platform's chain records what the platform's own people did across tenants (an operator signing in,
a lifecycle step, every step of a support access), and the tenant cannot change it. It is the same
hash chain as a tenant's (`application/ports/outbound/audit.py`: each link is
`sha256(previous_hash + canonical entry)`), in the platform's own scope: one `PlatformAuditHead`
and the `PlatformAuditEntry` nodes after it. Neither carries a `tenantId`: the entry names the one
tenant it was for as data (`forTenant`), and the chain is the platform's.

The chain starts from a genesis of its own (`genesis_hash_for("platform")`, a scope id no tenant can
have), so a tenant's chain cannot be grafted onto it and a link hashed here verifies nowhere else.

Appends queue on the head, as a tenant's do (lesson L63): the first statement writes the head (and
creates it on the first use) and reads where the chain stands, and the second adds the link only
when the head is still at the sequence that was read and moves it, in the same transaction. A
failed append raises, and the caller then does not let the thing it was recording stand.

The four statements are platform statements (`PLATFORM_QUERY_IDS`): fixed text, pinned by digest,
run only through `run_platform_query`, naming the platform's own labels only. Nothing is deleted.
"""

import json
import secrets
from datetime import UTC, datetime
from typing import Any, Final

from neo4j import AsyncManagedTransaction
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import run_platform_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.application.ports.outbound.audit import (
    TIME_FORMAT,
    canonical_json,
    chain_hash_over,
    genesis_hash_for,
)
from diucs.application.ports.outbound.platform_audit import PlatformAuditEntry, PlatformAuditRecord
from diucs.domain.errors import ValidationFailed

HEAD_ID: Final = "platform"
GENESIS_SCOPE: Final = "platform"
PAGE: Final = 500
MAX_ENTRIES: Final = 200
APPEND_MESSAGE: Final = "the platform audit chain could not be appended"

_LOCK = NamedQuery(
    id="Q-PLATFORM-AUDIT-LOCK",
    cypher=(
        "MERGE (h:PlatformAuditHead {id: $id}) "
        "ON CREATE SET h.lastSeq = 0, h.lastHash = $genesis "
        "SET h.lockStamp = $stamp "
        "RETURN h.lastSeq AS lastSeq, h.lastHash AS lastHash"
    ),
    mode="write",
    scope="platform",
)
_APPEND = NamedQuery(
    id="Q-PLATFORM-AUDIT-APPEND",
    cypher=(
        "MATCH (h:PlatformAuditHead {id: $id, lastSeq: $expectedSeq}) "
        "CREATE (e:PlatformAuditEntry {seq: $seq}) "
        "SET e += $props, h.lastSeq = $seq, h.lastHash = $hash "
        "RETURN e.seq AS seq"
    ),
    mode="write",
    scope="platform",
)
_ENTRIES = NamedQuery(
    id="Q-PLATFORM-AUDIT-ENTRIES",
    cypher=(
        "MATCH (e:PlatformAuditEntry) WHERE e.seq > $afterSeq "
        "RETURN properties(e) AS entry ORDER BY e.seq LIMIT $limit"
    ),
    mode="read",
    scope="platform",
)
_HEAD = NamedQuery(
    id="Q-PLATFORM-AUDIT-HEAD",
    cypher=(
        "MATCH (h:PlatformAuditHead {id: $id}) RETURN h.lastSeq AS lastSeq, h.lastHash AS lastHash"
    ),
    mode="read",
    scope="platform",
)
for _query in (_LOCK, _APPEND, _ENTRIES, _HEAD):
    REGISTRY.register(_query)


def entry_json(entry: PlatformAuditEntry) -> str:
    """The canonical text of an entry: what the chain hashes. The snapshot is its own business to
    keep free of names and patient data (the guard writes the expiry, a reason word, an action)."""
    if entry.at.utcoffset() is None:
        raise ValidationFailed("at", "must be a timezone-aware datetime")
    return canonical_json(
        {
            "action": entry.action,
            "principal_ref": entry.principal_ref,
            "tenant_id": entry.tenant_id,
            "access_id": entry.access_id,
            "snapshot": entry.snapshot,
            "at": entry.at,
        }
    )


def _native(value: object) -> datetime:
    native = value.to_native() if isinstance(value, DateTime) else value
    if not isinstance(native, datetime):
        raise ValidationFailed("at", "is not a time")
    return native


def record_from_properties(props: dict[str, Any]) -> PlatformAuditRecord:
    """A link as read back, from the text that was hashed. The entry's time and snapshot come from
    that text, so what a reader sees is what the chain verified."""
    body = json.loads(str(props["entryJson"]))
    return PlatformAuditRecord(
        seq=int(props["seq"]),
        action=str(body["action"]),
        principal_ref=str(body["principal_ref"]),
        tenant_id=body["tenant_id"],
        access_id=body["access_id"],
        snapshot=body["snapshot"],
        at=datetime.strptime(body["at"], TIME_FORMAT).replace(tzinfo=UTC),
        chain_hash=str(props["chainHash"]),
        previous_hash=str(props["previousHash"]),
    )


class Neo4jPlatformAudit:
    """The `PlatformAudit` and `PlatformAuditReader` ports over the platform's own chain."""

    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection
        self._genesis = genesis_hash_for(GENESIS_SCOPE)

    async def append(self, entry: PlatformAuditEntry) -> None:
        text = entry_json(entry)
        stamp = secrets.token_hex(8)

        async def work(tx: AsyncManagedTransaction) -> None:
            head = await run_platform_query(
                tx, _LOCK, id=HEAD_ID, genesis=self._genesis, stamp=stamp
            )
            seq = int(head[0]["lastSeq"])
            previous = str(head[0]["lastHash"])
            chain_hash = chain_hash_over(previous, text)
            props = {
                "action": entry.action,
                "principalRef": entry.principal_ref,
                "forTenant": entry.tenant_id,
                "accessId": entry.access_id,
                "recordedAt": entry.at,
                "previousHash": previous,
                "chainHash": chain_hash,
                "entryJson": text,
            }
            rows = await run_platform_query(
                tx,
                _APPEND,
                id=HEAD_ID,
                expectedSeq=seq,
                seq=seq + 1,
                props=props,
                hash=chain_hash,
            )
            if not rows:
                raise RuntimeError(APPEND_MESSAGE)

        await self._connection.run_write(work)

    async def entries(self, after_seq: int, limit: int) -> list[PlatformAuditRecord]:
        if type(after_seq) is not int or after_seq < 0:
            raise ValidationFailed("after_seq", "must be a whole number from 0")
        if type(limit) is not int or not 1 <= limit <= MAX_ENTRIES:
            raise ValidationFailed("limit", f"must be from 1 to {MAX_ENTRIES}")

        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            return await run_platform_query(tx, _ENTRIES, afterSeq=after_seq, limit=limit)

        rows = await self._connection.run_read(work)
        return [record_from_properties(dict(row["entry"])) for row in rows]

    async def verify(self) -> bool:
        async def work(tx: AsyncManagedTransaction) -> tuple[list[dict[str, Any]], list[Any]]:
            head = await run_platform_query(tx, _HEAD, id=HEAD_ID)
            links: list[dict[str, Any]] = []
            after = 0
            while True:
                page = await run_platform_query(tx, _ENTRIES, afterSeq=after, limit=PAGE)
                links.extend(dict(row["entry"]) for row in page)
                if len(page) < PAGE:
                    break
                after = int(page[-1]["entry"]["seq"])
            return head, links

        head, links = await self._connection.run_read(work)
        previous = self._genesis
        expected_seq = 0
        for props in links:
            expected_seq += 1
            text = str(props.get("entryJson"))
            chain_hash = chain_hash_over(previous, text)
            if (
                props.get("seq") != expected_seq
                or props.get("previousHash") != previous
                or props.get("chainHash") != chain_hash
                or _props_disagree(props, text)
            ):
                return False
            previous = chain_hash
        if not head:
            return expected_seq == 0
        return bool(head[0]["lastSeq"] == expected_seq and head[0]["lastHash"] == previous)


def _props_disagree(props: dict[str, Any], text: str) -> bool:
    """A denormalised property that no longer matches the text that was hashed."""
    try:
        body = json.loads(text)
        return bool(
            props.get("action") != body["action"]
            or props.get("principalRef") != body["principal_ref"]
            or props.get("forTenant") != body["tenant_id"]
            or props.get("accessId") != body["access_id"]
        )
    except ValueError, KeyError, TypeError:
        return True
