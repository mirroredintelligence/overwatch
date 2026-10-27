"""A test-only write path for the FHIR concurrency tests (R03).

`:TestThing` nodes carry a versionId, as a real resource does, and are written through a real
Neo4j transaction inside the unit of work. Nothing here is an in-memory fake (DEC-004). The write
lock is taken before the version is read (lesson L63), as the real stores do.
"""

import uuid
from typing import cast

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.unit_of_work import DEFAULT_FACTORIES, RepositoryFactory


class TestThingRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def create(self, thing_id: str) -> None:
        await self._tx.run("CREATE (:TestThing {id: $id, versionId: 1})", id=thing_id)

    async def lock_and_version(self, thing_id: str) -> int | None:
        # Take the write lock with a fresh lockStamp (lesson L63, as G05 does), then read the
        # version in a second statement. A self-SET of versionId would write back the value read
        # before the lock was granted, which can overwrite a version committed by a held writer.
        await self._tx.run(
            "MATCH (t:TestThing {id: $id}) SET t.lockStamp = $stamp RETURN count(t) AS locked",
            id=thing_id,
            stamp=uuid.uuid4().hex,
        )
        return await self.version_of(thing_id)

    async def version_of(self, thing_id: str) -> int | None:
        result = await self._tx.run(
            "MATCH (t:TestThing {id: $id}) RETURN t.versionId AS version", id=thing_id
        )
        record = await result.single()
        return None if record is None else int(record["version"])

    async def bump(self, thing_id: str, version: int) -> None:
        await self._tx.run(
            "MATCH (t:TestThing {id: $id}) SET t.versionId = $version", id=thing_id, version=version
        )

    async def count(self) -> int:
        result = await self._tx.run("MATCH (t:TestThing) RETURN count(t) AS n")
        record = await result.single()
        return 0 if record is None else int(record["n"])


def _thing_repository(tx: AsyncManagedTransaction, store: ResourceStore) -> object:
    return TestThingRepository(tx)


THING_FACTORIES: dict[str, RepositoryFactory] = {**DEFAULT_FACTORIES, "things": _thing_repository}


def as_things(repository: object) -> TestThingRepository:
    return cast(TestThingRepository, repository)
