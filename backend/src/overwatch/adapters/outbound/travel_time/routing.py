"""Routing travel-time adapter (I15): the TravelTime port answered by a self-hosted routing engine
that speaks the OSRM route API (OSRM itself, or Valhalla's OSRM-compatible endpoint).

Why self-hosted, and why behind this port (orchestrator decision, I15 round 2): patient positions
stay in-house, with no third-party data transfer and no per-request licence; the port keeps the
choice of engine reversible. The position sent is a postcode centroid, never an address.

The route is requested as `GET {base}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false`
and `routes[0].duration` (seconds) gives the low end of the range. Any failure (a timeout, a
transport error, an error status, a reply that is not a route) falls back to the TravelTime port
given at construction (the straight-line estimate, I11). Nothing here logs, and no error carries a
coordinate, a URL or a reply body.
"""

import asyncio
import hashlib
import json
import math
from datetime import timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Final, Protocol

import httpx

from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.geo import LatLon, TravelRange, TravelTime
from diucs.application.tenancy import TenantNotBound, current_tenant
from diucs.domain.errors import ValidationFailed

# [ASSUMED] The request timeout. The I15 prompt said 2 s; the owner set 3 s.
ROUTING_TIMEOUT: Final = timedelta(seconds=3)
# [ASSUMED] The high end of the range is the duration times this traffic spread (I15 prompt).
TRAFFIC_SPREAD: Final = Decimal("1.4")
# Both ends of the range are rounded up to a whole number of minutes, then to this step (I15).
ROUND_UP_TO_MINUTES: Final = 5
# A routed range is kept for 24 hours, keyed by the directional pair (I15). The cache puts the bound
# tenant in every name itself (TEN-019), so the key does not repeat it (KI-203).
ROUTE_CACHE_TTL: Final = timedelta(hours=24)
# Six decimal places of a degree is about 0.1 metre: more than a postcode centroid needs.
_COORDINATE: Final = "{:.6f}"
_CACHE_KEY: Final = "travel:{}"


class RoutingFailed(Exception):
    """A routing answer cannot be used. Carries no coordinate, URL, status text or reply body."""

    def __init__(self) -> None:
        super().__init__()


class RoutingReplyMalformed(RoutingFailed):
    """The routing reply holds no usable duration. Carries nothing (no coordinate, no body)."""


class RouteHttpClient(Protocol):
    """Sends one GET and returns the status code and the parsed JSON body (None when the body is
    not JSON). A timeout raises TimeoutError; any other transport failure raises RoutingFailed.
    Production: HttpxRouteClient. Tests: a recording fake, so no engine is called."""

    async def get_json(self, url: str, timeout: timedelta) -> tuple[int, object]: ...


