import dataclasses
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncGraphDatabase

from diucs.adapters.outbound.clock_system.system_clock import SystemClock
from diucs.adapters.outbound.graph_store.driver import create_driver
from diucs.adapters.outbound.ids_uuid.uuid_ids import UuidGenerator
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.bootstrap import container as container_module
from diucs.bootstrap.container import build, build_for_tests
from diucs.bootstrap.settings import Settings

TEST_NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def neo4j_driver() -> AsyncIterator[AsyncDriver]:
    """One driver per test, shared by every container the test builds. Nothing here connects."""
    driver = create_driver("bolt://localhost:1", "neo4j", "unused-without-a-session")
    try:
        yield driver
    finally:
        await driver.close()


async def test_build_wires_the_system_clock_and_uuid_ids() -> None:
    container = build(Settings())
    try:
        assert isinstance(container.clock, SystemClock)
        assert isinstance(container.ids, UuidGenerator)
    finally:
        await container.neo4j_driver.close()


async def test_build_for_tests_defaults_to_a_fixed_clock_at_the_test_time(
    neo4j_driver: AsyncDriver,
) -> None:
    container = build_for_tests(neo4j_driver=neo4j_driver)
    assert container.clock.now() == TEST_NOW
    assert isinstance(container.ids, SequentialIds)


async def test_build_for_tests_uses_a_clock_that_is_passed_in(neo4j_driver: AsyncDriver) -> None:
    later = datetime(2026, 12, 1, 8, 30, tzinfo=UTC)
    container = build_for_tests(clock=FixedClock(later), neo4j_driver=neo4j_driver)
    assert container.clock.now() == later


async def test_container_is_frozen(neo4j_driver: AsyncDriver) -> None:
    container = build_for_tests(neo4j_driver=neo4j_driver)
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.clock = SystemClock()  # type: ignore[misc]


async def test_build_for_tests_shares_the_driver_it_is_given(neo4j_driver: AsyncDriver) -> None:
    first = build_for_tests(neo4j_driver=neo4j_driver)
    second = build_for_tests(neo4j_driver=neo4j_driver)
    assert first.neo4j_driver is neo4j_driver
    assert second.neo4j_driver is neo4j_driver


async def test_build_wires_one_neo4j_driver_from_settings() -> None:
    container = build(Settings())
    try:
        assert isinstance(container.neo4j_driver, AsyncDriver)
    finally:
        await container.neo4j_driver.close()


async def test_build_passes_the_dec_012_pool_settings_to_the_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_MAX_CONNECTION_LIFETIME_S", "600")
    monkeypatch.setenv("DIUCS_NEO4J_LIVENESS_CHECK_TIMEOUT_S", "5")
    monkeypatch.setenv("DIUCS_NEO4J_CONNECTION_ACQUISITION_TIMEOUT_S", "2")
    monkeypatch.setenv("DIUCS_NEO4J_MAX_CONNECTION_POOL_SIZE", "7")
    container = build(Settings())
    try:
        pool = container.neo4j_driver._pool.pool_config  # type: ignore[attr-defined]
        assert pool.max_connection_lifetime == 600.0
        assert pool.liveness_check_timeout == 5.0
        assert pool.max_connection_pool_size == 7
        workspace = container.neo4j_driver._default_workspace_config  # type: ignore[attr-defined]
        assert workspace.connection_acquisition_timeout == 2.0
    finally:
        await container.neo4j_driver.close()


async def test_build_for_tests_makes_no_driver_calls(
    neo4j_driver: AsyncDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEC-012: one driver per process, never per test. build_for_tests only uses the driver it is
    given, so neither factory may be called while it builds containers."""
    calls: list[str] = []

    def _spy(name: str) -> Callable[..., AsyncDriver]:
        def _record(*args: object, **kwargs: object) -> AsyncDriver:
            calls.append(name)
            raise AssertionError(f"build_for_tests must not call {name}")

        return _record

    monkeypatch.setattr(container_module, "create_driver", _spy("create_driver"))
    monkeypatch.setattr(AsyncGraphDatabase, "driver", _spy("AsyncGraphDatabase.driver"))

    build_for_tests(neo4j_driver=neo4j_driver)
    build_for_tests(clock=FixedClock(TEST_NOW), neo4j_driver=neo4j_driver)

    assert calls == []


def test_build_for_tests_requires_the_driver_to_be_passed_in() -> None:
    with pytest.raises(TypeError):
        build_for_tests()  # type: ignore[call-arg]
