"""Neo4j audit log and provenance on one hash chain (P05, DEC-055).

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

There is one chain per scope (DEC-055, DEC-130 item 7, TEN-017): one AuditHead, one sequence and
one genesis per tenant or network scope, and every node of a chain carries the scope's tenantId. The
hashed text of a link does not carry the tenant; the tenant is the chain's own. The default tenant's
genesis is GENESIS_HASH, so the chain the development data holds verifies unchanged.

ensure_audit_head must run once per scope, after apply_migrations: the start-up does it for each
active tenant. Appending without a head raises AuditHeadMissing rather than creating one: creating
the head inside a concurrent append would race. Every statement here refuses an unbound call
(TenantNotBound) before any Cypher is sent.

The adapter imports the G01 driver and query registry from graph_store. The import-linter contract
"Adapters are independent" allows exactly those two imports (see .importlinter, DEC-055).
"""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Final

from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import ScopedTx, Tx, run_query
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
from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import (
    TIME_FORMAT,
    AuditEntry,
    AuditRecord,
    canonical_entry_json,
    canonical_json,
    chain_hash_over,
    genesis_hash_for,
)
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.tenancy import (
    ScopeId,
    TenantNotBound,
    current_scope_or_none,
    scope_for_new_unit,
)
from diucs.domain.codes import Role, code_system_url
from diucs.domain.errors import ValidationFailed

HEAD_ID = "audit"
OUTCOME_RECORDED = "recorded"
PROVENANCE_ACTIVITIES = frozenset({"create", "confirm", "approve", "call-back", "scope-decision"})
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
        # The stamp of the scope: an extra of this name would overwrite it (`SET p += $extra`).
        "tenantId",
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
        "tenantId",
    }
)
_PROVENANCE_PROPERTIES = frozenset(
    {"id", "recorded", "activity", "chainHash", "previousHash", "seq", "entryJson", "tenantId"}
)

