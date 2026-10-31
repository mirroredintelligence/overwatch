"""Pure tests of the routing travel-time adapter (I15) against a recording fake of the HTTP client.

No routing engine is called: every reply is scripted. The fallback is the TravelTime port, here the
fixed fake, because the straight-line adapter (I11) is not on this branch. The cache is the
in-memory fake. Patient positions are postcode centroids; the sample values below are not real
addresses.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from diucs.adapters.outbound.travel_time.routing import (
    HttpxRouteClient,
    RoutingFailed,
    RoutingReplyMalformed,
    RoutingTravelTime,
    duration_seconds,
    range_from_duration,
    route_url,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_geo import FixedTravelTime
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.ports.outbound.geo import LatLon, TravelRange
from diucs.application.tenancy import TenantNotBound, bind_tenant

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
EXTRACT = "2026-10-01"
SOURCE = f"Routing data, updated {EXTRACT}"
BASE = "http://routing.test"
PATIENT = LatLon(lat=50.7100, lon=-2.4400)  # sample postcode centroid
SITE = LatLon(lat=50.7500, lon=-2.2900)  # sample postcode centroid
FALLBACK_RANGE = TravelRange(low_minutes=10, high_minutes=20, source="Straight-line estimate")
ROUTE_1800 = {"routes": [{"duration": 1800.0}]}
COORDINATE = "50.7100"  # a fragment of PATIENT's latitude, which must not appear in any error


class RecordingRouteClient:
    """Answers with a scripted reply, or raises it, and records every call."""

    def __init__(self, reply: tuple[int, object] | BaseException) -> None:
        self.reply = reply
        self.urls: list[str] = []
        self.timeouts: list[timedelta] = []

    async def get_json(self, url: str, timeout: timedelta) -> tuple[int, object]:
        self.urls.append(url)
        self.timeouts.append(timeout)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def _adapter(
    client: RecordingRouteClient,
    clock: FixedClock | None = None,
    timeout: timedelta | None = None,
) -> tuple[RoutingTravelTime, InMemoryCache]:
    cache = InMemoryCache(clock or FixedClock(NOW))
    fallback = FixedTravelTime(FALLBACK_RANGE)
    if timeout is None:
        adapter = RoutingTravelTime(client, BASE, EXTRACT, cache, fallback)
    else:
        adapter = RoutingTravelTime(client, BASE, EXTRACT, cache, fallback, timeout)
    return adapter, cache


# The range, from a duration in seconds


@pytest.mark.parametrize(
    ("seconds", "low", "high"),
    [
        (0, 0, 0),
        (61, 5, 5),  # the prompt's case: 2 minutes and 2.5 minutes, both rounded up to 5
        (1800, 30, 45),  # the prompt's case: 30 minutes and 42 minutes, rounded up to 5
        (300, 5, 10),
        (301, 10, 10),  # 5.02 minutes rounds up to 10; rounding down would give 5
        (3600, 60, 85),
    ],
)
def test_a_duration_gives_a_range_of_whole_minutes_rounded_up_to_five(
    seconds: float, low: int, high: int
) -> None:
    result = range_from_duration(seconds, EXTRACT)
    assert (result.low_minutes, result.high_minutes) == (low, high)


def test_the_range_source_names_the_extract_date() -> None:
    assert range_from_duration(1800, EXTRACT).source == SOURCE


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf")])
def test_a_negative_or_non_finite_duration_is_refused(seconds: float) -> None:
    with pytest.raises(ValueError):
        range_from_duration(seconds, EXTRACT)


# The request


def test_the_url_puts_longitude_before_latitude_and_asks_for_no_geometry() -> None:
    url = route_url(BASE + "/", PATIENT, SITE)
    assert url == (
        "http://routing.test/route/v1/driving/-2.440000,50.710000;-2.290000,50.750000"
        "?overview=false"
    )


async def test_a_routed_estimate_is_the_duration_range_with_its_source() -> None:
    client = RecordingRouteClient((200, ROUTE_1800))
    adapter, _ = _adapter(client)
    with bind_tenant("tenant-alpha"):
        result = await adapter.estimate(PATIENT, SITE)
    assert result == TravelRange(low_minutes=30, high_minutes=45, source=SOURCE)
    assert len(client.urls) == 1


async def test_a_second_call_for_the_same_pair_is_answered_from_the_cache() -> None:
    client = RecordingRouteClient((200, ROUTE_1800))
    adapter, _ = _adapter(client)
    with bind_tenant("tenant-alpha"):
        first = await adapter.estimate(PATIENT, SITE)
        second = await adapter.estimate(PATIENT, SITE)
    assert first == second
    assert len(client.urls) == 1


async def test_a_cached_route_expires_after_twenty_four_hours() -> None:
    clock = FixedClock(NOW)
    client = RecordingRouteClient((200, ROUTE_1800))
    adapter, _ = _adapter(client, clock=clock)
    with bind_tenant("tenant-alpha"):
        await adapter.estimate(PATIENT, SITE)
        clock.advance(timedelta(hours=24))
        await adapter.estimate(PATIENT, SITE)
    assert len(client.urls) == 2


async def test_the_two_directions_of_a_pair_are_cached_apart() -> None:
    client = RecordingRouteClient((200, ROUTE_1800))
    adapter, _ = _adapter(client)
    with bind_tenant("tenant-alpha"):
        await adapter.estimate(PATIENT, SITE)
        await adapter.estimate(SITE, PATIENT)
    assert len(client.urls) == 2


async def test_the_cache_key_carries_the_tenant() -> None:
    client = RecordingRouteClient((200, ROUTE_1800))
    adapter, _ = _adapter(client)
    with bind_tenant("tenant-alpha"):
        await adapter.estimate(PATIENT, SITE)
    with bind_tenant("tenant-beta"):
        await adapter.estimate(PATIENT, SITE)
    assert len(client.urls) == 2


async def test_no_tenant_bound_is_an_error_not_a_default() -> None:
    adapter, _ = _adapter(RecordingRouteClient((200, ROUTE_1800)))
    with pytest.raises(TenantNotBound):
        await adapter.estimate(PATIENT, SITE)


# Falling back to the straight-line port


async def test_a_timeout_falls_back_to_the_fallback_estimate() -> None:
    adapter, _ = _adapter(RecordingRouteClient(TimeoutError()))
    with bind_tenant("tenant-alpha"):
        assert await adapter.estimate(PATIENT, SITE) == FALLBACK_RANGE


async def test_a_reply_that_never_comes_falls_back_at_the_adapter_timeout() -> None:
    never = asyncio.Event()

    class HangingClient:
        async def get_json(self, url: str, timeout: timedelta) -> tuple[int, object]:
            await never.wait()
            return 200, ROUTE_1800

    cache = InMemoryCache(FixedClock(NOW))
    adapter = RoutingTravelTime(
        HangingClient(),
        BASE,
        EXTRACT,
        cache,
        FixedTravelTime(FALLBACK_RANGE),
        timedelta(milliseconds=50),
    )
    with bind_tenant("tenant-alpha"):
        assert await adapter.estimate(PATIENT, SITE) == FALLBACK_RANGE


@pytest.mark.parametrize("status", [500, 502, 503, 404])
async def test_an_error_status_falls_back(status: int) -> None:
    adapter, _ = _adapter(RecordingRouteClient((status, None)))
    with bind_tenant("tenant-alpha"):
        assert await adapter.estimate(PATIENT, SITE) == FALLBACK_RANGE


async def test_an_empty_list_of_routes_falls_back() -> None:
    adapter, _ = _adapter(RecordingRouteClient((200, {"routes": []})))
    with bind_tenant("tenant-alpha"):
        assert await adapter.estimate(PATIENT, SITE) == FALLBACK_RANGE


async def test_a_failed_route_is_not_cached_so_the_next_call_asks_again() -> None:
    client = RecordingRouteClient(TimeoutError())
    adapter, _ = _adapter(client)
    with bind_tenant("tenant-alpha"):
        await adapter.estimate(PATIENT, SITE)
        client.reply = (200, ROUTE_1800)
        assert await adapter.estimate(PATIENT, SITE) == TravelRange(30, 45, SOURCE)
    assert len(client.urls) == 2


# A malformed reply is an error that carries no coordinates


@pytest.mark.parametrize(
    "body",
    [
        None,
        "text",
        [],
        {},
        {"routes": []},
        {"routes": [{}]},
        {"routes": "not-a-list"},
        {"routes": [{"duration": "1800"}]},
        {"routes": [{"duration": True}]},
        {"routes": [{"duration": -5}]},
        {"routes": [{"duration": float("nan")}]},
    ],
)
def test_a_malformed_reply_is_a_routing_error(body: Any) -> None:
    with pytest.raises(RoutingReplyMalformed):
        duration_seconds(body)


def test_a_malformed_reply_error_carries_no_coordinates_or_body() -> None:
    with pytest.raises(RoutingReplyMalformed) as caught:
        duration_seconds(
            {"routes": [{"duration": "50.7100"}], "waypoints": [{"location": [-2.44, 50.71]}]}
        )
    assert str(caught.value) == ""
    assert caught.value.args == ()
    assert "50.7100" not in repr(caught.value)


async def test_a_malformed_reply_falls_back_rather_than_failing_the_options_list() -> None:
    adapter, _ = _adapter(RecordingRouteClient((200, {"routes": [{"duration": "soon"}]})))
    with bind_tenant("tenant-alpha"):
        assert await adapter.estimate(PATIENT, SITE) == FALLBACK_RANGE


async def test_no_coordinates_reach_the_logs_on_any_path(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    for reply in ((200, ROUTE_1800), (503, None), (200, {"routes": []})):
        adapter, _ = _adapter(RecordingRouteClient(reply))
        with bind_tenant("tenant-alpha"):
            await adapter.estimate(PATIENT, SITE)
    adapter, _ = _adapter(RecordingRouteClient(TimeoutError()))
    with bind_tenant("tenant-alpha"):
        await adapter.estimate(PATIENT, SITE)
    assert COORDINATE not in caplog.text
    assert "routing.test" not in caplog.text


# The HTTP client wrapper, over a local mock transport (no network)


async def test_the_httpx_client_returns_the_status_and_the_json_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ROUTE_1800)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reply = await HttpxRouteClient(client).get_json(BASE + "/route", timedelta(seconds=1))
    assert reply == (200, ROUTE_1800)


async def test_the_httpx_client_turns_a_timeout_into_the_timeout_error_without_the_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TimeoutError) as caught:
            await HttpxRouteClient(client).get_json(
                BASE + "/route/-2.44,50.71", timedelta(seconds=1)
            )
    assert "50.71" not in str(caught.value)


async def test_the_httpx_client_turns_a_transport_error_into_a_routing_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RoutingFailed) as caught:
            await HttpxRouteClient(client).get_json(
                BASE + "/route/-2.44,50.71", timedelta(seconds=1)
            )
    assert "50.71" not in str(caught.value)


# KI-202 and KI-203: a cache that fails does not fail the options list, and its key does not repeat
# the tenant the cache already puts in every name.


class _FailingCache(InMemoryCache):
    def __init__(
        self, clock: FixedClock, *, fail_get: bool = False, fail_set: bool = False
    ) -> None:
        super().__init__(clock)
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.names: list[str] = []

    async def get(self, key: str) -> str | None:
        self.names.append(key)
        if self.fail_get:
            raise ConnectionError("cache down")
        return await super().get(key)

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        self.names.append(key)
        if self.fail_set:
            raise ConnectionError("cache down")
        await super().set(key, value, ttl)


def _adapter_over(cache: InMemoryCache, client: RecordingRouteClient) -> RoutingTravelTime:
    return RoutingTravelTime(client, BASE, EXTRACT, cache, FixedTravelTime(FALLBACK_RANGE))


async def test_a_cache_that_cannot_be_read_falls_back_to_the_estimate_and_asks_no_engine() -> None:
    cache = _FailingCache(FixedClock(NOW), fail_get=True)
    client = RecordingRouteClient((200, ROUTE_1800))
    with bind_tenant("tenant-alpha"):
        found = await _adapter_over(cache, client).estimate(PATIENT, SITE)

    assert found == FALLBACK_RANGE
    assert client.urls == []


async def test_a_cache_that_cannot_be_written_still_answers_the_routed_range() -> None:
    cache = _FailingCache(FixedClock(NOW), fail_set=True)
    client = RecordingRouteClient((200, ROUTE_1800))
    with bind_tenant("tenant-alpha"):
        found = await _adapter_over(cache, client).estimate(PATIENT, SITE)

    assert found != FALLBACK_RANGE
    assert found.source == f"Routing data, updated {EXTRACT}"
    assert len(client.urls) == 1


async def test_the_key_names_the_pair_and_not_the_tenant() -> None:
    cache = _FailingCache(FixedClock(NOW))
    with bind_tenant("tenant-alpha"):
        await _adapter_over(cache, RecordingRouteClient((200, ROUTE_1800))).estimate(PATIENT, SITE)

    assert cache.names
    assert all("tenant-alpha" not in name for name in cache.names)
    assert all(name.startswith("travel:") for name in cache.names)


async def test_a_missing_tenant_still_stops_the_estimate_even_with_a_failing_cache() -> None:
    cache = _FailingCache(FixedClock(NOW), fail_get=True)
    with pytest.raises(TenantNotBound):
        await _adapter_over(cache, RecordingRouteClient((200, ROUTE_1800))).estimate(PATIENT, SITE)
