"""Neo4j idempotency store and processed-message markers (P15, DEC-012, DEC-090, DEC-001).

Layout, graph-native (no JSON text and no map-valued property is stored):

- (:IdempotencyRecord {key, resultType, createdAt}), key unique (migration 0029). createdAt is a
  Neo4j datetime written by the database in UTC.
- The result is a tree of (:IdempotencyValue {seq, kind, text, num, flag, at}) nodes, one per JSON
  value. The record reaches each one by [:HAS_VALUE]. Each value holds its scalar in one typed
  property: text for strings, num for numbers, flag for booleans, at for instants (a canonical UTC
  instant is a Neo4j datetime). The children of an array or object hang off it by
  [:MEMBER {position, name}], name set for object members only.
- (:Processed {key, messageId, consumer, processedAt}), key unique (migration 0030). key joins the
  consumer and the message id with the consumer's length, so no two pairs share a key. Neo4j
  Community 5.26.32 does enforce a composite key (probe, DEC-090 item 5); one property is used here
  as the guard for a simpler form, not because composite keys are unavailable.

A racing first write meets the unique key: its CREATE or MERGE fails with ConstraintError, which
is mapped to Conflict, so the unit of work that made it is refused and never commits (lesson L106).
"""

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Final, Literal
from uuid import uuid4

from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

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
from diucs.application.idempotency import (
    DATETIME_TAG,
    decode_result,
    encode_result,
    format_instant,
    parse_instant,
)
from diucs.application.tenancy import scope_for_new_unit
from diucs.domain.errors import Conflict

# The scenario of the one converted statement (DEC-142 item 5, DEC-150). A marker's key is composite
# with the tenant (migration 0031), so both tenants hold the same marker, and the scenario marks a
# message that no marker holds yet, so the node the statement creates must carry the tenant. The
# claim of the held marker is `Marked`, so the two tenants' markers differ. Residual (DEC-156 item
# 4): the key is declared `new`, so only the creation is run, not a match on a held key.
_PROCESSED_SCENARIO: Final = Scenario(
    "mark a message as processed by a consumer, once",
    seed=TenantSeed(
        nodes=(
            SeedNode(
                "done",
                ("Processed",),
                {
                    "key": "8:consumer:m-0",
                    "messageId": "m-0",
                    "consumer": "consumer",
                    "claim": Marked("claim"),
                },
            ),
        )
    ),
    params={
        "key": "8:consumer:m-1",
        "messageId": "m-1",
        "consumer": "consumer",
        "claim": "claim-1",
    },
    new=("key", "messageId", "claim"),
    expect=Expect(
        rows=({"created": True},),
        nodes={"Processed": 1},
        after=(
            NodeSpec(
                ("Processed",),
                {"key": "8:consumer:m-1", "messageId": "m-1"},
            ),
        ),
    ),
)

# The read that asks whether a marker is held (I08). The scenario seeds the marker for both tenants
# under one key, and the count is the tenant's own: a statement without the tenant would count two.
_SEEN_SCENARIO: Final = Scenario(
    "ask whether the tenant's own marker for a message is held",
    seed=_PROCESSED_SCENARIO.seed,
    params={"key": "8:consumer:m-0"},
    lookup=("key",),
    expect=Expect(rows=({"found": 1},)),
)

