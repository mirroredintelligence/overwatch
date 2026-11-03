"""ONS Postcode Directory adapter (DEC-1329): the postcodes of a district, from the ONS hosted table
on the Open Geography Portal (February 2026 release, under the Open Government Licence).

Only a district or a district with a typed inward start ("DT4", "DT4 0") is sent, and it is checked
against a fixed pattern before it reaches the query, because the value is placed in the ArcGIS SQL
`where` clause. A malformed prefix raises ValueError and makes no request.

The directory is queried in pages of 1000 with an ObjectId order, so every page is stable. A count
is one request. A transient failure (unreachable, 5xx, 429, a malformed answer) raises
TransientLookupError; a refusal, including an ArcGIS error answer, raises LookupRejected.
"""

import math
import re
from typing import Any, Final

import httpx

from overwatch.application.ports.outbound.lookups import LookupRejected, TransientLookupError
from overwatch.application.ports.outbound.postcode_directory import DirectoryPostcode

QUERY_URL: Final = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "ONS_Postcode_Directory_(February_2026)_for_the_UK_(Hosted_Table)/FeatureServer/0/query"
)
PAGE_SIZE: Final = 1000
MAX_PAGES: Final = 200  # 200,000 postcodes: far beyond any district; a guard, not a limit we expect
REQUEST_TIMEOUT_SECONDS: Final = 30.0

# The outward code, then optionally a space and the typed start of the inward code (a digit, then up
# to two letters). Nothing else reaches the query.
PREFIX: Final = re.compile(r"[A-Z]{1,2}[0-9][A-Z0-9]?(?: [0-9][A-Z]{0,2})?")


def _like(prefix: str) -> str:
    """The SQL LIKE pattern for a prefix. A bare district gets a space: DT4 must not match DT40."""
    if not PREFIX.fullmatch(prefix):
        raise ValueError("not a district or a typed prefix of one")
    return f"{prefix}%" if " " in prefix else f"{prefix} %"


def _number(value: Any) -> float:
    if type(value) not in (int, float):
        raise TransientLookupError("the directory answer has no coordinate")
    number = float(value)
    if not math.isfinite(number):
        raise TransientLookupError("the directory answer has no coordinate")
    return number


def parse_page(payload: Any) -> tuple[list[DirectoryPostcode], bool]:
    """The postcodes in one page, and whether the directory has more pages."""
    if not isinstance(payload, dict):
        raise TransientLookupError("the directory answer is not an object")
    if "error" in payload:
        raise LookupRejected("the directory refused the query")
    features = payload.get("features")
    if not isinstance(features, list):
        raise TransientLookupError("the directory answer has no features list")
    postcodes: list[DirectoryPostcode] = []
    for feature in features:
        attributes = feature.get("attributes") if isinstance(feature, dict) else None
        if not isinstance(attributes, dict):
            raise TransientLookupError("the directory answer has no attributes")
        code = attributes.get("pcds")
        if type(code) is not str or not code:
            raise TransientLookupError("the directory answer has no postcode")
        postcodes.append(
            DirectoryPostcode(
                postcode=code,
                lat=_number(attributes.get("lat")),
                lon=_number(attributes.get("long")),
            )
        )
    return postcodes, bool(payload.get("exceededTransferLimit"))


class OnsPostcodeDirectory:
    """The PostcodeDirectory port over the ONS hosted table. The client is injected; tests give it a
    MockTransport."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def _get(self, params: dict[str, str]) -> Any:
        try:
            response = await self._client.get(
                QUERY_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except httpx.HTTPError:
            raise TransientLookupError("the postcode directory could not be reached") from None
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientLookupError(f"the postcode directory answered {response.status_code}")
        if response.status_code != 200:
            raise LookupRejected(
                f"the postcode directory refused the request with {response.status_code}"
            )
        try:
            return response.json()
        except ValueError:
            raise TransientLookupError("the directory answer is not JSON") from None

    async def count(self, prefix: str) -> int:
        # A bare district is one fast count. A narrowed prefix ("DT4 0") is slow on the directory's
        # side (about 20 seconds, for a LIKE or a range), so it is counted here from the district's
        # own postcodes, which come back in pages in well under a second.
        if " " not in prefix:
            payload = await self._get(
                {"where": f"pcds LIKE '{_like(prefix)}'", "returnCountOnly": "true", "f": "json"}
            )
            if not isinstance(payload, dict) or "error" in payload:
                raise LookupRejected("the directory refused the count")
            count = payload.get("count")
            if type(count) is not int or count < 0:
                raise TransientLookupError("the directory answer has no count")
            return count
        _like(
            prefix
        )  # the same pattern check as the query: a malformed prefix raises before any request
        district = prefix.split(" ", 1)[0]
        found = await self.postcodes(district)
        return sum(1 for point in found if point.postcode.startswith(prefix))

    async def postcodes(self, prefix: str) -> list[DirectoryPostcode]:
        where = f"pcds LIKE '{_like(prefix)}'"
        found: list[DirectoryPostcode] = []
        for page in range(MAX_PAGES):
            payload = await self._get(
                {
                    "where": where,
                    "outFields": "pcds,lat,long",
                    "returnGeometry": "false",
                    "orderByFields": "ObjectId",
                    "resultOffset": str(page * PAGE_SIZE),
                    "resultRecordCount": str(PAGE_SIZE),
                    "f": "json",
                }
            )
            postcodes, more = parse_page(payload)
            found.extend(postcodes)
            if not more or not postcodes:
                return found
        raise TransientLookupError("the postcode directory has more pages than the guard allows")
