"""Owns the one AsyncDriver of the process (DEC-012). STUB: red commit, bodies not implemented."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from neo4j import AsyncManagedTransaction, AsyncSession


@dataclass(frozen=True, slots=True)
class Neo4jPoolOptions:
    """The four DEC-012 values. Defaults are [ASSUMED] until measured."""

    max_connection_lifetime: float = 1800.0
    liveness_check_timeout: float = 30.0
    connection_acquisition_timeout: float = 30.0
    max_connection_pool_size: int = 50


class Neo4jConnectionError(RuntimeError):
    """The connection cannot be opened, or is used before open or after close."""


class Neo4jConnection:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        options: Neo4jPoolOptions | None = None,
    ) -> None:
        raise NotImplementedError

    @property
    def endpoint(self) -> str:
        raise NotImplementedError

    @property
    def pool_options(self) -> Neo4jPoolOptions:
        raise NotImplementedError

    @property
    def open_session_count(self) -> int:
        raise NotImplementedError

    async def open(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    def session(self) -> AbstractAsyncContextManager[AsyncSession]:
        raise NotImplementedError

    async def run_read[T](self, work: Callable[[AsyncManagedTransaction], Awaitable[T]]) -> T:
        raise NotImplementedError

    async def run_write[T](self, work: Callable[[AsyncManagedTransaction], Awaitable[T]]) -> T:
        raise NotImplementedError

    def pool_connection_count(self) -> int:
        raise NotImplementedError
