"""The travel-time switch of the container (KI-200): the routing engine when one is configured,
the straight-line estimate otherwise, and a refusal to start on a half-set configuration."""

from datetime import UTC, datetime

import httpx
import pytest

from diucs.adapters.outbound.travel_time.routing import RoutingTravelTime
from diucs.adapters.outbound.travel_time.straight_line import StraightLineTravelTime
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.bootstrap.container import build, travel_time_for
from diucs.bootstrap.settings import Settings

CLOCK = FixedClock(datetime(2026, 10, 23, 13, 0, tzinfo=UTC))


def test_with_no_routing_engine_the_estimate_is_the_straight_line() -> None:
    assert isinstance(
        travel_time_for(Settings(), InMemoryCache(CLOCK), None), StraightLineTravelTime
    )


async def test_with_an_engine_and_the_extract_date_the_estimate_is_routed() -> None:
    settings = Settings(routing_base_url="http://routing.test", routing_extract_date="2026-10-01")
    async with httpx.AsyncClient() as client:
        found = travel_time_for(settings, InMemoryCache(CLOCK), client)

    assert isinstance(found, RoutingTravelTime)


def test_an_engine_without_the_extract_date_is_refused_because_the_source_must_name_the_data() -> (
    None
):
    settings = Settings(routing_base_url="http://routing.test")

    with pytest.raises(ValueError, match="routing_extract_date"):
        travel_time_for(settings, InMemoryCache(CLOCK), httpx.AsyncClient())


def test_an_engine_without_an_http_client_is_refused() -> None:
    settings = Settings(routing_base_url="http://routing.test", routing_extract_date="2026-10-01")

    with pytest.raises(ValueError, match="client"):
        travel_time_for(settings, InMemoryCache(CLOCK), None)


async def test_the_built_container_uses_the_switch() -> None:
    plain = build(Settings())
    routed = build(
        Settings(routing_base_url="http://routing.test", routing_extract_date="2026-10-01")
    )
    try:
        assert isinstance(plain.travel, StraightLineTravelTime)
        assert isinstance(routed.travel, RoutingTravelTime)
        assert routed.http is not None
    finally:
        await plain.shutdown()
        await routed.shutdown()
