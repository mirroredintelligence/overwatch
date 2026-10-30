"""The projection repository on Neo4j (TEN-053). Stub for the red commit."""

from typing import Any


class Neo4jProjectionRepository:
    def __init__(self, tx: Any) -> None:
        self._tx = tx

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError
