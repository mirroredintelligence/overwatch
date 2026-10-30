"""Graph writer and reader for FHIR resources, with versions (G05, rule R10, DEC-053).

ResourceStore(tx, clock) works inside the caller's transaction. put() decomposes one resource with
the mapper and writes the fragment; get() and history() rebuild resources from the graph alone
(DEC-001: no json property anywhere). Nothing is dropped, overwritten or moved (DEC-049): a value
that would not read back identically is refused with ValidationFailed before the graph changes.

Layout. Every node written here has a `key` property: the mapper's NodeSpec.key (`Type/id` for a
resource, `<parent>#<element>[i]` for a backbone child, `Concept|...`, `Identifier|...`,
`CodeSystem|...` for shared nodes). A version is a `ResourceVersion` node keyed `Type/id@<version>`,
a copy of the owned nodes and their relationships, linked from the resource by HAS_VERSION.

Writers are serialised by a write on the resource's root node (Q-RES-LOCK): a second writer waits
for the first to commit, then reads the committed version, so a stale expected version is Conflict.
Named queries run through driver.run_query. A query that needs a label or a relationship type from
data is registered on first use under its template id plus that label or type (for example
Q-RES-UPSERT-NODE:Organization). Its text is built only from names that passed a check.

Tenancy (TEN-009, DEC-164). Every node written here carries `tenantId`, the tenant of the unit of
work, stamped by the statement from the bound scope: the resource root, its backbone children, the
version copies, the placeholders for reference targets, and the Concept, CodeSystem and Identifier
nodes, which are the tenant's own (DEC-134 item 1). Every statement matches on it, so another
tenant's resource reads as absent (`get` returns None, `exists` is False, `history` is empty) and a
put creates the tenant's own. A resource cannot carry the stamp: the mapper refuses the name and the
store refuses and strips it too (`RESERVED_PROPERTIES`).
"""

import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ClientError
from neo4j.time import Date, DateTime, Time

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.extensions import TENANT_OWNED_NAMES
from diucs.adapters.outbound.graph_store.mapper import (
    GraphFragment,
    NodeSpec,
    RelSpec,
    from_graph,
    to_graph,
)
from diucs.adapters.outbound.graph_store.migrations_tenant import REGISTRY_LABELS
from diucs.adapters.outbound.graph_store.queries import (
    GLOBAL_STATEMENT_LABELS,
    REGISTRY,
    QueryTemplate,
)
from diucs.adapters.outbound.graph_store.resource_scenarios import SCENARIOS
from diucs.application.ports.outbound.clock import Clock
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed

# DEC-053 item 3: these types keep no ResourceVersion, so a cleared value is gone everywhere.
NO_HISTORY_TYPES = frozenset({"Patient", "ServiceRequest"})
# Observations are facts: a second put is refused, never an update.
NEVER_UPDATED_TYPES = frozenset({"Observation"})
# Names the store uses for its own properties, and the names of the tenancy seam. An element with
# one of these names is refused, and they are left out of what is read back (TEN-009, DEC-164).
RESERVED_PROPERTIES = frozenset(
    {"key", "placeholder", "lockStamp", "position", *TENANT_OWNED_NAMES}
)
# Local relationships that are not FHIR elements, so they have no fhirPath (DEC-065 item 5,
# DEC-076 item 2 for CURRENT_CRITERIA). HAS_CREDENTIAL and HAS_DEVICE hang a practitioner's PIN
# credential and registered devices from it (P16, U32): the credential store writes them, the
# resource is not made of them, so a read leaves them out and a save leaves them in place.
LOCAL_RELATIONSHIP_TYPES = frozenset(
    {"CHANNEL", "COVERED_BY", "CURRENT_CRITERIA", "HAS_CREDENTIAL", "HAS_DEVICE"}
)

