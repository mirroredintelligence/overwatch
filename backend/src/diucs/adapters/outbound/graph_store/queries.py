"""Named Cypher queries and the registry of fixed statements (DEC-130 item 3, DEC-142).

Every statement is fixed text in the code, registered once with a name, its text and a scenario.
`run_query` takes only a registered `NamedQuery`: no string, no text built at the call. Only the id
ever reaches telemetry, never the Cypher text.

The check at registration is cheap and is not a proof. A tenant statement must carry a
`tenantId: $tenant` entry and a `Scenario`, always: there is no ratchet and no list of ids that
are excused (TEN-030 ended it, DEC-440). A global statement must be on the short
allowlist `GLOBAL_QUERY_IDS` and be pinned in `GLOBAL_STATEMENTS` by the SHA-256 of its exact text
(that pin is the guarantee, TEN-007 round 2); it must also not mention `$tenant`, must be read-only
and may name registry labels only (`GLOBAL_STATEMENT_LABELS`), as defence in depth. That
catches omissions only. The proof
that a statement cannot read or change another tenant's data is the generated two-tenant test that
runs each statement's scenario on a real Neo4j (TEN-004). The `Scenario` type and its validator
are in `scenario.py` (DEC-150).

A statement that needs a label or a relationship type is a `QueryTemplate`: one fixed text with
one `{insert}` place. `QueryRegistry.instance` expands it, once per insert, and only for an insert
that is a chain of label names (`:Resource:Organization`), so nothing but identifiers can be put
into the text.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from diucs.adapters.outbound.graph_store.scenario import Scenario

_MODES = ("read", "write")
_SCOPES = ("tenant", "global")

# `$tenant` and not `$tenantId`, `$tenants` or `$tenant_x`.
_TENANT_PARAMETER = re.compile(r"\$tenant\b")
# The predicate itself: a map entry `tenantId: $tenant`. `$tenant` in a result, a comparison or a
# comment is not one (a comment and the inside of a string are blanked before the look).
_TENANT_ENTRY = re.compile(r"\btenantId\s*:\s*\$tenant\b")

PLACEHOLDER: Final = "{insert}"
# `:Label` or `:Label:Other` or `:HAS_X`: ASCII identifiers only. fullmatch, so no trailing text.
_INSERT = re.compile(r"(?::[A-Za-z_][A-Za-z0-9_]*)+")
# A plain statement id has no colon: `Q-RES-UPSERT-ROOT:Resource:Organization` is an instance of
# the template `Q-RES-UPSERT-ROOT`, and a template instance is judged by its template.
_INSTANCE_SEPARATOR: Final = ":"

# The short global allowlist (DEC-130 item 3): statements that run before any tenant is known or
# on data that is shared. Each has the reason it is here. Adding one is a deliberate change: the
# list and the text of every statement on it are pinned in test_global_allowlist.py, and a global
# statement must be read-only and may name registry labels only (GLOBAL_STATEMENT_LABELS), so being
# on this list does not let a statement reach a tenant's data. Later tasks add theirs (the
# link-token hash lookup, the network registry) in their own commit.
GLOBAL_QUERY_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Q-NEO4J-PING": "the health ping answers RETURN 1: no data, and no tenant is known yet",
        "Q-TENANT-GET": (
            "reads one Tenant registry node by id: registry data only, and the caller needs the "
            "record before a tenant is bound"
        ),
        "Q-TENANT-LIST-ACTIVE": (
            "lists the Tenant registry nodes that are active, for the workers that visit each "
            "tenant in turn"
        ),
        "Q-TENANT-ACTIVE-IDS": (
            "lists the ids of the active Tenant registry nodes, so the outbox relay can bind each "
            "tenant in turn without reading a whole record"
        ),
        "Q-TENANT-BY-NUMBER": (
            "finds the tenant of an active TenantNumber registry node by the number called and "
            "the Twilio account (DEC-131 item 2): the tenant is not known until this answers"
        ),
        "Q-TENANT-BY-ACCOUNT": (
            "finds the tenant of the active TenantNumber registry nodes of a Twilio account, for "
            "delivery receipts (DEC-131 item 2): matched by account alone"
        ),
        "Q-TENANT-ACTIVE-LINE": (
            "reads the active number of one active Tenant (the bound tenant, I10 outbound "
            "sender): registry data for that id only, and the caller is already bound to it"
        ),
        "Q-TENANT-BY-HOST": (
            "finds the Tenant registry node of a host name (DEC-134 item 3): the host of an "
            "unauthenticated request is the only thing that names its tenant"
        ),
        "Q-TENANT-BY-ENTRA": (
            "finds the Tenant registry node bound to an Entra directory id (DEC-134 item 14): "
            "sign-in maps a verified directory to exactly one tenant"
        ),
        "Q-INVARIANT-UNSTAMPED": (
            "counts, by label set, the nodes that carry no tenantId and are not registry nodes "
            "(TEN-031): Community cannot require the property, so this is the control; it scans "
            "the whole graph and returns label names and a count, never a value"
        ),
        "Q-INVARIANT-CROSS-SCOPE": (
            "counts, by relationship type, the relationships that join two scopes (TEN-031): it "
            "scans the whole graph and returns a type and a count, never a value"
        ),
    }
)

# The two statements that count over the whole graph (TEN-031, the start-up and daily invariant
# check). A scan of every node names no label, so the label rule of `_check_global_text` cannot hold
# for them; what stands in its place, for these ids only, is that the text returns a label set or
# a relationship type and a count and nothing else, so no property value can leave the graph. The
# digest pin is still the guarantee. Adding an id here is as deliberate as adding one to the
# allowlist, and test_global_allowlist.py pins the set.
GLOBAL_WHOLE_GRAPH_IDS: Final[frozenset[str]] = frozenset(
    {"Q-INVARIANT-UNSTAMPED", "Q-INVARIANT-CROSS-SCOPE"}
)

# THE GUARANTEE (TEN-007 round 2, DEC-163 item 2): every global statement is pinned by the SHA-256
# of its exact text, stripped of leading and trailing whitespace and nothing else. A global
# statement registers only when its id is in this mapping AND the digest of its text equals the one
# here, so a changed byte, a comment, a case change or a new clause is refused. Adding or changing a
# global statement is a deliberate edit of this constant, to be reviewed like any security-relevant
# diff, with its reason in GLOBAL_QUERY_IDS and its text in test_global_allowlist.py. The structural
# checks below are a second defence, not a parser and not the guarantee: DEC-142 chose a registry
# of fixed statements over any analysis of arbitrary Cypher, and an earlier Cypher reader leaked
# through every verification round.
GLOBAL_STATEMENTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Q-NEO4J-PING": "505067033faf8e26ec2f3ea6c987e7e79bb32316d5db6e84ad32b16ff2e6f81b",
        "Q-TENANT-GET": "965a4ab096723692fa714be037e194e81dc2a8b017d6fc3e71c9f6a87b2b80be",
        "Q-TENANT-LIST-ACTIVE": "8060d795ec86eea21ee4368cc2406b7530211faec8750e3e4ec23529f20d340d",
        "Q-TENANT-ACTIVE-IDS": "230af35beaafb4e989676fe9c7dc999173adc599ee2e13a65b004b8475a7ed98",
        "Q-TENANT-BY-NUMBER": "f8b70805b9fc22b2d3e55ebcb146543528bb44e4f63251690ab60fd8c5ff65c6",
        "Q-TENANT-BY-ACCOUNT": "d835f568a9fb00629afba8db585d72d9d516d90aceea42191046fee236891550",
        "Q-TENANT-ACTIVE-LINE": "5d63a256430a4267c7848d6f6e445759b94049a937ef9631a1d042d915182f76",
        "Q-TENANT-BY-HOST": "6d54e9494484becff85e4c68de1c95f2e070c302e575657011295042235a2d21",
        "Q-TENANT-BY-ENTRA": "cde6d057e41dba1d35ca029ef4f29e51b16d1d4e0c9dfd909d297bcaba844888",
        "Q-INVARIANT-UNSTAMPED": "795489a314b9d937367c5d30b530ded1f438ece68ffc863bcb3bcb013ed90f3f",
        "Q-INVARIANT-CROSS-SCOPE": (
            "bbd3e4db80928a1d8dba2bf3991dc4c840acd649e682b3b0961f04ed9e55a179"
        ),
    }
)


def statement_digest(cypher: str) -> str:
    """The SHA-256 hex digest of a statement's text, stripped of leading and trailing whitespace
    and otherwise unchanged: the value pinned in GLOBAL_STATEMENTS."""
    return hashlib.sha256(cypher.strip().encode("utf-8")).hexdigest()


# The labels a global statement may name: the registry nodes, which carry no tenant (DEC-132,
# `REGISTRY_LABELS` in migrations_tenant.py). A global statement runs with no tenant, so it must not
# be able to match a node that holds a tenant's data. Adding a label here is as deliberate as adding
# an id to the allowlist, and the pinned test names both.
GLOBAL_STATEMENT_LABELS: Final[frozenset[str]] = frozenset({"Tenant", "TenantNumber"})

_IDENT = r"(?:[A-Za-z_]\w*|`[^`]*`)"
# A node pattern in its simple form, matched where a `(` stands: `(x:Label:Label {key: value})`,
# every part optional.
_NODE_PATTERN = re.compile(rf"\(\s*(?:{_IDENT})?\s*((?::\s*{_IDENT}\s*)*)(?:\{{[^{{}}]*\}})?\s*\)")
_LABEL = re.compile(rf":\s*({_IDENT})")
_NAME_BEFORE = re.compile(r"(?:[\w.]+|`[^`]*`)$")
_WRITES = re.compile(
    r"\b(?:CREATE|MERGE|SET|DELETE|DETACH|REMOVE|CALL|LOAD|FOREACH|DROP)\b", re.IGNORECASE
)
# A `(` that follows a name with no space is a function call only when the name is on the short
# list of functions (`properties(t)`); after a clause keyword (`MATCH(n:X)`, `WHERE(...)`) it is
# a node pattern or an expression, read exactly as it would be with a space; after any other name
# it is refused. So a keyword cannot hide a node pattern.
_FUNCTIONS = frozenset({"properties", "count", "coalesce", "tolower", "toupper", "size", "labels"})
# The functions a whole-graph count adds: `none(l IN labels(n) WHERE ...)` and `type(r)`.
_WHOLE_GRAPH_FUNCTIONS = _FUNCTIONS | {"none", "type"}
# What a whole-graph count may return: a label set or a relationship type, and a count.
_WHOLE_GRAPH_RETURN = re.compile(
    r"\bRETURN\s+(?:labels\(\s*\w+\s*\)|type\(\s*\w+\s*\))\s+AS\s+\w+\s*,"
    r"\s*count\(\s*\*\s*\)\s+AS\s+\w+\s*$"
)
_KEYWORDS = frozenset(
    [
        "match",
        "optional",
        "where",
        "with",
        "return",
        "union",
        "all",
        "unwind",
        "and",
        "or",
        "not",
        "xor",
        "in",
        "exists",
        "distinct",
        "as",
        "by",
        "order",
        "skip",
        "limit",
        "then",
        "else",
        "when",
        "case",
        "on",
        "is",
        "null",
        "starts",
        "ends",
        "contains",
        "asc",
        "desc",
    ]
)


def _blank(query_id: str, cypher: str) -> str:
    """The statement with each comment replaced by a space and the inside of each string literal
    removed, so a pattern in a comment or a string is not read as one. An unterminated string,
    quoted name or comment is refused."""
    out: list[str] = []
    i, n = 0, len(cypher)
    while i < n:
        c = cypher[i]
        if c in "'\"":
            i += 1
            while True:
                if i >= n:
                    raise ValueError(f"query {query_id}: a string in the statement is open")
                if cypher[i] == "\\":
                    i += 2
                elif cypher[i] == c:
                    i += 1
                    break
                else:
                    i += 1
            out.append(c + c)
        elif c == "`":
            end = cypher.find("`", i + 1)
            if end < 0:
                raise ValueError(f"query {query_id}: a quoted name in the statement is open")
            out.append(cypher[i : end + 1])
            i = end + 1
        elif cypher.startswith("//", i):
            end = cypher.find("\n", i)
            i = n if end < 0 else end
            out.append(" ")
        elif cypher.startswith("/*", i):
            end = cypher.find("*/", i + 2)
            if end < 0:
                raise ValueError(f"query {query_id}: a comment in the statement is open")
            i = end + 2
            out.append(" ")
        else:
            out.append(c)
            i += 1
    return "".join(out)


class TenantPredicateMissing(ValueError):
    """A tenant statement that has no `tenantId: $tenant` entry."""


class ScenarioMissing(ValueError):
    """A tenant statement that has no scenario."""


def _check_global_text(query_id: str, cypher: str) -> None:
    """The structural checks of a global statement's text: DEFENCE IN DEPTH behind the digest pin,
    not a parser and not the guarantee (see GLOBAL_STATEMENTS). They refuse a write or procedure
    word, a `;`, a `(` after a name that is not an allowed function (so `MATCH(n:X)` is read as a
    node pattern, as `MATCH (n:X)` is), a node with no label, a label outside the registry, a
    parenthesis that is neither a node nor a function call, and a brace outside a node's property
    map. Comments and the inside of strings are removed first. The two whole-graph counts
    (GLOBAL_WHOLE_GRAPH_IDS) may name a node by variable alone and call `none` and `type`, and must
    return a label set or a relationship type and a count and nothing else."""
    text = _blank(query_id, cypher)
    whole_graph = query_id in GLOBAL_WHOLE_GRAPH_IDS
    functions = _WHOLE_GRAPH_FUNCTIONS if whole_graph else _FUNCTIONS
    if whole_graph and (
        len(re.findall(r"\bRETURN\b", text, re.IGNORECASE)) != 1
        or _WHOLE_GRAPH_RETURN.search(text) is None
    ):
        raise ValueError(
            f"query {query_id}: a whole-graph count may return only a label set or a "
            "relationship type and a count"
        )
    if _WRITES.search(text) is not None:
        raise ValueError(f"query {query_id}: a global statement cannot write or call a procedure")
    if ";" in text:
        raise ValueError(f"query {query_id}: a global statement is one statement")
    remaining = text
    for position in (m.start() for m in re.finditer(r"\(", text)):
        before = _NAME_BEFORE.search(text[:position])
        name = None if before is None or before.end() != position else before.group(0).lower()
        if name in functions:
            continue
        if name is not None and name not in _KEYWORDS:
            raise ValueError(
                f"query {query_id}: a global statement may put a parenthesis after the name "
                "of an allowed function or a clause keyword only"
            )
        node = _NODE_PATTERN.match(text, position)
        if node is None:
            raise ValueError(
                f"query {query_id}: a global statement may use parentheses only for node "
                "patterns and function calls"
            )
        labels = [label.strip("`") for label in _LABEL.findall(node.group(1))]
        if not labels and whole_graph and "{" not in node.group(0):
            # A scan names its nodes by variable only: `(n)`, `(a)`. No label, no property map.
            remaining = remaining.replace(node.group(0), " ", 1)
            continue
        if not labels:
            raise ValueError(f"query {query_id}: every node in a global statement needs a label")
        if not set(labels) <= GLOBAL_STATEMENT_LABELS:
            raise ValueError(f"query {query_id}: a global statement may name registry labels only")
        remaining = remaining.replace(node.group(0), " ", 1)
    if "{" in remaining or "}" in remaining:
        raise ValueError(
            f"query {query_id}: a global statement may use braces only in a node's properties"
        )


def _validate(query_id: str, mode: object, scope: object, scenario: object) -> None:
    if mode not in _MODES:
        raise ValueError(f"query {query_id}: mode must be 'read' or 'write', not {mode!r}")
    if scope not in _SCOPES:
        raise ValueError(f"query {query_id}: scope must be 'tenant' or 'global', not {scope!r}")
    if scenario is not None and not isinstance(scenario, Scenario):
        raise ValueError(f"query {query_id}: scenario must be a Scenario or None")


@dataclass(frozen=True, slots=True)
class NamedQuery:
    id: str
    cypher: str
    mode: Literal["read", "write"]
    scope: Literal["tenant", "global"] = "tenant"
    scenario: Scenario | None = None

    def __post_init__(self) -> None:
        _validate(self.id, self.mode, self.scope, self.scenario)


@dataclass(frozen=True, slots=True)
class QueryTemplate:
    """One fixed statement with one `{insert}` place for a label chain or a relationship type."""

    id: str
    cypher: str
    mode: Literal["read", "write"]
    scope: Literal["tenant", "global"] = "tenant"
    scenario: Scenario | None = None

    def __post_init__(self) -> None:
        _validate(self.id, self.mode, self.scope, self.scenario)


def _mentions_tenant(cypher: str) -> bool:
    return _TENANT_PARAMETER.search(cypher) is not None


class QueryRegistry:
    def __init__(self) -> None:
        self._queries: dict[str, NamedQuery] = {}
        self._templates: dict[str, QueryTemplate] = {}

    def register(self, query: NamedQuery) -> None:
        if _INSTANCE_SEPARATOR in query.id:
            raise ValueError(f"query {query.id}: a statement id cannot contain a colon")
        self._refuse_taken(query.id)
        self._check(query.id, query.cypher, query.mode, query.scope, query.scenario)
        self._queries[query.id] = query

    def register_template(self, template: QueryTemplate) -> None:
        if _INSTANCE_SEPARATOR in template.id:
            raise ValueError(f"template {template.id}: a statement id cannot contain a colon")
        if template.scope == "global":
            raise ValueError(f"template {template.id}: a template cannot be a global statement")
        self._refuse_taken(template.id)
        self._check(template.id, template.cypher, template.mode, template.scope, template.scenario)
        self._templates[template.id] = template

    def instance(self, template_id: str, insert: str = "") -> NamedQuery:
        """The statement of a template with its insert, registered the first time it is asked for.
        The insert must be a chain of label names (`:Resource:Organization`), or empty for a
        template with no `{insert}` place."""
        try:
            template = self._templates[template_id]
        except KeyError:
            raise KeyError(f"unknown query template: {template_id}") from None
        takes_insert = PLACEHOLDER in template.cypher
        if takes_insert and _INSERT.fullmatch(insert) is None:
            raise ValueError(f"template {template_id}: the insert must be a chain of label names")
        if not takes_insert and insert:
            raise ValueError(f"template {template_id}: the template takes no insert")
        query_id = f"{template_id}{insert}"
        existing = self._queries.get(query_id)
        if existing is not None:
            return existing
        query = NamedQuery(
            id=query_id,
            cypher=template.cypher.replace(PLACEHOLDER, insert),
            mode=template.mode,
            scope=template.scope,
            scenario=template.scenario,
        )
        self._queries[query_id] = query
        return query

    def template(self, template_id: str) -> QueryTemplate:
        """A registered template, for the tools that list every statement (the generated test)."""
        try:
            return self._templates[template_id]
        except KeyError:
            raise KeyError(f"unknown query template: {template_id}") from None

    def get(self, query_id: str) -> NamedQuery:
        try:
            return self._queries[query_id]
        except KeyError:
            raise KeyError(f"unknown query id: {query_id}") from None

    def ids(self) -> list[str]:
        return sorted(self._queries)

    def template_ids(self) -> list[str]:
        return sorted(self._templates)

    def is_registered(self, query: object) -> bool:
        """True only for the very statement that was registered: the same id and the same text,
        mode, scope and scenario. An id alone is not enough."""
        return isinstance(query, NamedQuery) and self._queries.get(query.id) == query

    def _refuse_taken(self, query_id: str) -> None:
        if query_id in self._queries or query_id in self._templates:
            raise ValueError(f"duplicate query id: {query_id}")

    def _check(
        self, query_id: str, cypher: str, mode: str, scope: str, scenario: Scenario | None
    ) -> None:
        if scope != "global" and query_id in GLOBAL_QUERY_IDS:
            raise ValueError(
                f"query {query_id}: this id is on the global allowlist, so it must be registered "
                "with scope='global'"
            )
        if scope == "global":
            if query_id not in GLOBAL_QUERY_IDS:
                raise ValueError(f"query {query_id}: not on the global allowlist")
            if _mentions_tenant(cypher):
                raise ValueError(f"query {query_id}: a global statement cannot mention $tenant")
            if mode != "read":
                raise ValueError(f"query {query_id}: a global statement must be read-only")
            _check_global_text(query_id, cypher)
            pinned = GLOBAL_STATEMENTS.get(query_id)
            if pinned is None:
                raise ValueError(f"query {query_id}: this global statement has no pinned digest")
            if statement_digest(cypher) != pinned:
                raise ValueError(
                    f"query {query_id}: the text is not the pinned text of this global statement"
                )
            return
        if _TENANT_ENTRY.search(_blank(query_id, cypher)) is None:
            raise TenantPredicateMissing(
                f"query {query_id}: no tenantId: $tenant entry in the statement"
            )
        if scenario is None:
            raise ScenarioMissing(f"query {query_id}: no scenario")


REGISTRY = QueryRegistry()
