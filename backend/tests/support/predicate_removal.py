"""The predicate-removal check of the generated two-tenant test (TEN-004, DEC-142 item 9).

STUB (DEC-010, red commit).
"""

from typing import Final

from diucs.adapters.outbound.graph_store.queries import NamedQuery, QueryRegistry

PREDICATE: Final = "tenantId: $tenant"


def predicate_count(cypher: str) -> int:
    raise NotImplementedError


def without_predicate(cypher: str, occurrence: int | None = None) -> str:
    raise NotImplementedError


def mutant_of(query: NamedQuery, occurrence: int | None = None) -> tuple[QueryRegistry, NamedQuery]:
    raise NotImplementedError
