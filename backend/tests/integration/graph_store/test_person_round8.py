"""Round 8 (verifier finding): `now` is validated before any query.

A naive datetime passed as `now` raises ValidationFailed from the phone and service lookups, even
when nothing is stored. Run against the throwaway Neo4j of the F10 harness (DEC-008). The values
are synthetic.
"""

from datetime import datetime

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.person_repository import Neo4jPersonRepository
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.errors import ValidationFailed
from tests.support.neo4j import read_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

H1 = "a" * 64
NAIVE_NOW = datetime(2026, 10, 25, 13, 0)


async def test_a_naive_now_is_refused_by_the_phone_lookup_on_an_empty_graph(
    neo4j_driver: AsyncDriver,
) -> None:
    async def lookup(tx: AsyncManagedTransaction) -> object:
        repo = Neo4jPersonRepository(tx, ResourceStore(tx))
        return await repo.services_for_phone_hash(H1, NAIVE_NOW)

    with pytest.raises(ValidationFailed) as refused:
        await read_tx(neo4j_driver, lookup)

    assert refused.value.field == "now"


async def test_a_naive_now_is_refused_by_the_service_lookup_on_an_empty_graph(
    neo4j_driver: AsyncDriver,
) -> None:
    async def lookup(tx: AsyncManagedTransaction) -> object:
        repo = Neo4jPersonRepository(tx, ResourceStore(tx))
        return await repo.reporter_roles_for_service("svc-none", NAIVE_NOW)

    with pytest.raises(ValidationFailed) as refused:
        await read_tx(neo4j_driver, lookup)

    assert refused.value.field == "now"