class HttpxRouteClient:
    """The RouteHttpClient over an httpx client. Errors are re-raised without the URL, because the
    URL carries the coordinates."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_json(self, url: str, timeout: timedelta) -> tuple[int, object]:
        try:
            response = await self._client.get(url, timeout=timeout.total_seconds())
        except httpx.TimeoutException:
            raise TimeoutError() from None
        except httpx.HTTPError:
            raise RoutingFailed() from None
        try:
            body: object = response.json()
        except ValueError:
            body = None
        return response.status_code, body


def _whole_minutes_up(seconds: Decimal) -> int:
    return int((seconds / 60).to_integral_value(rounding=ROUND_CEILING))


def _up_to_step(minutes: int) -> int:
    return -(-minutes // ROUND_UP_TO_MINUTES) * ROUND_UP_TO_MINUTES


def range_from_duration(seconds: float, extract_date: str) -> TravelRange:
    """The range for one routed duration: the low end is the duration, the high end the duration
    times TRAFFIC_SPREAD; both are rounded up to whole minutes, then to five minutes. The source
    names the extract date of the routing data."""
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("a duration must be a finite, non-negative number of seconds")
    exact = Decimal(repr(seconds))
    low = _up_to_step(_whole_minutes_up(exact))
    high = _up_to_step(_whole_minutes_up(exact * TRAFFIC_SPREAD))
    return TravelRange(
        low_minutes=low, high_minutes=high, source=f"Routing data, updated {extract_date}"
    )


def _coordinate(value: float) -> str:
    return _COORDINATE.format(value)


def route_url(base_url: str, origin: LatLon, destination: LatLon) -> str:
    """The OSRM route request for one pair. Longitude comes before latitude."""
    pair = (
        f"{_coordinate(origin.lon)},{_coordinate(origin.lat)};"
        f"{_coordinate(destination.lon)},{_coordinate(destination.lat)}"
    )
    return f"{base_url.rstrip('/')}/route/v1/driving/{pair}?overview=false"


def duration_seconds(body: object) -> float:
    """The duration of routes[0], in seconds. Anything else is a RoutingReplyMalformed."""
    if not isinstance(body, dict):
        raise RoutingReplyMalformed()
    routes = body.get("routes")
    if not isinstance(routes, list) or not routes:
        raise RoutingReplyMalformed()
    first = routes[0]
    if not isinstance(first, dict):
        raise RoutingReplyMalformed()
    duration = first.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, int | float):
        raise RoutingReplyMalformed()
    value = float(duration)
    if not math.isfinite(value) or value < 0:
        raise RoutingReplyMalformed()
    return value


def _cache_key(origin: LatLon, destination: LatLon) -> str:
    """Directional: patient to site and site to patient are different keys (architecture F8). The
    pair is hashed, so no coordinate is readable in a key name. The tenant is not in the key: the
    cache qualifies every name with the bound scope (TEN-019, KI-203)."""
    pair = (
        f"{_coordinate(origin.lat)},{_coordinate(origin.lon)}>"
        f"{_coordinate(destination.lat)},{_coordinate(destination.lon)}"
    )
    return _CACHE_KEY.format(hashlib.sha256(pair.encode("ascii")).hexdigest())


def _encode_range(travel: TravelRange) -> str:
    return json.dumps(
        {"low": travel.low_minutes, "high": travel.high_minutes, "source": travel.source},
        sort_keys=True,
    )


def _decode_range(text: str) -> TravelRange | None:
    try:
        body = json.loads(text)
        return TravelRange(
            low_minutes=int(body["low"]),
            high_minutes=int(body["high"]),
            source=str(body["source"]),
        )
    except ValueError, KeyError, TypeError, ValidationFailed:
        return None


class RoutingTravelTime:
    """The TravelTime port over a routing engine, with the port `fallback` for any failure.

    The cache is read and written under the bound tenant; a missing tenant is an error, never a
    default. Only routed answers are cached: a fallback is not, so routing is asked again next time.
    A cache that cannot be read or written never fails the options list (KI-202): an unreadable
    cache answers the fallback estimate at once (the engine is not asked on a cache that is down,
    so a Redis outage does not turn into a burst of route requests), and an unwritable cache only
    loses the keeping of an answer already in hand.
    """

    def __init__(
        self,
        client: RouteHttpClient,
        base_url: str,
        extract_date: str,
        cache: Cache,
        fallback: TravelTime,
        timeout: timedelta = ROUTING_TIMEOUT,
    ) -> None:
        self._client = client
        self._base_url = base_url
        self._extract_date = extract_date
        self._cache = cache
        self._fallback = fallback
        self._timeout = timeout

    async def estimate(self, origin: LatLon, destination: LatLon) -> TravelRange:
        current_tenant()  # no tenant bound is an error, never a default
        key = _cache_key(origin, destination)
        try:
            cached = await self._cache.get(key)
        except TenantNotBound:
            raise
        except Exception:
            return await self._fallback.estimate(origin, destination)
        if cached is not None:
            found = _decode_range(cached)
            if found is not None:
                return found
        try:
            seconds = await self._route_seconds(origin, destination)
        except RoutingFailed, TimeoutError:
            return await self._fallback.estimate(origin, destination)
        result = range_from_duration(seconds, self._extract_date)
        try:
            await self._cache.set(key, _encode_range(result), ROUTE_CACHE_TTL)
        except TenantNotBound:
            raise
        except Exception:
            pass  # the answer is in hand; only the keeping of it is lost
        return result

    async def _route_seconds(self, origin: LatLon, destination: LatLon) -> float:
        url = route_url(self._base_url, origin, destination)
        # The adapter's own deadline, so a client that ignores its timeout still falls back.
        async with asyncio.timeout(self._timeout.total_seconds()):
            status, body = await self._client.get_json(url, self._timeout)
        if status != 200:
            raise RoutingFailed()
        return duration_seconds(body)
