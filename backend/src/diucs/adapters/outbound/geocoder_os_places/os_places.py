"""OS Places geocoder for service site postcodes (I12). STUB for the red commit: names only."""

from typing import Any

from diucs.application.ports.outbound.geo import AddressCandidate


def parse_os_places(payload: Any) -> list[AddressCandidate]:
    raise NotImplementedError


class OsPlacesGeocoder:
    def __init__(self, client: Any, api_key: str) -> None:
        self._client = client
        self._api_key = api_key

    async def find_addresses(self, postcode: str) -> list[AddressCandidate]:
        raise NotImplementedError
