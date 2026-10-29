"""Protected text on Neo4j (P20). Red stub: every method raises NotImplementedError."""

from neo4j import AsyncManagedTransaction


def new_handle() -> str:
    raise NotImplementedError("P20: new_handle")


def checked_text(text: str) -> str:
    raise NotImplementedError("P20: checked_text")


class Neo4jProtectedTextStore:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def put(self, kind: str, about_id: str, text: str) -> str:
        raise NotImplementedError("P20: put")

    async def get(self, handle: str) -> str | None:
        raise NotImplementedError("P20: get")