# The replay record and its value tree (TEN-016, DEC-130 item 6). A record is unique per tenant on
# (tenantId, key) (migration 0029, composite in 0031), and every value node of the tree carries the
# tenant too, so a read in one tenant never reaches another tenant's tree. The scenarios seed the
# same key for both tenants: a statement that forgot the tenant would find the other tenant's
# record, or its value nodes, and the generated test reports it.
_TREE_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "record",
            ("IdempotencyRecord",),
            {"key": "k-0", "resultType": Marked("type")},
        ),
        SeedNode("root", ("IdempotencyValue",), {"seq": 0, "kind": "object"}),
        SeedNode(
            "name",
            ("IdempotencyValue",),
            {"seq": 1, "kind": "string", "text": Marked("text")},
        ),
    ),
    rels=(
        SeedRel("record", "HAS_VALUE", "root"),
        SeedRel("record", "HAS_VALUE", "name"),
    ),
)
_LINKED_SEED: Final = TenantSeed(
    nodes=_TREE_SEED.nodes,
    rels=(*_TREE_SEED.rels, SeedRel("root", "MEMBER", "name", {"name": "label", "position": 0})),
)
_HEAD_SCENARIO: Final = Scenario(
    "read the result type of the tenant's own record for a key",
    seed=_TREE_SEED,
    params={"key": "k-0"},
    lookup=("key",),
    expect=Expect(rows=({"resultType": Marked("type")},)),
)
_VALUES_SCENARIO: Final = Scenario(
    "read the tenant's own value nodes of a record and no other tenant's",
    seed=_TREE_SEED,
    params={"key": "k-0"},
    lookup=("key",),
    expect=Expect(
        rows=(
            {"seq": 0, "kind": "object"},
            {"seq": 1, "kind": "string", "text": Marked("text")},
        )
    ),
)
_EDGES_SCENARIO: Final = Scenario(
    "read the member edges of the tenant's own record and no other tenant's",
    seed=_LINKED_SEED,
    params={"key": "k-0"},
    lookup=("key",),
    expect=Expect(rows=({"parent": 0, "child": 1, "name": "label", "position": 0},)),
)
_CREATE_SCENARIO: Final = Scenario(
    "store a one-value result for a new key beside the tenant's own record",
    seed=_TREE_SEED,
    params={
        "key": "k-1",
        "resultType": "type-new",
        "values": [{"seq": 0, "kind": "null", "text": None, "num": None, "flag": None, "at": None}],
    },
    new=("key", "resultType", "values"),
    expect=Expect(
        rows=({"written": 1},),
        nodes={"IdempotencyRecord": 1, "IdempotencyValue": 1},
        # The statement joins the new record to each new value node it creates (both stamped with
        # the tenant): one value here, so one HAS_VALUE. The declaration was missing, not a leak.
        rels={"HAS_VALUE": 1},
        after=(NodeSpec(("IdempotencyRecord",), {"key": "k-1"}),),
    ),
)
_LINK_SCENARIO: Final = Scenario(
    "link two values of the tenant's own record and no other tenant's",
    seed=_TREE_SEED,
    params={
        "key": "k-0",
        "edges": [{"parent": 0, "child": 1, "name": "label", "position": 0}],
    },
    lookup=("key",),
    new=("edges",),
    expect=Expect(rows=({"linked": 1},), rels={"MEMBER": 1}),
)

# Each statement, its mode and its scenario (DEC-142 item 5). The replay record statements are
# converted by TEN-016; the processed-message statements (converted by TEN-004) are listed too.
_QUERIES: dict[str, tuple[str, Literal["read", "write"], Scenario | None]] = {
    "Q-IDEM-HEAD": (
        "MATCH (r:IdempotencyRecord {key: $key, tenantId: $tenant}) "
        "RETURN r.resultType AS resultType",
        "read",
        _HEAD_SCENARIO,
    ),
    "Q-IDEM-VALUES": (
        "MATCH (r:IdempotencyRecord {key: $key, tenantId: $tenant})-[:HAS_VALUE]->"
        "(v:IdempotencyValue {tenantId: $tenant}) "
        "RETURN v.seq AS seq, v.kind AS kind, v.text AS text, v.num AS num, v.flag AS flag, "
        "v.at AS at",
        "read",
        _VALUES_SCENARIO,
    ),
    "Q-IDEM-EDGES": (
        "MATCH (r:IdempotencyRecord {key: $key, tenantId: $tenant})-[:HAS_VALUE]->"
        "(p:IdempotencyValue {tenantId: $tenant})-[e:MEMBER]->"
        "(c:IdempotencyValue {tenantId: $tenant}) "
        "RETURN p.seq AS parent, c.seq AS child, e.name AS name, e.position AS position",
        "read",
        _EDGES_SCENARIO,
    ),
    "Q-IDEM-CREATE": (
        "CREATE (r:IdempotencyRecord {key: $key, resultType: $resultType, "
        "createdAt: datetime({timezone: 'UTC'}), tenantId: $tenant}) "
        "WITH r UNWIND $values AS row "
        "CREATE (v:IdempotencyValue {seq: row.seq, kind: row.kind, text: row.text, "
        "num: row.num, flag: row.flag, at: row.at, tenantId: $tenant}) "
        "CREATE (r)-[:HAS_VALUE]->(v) "
        "RETURN count(v) AS written",
        "write",
        _CREATE_SCENARIO,
    ),
    "Q-IDEM-LINK": (
        "UNWIND $edges AS e "
        "MATCH (r:IdempotencyRecord {key: $key, tenantId: $tenant})-[:HAS_VALUE]->"
        "(p:IdempotencyValue {seq: e.parent, tenantId: $tenant}) "
        "MATCH (r)-[:HAS_VALUE]->(c:IdempotencyValue {seq: e.child, tenantId: $tenant}) "
        "CREATE (p)-[:MEMBER {name: e.name, position: e.position}]->(c) "
        "RETURN count(c) AS linked",
        "write",
        _LINK_SCENARIO,
    ),
    "Q-PROCESSED-MARK": (
        "MERGE (p:Processed {key: $key, tenantId: $tenant}) "
        "ON CREATE SET p.messageId = $messageId, p.consumer = $consumer, "
        "p.processedAt = datetime({timezone: 'UTC'}), p.claim = $claim "
        "WITH p, p.claim = $claim AS created "
        "REMOVE p.claim "
        "RETURN coalesce(created, false) AS created",
        "write",
        _PROCESSED_SCENARIO,
    ),
    "Q-PROCESSED-SEEN": (
        "MATCH (p:Processed {key: $key, tenantId: $tenant}) RETURN count(p) AS found",
        "read",
        _SEEN_SCENARIO,
    ),
}

