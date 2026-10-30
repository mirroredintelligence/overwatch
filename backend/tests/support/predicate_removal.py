"""The predicate-removal check of the generated two-tenant test (TEN-004, DEC-142 item 9).

`mutant_of` makes a scratch copy of a registered statement with `tenantId: $tenant` taken out of
its text (every occurrence, or one), in a private registry. The registry would refuse the copy at
registration (the predicate is gone), so the copy goes into a `LeakyRegistry` (tests/support): the
copy exists only to be run. The integration test then shows the generated test fails for it.
"""

import re
from typing import Final

from diucs.adapters.outbound.graph_store.queries import NamedQuery
from tests.support.leaky_registry import LeakyRegistry

PREDICATE: Final = "tenantId: $tenant"
# A map entry `tenantId: $tenant` with the comma that joins it to its neighbour: the one before it
# when there is one, else the one after it. `$tenant` and not `$tenantX` or `$tenant_x`.
_ENTRY: Final = re.compile(r",\s*tenantId:\s*\$tenant\b|tenantId:\s*\$tenant\b(?:\s*,\s*)?")


def predicate_count(cypher: str) -> int:
    """How many map entries `tenantId: $tenant` the statement has."""
    return len(_ENTRY.findall(cypher))


def without_predicate(cypher: str, occurrence: int | None = None) -> str:
    """The text with every occurrence of the entry removed, or only the one at index `occurrence`
    (counted from 0, in the order they appear). Refuses a text that has none, or no such one."""
    matches = list(_ENTRY.finditer(cypher))
    if not matches:
        raise ValueError("the statement has no tenantId: $tenant entry to remove")
    if occurrence is not None and not 0 <= occurrence < len(matches):
        raise ValueError(f"the statement has no occurrence {occurrence} of tenantId: $tenant")
    chosen = matches if occurrence is None else [matches[occurrence]]
    out = cypher
    for match in reversed(chosen):
        out = out[: match.start()] + out[match.end() :]
    return out


def mutant_of(query: NamedQuery, occurrence: int | None = None) -> tuple[LeakyRegistry, NamedQuery]:
    """A private registry holding the statement without its predicate (the same mode, scope and
    scenario, and the same id, but for an instance of a template: the registry refuses a colon in a
    statement id, so the copy takes the template's id), and that statement."""
    mutant = NamedQuery(
        id=query.id.partition(":")[0],
        cypher=without_predicate(query.cypher, occurrence),
        mode=query.mode,
        scope=query.scope,
        scenario=query.scenario,
    )
    registry = LeakyRegistry()
    registry.register(mutant)
    return registry, mutant