# The statements of one chain, converted by TEN-017 (DEC-150). The scenarios seed the same chain for
# both tenants: an AuditHead 'audit', two links (an AuditEvent at seq 1 and a Provenance at seq 2)
# and the AuditRef and Concept nodes they point at. The texts of the links are `Marked`, so a link
# read from the other tenant shows as the other tenant's. Each scenario checks that the caller's own
# chain is the one it reads or extends, and that the other tenant's chain is untouched.
_SEED_AT: Final = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
_CHAIN_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "head",
            ("AuditHead",),
            {"id": HEAD_ID, "lastHash": Marked("chain-2"), "lastSeq": 2},
        ),
        SeedNode(
            "event",
            ("AuditEvent", "ChainLink"),
            {
                "id": "e-1",
                "action": "report-capacity",
                "useCase": "ReportCapacity",
                "recorded": _SEED_AT,
                "outcome": OUTCOME_RECORDED,
                "chainHash": Marked("chain-1"),
                "previousHash": "genesis-seed",
                "seq": 1,
                "entryJson": Marked("entry-1"),
            },
        ),
        SeedNode(
            "provenance",
            ("Provenance", "ChainLink"),
            {
                "id": "p-1",
                "recorded": _SEED_AT,
                "activity": "create",
                "chainHash": Marked("chain-2"),
                "previousHash": Marked("chain-1"),
                "seq": 2,
                "entryJson": Marked("entry-2"),
            },
        ),
        SeedNode("agent", ("AuditRef",), {"id": "pr-1", "kind": "Practitioner"}),
        SeedNode("entity", ("AuditRef",), {"id": "ent-1", "kind": "entity"}),
    ),
    rels=(SeedRel("event", "AGENT", "agent", {"role": "reporter", "requestor": True}),),
)
_HEAD_ROW: Final = {"lastHash": Marked("chain-2"), "lastSeq": 2}
_ENSURE_HEAD_SCENARIO: Final = Scenario(
    "make sure the tenant's head exists and leave it as it is",
    seed=_CHAIN_SEED,
    params={"genesis": "genesis-new"},
    new=("genesis",),
    expect=Expect(rows=({"lastSeq": 2},)),
)
_LOCK_HEAD_SCENARIO: Final = Scenario(
    "lock the tenant's own head and read where its chain stands",
    seed=_CHAIN_SEED,
    expect=Expect(
        rows=(_HEAD_ROW,),
        after=(NodeSpec(("AuditHead",), {"id": HEAD_ID, "_lock": 1}),),
    ),
)
_HEAD_SCENARIO: Final = Scenario(
    "read where the tenant's own chain stands",
    seed=_CHAIN_SEED,
    expect=Expect(rows=(_HEAD_ROW,)),
)
_LIST_SCENARIO: Final = Scenario(
    "list the tenant's own links in order and no other tenant's",
    seed=_CHAIN_SEED,
    expect=Expect(
        rows=(
            {
                "id": "e-1",
                "entryJson": Marked("entry-1"),
                "chainHash": Marked("chain-1"),
                "previousHash": "genesis-seed",
            },
        )
    ),
)
_CHAIN_WALK_SCENARIO: Final = Scenario(
    "walk the tenant's own links in sequence order",
    seed=_CHAIN_SEED,
    expect=Expect(
        rows=(
            {"seq": 1, "chainHash": Marked("chain-1"), "entryJson": Marked("entry-1")},
            {"seq": 2, "chainHash": Marked("chain-2"), "entryJson": Marked("entry-2")},
        )
    ),
)
_APPEND_SCENARIO: Final = Scenario(
    "append an entry after the tenant's own chain and move its head",
    seed=_CHAIN_SEED,
    params={
        "id": "e-2",
        "action": "report-capacity",
        "useCase": "ReportCapacity",
        "recorded": _SEED_AT,
        "outcome": OUTCOME_RECORDED,
        "chainHash": "chain-3",
        "previousHash": Marked("chain-2"),
        "seq": 3,
        "entryJson": "entry-3",
        "snapshotHash": None,
        "snapshotJson": None,
    },
    new=("id", "chainHash", "seq", "entryJson"),
    expect=Expect(
        rows=({"id": "e-2"},),
        nodes={"AuditEvent": 1, "ChainLink": 1},
        after=(
            NodeSpec(("AuditEvent",), {"id": "e-2", "seq": 3}),
            NodeSpec(("AuditHead",), {"id": HEAD_ID, "lastSeq": 3, "lastHash": "chain-3"}),
        ),
    ),
)
_LINK_AGENT_SCENARIO: Final = Scenario(
    "link the tenant's own entry to its own agent, not the agent of the same id in another tenant",
    seed=_CHAIN_SEED,
    params={
        "id": "e-1",
        "agentId": "pr-1",
        "agentKind": "Practitioner",
        "role": "reporter",
    },
    lookup=("id",),
    new=("role",),
    expect=Expect(rels={"AGENT": 1}),
)
_LINK_ENTITY_SCENARIO: Final = Scenario(
    "link the tenant's own entry to its entities, reusing the one it already has",
    seed=_CHAIN_SEED,
    params={"id": "e-1", "entityIds": ["ent-1", "ent-2"]},
    lookup=("id",),
    new=("entityIds",),
    expect=Expect(nodes={"AuditRef": 1}, rels={"ENTITY": 2}),
)
_PROV_APPEND_SCENARIO: Final = Scenario(
    "append a provenance record after the tenant's own chain and move its head",
    seed=_CHAIN_SEED,
    params={
        "id": "p-2",
        "recorded": _SEED_AT,
        "activity": "confirm",
        "chainHash": "chain-p2",
        "previousHash": Marked("chain-2"),
        "seq": 3,
        "entryJson": "prov-2",
        "extra": {},
    },
    new=("id", "activity", "chainHash", "seq", "entryJson"),
    expect=Expect(
        rows=({"id": "p-2"},),
        nodes={"Provenance": 1, "ChainLink": 1},
        after=(
            NodeSpec(("Provenance",), {"id": "p-2", "seq": 3}),
            NodeSpec(("AuditHead",), {"id": HEAD_ID, "lastSeq": 3, "lastHash": "chain-p2"}),
        ),
    ),
)
_PROV_LINK_SCENARIO: Final = Scenario(
    "link the tenant's own provenance record to its target, agent and activity",
    seed=_CHAIN_SEED,
    params={
        "id": "p-1",
        "targetType": "Communication",
        "targetId": "comm-1",
        "agentType": "Practitioner",
        "agentId": "pr-1",
        "agentRole": "reporter",
        "activity": "create",
        "activitySystem": "https://diucs.example/codes/provenance-activity",
        "activityKey": "Concept|https://diucs.example/codes/provenance-activity|create",
    },
    lookup=("id",),
    new=(
        "targetType",
        "targetId",
        "agentRole",
        "activitySystem",
        "activityKey",
    ),
    expect=Expect(
        nodes={"AuditRef": 1, "Concept": 1},
        rels={"TARGET": 1, "AGENT": 1, "ACTIVITY": 1},
    ),
)
_PROV_SOURCE_SCENARIO: Final = Scenario(
    "link the tenant's own provenance record to its source communication",
    seed=_CHAIN_SEED,
    params={"id": "p-1", "sourceId": "comm-1"},
    lookup=("id",),
    new=("sourceId",),
    expect=Expect(nodes={"AuditRef": 1}, rels={"ENTITY": 1}),
)

