"""Neo4j audit log and provenance on one hash chain (P05, DEC-054).

Neo4jAuditLog(tx) works inside the caller's transaction, so an audit entry or provenance record
commits or rolls back with the change it records (the unit of work, P06, passes its transaction).

Chain. Every AuditEvent and every Provenance node is a ChainLink with a seq number, a previousHash,
a chainHash and the canonical text it was hashed from (entryJson). Verification walks the links in
seq order, recomputes every hash, and checks each node's denormalised properties against the text.
Edited text, a reordered, removed or inserted link, or an edited property makes verify_chain False.
The AuditHead node holds lastHash and lastSeq, so a removed tail link is also caught.

Serialisation. Every append first writes the head (SET _lock) and only then reads lastHash, so
concurrent appends queue on the head and each links to the one before it (lesson L63). This is a
write hot spot by design: measure it under load before relying on throughput.

Not covered by the hash: the node id of an AuditEvent (the spec formula hashes the entry only). The
id is unique by constraint and is the key that AuditLog.records(since=...) uses.

TODO(enterprise): Community cannot deny SET or DELETE by role. When the Enterprise edition is
chosen (architecture.md), add role-based write restrictions on AuditEvent, Provenance, ChainLink
and AuditHead, so that the application role can create but never change or remove a link.

ensure_audit_head must run once at startup, after apply_migrations. Appending without a head raises
AuditHeadMissing rather than creating one: creating the head inside a concurrent append would race.

The adapter imports the G01 driver and query registry from graph_store. The import-linter contract
"Adapters are independent" allows exactly those two imports (see .importlinter, DEC-054).
"""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import (
    GENESIS_HASH,
    TIME_FORMAT,
    AuditEntry,
    AuditRecord,
    canonical_entry_json,
    canonical_json,
    chain_hash_over,
)
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.domain.codes import Role, code_system_url
from diucs.domain.errors import ValidationFailed

HEAD_ID = "audit"
OUTCOME_RECORDED = "recorded"
PROVENANCE_ACTIVITIES = frozenset({"create", "confirm", "approve", "call-back"})
ACTIVITY_CODE_SYSTEM = code_system_url("provenance-activity")

_EXTRA_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$")
_RESERVED = frozenset(
    {
        "id",
        "recorded",
        "activity",
        "chainHash",
        "previousHash",
        "seq",
        "entryJson",
        "key",
        "placeholder",
        "lockStamp",
    }
)
_AUDIT_PROPERTIES = frozenset(
    {
        "id",
        "action",
        "useCase",
        "recorded",
        "outcome",
        "chainHash",
        "previousHash",
        "seq",
        "entryJson",
    }
)
_PROVENANCE_PROPERTIES = frozenset(
    {"id", "recorded", "activity", "chainHash", "previousHash", "seq", "entryJson"}
)

