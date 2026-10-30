"""Each tenant predicate of the communication and scheduled-work statements is needed, or is
redundant under the invariant that no relationship joins two tenants (TEN-015, DEC-132 item 8).

For every occurrence of `tenantId: $tenant` in the statements of TEN_015 (thirteen from TEN-015,
and the two that the week bundle B1 added to the same module, Q-COMM-PROMPTS-DUE-BETWEEN and
Q-COMM-RECORD-OUTCOME), the statement is run with
that one predicate taken out, and the generated two-tenant test (the same probe as
test_tenant_isolation.py) runs it on a contracted container. A predicate on a node the statement
anchors on, or on a node it creates, must be killed. A predicate on a node reached through a
relationship from a node that is already scoped is not: with the scoped node in the caller's tenant,
the relationship can only lead to the caller's node, so the predicate cannot change a row. Those are
listed below with the reason, and the list is pinned, so a predicate that becomes necessary (or a
new one that is redundant) fails this test.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from tests.support.leaky_registry import LeakyRegistry
from tests.support.predicate_removal import predicate_count, without_predicate
from tests.support.query_probes import production_statements, run_isolation
from tests.support.tenant_seed import contracted_container

pytestmark = pytest.mark.asyncio(loop_scope="session")

# The occurrences that are redundant: (statement, occurrence counted from 0 in the text). The
# optional matches of `_READ` reach the topic, medium, role and service of a communication through
# its own relationships; the second node of a work item's subject match is reached from the first.
_VIA_RELATIONSHIP = "reached through an in-tenant relationship from a scoped node"
REDUNDANT: dict[tuple[str, int], str] = {
    **{("Q-COMM-BY-PROVIDER", k): _VIA_RELATIONSHIP for k in (1, 2, 3, 4)},
    **{("Q-COMM-GET", k): _VIA_RELATIONSHIP for k in (1, 2, 3, 4)},
    **{("Q-COMM-LATEST-PROMPT", k): _VIA_RELATIONSHIP for k in range(7)},
    # Each of the three nodes is joined to the other two by TOPIC and ABOUT, so with the other two
    # in the caller's tenant a third in another tenant cannot join them (the same as the prompt
    # statement above, which the anchor is no exception to).
    **{("Q-COMM-PROMPTS-DUE-BETWEEN", k): _VIA_RELATIONSHIP for k in (0, 1, 2)},
    **{("Q-WORK-GET", k): _VIA_RELATIONSHIP for k in (0, 1)},
    **{("Q-WORK-FOR-ABOUT", k): _VIA_RELATIONSHIP for k in (0, 1)},
}

TEN_015 = (
    "Q-COMM-ADD",
    "Q-COMM-BY-PROVIDER",
    "Q-COMM-EXISTS",
    "Q-COMM-GET",
    "Q-COMM-LATEST-PROMPT",
    "Q-COMM-LINK-ABOUT",
    "Q-COMM-LINK-RECIPIENT",
    "Q-COMM-LINK-REPLY",
    "Q-COMM-PROMPTS-DUE-BETWEEN",
    "Q-COMM-RECORD-OUTCOME",
    "Q-COMM-SET-STATUS",
    "Q-WORK-ADD",
    "Q-WORK-FOR-ABOUT",
    "Q-WORK-GET",
    "Q-WORK-SAVE",
)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def predicate_driver() -> AsyncIterator[AsyncDriver]:
    async with contracted_container() as driver:
        yield driver


async def test_each_predicate_is_killed_or_redundant_as_pinned(
    predicate_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    statements = production_statements(REGISTRY)
    surprises: list[str] = []
    for query_id in TEN_015:
        original = statements[query_id]
        for occurrence in range(predicate_count(original.cypher)):
            mutant = NamedQuery(
                id=query_id,
                cypher=without_predicate(original.cypher, occurrence),
                mode=original.mode,
                scenario=original.scenario,
            )
            registry = LeakyRegistry()
            registry.register(mutant)
            found = await run_isolation(
                predicate_driver,
                {query_id: mutant},
                registry=registry,
                tenant_a=tenant_id,
                tenant_b=other_tenant_id,
            )
            redundant = (query_id, occurrence) in REDUNDANT
            if bool(found) == redundant:
                surprises.append(f"{query_id} occurrence {occurrence}: found={bool(found)}")
    assert surprises == []


def test_every_pinned_redundancy_is_an_occurrence_of_a_statement_of_the_list() -> None:
    statements = production_statements(REGISTRY)
    for query_id, occurrence in REDUNDANT:
        assert query_id in TEN_015
        assert 0 <= occurrence < predicate_count(statements[query_id].cypher)


def test_the_statements_of_the_list_are_the_registered_communication_and_work_ids() -> None:
    registered = production_statements(REGISTRY)
    assert set(TEN_015) == {i for i in registered if i.startswith(("Q-COMM-", "Q-WORK-"))}
