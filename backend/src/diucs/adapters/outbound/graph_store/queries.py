"""DEC-010 stub for the red commit of TEN-001: the new names of the registry, no behaviour.
Named Cypher queries. Only the id ever reaches telemetry, never the Cypher text."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED

_MODES = ("read", "write")

GLOBAL_QUERY_IDS: Final[Mapping[str, str]] = {}


class TenantPredicateMissing(ValueError):
    pass


class ScenarioMissing(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Scenario:
    description: str


@dataclass(frozen=True, slots=True)
class NamedQuery:
    id: str
    cypher: str
    mode: Literal["read", "write"]
    scope: Literal["tenant", "global"] = "tenant"
    scenario: Scenario | None = None

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError(f"query {self.id}: mode must be 'read' or 'write', not {self.mode!r}")


@dataclass(frozen=True, slots=True)
class QueryTemplate:
    id: str
    cypher: str
    mode: Literal["read", "write"]
    scope: Literal["tenant", "global"] = "tenant"
    scenario: Scenario | None = None


class QueryRegistry:
    def __init__(
        self,
        unconverted: frozenset[str] = UNCONVERTED,
        global_ids: Mapping[str, str] = GLOBAL_QUERY_IDS,
    ) -> None:
        self._queries: dict[str, NamedQuery] = {}

    def register(self, query: NamedQuery) -> None:
        if query.id in self._queries:
            raise ValueError(f"duplicate query id: {query.id}")
        self._queries[query.id] = query

    def register_template(self, template: QueryTemplate) -> None:
        raise NotImplementedError

    def instance(self, template_id: str, insert: str = "") -> NamedQuery:
        raise NotImplementedError

    def get(self, query_id: str) -> NamedQuery:
        try:
            return self._queries[query_id]
        except KeyError:
            raise KeyError(f"unknown query id: {query_id}") from None

    def ids(self) -> list[str]:
        return sorted(self._queries)

    def template_ids(self) -> list[str]:
        raise NotImplementedError

    def is_registered(self, query: object) -> bool:
        raise NotImplementedError

    def is_tenant_pending(self, query: NamedQuery | QueryTemplate) -> bool:
        raise NotImplementedError

    def needs_conversion(self, query: NamedQuery | QueryTemplate) -> bool:
        raise NotImplementedError

    def ratchet_ids(self) -> list[str]:
        raise NotImplementedError


REGISTRY = QueryRegistry()
