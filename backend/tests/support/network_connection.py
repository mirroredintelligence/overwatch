"""A recording stand-in for the Neo4j connection, for the unit tests of the network registry
(TEN-051). It answers each registered statement by its id with rows the test gives, records every
call (statement text and parameters), and can raise a constraint error for a write, so a test can
show what is sent, that no tenant is sent, and what the adapter makes of the answer. The real
server is exercised by the integration tests.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from diucs.adapters.outbound.graph_store.queries import REGISTRY


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def data(self) -> list[dict[str, Any]]:
        return self._rows


class NetworkTx:
    def __init__(
        self, answers: dict[str, list[dict[str, Any]]], errors: dict[str, Exception]
    ) -> None:
        self._by_text = {REGISTRY.get(query_id).cypher: rows for query_id, rows in answers.items()}
        self._errors = {REGISTRY.get(query_id).cypher: err for query_id, err in errors.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, cypher: str, parameters: dict[str, Any] | None = None) -> _Result:
        self.calls.append((cypher, {} if parameters is None else dict(parameters)))
        if cypher in self._errors:
            raise self._errors[cypher]
        return _Result(self._by_text.get(cypher, []))


class NetworkConnection:
    """`answers` maps a registered statement id to the rows it returns; `errors` maps one to an
    exception it raises."""

    def __init__(
        self,
        answers: dict[str, list[dict[str, Any]]] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.tx = NetworkTx({} if answers is None else answers, {} if errors is None else errors)
        self.reads = 0
        self.writes = 0

    async def run_read[T](self, work: Callable[[NetworkTx], Awaitable[T]]) -> T:
        self.reads += 1
        return await work(self.tx)

    async def run_write[T](self, work: Callable[[NetworkTx], Awaitable[T]]) -> T:
        self.writes += 1
        return await work(self.tx)

    @property
    def calls(self) -> list[tuple[str, dict[str, Any]]]:
        return self.tx.calls

    def ids_called(self) -> list[str]:
        by_text = {REGISTRY.get(i).cypher: i for i in REGISTRY.ids() if i.startswith("Q-NETWORK-")}
        return [by_text[text] for text, _ in self.tx.calls]
