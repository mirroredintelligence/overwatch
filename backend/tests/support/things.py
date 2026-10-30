"""A test-only write path for the FHIR concurrency tests (R03).

`:TestThing` nodes carry a versionId, as a real resource does, and are written through a real
Neo4j transaction inside the unit of work. Nothing here is an in-memory fake (DEC-004). The write
lock is taken before the version is read (lesson L63), as the real stores do.
"""

import uuid
from typing import cast

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import NamedQuery, QueryRegistry, Scenario
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.unit_of_work import DEFAULT_FACTORIES, RepositoryFactory

# A unit of work hands its repositories a ScopedTx, which has no `run` (TEN-002): the statements of
# this test-only repository are registered in a registry of its own and run through run_query. Since
# TEN-030 the registry has no ratchet: each statement names `tenantId: $tenant` and has a scenario
# (a placeholder: this registry is not the product's and the generated test never reads it).
_SCENARIO = Scenario("test-only statement of the concurrency tests")
_STATEMENTS = (
    NamedQuery(
        id="Q-TEST-THING-CREATE",
        cypher="CREATE (:TestThing {id: $id, versionId: 1, tenantId: $tenant})",
        mode="write",
        scenario=_SCENARIO,
    ),
    NamedQuery(
        id="Q-TEST-THING-LOCK",
        cypher=(
            "MATCH (t:TestThing {id: $id, tenantId: $tenant}) SET t.lockStamp = $stamp "
            "RETURN count(t) AS locked"
        ),
        mode="write",
        scenario=_SCENARIO,
    ),
    NamedQuery(
        id="Q-TEST-THING-VERSION",
        cypher="MATCH (t:TestThing {id: $id, tenantId: $tenant}) RETURN t.versionId AS version",
        mode="read",
        scenario=_SCENARIO,
    ),
    NamedQuery(
        id="Q-TEST-THING-BUMP",
        cypher="MATCH (t:TestThing {id: $id, tenantId: $tenant}) SET t.versionId = $version",
        mode="write",
        scenario=_SCENARIO,
    ),
    NamedQuery(
        id="Q-TEST-THING-COUNT",
        cypher="MATCH (t:TestThing {tenantId: $tenant}) RETURN count(t) AS n",
        mode="read",
        scenario=_SCENARIO,
    ),
)
_REGISTRY = QueryRegistry()
for _query in _STATEMENTS:
    _REGISTRY.register(_query)


class TestThingRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def _run(self, query_id: str, **params: object) -> list[dict[str, object]]:
        return await run_query(self._tx, _REGISTRY.get(query_id), registry=_REGISTRY, **params)

    async def create(self, thing_id: str) -> None:
        await self._run("Q-TEST-THING-CREATE", id=thing_id)

    async def lock_and_version(self, thing_id: str) -> int | None:
        # Take the write lock with a fresh lockStamp (lesson L63, as G05 does), then read the
        # version in a second statement. A self-SET of versionId would write back the value read
        # before the lock was granted, which can overwrite a version committed by a held writer.
        await self._run("Q-TEST-THING-LOCK", id=thing_id, stamp=uuid.uuid4().hex)
        return await self.version_of(thing_id)

    async def version_of(self, thing_id: str) -> int | None:
        rows = await self._run("Q-TEST-THING-VERSION", id=thing_id)
        return None if not rows else int(cast(int, rows[0]["version"]))

    async def bump(self, thing_id: str, version: int) -> None:
        await self._run("Q-TEST-THING-BUMP", id=thing_id, version=version)

    async def count(self) -> int:
        rows = await self._run("Q-TEST-THING-COUNT")
        return int(cast(int, rows[0]["n"])) if rows else 0


def _thing_repository(tx: AsyncManagedTransaction, store: ResourceStore) -> object:
    return TestThingRepository(tx)


THING_FACTORIES: dict[str, RepositoryFactory] = {**DEFAULT_FACTORIES, "things": _thing_repository}


def as_things(repository: object) -> TestThingRepository:
    return cast(TestThingRepository, repository)
