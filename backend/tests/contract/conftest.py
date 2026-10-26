"""Fixtures for the contract suites: each test runs once per adapter factory in factories.py."""

from collections.abc import AsyncIterator

import pytest

from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.event_bus import EventBus
from tests.contract.factories import CACHE_FACTORIES, EVENT_BUS_FACTORIES
from tests.contract.harness import Harness


@pytest.fixture(params=CACHE_FACTORIES)
async def cache_harness(request: pytest.FixtureRequest) -> AsyncIterator[Harness[Cache]]:
    harness: Harness[Cache] = await request.param()
    try:
        yield harness
    finally:
        await harness.close()


@pytest.fixture(params=EVENT_BUS_FACTORIES)
async def bus_harness(request: pytest.FixtureRequest) -> AsyncIterator[Harness[EventBus]]:
    harness: Harness[EventBus] = await request.param()
    try:
        yield harness
    finally:
        await harness.close()