_TYPE = re.compile(r"[A-Z][A-Za-z0-9]{0,63}")
# A reference makes a placeholder labelled with its type, so a type is letters only with a capital.
_REFERENCE_TYPE = re.compile(r"[A-Z][A-Za-z]{0,63}")
# Labels no resource or reference may take (DEC-164 item 11): the registry labels (the global
# statements read them with no tenant bound) and the store's own labels.
_STORE_LABELS = frozenset(
    {"Resource", "ResourceVersion", "ResourceVersionPart", "Concept", "CodeSystem", "Identifier"}
)
_FORBIDDEN_TYPES = frozenset(REGISTRY_LABELS) | GLOBAL_STATEMENT_LABELS | _STORE_LABELS
_LABEL = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}")
_FHIR_ID = re.compile(r"[A-Za-z0-9.\-]{1,64}")
_SHARED_PREFIXES = ("Concept|", "Identifier|", "CodeSystem|")
_SHARED_FILLABLE = ("display", "version")
_HAS_VERSION = "HAS_VERSION"

_DATETIME = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})"
)
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?")
_PARTIAL = re.compile(r"\d{4}-\d{2}")

# Query templates. {insert} is a label list (":Organization") or a relationship type (":HAS_X").
#
# Tenancy (TEN-009, DEC-164). Every node pattern names `tenantId: $tenant`, so a statement reads,
# changes and creates only the bound tenant's nodes, and every node it writes is stamped. A write
# that replaces a node's properties (`SET n = row.props`) sets `n.tenantId = $tenant` straight
# after, because the replacement would erase the stamp; the properties it replaces with come from
# the mapper, which refuses the name `tenantId` (TEN-008). A match is typed (by the label it can
# only be: the resource root, a shared label, a version) or reaches its nodes from a typed root.
#
# Children are the nodes whose key starts with the root's key and `#`. They are reached from the
# tenant's root along relationships, through nodes of that prefix only (a quantified path pattern),
# so the statement never looks at another resource's or another tenant's nodes. A relationship
# belongs to the tenant of the nodes it joins and never joins two tenants (DEC-130 item 1), so
# `Q-RES-CLEAR-ROOT-RELS` anchors the root alone: it clears every relationship a resource starts,
# whatever it points at, as it always has (a CHANNEL to a concept another statement wrote).
_TEMPLATES: dict[str, tuple[str, Literal["read", "write"]]] = {
    "Q-RES-LOCK": (
        "MERGE (n:Resource {key: $key, tenantId: $tenant}) "
        "ON CREATE SET n.id = $id, n.placeholder = true "
        "SET n{insert} SET n.lockStamp = $stamp RETURN count(n) AS locked",
        "write",
    ),
    "Q-RES-GET": (
        "MATCH (n:Resource {key: $key, tenantId: $tenant}) WHERE $type IN labels(n) "
        "RETURN properties(n) AS props",
        "read",
    ),
    "Q-RES-UPSERT-ROOT": (
        "UNWIND $rows AS row MERGE (n{insert} {key: row.key, tenantId: $tenant}) "
        "SET n = row.props, n.tenantId = $tenant RETURN count(n) AS written",
        "write",
    ),
    "Q-RES-UPSERT-NODE": (
        "UNWIND $rows AS row MERGE (n{insert} {key: row.key, tenantId: $tenant}) "
        "SET n = row.props, n.tenantId = $tenant RETURN count(n) AS written",
        "write",
    ),
    "Q-RES-SHARED-READ": (
        "UNWIND $keys AS k "
        "MATCH (n:Concept|Identifier|CodeSystem {key: k, tenantId: $tenant}) "
        "RETURN n.key AS key, properties(n) AS props",
        "read",
    ),
    "Q-RES-SHARED-CREATE": (
        "UNWIND $rows AS row MERGE (n{insert} {key: row.key, tenantId: $tenant}) "
        "ON CREATE SET n = row.props, n.tenantId = $tenant RETURN count(n) AS written",
        "write",
    ),
    "Q-RES-SHARED-FILL": (
        "MATCH (n:Concept|Identifier|CodeSystem {key: $key, tenantId: $tenant}) "
        "SET n += $fill RETURN count(n) AS filled",
        "write",
    ),
    "Q-RES-MERGE-NODES": (
        "UNWIND $rows AS row MERGE (n:Resource {key: row.key, tenantId: $tenant}) "
        "ON CREATE SET n.id = row.id, n.placeholder = true SET n{insert} "
        "RETURN count(n) AS written",
        "write",
    ),
    "Q-RES-CLEAR-OWNED": (
        "MATCH (r:Resource {key: $key, tenantId: $tenant}) "
        "MATCH (r) (()-[]->(c {tenantId: $tenant} WHERE c.key STARTS WITH $prefix))+ () "
        "UNWIND c AS node WITH DISTINCT node WHERE NOT node:Resource AND NOT node:ResourceVersion "
        "DETACH DELETE node RETURN count(*) AS cleared",
        "write",
    ),
    "Q-RES-CLEAR-ROOT-RELS": (
        "MATCH (r:Resource {key: $key, tenantId: $tenant})-[rel]->() "
        "WHERE NOT type(rel) IN ['HAS_VERSION', 'HAS_CREDENTIAL', 'HAS_DEVICE'] "
        "DELETE rel RETURN count(*) AS cleared",
        "write",
    ),
    "Q-RES-MERGE-RELS": (
        "UNWIND $rows AS row MATCH (a {key: row.start, tenantId: $tenant}) "
        "MATCH (b {key: row.end, tenantId: $tenant}) "
        "CREATE (a)-[r{insert}]->(b) SET r = row.props RETURN count(r) AS created",
        "write",
    ),
    "Q-RES-LINK-SHARED": (
        "UNWIND $rows AS row MATCH (a:Concept {key: row.start, tenantId: $tenant}) "
        "MATCH (b:CodeSystem {key: row.end, tenantId: $tenant}) "
        "MERGE (a)-[r{insert}]->(b) RETURN count(DISTINCT [a.key, b.key]) AS linked",
        "write",
    ),
    "Q-RES-SET-POSITION": (
        "MATCH (n:Location {key: $key, tenantId: $tenant}) WHERE n.positionLatitude IS NOT NULL "
        "AND n.positionLongitude IS NOT NULL "
        "SET n.position = point({latitude: n.positionLatitude, longitude: n.positionLongitude}) "
        "RETURN count(n) AS positioned",
        "write",
    ),
    "Q-RES-LOAD-NODES": (
        "MATCH (res:Resource {key: $resourceKey, tenantId: $tenant}) "
        "MATCH (res)-[:HAS_VERSION*0..1]->(r{insert} {key: $key, tenantId: $tenant}) "
        "OPTIONAL MATCH (r) "
        "(()-[]->(c {tenantId: $tenant} WHERE c.key STARTS WITH $prefix))+ () "
        "WITH r, reduce(acc = [], p IN collect(c) | acc + p) AS kids "
        "UNWIND [r] + kids AS x WITH DISTINCT x AS o "
        "RETURN labels(o) AS labels, properties(o) AS props",
        "read",
    ),
    "Q-RES-LOAD-RELS": (
        "MATCH (res:Resource {key: $resourceKey, tenantId: $tenant}) "
        "MATCH (res)-[:HAS_VERSION*0..1]->(r{insert} {key: $key, tenantId: $tenant}) "
        "OPTIONAL MATCH (r) "
        "(()-[]->(c {tenantId: $tenant} WHERE c.key STARTS WITH $prefix))+ () "
        "WITH r, reduce(acc = [], p IN collect(c) | acc + p) AS kids "
        "UNWIND [r] + kids AS x WITH DISTINCT x AS o "
        "MATCH (o)-[rel]->(t {tenantId: $tenant}) WHERE type(rel) <> 'HAS_VERSION' "
        "RETURN o.key AS start, type(rel) AS type, properties(rel) AS props, t.key AS end, "
        "labels(t) AS endLabels, "
        "CASE WHEN t:Resource OR t:ResourceVersion THEN null ELSE properties(t) END AS endProps",
        "read",
    ),
    "Q-RES-HISTORY": (
        "MATCH (r:Resource {key: $key, tenantId: $tenant})-[h:HAS_VERSION]->"
        "(v:ResourceVersion {tenantId: $tenant}) "
        "RETURN v.key AS key, h.versionId AS versionId",
        "read",
    ),
}