# Each statement, its mode and its scenario (DEC-142 item 5). Every node a statement matches or
# creates carries `$tenant`; the chain walk matches its targets within the tenant too.
_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        id="Q-AUDIT-ENSURE-HEAD",
        cypher=(
            "MERGE (h:AuditHead {id: 'audit', tenantId: $tenant}) "
            "ON CREATE SET h.lastHash = $genesis, h.lastSeq = 0 "
            "RETURN h.lastSeq AS lastSeq"
        ),
        mode="write",
        scenario=_ENSURE_HEAD_SCENARIO,
    ),
    NamedQuery(
        id="Q-AUDIT-LOCK-HEAD",
        cypher=(
            "MATCH (h:AuditHead {id: 'audit', tenantId: $tenant}) "
            "SET h._lock = coalesce(h._lock, 0) + 1 "
            "RETURN h.lastHash AS lastHash, h.lastSeq AS lastSeq"
        ),
        mode="write",
        scenario=_LOCK_HEAD_SCENARIO,
    ),
    NamedQuery(
        id="Q-AUDIT-APPEND",
        cypher=(
            "MATCH (h:AuditHead {id: 'audit', tenantId: $tenant}) "
            "CREATE (e:AuditEvent:ChainLink {id: $id, action: $action, useCase: $useCase, "
            "recorded: $recorded, outcome: $outcome, chainHash: $chainHash, "
            "previousHash: $previousHash, seq: $seq, entryJson: $entryJson, tenantId: $tenant}) "
            "SET h.lastHash = $chainHash, h.lastSeq = $seq "
            "WITH e "
            "FOREACH (_ IN CASE WHEN $snapshotHash IS NULL THEN [] ELSE [1] END | "
            "CREATE (s:Snapshot {hash: $snapshotHash, json: $snapshotJson, tenantId: $tenant}) "
            "CREATE (e)-[:SNAPSHOT]->(s)) "
            "RETURN e.id AS id"
        ),
        mode="write",
        scenario=_APPEND_SCENARIO,
    ),
    NamedQuery(
        id="Q-AUDIT-LINK-AGENT",
        cypher=(
            "MATCH (e:AuditEvent {id: $id, tenantId: $tenant}) "
            "MERGE (a:AuditRef {id: $agentId, tenantId: $tenant}) "
            "ON CREATE SET a.kind = $agentKind "
            "CREATE (e)-[:AGENT {role: $role, requestor: true}]->(a)"
        ),
        mode="write",
        scenario=_LINK_AGENT_SCENARIO,
    ),
    NamedQuery(
        id="Q-AUDIT-LINK-ENTITY",
        cypher=(
            "MATCH (e:AuditEvent {id: $id, tenantId: $tenant}) "
            "UNWIND $entityIds AS entityId "
            "MERGE (r:AuditRef {id: entityId, tenantId: $tenant}) ON CREATE SET r.kind = 'entity' "
            "MERGE (e)-[:ENTITY {role: 'subject'}]->(r)"
        ),
        mode="write",
        scenario=_LINK_ENTITY_SCENARIO,
    ),
    NamedQuery(
        id="Q-AUDIT-LIST",
        cypher=(
            "MATCH (e:AuditEvent {tenantId: $tenant}) "
            "RETURN e.id AS id, e.entryJson AS entryJson, e.chainHash AS chainHash, "
            "e.previousHash AS previousHash "
            "ORDER BY e.seq"
        ),
        mode="read",
        scenario=_LIST_SCENARIO,
    ),
    NamedQuery(
        id="Q-AUDIT-HEAD",
        cypher=(
            "MATCH (h:AuditHead {id: 'audit', tenantId: $tenant}) "
            "RETURN h.lastHash AS lastHash, h.lastSeq AS lastSeq"
        ),
        mode="read",
        scenario=_HEAD_SCENARIO,
    ),
    NamedQuery(
        id="Q-AUDIT-CHAIN",
        cypher=(
            "MATCH (n:ChainLink {tenantId: $tenant}) "
            "OPTIONAL MATCH (n)-[r]->(m {tenantId: $tenant}) "
            "WITH n, collect(CASE WHEN r IS NULL THEN NULL ELSE {type: type(r), "
            "props: properties(r), target: CASE WHEN m:Snapshot THEN m.hash + '|' + m.json "
            "WHEN m:Concept THEN m.system + '|' + m.code ELSE m.id END} END) AS edges "
            "RETURN labels(n) AS labels, n.seq AS seq, n.previousHash AS previousHash, "
            "n.chainHash AS chainHash, n.entryJson AS entryJson, properties(n) AS props, "
            "edges ORDER BY seq"
        ),
        mode="read",
        scenario=_CHAIN_WALK_SCENARIO,
    ),
    NamedQuery(
        id="Q-PROV-APPEND",
        cypher=(
            "MATCH (h:AuditHead {id: 'audit', tenantId: $tenant}) "
            "CREATE (p:Provenance:ChainLink {id: $id, recorded: $recorded, activity: $activity, "
            "chainHash: $chainHash, previousHash: $previousHash, seq: $seq, "
            "entryJson: $entryJson, tenantId: $tenant}) "
            "SET p += $extra "
            "SET h.lastHash = $chainHash, h.lastSeq = $seq "
            "RETURN p.id AS id"
        ),
        mode="write",
        scenario=_PROV_APPEND_SCENARIO,
    ),
    NamedQuery(
        id="Q-PROV-LINK",
        cypher=(
            "MATCH (p:Provenance {id: $id, tenantId: $tenant}) "
            "MERGE (t:AuditRef {id: $targetId, tenantId: $tenant}) "
            "ON CREATE SET t.kind = $targetType "
            "MERGE (p)-[:TARGET]->(t) "
            "MERGE (g:AuditRef {id: $agentId, tenantId: $tenant}) "
            "ON CREATE SET g.kind = $agentType "
            "MERGE (p)-[:AGENT {type: $agentType, role: $agentRole}]->(g) "
            "MERGE (c:Concept {system: $activitySystem, code: $activity, tenantId: $tenant}) "
            "ON CREATE SET c.key = $activityKey "
            "MERGE (p)-[:ACTIVITY]->(c)"
        ),
        mode="write",
        scenario=_PROV_LINK_SCENARIO,
    ),
    NamedQuery(
        id="Q-PROV-SOURCE",
        cypher=(
            "MATCH (p:Provenance {id: $id, tenantId: $tenant}) "
            "MERGE (c:AuditRef {id: $sourceId, tenantId: $tenant}) "
            "ON CREATE SET c.kind = 'Communication' "
            "MERGE (p)-[:ENTITY {role: 'source'}]->(c)"
        ),
        mode="write",
        scenario=_PROV_SOURCE_SCENARIO,
    ),
)

