"""Named Cypher queries. Only the id ever reaches telemetry, never the Cypher text."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class NamedQuery:
    id: str
    cypher: str
    mode: Literal["read", "write"]


class QueryRegistry:
    def register(self, query: NamedQuery) -> None:
        return None

    def get(self, query_id: str) -> NamedQuery:
        raise NotImplementedError

    def ids(self) -> list[str]:
        raise NotImplementedError


REGISTRY = QueryRegistry()
