"""Routing travel-time adapter (I15): the TravelTime port answered by a self-hosted routing engine
that speaks the OSRM route API. Stub for the red commit; the implementation follows.
"""

from datetime import timedelta
from typing import Final, Protocol

from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.geo import LatLon, TravelRange, TravelTime

ROUTING_TIMEOUT: Final = timedelta(seconds=3)  # [ASSUMED] I15 prompt: 2 s; owner set 3 s


class RoutingFailed(Exception):
    def __init__(self) -> None:
        raise NotImplementedError


class RoutingReplyMalformed(RoutingFailed):
    pass


class RouteHttpClient(Protocol):
    async def get_json(self, url: str, timeout: timedelta) -> tuple[int, object]: ...


class HttpxRouteClient:
    def __init__(self, client: object) -> None:
        raise NotImplementedError

    async def get_json(self, url: str, timeout: timedelta) -> tuple[int, object]:
        raise NotImplementedError


def range_from_duration(seconds: float, extract_date: str) -> TravelRange:
    raise NotImplementedError


def route_url(base_url: str, origin: LatLon, destination: LatLon) -> str:
    raise NotImplementedError


def duration_seconds(body: object) -> float:
    raise NotImplementedError


class RoutingTravelTime:
    def __init__(
        self,
        client: RouteHttpClient,
        base_url: str,
        extract_date: str,
        cache: Cache,
        fallback: TravelTime,
        timeout: timedelta = ROUTING_TIMEOUT,
    ) -> None:
        raise NotImplementedError

    async def estimate(self, origin: LatLon, destination: LatLon) -> TravelRange:
        raise NotImplementedError