_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        id="Q-AUDIT-ENSURE-HEAD",
        cypher=(
            "MERGE (h:AuditHead {id: 'audit'}) ON CREATE SET h.lastHash = $genesis, h.lastSeq = 0 "
            "RETURN h.lastSeq AS lastSeq"
        ),
        mode="write",
    ),
    NamedQuery(
        id="Q-AUDIT-LOCK-HEAD",
        cypher=(
            "MATCH (h:AuditHead {id: 'audit'}) SET h._lock = coalesce(h._lock, 0) + 1 "
            "RETURN h.lastHash AS lastHash, h.lastSeq AS lastSeq"
        ),
        mode="write",
    ),
    NamedQuery(
        id="Q-AUDIT-APPEND",
        cypher=(
            "MATCH (h:AuditHead {id: 'audit'}) "
            "CREATE (e:AuditEvent:ChainLink {id: $id, action: $action, useCase: $useCase, "
            "recorded: $recorded, outcome: $outcome, chainHash: $chainHash, "
            "previousHash: $previousHash, seq: $seq, entryJson: $entryJson}) "
            "SET h.lastHash = $chainHash, h.lastSeq = $seq "
            "WITH e "
            "FOREACH (_ IN CASE WHEN $snapshotHash IS NULL THEN [] ELSE [1] END | "
            "CREATE (s:Snapshot {hash: $snapshotHash, json: $snapshotJson}) "
            "CREATE (e)-[:SNAPSHOT]->(s)) "
            "RETURN e.id AS id"
        ),
        mode="write",
    ),
    NamedQuery(
        id="Q-AUDIT-LINK-AGENT",
        cypher=(
            "MATCH (e:AuditEvent {id: $id}) "
            "MERGE (a:AuditRef {id: $agentId}) ON CREATE SET a.kind = $agentKind "
            "CREATE (e)-[:AGENT {role: $role, requestor: true}]->(a)"
        ),
        mode="write",
    ),
    NamedQuery(
        id="Q-AUDIT-LINK-ENTITY",
        cypher=(
            "MATCH (e:AuditEvent {id: $id}) "
            "UNWIND $entityIds AS entityId "
            "MERGE (r:AuditRef {id: entityId}) ON CREATE SET r.kind = 'entity' "
            "MERGE (e)-[:ENTITY {role: 'subject'}]->(r)"
        ),
        mode="write",
    ),
    NamedQuery(
        id="Q-AUDIT-LIST",
        cypher=(
            "MATCH (e:AuditEvent) "
            "RETURN e.id AS id, e.entryJson AS entryJson, e.chainHash AS chainHash, "
            "e.previousHash AS previousHash "
            "ORDER BY e.seq"
        ),
        mode="read",
    ),
    NamedQuery(
        id="Q-AUDIT-HEAD",
        cypher=(
            "MATCH (h:AuditHead {id: 'audit'}) RETURN h.lastHash AS lastHash, h.lastSeq AS lastSeq"
        ),
        mode="read",
    ),
    NamedQuery(
        id="Q-AUDIT-CHAIN",
        cypher=(
            "MATCH (n:ChainLink) "
            "RETURN labels(n) AS labels, n.seq AS seq, n.previousHash AS previousHash, "
            "n.chainHash AS chainHash, n.entryJson AS entryJson, properties(n) AS props "
            "ORDER BY n.seq"
        ),
        mode="read",
    ),
    NamedQuery(
        id="Q-PROV-APPEND",
        cypher=(
            "MATCH (h:AuditHead {id: 'audit'}) "
            "CREATE (p:Provenance:ChainLink {id: $id, recorded: $recorded, activity: $activity, "
            "chainHash: $chainHash, previousHash: $previousHash, seq: $seq, "
            "entryJson: $entryJson}) "
            "SET p += $extra "
            "SET h.lastHash = $chainHash, h.lastSeq = $seq "
            "RETURN p.id AS id"
        ),
        mode="write",
    ),
    NamedQuery(
        id="Q-PROV-LINK",
        cypher=(
            "MATCH (p:Provenance {id: $id}) "
            "MERGE (t:AuditRef {id: $targetId}) ON CREATE SET t.kind = $targetType "
            "MERGE (p)-[:TARGET]->(t) "
            "MERGE (g:AuditRef {id: $agentId}) ON CREATE SET g.kind = $agentType "
            "MERGE (p)-[:AGENT {type: $agentType, role: $agentRole}]->(g) "
            "MERGE (c:Concept {system: $activitySystem, code: $activity}) "
            "ON CREATE SET c.key = $activityKey "
            "MERGE (p)-[:ACTIVITY]->(c)"
        ),
        mode="write",
    ),
    NamedQuery(
        id="Q-PROV-SOURCE",
        cypher=(
            "MATCH (p:Provenance {id: $id}) "
            "MERGE (c:AuditRef {id: $sourceId}) ON CREATE SET c.kind = 'Communication' "
            "MERGE (p)-[:ENTITY {role: 'source'}]->(c)"
        ),
        mode="write",
    ),
)

for _query in _QUERIES:
    REGISTRY.register(_query)


class AuditHeadMissing(RuntimeError):
    """The chain head does not exist. Call ensure_audit_head at startup."""


async def ensure_audit_head(driver: AsyncDriver) -> None:
    """Create the chain head if missing. Idempotent. Call once at startup, after migrations."""

    async def work(tx: AsyncManagedTransaction) -> None:
        await run_query(tx, "Q-AUDIT-ENSURE-HEAD", genesis=GENESIS_HASH)

    async with driver.session() as session:
        await session.execute_write(work)