for _query in _QUERIES:
    REGISTRY.register(_query)


class AuditHeadMissing(RuntimeError):
    """The chain head does not exist. Call ensure_audit_head at startup."""


async def ensure_audit_head(driver: AsyncDriver) -> None:
    """Create the bound scope's chain head if missing, with that scope's genesis. Idempotent. Call
    once per scope at startup, after migrations (the start-up does it for each active tenant).

    The scope is read once, before the session opens, and carried on a ScopedTx, so a retry of the
    managed transaction uses the same one (TEN-002). With no scope bound there is no head to make:
    TenantNotBound is raised before a session opens (TEN-017, fail closed).
    """
    scope = scope_for_new_unit()
    if scope is None:
        raise TenantNotBound

    async def work(tx: AsyncManagedTransaction) -> None:
        await run_query(
            ScopedTx(tx, scope),
            REGISTRY.get("Q-AUDIT-ENSURE-HEAD"),
            genesis=genesis_hash_for(scope.value),
        )

    async with driver.session() as session:
        await session.execute_write(work)


def _bound_scope(tx: Tx) -> ScopeId:
    """The scope the chain is read or written in: the one the unit of work carries, or the one bound
    in the context for a raw transaction (the same one run_query uses). None is refused."""
    scope = tx.scope if isinstance(tx, ScopedTx) else current_scope_or_none()
    if scope is None:
        raise TenantNotBound
    return scope


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


