"""Named Cypher queries. Only the id ever reaches telemetry, never the Cypher text."""

from dataclasses import dataclass
from typing import Literal

_MODES = ("read", "write")


@dataclass(frozen=True, slots=True)
class NamedQuery:
    id: str
    cypher: str
    mode: Literal["read", "write"]

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError(f"query {self.id}: mode must be 'read' or 'write', not {self.mode!r}")


class QueryRegistry:
    def __init__(self) -> None:
        self._queries: dict[str, NamedQuery] = {}

    def register(self, query: NamedQuery) -> None:
        if query.id in self._queries:
            raise ValueError(f"duplicate query id: {query.id}")
        self._queries[query.id] = query

    def get(self, query_id: str) -> NamedQuery:
        try:
            return self._queries[query_id]
        except KeyError:
            raise KeyError(f"unknown query id: {query_id}") from None

    def ids(self) -> list[str]:
        return sorted(self._queries)


REGISTRY = QueryRegistry()
