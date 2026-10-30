"""A registry that registers any statement, for the tests that must run a leaky one (TEN-030).

The production `QueryRegistry` has one rule and no escape: a tenant statement without a
`tenantId: $tenant` entry or a scenario is refused, and nothing lists an id that is excused. The
generated two-tenant test has to prove it catches a leak, and for that it must run a statement the
registry would refuse (a leaky twin, or a statement with its predicate taken out). Those go in a
`LeakyRegistry`, a private registry of the test, never the module registry: the architecture
test refuses `registry=` and this module in `src`.
"""

from diucs.adapters.outbound.graph_store.queries import QueryRegistry
from diucs.adapters.outbound.graph_store.scenario import Scenario


class LeakyRegistry(QueryRegistry):
    """Accepts any statement: no predicate check, no scenario check."""

    def _check(
        self, query_id: str, cypher: str, mode: str, scope: str, scenario: Scenario | None
    ) -> None:
        return None