# The templates are fixed text, registered once at import; an instance (the template with one label
# chain or relationship type in it) is registered the first time it is used (DEC-142).
for _template_id, (_cypher, _mode) in _TEMPLATES.items():
    REGISTRY.register_template(
        QueryTemplate(id=_template_id, cypher=_cypher, mode=_mode, scenario=SCENARIOS[_template_id])
    )


def _labels_text(labels: tuple[str, ...]) -> str:
    """The label list of a query. A name that is not a plain label is refused."""
    for label in labels:
        if not _LABEL.fullmatch(label):
            raise ValidationFailed("label", "not a plain Neo4j label name")
    return "".join(f":{label}" for label in labels)


def _is_owned(node_key: str, root_key: str) -> bool:
    return node_key == root_key or node_key.startswith(f"{root_key}#")


def _is_shared_key(key: str) -> bool:
    return key.startswith(_SHARED_PREFIXES)


def _is_reference_key(key: str) -> bool:
    return not key.startswith(_SHARED_PREFIXES) and "#" not in key


def _check_type(type_: str) -> None:
    if not _TYPE.fullmatch(type_):
        raise ValidationFailed("resourceType", "not a FHIR resource type")


def _check_reference_type(key: str) -> None:
    """A reference target `Type/id` must name a plain resource type that is not a label other
    statements read. Nothing of the value is repeated in the error."""
    target_type = key.partition("/")[0]
    if not _REFERENCE_TYPE.fullmatch(target_type) or target_type in _FORBIDDEN_TYPES:
        raise ValidationFailed("reference", "not a resource type this store can link to")


