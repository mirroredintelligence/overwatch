"""Graph writer and reader for FHIR resources, with versions (G05, rule R10, DEC-053).

DEC-010 stub: every method raises until the implementation commit.
"""

from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.application.ports.outbound.clock import Clock


class ResourceStore:
    def __init__(self, tx: AsyncManagedTransaction, clock: Clock | None = None) -> None:
        self._tx = tx
        self._clock = clock

    async def put(self, resource: dict[str, Any], expected_version: str | None) -> str:
        raise NotImplementedError("G05 stub")

    async def get(self, type: str, id: str) -> dict[str, Any] | None:
        raise NotImplementedError("G05 stub")

    async def history(self, type: str, id: str) -> list[dict[str, Any]]:
        raise NotImplementedError("G05 stub")

    async def exists(self, type: str, id: str) -> bool:
        raise NotImplementedError("G05 stub")
