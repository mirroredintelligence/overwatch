"""Adapter factories for the contract suites (P12).

Each list holds one `pytest.param(factory, id=...)` per adapter of its port. The memory fakes are
in every normal run. A real adapter is added later with its own factory and a marker:

    pytest.param(make_redis_cache, id="redis", marks=pytest.mark.integration)

A factory is an async function that returns a Harness over a fresh adapter that starts empty.
Real factories must delete what the test wrote when the harness is closed, so one test cannot
change another test's result.
"""

import pytest

from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.event_bus import EventBus
from tests.contract.harness import Harness


async def make_memory_cache() -> Harness[Cache]:
    raise NotImplementedError("P12 green commit builds the memory cache harness")


async def make_memory_event_bus() -> Harness[EventBus]:
    raise NotImplementedError("P12 green commit builds the memory event bus harness")


CACHE_FACTORIES = [pytest.param(make_memory_cache, id="memory")]
EVENT_BUS_FACTORIES = [pytest.param(make_memory_event_bus, id="memory")]