for _query_id, (_cypher, _mode, _scenario) in _QUERIES.items():
    REGISTRY.register(NamedQuery(id=_query_id, cypher=_cypher, mode=_mode, scenario=_scenario))


def _processed_key(message_id: str, consumer: str) -> str:
    # Length-prefixed consumer: the key cannot be split two ways, whatever the two values contain.
    return f"{len(consumer)}:{consumer}:{message_id}"


def _flatten(tree: object) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One value row per JSON value (root is seq 0) and one edge row per member or item."""
    values: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def visit(node: object) -> int:
        seq = len(values)
        row: dict[str, Any] = {
            "seq": seq,
            "kind": "",
            "text": None,
            "num": None,
            "flag": None,
            "at": None,
        }
        values.append(row)
        if node is None:
            row["kind"] = "null"
        elif isinstance(node, bool):
            row["kind"], row["flag"] = "boolean", node
        elif isinstance(node, (int, float)):
            row["kind"], row["num"] = "number", node
        elif isinstance(node, str):
            row["kind"], row["text"] = "string", node
        elif isinstance(node, list):
            row["kind"] = "array"
            for position, item in enumerate(node):
                edges.append(
                    {"parent": seq, "child": visit(item), "name": None, "position": position}
                )
        elif isinstance(node, dict) and set(node) == {DATETIME_TAG}:
            row["kind"] = "instant"
            row["at"] = parse_instant(str(node[DATETIME_TAG]))
        elif isinstance(node, dict):
            row["kind"] = "object"
            for position, (name, item) in enumerate(node.items()):
                edges.append(
                    {"parent": seq, "child": visit(item), "name": name, "position": position}
                )
        else:
            raise ValueError("a stored value must be JSON")
        return seq

    visit(tree)
    return values, edges


def _rebuild(values: list[dict[str, Any]], edges: list[dict[str, Any]]) -> object:
    by_seq = {row["seq"]: row for row in values}
    children: defaultdict[int, list[tuple[int, str | None, int]]] = defaultdict(list)
    for edge in edges:
        children[edge["parent"]].append((edge["position"], edge["name"], edge["child"]))

    def build(seq: int) -> object:
        row = by_seq[seq]
        kind = row["kind"]
        if kind == "null":
            return None
        if kind == "boolean":
            return bool(row["flag"])
        if kind == "number":
            return row["num"]
        if kind == "string":
            return row["text"]
        if kind == "instant":
            return {DATETIME_TAG: format_instant(_native(row["at"]))}
        ordered = sorted(children[seq], key=lambda entry: entry[0])
        if kind == "array":
            return [build(child) for _, _, child in ordered]
        return {name: build(child) for _, name, child in ordered}

    return build(0)


def _native(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    to_native = getattr(value, "to_native", None)
    if to_native is None:
        raise ValueError("a stored instant must be a Neo4j datetime")
    native = to_native()
    if not isinstance(native, datetime):
        raise ValueError("a stored instant must be a Neo4j datetime")
    return native


async def _read_record(tx: Tx, key: str) -> tuple[str, str] | None:
    """(resultType, canonical JSON text) of a stored record, or None. Read-only."""
    head = await run_query(tx, REGISTRY.get("Q-IDEM-HEAD"), key=key)
    if not head:
        return None
    values = await run_query(tx, REGISTRY.get("Q-IDEM-VALUES"), key=key)
    edges = await run_query(tx, REGISTRY.get("Q-IDEM-EDGES"), key=key)
    tree = _rebuild(values, edges)
    text = json.dumps(tree, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return str(head[0]["resultType"]), text


class Neo4jIdempotencyStore:
    """Command replay on one unit of work's transaction (P15, DEC-090). The transaction is a
    ScopedTx on the unit of work, so every statement runs in the tenant the unit opened with."""

    def __init__(self, tx: Tx) -> None:
        self._tx = tx

    async def get(self, key: str) -> object | None:
        stored = await _read_record(self._tx, key)
        if stored is None:
            return None
        result_type, json_text = stored
        return decode_result(result_type, json_text)

    async def put(self, key: str, result: object) -> None:
        """Store the first result of a key. The same result again changes nothing. A different
        result for a key already stored is Conflict, and so is a racing first write (the unique
        key refuses the second CREATE)."""
        result_type, json_text = encode_result(result)
        stored = await _read_record(self._tx, key)
        if stored is not None:
            if stored == (result_type, json_text):
                return
            raise Conflict("a different result is already stored for this command key")
        values, edges = _flatten(json.loads(json_text))
        try:
            await run_query(
                self._tx,
                REGISTRY.get("Q-IDEM-CREATE"),
                key=key,
                resultType=result_type,
                values=values,
            )
            await run_query(self._tx, REGISTRY.get("Q-IDEM-LINK"), key=key, edges=edges)
        except ConstraintError as error:
            raise Conflict("a result for this command key was stored first") from error


class Neo4jProcessedMessages:
    """Consumer idempotency: (messageId, consumer) is handled once (P15, DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def mark_if_new(self, message_id: str, consumer: str) -> bool:
        """True when this call created the marker; False when it already existed. A racing first
        mark is refused with Conflict (the unique key), so the caller must not commit."""
        try:
            rows = await run_query(
                self._tx,
                REGISTRY.get("Q-PROCESSED-MARK"),
                key=_processed_key(message_id, consumer),
                messageId=message_id,
                consumer=consumer,
                claim=uuid4().hex,
            )
        except ConstraintError as error:
            raise Conflict("this message is being processed by another unit of work") from error
        return bool(rows[0]["created"])

    async def seen(self, message_id: str, consumer: str) -> bool:
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-PROCESSED-SEEN"),
            key=_processed_key(message_id, consumer),
        )
        return int(rows[0]["found"]) > 0


class DriverIdempotencyStore:
    """The idempotency store for constructor injection: each call runs in its own transaction on
    the process's driver, and its session is always closed (DEC-012)."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    async def get(self, key: str) -> object | None:
        # The scope is read once, here, before the session opens: a managed-transaction retry runs
        # the callback again and must use the same one (TEN-002).
        scope = scope_for_new_unit()

        async def read(tx: AsyncManagedTransaction) -> object | None:
            return await Neo4jIdempotencyStore(ScopedTx(tx, scope)).get(key)

        async with self._driver.session() as session:
            return await session.execute_read(read)

    async def put(self, key: str, result: object) -> None:
        scope = scope_for_new_unit()

        async def write(tx: AsyncManagedTransaction) -> None:
            await Neo4jIdempotencyStore(ScopedTx(tx, scope)).put(key, result)

        async with self._driver.session() as session:
            await session.execute_write(write)
