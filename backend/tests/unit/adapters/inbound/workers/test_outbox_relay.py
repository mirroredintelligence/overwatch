"""The outbox relay without a database (I03): the tenant list, the constants and the layering.

A unit of work factory that fails the test when it is called stands in for "no database was
touched". It is not a fake store: nothing here stores or reads a record.
"""

import ast
import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from diucs.adapters.inbound.workers import outbox_relay
from diucs.adapters.inbound.workers.outbox_relay import (
    BACKOFF_CAP_SECONDS,
    BACKOFF_START_SECONDS,
    BATCH_SIZE,
    LOCK_MARGIN,
    LOCK_NAME,
    LOCK_TTL,
    OutboxRelay,
    RelayResult,
    StaticTenants,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.unit_of_work import UnitOfWork

CLOCK = FixedClock(datetime(2026, 10, 23, 13, 16, tzinfo=UTC))


def _no_unit() -> UnitOfWork:
    raise AssertionError("no unit of work may be opened")


def _relay(tenants: Sequence[str]) -> OutboxRelay:
    return OutboxRelay(
        _no_unit, ManualEventBus(CLOCK), InMemoryCache(CLOCK), CLOCK, StaticTenants(tenants)
    )


async def test_static_tenants_lists_the_ids_it_was_given_in_order() -> None:
    assert list(await StaticTenants(["b-one", "a-two"]).active_tenant_ids()) == ["b-one", "a-two"]


async def test_no_tenants_is_an_empty_round_that_opens_nothing() -> None:
    result = await _relay([]).run_once()

    assert result == RelayResult(published=0, failed=0, skipped_no_lock=False)


@pytest.mark.parametrize(
    "bad",
    [
        "net-abcd1234",  # a network scope is not a tenant
        "Not A Tenant",
        "a",  # too short
        "x" * 40,  # too long
        "has:colon",
        "",
    ],
)
async def test_an_entry_that_is_not_a_tenant_id_is_skipped_and_opens_nothing(bad: str) -> None:
    result = await _relay([bad]).run_once()

    assert result == RelayResult(published=0, failed=0, skipped_no_lock=False)


def test_the_named_constants_hold_the_values_the_task_fixes() -> None:
    assert (LOCK_NAME, BATCH_SIZE) == ("outbox-relay", 100)
    assert (timedelta(seconds=30), timedelta(seconds=5)) == (LOCK_TTL, LOCK_MARGIN)
    assert (BACKOFF_START_SECONDS, BACKOFF_CAP_SECONDS) == (1.0, 60.0)


async def test_the_result_is_a_value_that_cannot_be_changed() -> None:
    result = RelayResult(published=1, failed=2, skipped_no_lock=False)

    with pytest.raises(AttributeError):
        result.published = 5  # type: ignore[misc]


async def test_run_forever_returns_at_once_when_stop_is_already_set() -> None:
    relay = _relay([])
    stop = asyncio.Event()
    stop.set()

    await asyncio.wait_for(relay.run_forever(stop), timeout=2)


def test_the_worker_imports_no_outbound_adapter_and_no_driver() -> None:
    source = Path(outbox_relay.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)

    forbidden = ("diucs.adapters.outbound", "diucs.adapters.testing", "diucs.bootstrap")
    assert not [name for name in imported if name.startswith(forbidden)]
    assert not [name for name in imported if name.split(".")[0] in {"neo4j", "redis", "azure"}]


async def test_a_directory_that_cannot_be_read_is_raised_so_run_forever_can_wait_it_out() -> None:
    class Down:
        async def active_tenant_ids(self) -> Sequence[str]:
            raise ConnectionError("directory down")

    relay = OutboxRelay(_no_unit, ManualEventBus(CLOCK), InMemoryCache(CLOCK), CLOCK, Down())

    with pytest.raises(ConnectionError):
        await relay.run_once()


async def test_an_id_that_is_not_a_tenant_is_logged_once_however_many_rounds_see_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    relay = _relay(["Not A Tenant"])

    with caplog.at_level(logging.DEBUG, logger=outbox_relay.__name__):
        for _ in range(3):
            await relay.run_once()

    assert len(caplog.records) == 1
    assert "Not A Tenant" not in caplog.text
