"""Save-then-load round trip across two transactions (F10). Stub for the red commit (DEC-010)."""

from collections.abc import Awaitable, Callable
from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction


async def assert_round_trip(
    driver: AsyncDriver,
    save: Callable[[AsyncManagedTransaction], Awaitable[Any]],
    load: Callable[[AsyncManagedTransaction], Awaitable[Any]],
    expected: Any,
) -> None:
    raise NotImplementedError("F10 red stub: assert_round_trip")