def _check_identity(type_: Any, id_: Any) -> tuple[str, str]:
    if not isinstance(type_, str) or not _TYPE.fullmatch(type_) or type_ in _FORBIDDEN_TYPES:
        raise ValidationFailed("resourceType", "not a FHIR resource type")
    if not isinstance(id_, str) or not _FHIR_ID.fullmatch(id_):
        raise ValidationFailed("id", "not a FHIR id")
    return type_, id_


def _nanos(fraction: str | None) -> int:
    return int(fraction.ljust(9, "0")) if fraction else 0


def _fraction_text(nanos: int) -> str:
    return f".{nanos:09d}".rstrip("0") if nanos else ""


def _zone_text(offset: timedelta) -> str:
    if offset == timedelta(0):
        return "Z"
    minutes = int(offset.total_seconds()) // 60
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _format(value: Any) -> str:
    """The FHIR text of a stored date, time or datetime. A zero offset reads back as Z."""
    if isinstance(value, DateTime):
        offset = value.utcoffset()
        if offset is None:
            raise ValidationFailed("datetime", "stored without a zone")
        return (
            f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
            f"T{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
            f"{_fraction_text(value.nanosecond)}{_zone_text(offset)}"
        )
    if isinstance(value, Date):
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
    if isinstance(value, Time):
        return (
            f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
            f"{_fraction_text(value.nanosecond)}"
        )
    raise ValidationFailed("value", "not a date, time or datetime")