def _parse_entry(text: str) -> AuditEntry:
    data: dict[str, Any] = json.loads(text)
    actor: dict[str, Any] = data["actor"]
    return AuditEntry(
        action=str(data["action"]),
        use_case=str(data["use_case"]),
        actor=Actor(
            role=Role(actor["role"]),
            practitioner_id=actor["practitioner_id"],
            device_id=actor["device_id"],
            channel=str(actor["channel"]),
            service_ids=frozenset(actor["service_ids"]),
        ),
        entity_ids=tuple(data["entity_ids"]),
        snapshot=data["snapshot"],
        at=datetime.strptime(data["at"], TIME_FORMAT).replace(tzinfo=UTC),
    )


def _matches_stored_properties(row: dict[str, Any]) -> bool:
    """The node's own properties must agree with the hashed text, and carry nothing else."""
    text = str(row["entryJson"])
    props: dict[str, Any] = row["props"]
    try:
        if "AuditEvent" in row["labels"]:
            entry = _parse_entry(text)
            expected = {
                "action": entry.action,
                "useCase": entry.use_case,
                "outcome": OUTCOME_RECORDED,
            }
            allowed = _AUDIT_PROPERTIES
        else:
            payload: dict[str, Any] = json.loads(text)
            extra: dict[str, Any] = payload["extra"]
            expected = {"id": payload["id"], "activity": payload["activity"], **extra}
            allowed = _PROVENANCE_PROPERTIES | set(extra)
    except ValueError, KeyError, TypeError:
        return False
    if not set(props) <= allowed:
        return False
    return all(props.get(name) == value for name, value in expected.items())


