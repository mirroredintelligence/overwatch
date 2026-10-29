"""A recording stand-in for the Neo4j driver, for unit tests of code that opens sessions and
transactions (TEN-002, TEN-003). It talks to no server: it records the statements a transaction was
asked to run, how many sessions were opened and closed, and whether a transaction committed or
rolled back. The real server is exercised by the integration tests.

It is not a store: there is no in-memory Neo4j (DEC-004). It only shows what the code under test
handed to the driver.
"""

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def data(self) -> list[dict[str, Any]]:
        return self._rows


class FakeTx:
    """Stands in for both AsyncTransaction and AsyncManagedTransaction."""

    def __init__(
        self, log: list[tuple[str, dict[str, Any]]], rows: list[dict[str, Any]] | None = None
    ) -> None:
        self.calls = log
        self._rows = [] if rows is None else rows
        self.committed = False
        self.rolled_back = False

    async def run(
        self, cypher: str, parameters: dict[str, Any] | None = None, **kwparameters: Any
    ) -> FakeResult:
        # What the real driver does: the keywords are merged into the parameters dict.
        self.calls.append((cypher, dict(parameters or {}, **kwparameters)))
        return FakeResult(self._rows)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeSession:
    def __init__(self, driver: FakeDriver) -> None:
        self._driver = driver
        self.closed = False

    async def __aenter__(self) -> FakeSession:
        if self._driver.open_error is not None:
            raise self._driver.open_error
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.closed = True
        self._driver.closed_sessions += 1

    async def begin_transaction(self) -> FakeTx:
        if self._driver.begin_error is not None:
            raise self._driver.begin_error
        tx = FakeTx(self._driver.calls, self._driver.rows)
        self._driver.transactions.append(tx)
        return tx

    async def execute_read[T](self, work: Callable[[FakeTx], Awaitable[T]]) -> T:
        return await self._managed(work)

    async def execute_write[T](self, work: Callable[[FakeTx], Awaitable[T]]) -> T:
        return await self._managed(work)

    async def _managed[T](self, work: Callable[[FakeTx], Awaitable[T]]) -> T:
        """Run the callback `attempts` times, as the driver does after a transient error, and
        return the last result. `between_attempts` runs before each retry."""
        result: T | None = None
        for attempt in range(self._driver.attempts):
            if attempt > 0 and self._driver.between_attempts is not None:
                self._driver.between_attempts()
            tx = FakeTx(self._driver.calls, self._driver.rows)
            self._driver.transactions.append(tx)
            result = await work(tx)
        return result  # type: ignore[return-value]


class FakeDriver:
    """Records every session opened and every statement run on any of its transactions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.transactions: list[FakeTx] = []
        self.session_calls = 0
        self.closed_sessions = 0
        self.attempts = 1
        self.between_attempts: Callable[[], None] | None = None
        self.begin_error: BaseException | None = None
        self.open_error: BaseException | None = None
        # The rows every statement returns.
        self.rows: list[dict[str, Any]] = []

    def session(self, **_: Any) -> FakeSession:
        self.session_calls += 1
        return FakeSession(self)

    async def verify_connectivity(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def tenants_sent(self) -> list[object]:
        """The `tenant` parameter of every statement run, in order; the string "-" for a
        statement that was sent without one."""
        return [params.get("tenant", "-") for _, params in self.calls]