def _text_to_db(text: str, field: str) -> Any:
    """A FHIR date, time or datetime becomes the Neo4j type, but only if it reads back identically.

    A partial date (2026-10) has no Neo4j type that keeps its precision, so it is refused."""
    try:
        if match := _DATETIME.fullmatch(text):
            year, month, day, hour, minute, second = (int(group) for group in match.groups()[:6])
            zone = match.group(8)
            if zone == "Z":
                tzinfo: timezone = UTC
            else:
                sign = 1 if zone[0] == "+" else -1
                offset = timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
                tzinfo = timezone(sign * offset)
            value: Any = DateTime(
                year, month, day, hour, minute, second, _nanos(match.group(7)), tzinfo=tzinfo
            )
        elif match := _DATE.fullmatch(text):
            value = Date(*(int(group) for group in match.groups()))
        elif match := _TIME.fullmatch(text):
            hour, minute, second = (int(group) for group in match.groups()[:3])
            value = Time(hour, minute, second, _nanos(match.group(4)))
        elif _PARTIAL.match(text):
            raise ValidationFailed(field, "a partial date is refused: give the full value")
        else:
            return text
    except ValueError as error:
        raise ValidationFailed(field, "not a valid date, time or datetime") from error
    if _format(value) != text:
        raise ValidationFailed(field, "the zone or precision would not read back identically")
    return value


def _to_db(value: Any, field: str) -> Any:
    if isinstance(value, str):
        return _text_to_db(value, field)
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, list):
        return [_to_db(item, field) for item in value]
    raise ValidationFailed(field, "only primitives and lists of primitives can be stored")


def _from_db(value: Any) -> Any:
    if isinstance(value, DateTime | Date | Time):
        return _format(value)
    if isinstance(value, list):
        return [_from_db(item) for item in value]
    if isinstance(value, bool | int | float | str):
        return value
    raise ValidationFailed("value", "unexpected stored type")


def _props_to_db(props: dict[str, Any]) -> dict[str, Any]:
    return {name: _to_db(value, name) for name, value in props.items()}


def _node_props_to_db(key: str, props: dict[str, Any]) -> dict[str, Any]:
    for name in props:
        if name in RESERVED_PROPERTIES:
            raise ValidationFailed(name, "reserved: the store uses this name")
    return {**_props_to_db(props), "key": key}


def _props_from_db(props: dict[str, Any]) -> dict[str, Any]:
    """FHIR properties of a stored node or relationship. The store's own properties are left out."""
    return {
        name: _from_db(value) for name, value in props.items() if name not in RESERVED_PROPERTIES
    }


