"""Save-then-load round trip across two transactions (F10).

The save runs in one committed write transaction; the load runs in a new read session. Every
datetime in the loaded value must be timezone-aware UTC, because a naive or local time is a silent
clock error in this application (Python conventions in contracts.md).
"""

from collections.abc import Awaitable, Callable
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta
from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction

from tests.support.neo4j import read_tx, write_tx


def _assert_utc_datetimes(value: Any, path: str = "value") -> None:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise AssertionError(
                f"{path} is {value!r}: datetimes must be timezone-aware UTC, not naive or local"
            )
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            _assert_utc_datetimes(getattr(value, field.name), f"{path}.{field.name}")
    elif isinstance(value, dict):
        for key, item in value.items():
            _assert_utc_datetimes(item, f"{path}[{key!r}]")
    elif isinstance(value, list | tuple | set | frozenset):
        for index, item in enumerate(value):
            _assert_utc_datetimes(item, f"{path}[{index}]")


async def assert_round_trip(
    driver: AsyncDriver,
    save: Callable[[AsyncManagedTransaction], Awaitable[Any]],
    load: Callable[[AsyncManagedTransaction], Awaitable[Any]],
    expected: Any,
) -> None:
    await write_tx(driver, save)
    loaded = await read_tx(driver, load)
    _assert_utc_datetimes(loaded)
    assert loaded == expected, f"loaded {loaded!r} != expected {expected!r}"
