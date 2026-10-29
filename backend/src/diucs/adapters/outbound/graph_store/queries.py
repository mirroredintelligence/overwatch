"""Named Cypher queries and the registry of fixed statements (DEC-130 item 3, DEC-142).

Every statement is fixed text in the code, registered once with a name, its text and a scenario.
`run_query` takes only a registered `NamedQuery`: no string, no text built at the call. Only the id
ever reaches telemetry, never the Cypher text.

The check at registration is cheap and is not a proof. A tenant statement must mention `$tenant`
and must carry a `Scenario`, unless its id is on the ratchet (`UNCONVERTED`: the statements that
existed before the seam and have not been converted yet). A global statement must be on the short
allowlist `GLOBAL_QUERY_IDS` and must not mention `$tenant`. That catches omissions only. The proof
that a statement cannot read or change another tenant's data is the generated two-tenant test that
runs each statement's scenario on a real Neo4j (TEN-004).

A statement that needs a label or a relationship type is a `QueryTemplate`: one fixed text with
one `{insert}` place. `QueryRegistry.instance` expands it, once per insert, and only for an insert
that is a chain of label names (`:Resource:Organization`), so nothing but identifiers can be put
into the text.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from diucs.adapters.outbound.graph_store.scenario import Scenario
from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED

_MODES = ("read", "write")
_SCOPES = ("tenant", "global")

# `$tenant` and not `$tenantId`, `$tenants` or `$tenant_x`.
_TENANT_PARAMETER = re.compile(r"\$tenant\b")

PLACEHOLDER: Final = "{insert}"
# `:Label` or `:Label:Other` or `:HAS_X`: ASCII identifiers only. fullmatch, so no trailing text.
_INSERT = re.compile(r"(?::[A-Za-z_][A-Za-z0-9_]*)+")
# A plain statement id has no colon: `Q-RES-UPSERT-ROOT:Resource:Organization` is an instance of
# the template `Q-RES-UPSERT-ROOT`, and an instance inherits the template's place on the ratchet.
_INSTANCE_SEPARATOR: Final = ":"

# The short global allowlist (DEC-130 item 3): statements that run before any tenant is known or
# on data that is shared. Each has the reason it is here. Later tasks add theirs (the tenant
# lookups, the link-token hash lookup, the network registry) in their own commit.
GLOBAL_QUERY_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {"Q-NEO4J-PING": "the health ping answers RETURN 1: no data, and no tenant is known yet"}
)


class TenantPredicateMissing(ValueError):
    """A tenant statement that never mentions `$tenant` and is not on the ratchet."""


class ScenarioMissing(ValueError):
    """A tenant statement that has no scenario and is not on the ratchet."""


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
    def __init__(self, unconverted: frozenset[str] = UNCONVERTED) -> None:
        self._unconverted = unconverted
        self._queries: dict[str, NamedQuery] = {}
        self._templates: dict[str, QueryTemplate] = {}

    def register(self, query: NamedQuery) -> None:
        if _INSTANCE_SEPARATOR in query.id:
            raise ValueError(f"query {query.id}: a statement id cannot contain a colon")
        self._refuse_taken(query.id)
        self._check(query.id, query.cypher, query.scope, query.scenario)
        self._queries[query.id] = query

    def register_template(self, template: QueryTemplate) -> None:
        if _INSTANCE_SEPARATOR in template.id:
            raise ValueError(f"template {template.id}: a statement id cannot contain a colon")
        self._refuse_taken(template.id)
        self._check(template.id, template.cypher, template.scope, template.scenario)
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

    def is_tenant_pending(self, query: NamedQuery | QueryTemplate) -> bool:
        """A tenant statement that does not mention `$tenant`: it is on the ratchet, and it may
        still run with no scope bound. Every other tenant statement may not."""
        return query.scope == "tenant" and not _mentions_tenant(query.cypher)

    def needs_conversion(self, query: NamedQuery | QueryTemplate) -> bool:
        """A tenant statement that does not mention `$tenant` or has no scenario."""
        return query.scope == "tenant" and (
            not _mentions_tenant(query.cypher) or query.scenario is None
        )

    def ratchet_ids(self) -> list[str]:
        """The ids of the registered statements and templates that still need conversion: what
        `UNCONVERTED` must list, no more and no fewer. An instance counts as its template."""
        plain = [q.id for q in self._queries.values() if _INSTANCE_SEPARATOR not in q.id]
        pending = [i for i in plain if self.needs_conversion(self._queries[i])]
        pending += [t.id for t in self._templates.values() if self.needs_conversion(t)]
        return sorted(pending)

    def _refuse_taken(self, query_id: str) -> None:
        if query_id in self._queries or query_id in self._templates:
            raise ValueError(f"duplicate query id: {query_id}")

    def _check(self, query_id: str, cypher: str, scope: str, scenario: Scenario | None) -> None:
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
            return
        on_ratchet = query_id in self._unconverted
        if not _mentions_tenant(cypher) and not on_ratchet:
            raise TenantPredicateMissing(
                f"query {query_id}: no $tenant in the statement, and its id is not on the ratchet"
            )
        if scenario is None and not on_ratchet:
            raise ScenarioMissing(
                f"query {query_id}: no scenario, and its id is not on the ratchet"
            )


REGISTRY = QueryRegistry()