class ResourceStore:
    def __init__(self, tx: AsyncManagedTransaction, clock: Clock | None = None) -> None:
        self._tx = tx
        self._clock = clock

    async def put(self, resource: dict[str, Any], expected_version: str | None) -> str:
        """Write the resource and return its new version.

        expected_version None creates it (Conflict if it exists). A string replaces that version
        (Conflict if the stored version differs). An existing Observation raises NotAllowed. The
        resource is the bound tenant's: the same id in another tenant is another resource.
        """
        if "meta" in resource:
            raise ValidationFailed("meta", "the store sets meta; omit it")
        resource_type, resource_id = _check_identity(
            resource.get("resourceType"), resource.get("id")
        )
        key = f"{resource_type}/{resource_id}"
        try:
            return await self._put(resource, resource_type, resource_id, key, expected_version)
        except ClientError as error:
            if str(getattr(error, "code", "")).endswith("ConstraintValidationFailed"):
                raise Conflict(f"{key} was written by another request") from error
            raise

    async def get(self, type: str, id: str) -> dict[str, Any] | None:
        _check_type(type)
        key = f"{type}/{id}"
        if await self._root_props(type, key) is None:
            return None
        return from_graph(await self._load(key, type))

    async def history(self, type: str, id: str) -> list[dict[str, Any]]:
        _check_type(type)
        rows = await self._run("Q-RES-HISTORY", key=f"{type}/{id}")
        ordered = sorted(rows, key=lambda row: int(row["versionId"]))
        return [from_graph(await self._load(row["key"], type, version=True)) for row in ordered]

    async def exists(self, type: str, id: str) -> bool:
        _check_type(type)
        return await self._root_props(type, f"{type}/{id}") is not None

    # Writing

    async def _put(
        self,
        resource: dict[str, Any],
        resource_type: str,
        resource_id: str,
        key: str,
        expected_version: str | None,
    ) -> str:
        stamp = self._stamp()
        # Refusals on the input, the shared nodes and the version come before the lock write, so a
        # refused put leaves nothing in the graph, not even a lock node.
        nodes, _ = self._fragment(resource, key, "1", stamp)
        await self._plan_shared([node for node in nodes if not _is_owned(node.key, key)])
        before = await self._root_props(resource_type, key)
        self._next_version(resource_type, key, before, expected_version)

        # The lock write makes a concurrent writer wait, then the read sees the committed version.
        await self._run(
            "Q-RES-LOCK",
            insert=_labels_text((resource_type,)),
            key=key,
            id=resource_id,
            stamp=uuid.uuid4().hex,
        )
        current = await self._root_props(resource_type, key)
        new_version = self._next_version(resource_type, key, current, expected_version)
        nodes, rels = self._fragment(resource, key, new_version, stamp)
        owned = [node for node in nodes if _is_owned(node.key, key)]
        shared = [node for node in nodes if not _is_owned(node.key, key)]
        plan = await self._plan_shared(shared)
        node_keys = {node.key for node in nodes}
        placeholders = {
            rel.end for rel in rels if _is_reference_key(rel.end) and rel.end not in node_keys
        }

        if current is not None and resource_type not in NO_HISTORY_TYPES:
            old = await self._load(key, resource_type)
            await self._write_snapshot(key, str(current["versionId"]), old)
        await self._run("Q-RES-CLEAR-OWNED", key=key, prefix=f"{key}#")
        await self._run("Q-RES-CLEAR-ROOT-RELS", key=key)
        await self._write_nodes(owned)
        await self._apply_shared(plan)
        await self._write_placeholders(placeholders)
        await self._write_rels([rel for rel in rels if not _is_shared_key(rel.start)])
        await self._link_shared([rel for rel in rels if _is_shared_key(rel.start)])
        if resource_type == "Location":
            await self._run("Q-RES-SET-POSITION", key=key)
        return new_version

    @staticmethod
    def _next_version(
        resource_type: str, key: str, current: dict[str, Any] | None, expected_version: str | None
    ) -> str:
        if current is not None and resource_type in NEVER_UPDATED_TYPES:
            raise NotAllowed(f"{resource_type} is never updated: write a new one")
        if current is None:
            if expected_version is not None:
                raise Conflict(f"{key} does not exist at version {expected_version}")
            return "1"
        current_version = str(current["versionId"])
        if expected_version is None:
            raise Conflict(f"{key} exists: state the version it replaces")
        if expected_version != current_version:
            raise Conflict(f"{key} is at version {current_version}, not {expected_version}")
        return str(int(current_version) + 1)

    def _fragment(
        self, resource: dict[str, Any], key: str, version: str, stamp: str
    ) -> tuple[list[NodeSpec], list[RelSpec]]:
        """The mapper fragment with its stored values converted. Every refusal on a value raises
        here, before any write."""
        body = {**resource, "meta": {"versionId": version, "lastUpdated": stamp}}
        fragment = to_graph(body)
        for rel in fragment.rels:
            if _is_reference_key(rel.end):
                _check_reference_type(rel.end)
        nodes = [
            NodeSpec(node.key, node.labels, _node_props_to_db(node.key, node.properties))
            for node in fragment.nodes
        ]
        rels = [
            RelSpec(rel.type, rel.start, rel.end, _props_to_db(rel.properties))
            for rel in fragment.rels
        ]
        return nodes, rels

    def _stamp(self) -> str:
        now = self._clock.now() if self._clock is not None else datetime.now(UTC)
        return now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    async def _write_snapshot(self, key: str, version: str, old: GraphFragment) -> None:
        """Copy the owned nodes and relationships of the current state under the version key."""
        snapshot = f"{key}@{version}"

        def rekey(node_key: str) -> str:
            return snapshot + node_key[len(key) :] if _is_owned(node_key, key) else node_key

        nodes: list[NodeSpec] = []
        for node in old.nodes:
            if not _is_owned(node.key, key):
                continue
            # Copies carry their own labels, so a query for a live type or child never sees history.
            labels = ("ResourceVersion",) if node.key == key else ("ResourceVersionPart",)
            copy_key = rekey(node.key)
            nodes.append(NodeSpec(copy_key, labels, _node_props_to_db(copy_key, node.properties)))
        rels = [
            RelSpec(rel.type, rekey(rel.start), rekey(rel.end), _props_to_db(rel.properties))
            for rel in old.rels
            if _is_owned(rel.start, key)
        ]
        rels.append(RelSpec(_HAS_VERSION, key, snapshot, {"versionId": version}))
        await self._write_nodes(nodes)
        await self._write_rels(rels)

    async def _write_nodes(self, nodes: list[NodeSpec]) -> None:
        groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for node in nodes:
            groups.setdefault(node.labels, []).append({"key": node.key, "props": node.properties})
        for labels, rows in groups.items():
            template = "Q-RES-UPSERT-ROOT" if labels[0] == "Resource" else "Q-RES-UPSERT-NODE"
            await self._run(template, insert=_labels_text(labels), rows=rows)

    async def _plan_shared(self, nodes: list[NodeSpec]) -> tuple[list[NodeSpec], list[Any]]:
        """Shared Concept, Identifier and CodeSystem nodes are never overwritten (L59). A display
        or version that is missing is filled in. A different one is refused, and nothing changes."""
        if not nodes:
            return [], []
        rows = await self._run("Q-RES-SHARED-READ", keys=[node.key for node in nodes])
        existing = {row["key"]: row["props"] for row in rows}
        create: list[NodeSpec] = []
        fill: list[tuple[str, dict[str, Any]]] = []
        for node in nodes:
            current = existing.get(node.key)
            if current is None:
                create.append(node)
                continue
            missing: dict[str, Any] = {}
            for name in _SHARED_FILLABLE:
                if name not in node.properties:
                    continue
                if name in current and current[name] != node.properties[name]:
                    raise ValidationFailed(name, "the same concept has a different value stored")
                if name not in current:
                    missing[name] = node.properties[name]
            if missing:
                fill.append((node.key, missing))
        return create, fill

    async def _apply_shared(self, plan: tuple[list[NodeSpec], list[Any]]) -> None:
        create, fill = plan
        groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for node in create:
            groups.setdefault(node.labels, []).append({"key": node.key, "props": node.properties})
        for labels, rows in groups.items():
            await self._run("Q-RES-SHARED-CREATE", insert=_labels_text(labels), rows=rows)
        for key, missing in fill:
            await self._run("Q-RES-SHARED-FILL", key=key, fill=missing)

    async def _write_placeholders(self, keys: set[str]) -> None:
        """A reference target that does not exist yet becomes a placeholder. ON CREATE only."""
        groups: dict[str, list[dict[str, str]]] = {}
        for key in sorted(keys):
            target_type, target_id = key.split("/", 1)
            groups.setdefault(target_type, []).append({"key": key, "id": target_id})
        for target_type, rows in groups.items():
            await self._run("Q-RES-MERGE-NODES", insert=_labels_text((target_type,)), rows=rows)

    async def _write_rels(self, rels: list[RelSpec]) -> None:
        # CREATE, not MERGE: two relationships of one type between the same nodes are two facts
        # (one concept listed twice, in different positions). Owned ones were cleared above.
        groups: dict[str, list[dict[str, Any]]] = {}
        for rel in rels:
            groups.setdefault(rel.type, []).append(
                {"start": rel.start, "end": rel.end, "props": rel.properties}
            )
        for rel_type, rows in groups.items():
            created = await self._run(
                "Q-RES-MERGE-RELS", insert=_labels_text((rel_type,)), rows=rows
            )
            if int(created[0]["created"]) != len(rows):
                raise NotFound(f"an endpoint of {rel_type} is missing")

    async def _link_shared(self, rels: list[RelSpec]) -> None:
        """Link each concept to its code system once: MERGE, so a repeat adds no second edge."""
        groups: dict[str, dict[tuple[str, str], dict[str, str]]] = {}
        for rel in rels:
            # One row per distinct pair: a concept used twice in a resource is linked once.
            groups.setdefault(rel.type, {})[(rel.start, rel.end)] = {
                "start": rel.start,
                "end": rel.end,
            }
        for rel_type, pairs in groups.items():
            rows = list(pairs.values())
            linked = await self._run(
                "Q-RES-LINK-SHARED", insert=_labels_text((rel_type,)), rows=rows
            )
            # The statement counts distinct pairs, so legacy duplicate edges (one per earlier put)
            # are not read as a missing endpoint; a pair with a missing end has no row at all.
            if int(linked[0]["linked"]) != len(rows):
                raise NotFound(f"an endpoint of {rel_type} is missing")

    # Reading

    async def _run(self, template: str, insert: str = "", **params: Any) -> list[dict[str, Any]]:
        """Run an instance of a registered template. The first use of a label or type registers
        the instance; the registry checks that the insert is a chain of label names."""
        return await run_query(self._tx, REGISTRY.instance(template, insert), **params)

    async def _root_props(self, resource_type: str, key: str) -> dict[str, Any] | None:
        rows = await self._run("Q-RES-GET", key=key, type=resource_type)
        if not rows or "placeholder" in rows[0]["props"]:
            return None
        props: dict[str, Any] = rows[0]["props"]
        return props

    async def _load(self, key: str, root_type: str, *, version: bool = False) -> GraphFragment:
        """The owned nodes and relationships of one stored resource (or of one of its versions),
        plus the shared Concept and Identifier nodes they point at, in the shape the mapper rebuilds
        from. A version is reached from its resource, so both statements start at its own key."""
        prefix = f"{key}#"
        root_label = ":ResourceVersion" if version else ":Resource"
        resource_key = key.partition("@")[0]
        nodes: dict[str, NodeSpec] = {}
        for row in await self._run(
            "Q-RES-LOAD-NODES", root_label, resourceKey=resource_key, key=key, prefix=prefix
        ):
            stored_key = str(row["props"]["key"])
            nodes[stored_key] = _node_from_row(
                stored_key, row["labels"], row["props"], key, root_type
            )
        rels: list[RelSpec] = []
        for row in await self._run(
            "Q-RES-LOAD-RELS", root_label, resourceKey=resource_key, key=key, prefix=prefix
        ):
            # A named local relationship (P03) has no fhirPath and is not an element, so it is not
            # in the resource. Any other relationship without a fhirPath is kept, and from_graph
            # then refuses it with KeyError.
            if "fhirPath" not in row["props"] and row["type"] in LOCAL_RELATIONSHIP_TYPES:
                continue
            if row["endProps"] is not None and row["end"] not in nodes:
                nodes[row["end"]] = _node_from_row(
                    row["end"], row["endLabels"], row["endProps"], key, root_type
                )
            rels.append(
                RelSpec(row["type"], row["start"], row["end"], _props_from_db(row["props"]))
            )
        if key not in nodes:
            raise NotFound(key)
        return GraphFragment(root_key=key, nodes=tuple(nodes.values()), rels=tuple(rels))


def _node_from_row(
    stored_key: str, labels: list[str], props: dict[str, Any], root_key: str, root_type: str
) -> NodeSpec:
    node_labels = ("Resource", root_type) if stored_key == root_key else tuple(labels)
    return NodeSpec(key=stored_key, labels=node_labels, properties=_props_from_db(props))
