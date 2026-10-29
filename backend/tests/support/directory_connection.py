"""A recording stand-in for the Neo4j connection, for the unit tests of the tenant directory
(TEN-007). It answers each statement by its text with rows the test gives, and records every call
(statement text and parameters), so a test can show that nothing was sent for a key that is not the
shape it names, and that the parameters hold no tenant.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from diucs.adapters.outbound.graph_store.queries import REGISTRY


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def data(self) -> list[dict[str, Any]]:
        return self._rows


class RecordingTx:
    def __init__(self, answers: dict[str, list[dict[str, Any]]]) -> None:
        self._by_text = {REGISTRY.get(query_id).cypher: rows for query_id, rows in answers.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, cypher: str, parameters: dict[str, Any] | None = None) -> _Result:
        self.calls.append((cypher, {} if parameters is None else dict(parameters)))
        return _Result(self._by_text.get(cypher, []))


class RecordingConnection:
    """`answers` maps a registered statement id to the rows it returns."""

    def __init__(self, answers: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.tx = RecordingTx({} if answers is None else answers)

    async def run_read[T](self, work: Callable[[RecordingTx], Awaitable[T]]) -> T:
        return await work(self.tx)

    @property
    def calls(self) -> list[tuple[str, dict[str, Any]]]:
        return self.tx.calls

    def ids_called(self) -> list[str]:
        by_text = {REGISTRY.get(i).cypher: i for i in REGISTRY.ids() if i.startswith("Q-TENANT-")}
        return [by_text[text] for text, _ in self.tx.calls]
