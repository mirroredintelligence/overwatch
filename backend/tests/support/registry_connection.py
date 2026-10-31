"""A recording stand-in for the Neo4j connection, for the unit tests of the tenant registry's writes
(TEN-028). It answers each platform statement by its id with rows the test gives (or raises the
error the test gives, as a unique constraint would), and records every call: statement id, text and
parameters, and whether it ran in a read or a write transaction.
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
    def __init__(self, answers: dict[str, list[dict[str, Any]] | Exception], kind: str) -> None:
        self._by_text = {REGISTRY.get(query_id).cypher: rows for query_id, rows in answers.items()}
        self._ids = {
            REGISTRY.get(i).cypher: i
            for i in REGISTRY.ids()
            if i.startswith(("Q-TENANT", "Q-PLATFORM", "Q-SUPPORT-TICKET"))
        }
        self._kind = kind
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def run(self, cypher: str, parameters: dict[str, Any] | None = None) -> _Result:
        self.calls.append(
            (self._ids[cypher], self._kind, {} if parameters is None else dict(parameters))
        )
        answer = self._by_text.get(cypher, [])
        if isinstance(answer, Exception):
            raise answer
        return _Result(answer)


class RecordingWriteConnection:
    """`answers` maps a registered statement id to its rows, or to an exception to raise."""

    def __init__(self, answers: dict[str, list[dict[str, Any]] | Exception] | None = None) -> None:
        self._answers = {} if answers is None else answers
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def run_read[T](self, work: Callable[[RecordingTx], Awaitable[T]]) -> T:
        tx = RecordingTx(self._answers, "read")
        try:
            return await work(tx)
        finally:
            self.calls.extend(tx.calls)

    async def run_write[T](self, work: Callable[[RecordingTx], Awaitable[T]]) -> T:
        tx = RecordingTx(self._answers, "write")
        try:
            return await work(tx)
        finally:
            self.calls.extend(tx.calls)

    def ids_called(self) -> list[str]:
        return [query_id for query_id, _, _ in self.calls]