class Neo4jAuditLog:
    """The audit log on the caller's transaction. Append-only: there is no update, delete or remove.

    ids defaults to a random UUID4 string and clock to the UTC system time. Provenance records take
    their `recorded` time from clock; audit entries take `at` from the entry.
    """

    def __init__(
        self,
        tx: AsyncManagedTransaction,
        ids: IdGenerator | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._tx = tx
        self._ids = ids
        self._clock = clock

    def _new_id(self) -> str:
        return self._ids.new_id() if self._ids is not None else str(uuid.uuid4())

    def _now(self) -> datetime:
        return self._clock.now() if self._clock is not None else datetime.now(UTC)

    async def _lock_head(self) -> tuple[str, int]:
        """Take the head's write lock, then read where the chain stands (lesson L63)."""
        rows = await run_query(self._tx, "Q-AUDIT-LOCK-HEAD")
        if not rows:
            raise AuditHeadMissing(
                "the audit chain head does not exist; call ensure_audit_head at startup"
            )
        return str(rows[0]["lastHash"]), int(rows[0]["lastSeq"])

    async def _link_actor(self, record_id: str, actor: Actor) -> None:
        if actor.practitioner_id is not None:
            await run_query(
                self._tx,
                "Q-AUDIT-LINK-AGENT",
                id=record_id,
                agentId=actor.practitioner_id,
                agentKind="Practitioner",
                role=actor.role.value,
            )
        if actor.device_id is not None:
            await run_query(
                self._tx,
                "Q-AUDIT-LINK-AGENT",
                id=record_id,
                agentId=actor.device_id,
                agentKind="Device",
                role=actor.role.value,
            )

    async def append(self, entry: AuditEntry) -> AuditRecord:
        text = canonical_entry_json(entry)
        previous, last_seq = await self._lock_head()
        chain = chain_hash_over(previous, text)
        record_id = self._new_id()
        snapshot_json = None if entry.snapshot is None else canonical_json(entry.snapshot)
        snapshot_hash = (
            None if snapshot_json is None else hashlib.sha256(snapshot_json.encode()).hexdigest()
        )
        await run_query(
            self._tx,
            "Q-AUDIT-APPEND",
            id=record_id,
            action=entry.action,
            useCase=entry.use_case,
            recorded=entry.at,
            outcome=OUTCOME_RECORDED,
            chainHash=chain,
            previousHash=previous,
            seq=last_seq + 1,
            entryJson=text,
            snapshotHash=snapshot_hash,
            snapshotJson=snapshot_json,
        )
        await self._link_actor(record_id, entry.actor)
        if entry.entity_ids:
            await run_query(
                self._tx,
                "Q-AUDIT-LINK-ENTITY",
                id=record_id,
                entityIds=list(entry.entity_ids),
            )
        return AuditRecord(id=record_id, entry=entry, chain_hash=chain, previous_hash=previous)

    async def records(self, since: str | None = None) -> list[AuditRecord]:
        """Audit records in chain order. With since, only the records after that record's id."""
        rows = await run_query(self._tx, "Q-AUDIT-LIST")
        found = [
            AuditRecord(
                id=str(row["id"]),
                entry=_parse_entry(str(row["entryJson"])),
                chain_hash=str(row["chainHash"]),
                previous_hash=str(row["previousHash"]),
            )
            for row in rows
        ]
        if since is None:
            return found
        ids = [record.id for record in found]
        if since not in ids:
            raise ValidationFailed("since", "no audit record has this id")
        return found[ids.index(since) + 1 :]

    async def verify_chain(self) -> bool:
        """True when every link is intact, in order, and the head points at the last link."""
        rows = await run_query(self._tx, "Q-AUDIT-CHAIN")
        head_rows = await run_query(self._tx, "Q-AUDIT-HEAD")
        if not head_rows:
            return not rows
        previous = GENESIS_HASH
        for index, row in enumerate(rows, start=1):
            if row["seq"] != index or row["previousHash"] != previous:
                return False
            if chain_hash_over(previous, str(row["entryJson"])) != row["chainHash"]:
                return False
            if not _matches_stored_properties(row):
                return False
            previous = str(row["chainHash"])
        head = head_rows[0]
        return bool(head["lastHash"] == previous and head["lastSeq"] == len(rows))

    async def append_provenance(
        self,
        target_type: str,
        target_id: str,
        activity: str,
        agent_id: str,
        agent_role: Role,
        source_communication_id: str | None = None,
        extra: dict[str, Any] | None = None,
        agent_type: str = "Practitioner",
    ) -> str:
        """Append a Provenance record to the chain and link it to its target, agent and activity.

        extra holds small facts such as numberCalled or roleSpokenTo. Its names must be simple and
        must not reuse a name the store uses. Its values are strings, integers or booleans. The
        record stores ids and words, never patient values (the caller is responsible for that).
        """
        if activity not in PROVENANCE_ACTIVITIES:
            raise ValidationFailed("activity", "not a known provenance activity")
        extras: dict[str, Any] = dict(extra or {})
        for name, value in extras.items():
            if not _EXTRA_NAME.match(name) or name in _RESERVED:
                raise ValidationFailed(name, "is not allowed as a provenance property")
            if not isinstance(value, str | int | bool):
                raise ValidationFailed(name, "must be a string, an integer or a boolean")
        previous, last_seq = await self._lock_head()
        recorded = self._now()
        prov_id = self._new_id()
        payload: dict[str, Any] = {
            "id": prov_id,
            "recorded": recorded,
            "target_type": target_type,
            "target_id": target_id,
            "activity": activity,
            "agent_id": agent_id,
            "agent_type": agent_type,
            "agent_role": agent_role,
            "source_communication_id": source_communication_id,
            "extra": extras,
        }
        text = canonical_json(payload)
        chain = chain_hash_over(previous, text)
        await run_query(
            self._tx,
            "Q-PROV-APPEND",
            id=prov_id,
            recorded=recorded,
            activity=activity,
            chainHash=chain,
            previousHash=previous,
            seq=last_seq + 1,
            entryJson=text,
            extra=extras,
        )
        await run_query(
            self._tx,
            "Q-PROV-LINK",
            id=prov_id,
            targetType=target_type,
            targetId=target_id,
            agentId=agent_id,
            agentType=agent_type,
            agentRole=agent_role.value,
            activity=activity,
            activitySystem=ACTIVITY_CODE_SYSTEM,
            activityKey=f"Concept|{ACTIVITY_CODE_SYSTEM}|{activity}",
        )
        if source_communication_id is not None:
            await run_query(
                self._tx,
                "Q-PROV-SOURCE",
                id=prov_id,
                sourceId=source_communication_id,
            )
        return prov_id