_Edge = tuple[str, dict[str, Any], object]


def _instant_of(stored: object) -> datetime | None:
    """A stored Neo4j datetime as an aware UTC datetime, or None if it is not one."""
    native = stored.to_native() if hasattr(stored, "to_native") else stored
    if isinstance(native, datetime) and native.tzinfo is not None:
        return native.astimezone(UTC)
    return None


def _edge_key(kind: str, props: dict[str, Any], target: object) -> str:
    return canonical_json([kind, props, target])


def _expected_audit_edges(entry: AuditEntry) -> list[_Edge]:
    """The edges append writes for an entry: snapshot, touched ids and the agents."""
    edges: list[_Edge] = []
    if entry.snapshot is not None:
        snapshot_json = canonical_json(entry.snapshot)
        digest = hashlib.sha256(snapshot_json.encode()).hexdigest()
        edges.append(("SNAPSHOT", {}, f"{digest}|{snapshot_json}"))
    # MERGE writes one ENTITY edge per distinct id, however often the id repeats in the entry.
    distinct_ids = sorted(set(entry.entity_ids))
    edges.extend(("ENTITY", {"role": "subject"}, entity_id) for entity_id in distinct_ids)
    for agent_id in (entry.actor.practitioner_id, entry.actor.device_id):
        if agent_id is not None:
            agent_props = {"role": entry.actor.role.value, "requestor": True}
            edges.append(("AGENT", agent_props, agent_id))
    return edges


def _expected_provenance_edges(payload: dict[str, Any]) -> list[_Edge]:
    """The edges append_provenance writes: target, agent, activity and the optional source."""
    edges: list[_Edge] = [
        ("TARGET", {}, payload["target_id"]),
        (
            "AGENT",
            {"type": payload["agent_type"], "role": payload["agent_role"]},
            payload["agent_id"],
        ),
        ("ACTIVITY", {}, f"{ACTIVITY_CODE_SYSTEM}|{payload['activity']}"),
    ]
    if payload["source_communication_id"] is not None:
        edges.append(("ENTITY", {"role": "source"}, payload["source_communication_id"]))
    return edges


