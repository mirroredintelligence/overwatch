"""OS Places geocoder for service site postcodes (I12).

Only a service's site postcode is sent here, at registration (DEC-047). A patient's postcode never
is: it is located from the local file (I11). The request is the OS Places postcode search with the
normalised postcode (no space), output_srs=WGS84, dataset=DPA and the key.

The key is a query parameter, so the request URL carries it. httpx logs each request URL at INFO,
so this module lowers the httpx logger to WARNING, and no code here logs a URL or an error body.
A transient failure (unreachable, 5xx, 429, a malformed answer) raises TransientLookupError; a
refusal raises LookupRejected; "no results" is an empty list. Field names follow the prompt; they
are not yet verified against the OS documentation (open item).
"""

import logging
import math
from typing import Any, Final

import httpx

from diucs.application.ports.outbound.geo import AddressCandidate, LatLon
from diucs.application.ports.outbound.lookups import LookupRejected, TransientLookupError
from diucs.domain.rules.postcode import normalise_postcode

OS_PLACES_URL: Final = "https://api.os.uk/search/places/v1/postcode"
OUTPUT_SRS: Final = "WGS84"
DATASET: Final = "DPA"
NO_RESULTS: Final = "no results"
REQUEST_TIMEOUT_SECONDS: Final = 10.0

# The key travels in the request URL (see the module docstring): keep httpx's request lines out of
# the logs, so the key never reaches a log record (DEC-047).
logging.getLogger("httpx").setLevel(logging.WARNING)


def _text(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if type(value) is not str or not value:
        raise TransientLookupError(f"the address answer has no {field}")
    return value


def _number(record: dict[str, Any], field: str) -> float:
    value = record.get(field)
    try:
        number = float(value)  # type: ignore[arg-type]
    except TypeError, ValueError:
        raise TransientLookupError(f"the address answer has no {field}") from None
    if not math.isfinite(number):
        raise TransientLookupError(f"the address answer has no {field}")
    return number


def parse_os_places(payload: Any) -> list[AddressCandidate]:
    """The candidates in an OS Places answer. A missing field or a wrong shape is a transient error
    (a service fault), never a guessed address."""
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise TransientLookupError("the address answer has no results list")
    candidates: list[AddressCandidate] = []
    for item in payload["results"]:
        dpa = item.get("DPA") if isinstance(item, dict) else None
        if not isinstance(dpa, dict):
            raise TransientLookupError("the address answer has no DPA record")
        candidates.append(
            AddressCandidate(
                uprn=_text(dpa, "UPRN"),
                line=_text(dpa, "ADDRESS"),
                town=_text(dpa, "POST_TOWN"),
                postcode=_text(dpa, "POSTCODE"),
                position=LatLon(_number(dpa, "LAT"), _number(dpa, "LNG")),
            )
        )
    return candidates


def _is_no_results(response: httpx.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return isinstance(message, str) and NO_RESULTS in message.lower()


class OsPlacesGeocoder:
    """The Geocoder port over OS Places. The client is injected; tests give it a MockTransport."""

    def __init__(self, client: httpx.AsyncClient, api_key: str) -> None:
        self._client = client
        self._api_key = api_key

    async def find_addresses(self, postcode: str) -> list[AddressCandidate]:
        full = normalise_postcode(postcode)
        if full is None:
            return []
        params = {
            "postcode": full.replace(" ", ""),
            "output_srs": OUTPUT_SRS,
            "dataset": DATASET,
            "key": self._api_key,
        }
        try:
            response = await self._client.get(OS_PLACES_URL, params=params)
        except httpx.HTTPError:
            raise TransientLookupError("the address service could not be reached") from None
        status = response.status_code
        if status == 200:
            try:
                payload = response.json()
            except ValueError:
                raise TransientLookupError("the address answer is not JSON") from None
            return parse_os_places(payload)
        if status == 400 and _is_no_results(response):
            return []
        if status == 429 or status >= 500:
            raise TransientLookupError(f"the address service answered {status}")
        raise LookupRejected(f"the address service refused the request with {status}")