def _stored_node_matches(row: dict[str, Any]) -> bool:
    """A chain node must agree with its hashed text in every stored part: its own properties
    (including recorded), and its outgoing edges with their properties and targets. Anything the
    text does not account for is refused."""
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
            instant = entry.at.astimezone(UTC)
            expected_edges = _expected_audit_edges(entry)
        else:
            payload: dict[str, Any] = json.loads(text)
            extra: dict[str, Any] = payload["extra"]
            expected = {"id": payload["id"], "activity": payload["activity"], **extra}
            allowed = _PROVENANCE_PROPERTIES | set(extra)
            instant = datetime.strptime(payload["recorded"], TIME_FORMAT).replace(tzinfo=UTC)
            expected_edges = _expected_provenance_edges(payload)
    except ValueError, KeyError, TypeError:
        return False
    if not set(props) <= allowed:
        return False
    if not all(props.get(name) == value for name, value in expected.items()):
        return False
    if _instant_of(props.get("recorded")) != instant:
        return False
    actual = sorted(_edge_key(e["type"], e["props"] or {}, e["target"]) for e in row["edges"])
    return actual == sorted(
        _edge_key(kind, props_, target) for kind, props_, target in expected_edges
    )


class Neo4jAuditLog:
    """The audit log on the caller's transaction. Append-only: there is no update, delete or remove.

    ids defaults to a random UUID4 string and clock to the UTC system time. Provenance records take
    their `recorded` time from clock; audit entries take `at` from the entry.
    """

    def __init__(
        self,
        tx: Tx,
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
        rows = await run_query(self._tx, REGISTRY.get("Q-AUDIT-LOCK-HEAD"))
        if not rows:
            raise AuditHeadMissing(
                "the audit chain head does not exist; call ensure_audit_head at startup"
            )
        return str(rows[0]["lastHash"]), int(rows[0]["lastSeq"])

    async def _link_actor(self, record_id: str, actor: Actor) -> None:
        if actor.practitioner_id is not None:
            await run_query(
                self._tx,
                REGISTRY.get("Q-AUDIT-LINK-AGENT"),
                id=record_id,
                agentId=actor.practitioner_id,
                agentKind="Practitioner",
                role=actor.role.value,
            )
        if actor.device_id is not None:
            await run_query(
                self._tx,
                REGISTRY.get("Q-AUDIT-LINK-AGENT"),
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
            REGISTRY.get("Q-AUDIT-APPEND"),
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
                REGISTRY.get("Q-AUDIT-LINK-ENTITY"),
                id=record_id,
                entityIds=list(entry.entity_ids),
            )
        return AuditRecord(id=record_id, entry=entry, chain_hash=chain, previous_hash=previous)

    async def records(self, since: str | None = None) -> list[AuditRecord]:
        """Audit records in chain order. With since, only the records after that record's id."""
        rows = await run_query(self._tx, REGISTRY.get("Q-AUDIT-LIST"))
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
        """True when every link of the bound scope's chain is intact, in order, and its head points
        at the last link. Another scope's chain is not read, so it is not checked here."""
        genesis = genesis_hash_for(_bound_scope(self._tx).value)
        rows = await run_query(self._tx, REGISTRY.get("Q-AUDIT-CHAIN"))
        head_rows = await run_query(self._tx, REGISTRY.get("Q-AUDIT-HEAD"))
        if not head_rows:
            return not rows
        previous = genesis
        for index, row in enumerate(rows, start=1):
            if row["seq"] != index or row["previousHash"] != previous:
                return False
            if chain_hash_over(previous, str(row["entryJson"])) != row["chainHash"]:
                return False
            if not _stored_node_matches(row):
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
            REGISTRY.get("Q-PROV-APPEND"),
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
            REGISTRY.get("Q-PROV-LINK"),
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
                REGISTRY.get("Q-PROV-SOURCE"),
                id=prov_id,
                sourceId=source_communication_id,
            )
        return prov_id
