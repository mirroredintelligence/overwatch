"""The ONS Postcode Directory adapter (DEC-1329). httpx MockTransport, no network."""

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from overwatch.adapters.outbound.postcode_directory_ons.ons_directory import (
    OnsPostcodeDirectory,
    _like,
    parse_page,
)
from overwatch.application.ports.outbound.lookups import LookupRejected, TransientLookupError


def _feature(code: str, lat: float, lon: float) -> dict[str, Any]:
    return {"attributes": {"pcds": code, "lat": lat, "long": lon}}


def _client(
    answer: Any, status: int = 200, seen: list[dict[str, str]] | None = None
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        query = {
            key: values[0] for key, values in parse_qs(urlsplit(str(request.url)).query).items()
        }
        if seen is not None:
            seen.append(query)
        body = answer(query) if callable(answer) else answer
        return httpx.Response(status, content=json.dumps(body).encode())

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_a_bare_district_matches_with_a_space_so_dt4_does_not_match_dt40() -> None:
    assert _like("DT4") == "DT4 %"
    assert _like("DT4 0") == "DT4 0%"


@pytest.mark.parametrize("prefix", ["DT4'; DROP", "DT4 0' OR '1'='1", "dt4", "", "DT4 0AW1"])
def test_a_prefix_outside_the_pattern_never_reaches_the_query(prefix: str) -> None:
    with pytest.raises(ValueError):
        _like(prefix)


async def test_count_asks_for_a_count_only_and_returns_it() -> None:
    seen: list[dict[str, str]] = []
    directory = OnsPostcodeDirectory(_client({"count": 1505}, seen=seen))
    assert await directory.count("DT4") == 1505
    assert seen == [{"where": "pcds LIKE 'DT4 %'", "returnCountOnly": "true", "f": "json"}]


async def test_postcodes_pages_in_object_id_order_until_the_directory_says_no_more() -> None:
    seen: list[dict[str, str]] = []

    def answer(query: dict[str, str]) -> dict[str, Any]:
        if query["resultOffset"] == "0":
            return {"features": [_feature("DT4 0AW", 50.61, -2.46)], "exceededTransferLimit": True}
        return {"features": [_feature("DT4 0AX", 50.60, -2.46)]}

    found = await OnsPostcodeDirectory(_client(answer, seen=seen)).postcodes("DT4")
    assert [p.postcode for p in found] == ["DT4 0AW", "DT4 0AX"]
    assert [q["resultOffset"] for q in seen] == ["0", "1000"]
    assert all(q["orderByFields"] == "ObjectId" for q in seen)


async def test_a_refusal_answer_in_the_body_is_a_rejection_not_an_empty_district() -> None:
    with pytest.raises(LookupRejected):
        await OnsPostcodeDirectory(_client({"error": {"code": 400}})).postcodes("DT4")


async def test_a_server_error_is_transient() -> None:
    with pytest.raises(TransientLookupError):
        await OnsPostcodeDirectory(_client({}, status=503)).count("DT4")


def test_parse_page_rejects_a_point_that_is_not_a_number() -> None:
    with pytest.raises(TransientLookupError):
        parse_page({"features": [{"attributes": {"pcds": "DT4 0AW", "lat": None, "long": -2.4}}]})


def test_parse_page_keeps_the_points_as_given() -> None:
    postcodes, more = parse_page({"features": [_feature("DT4 0AW", 50.6, -2.5)]})
    assert postcodes[0].postcode == "DT4 0AW"
    assert (postcodes[0].lat, postcodes[0].lon) == (50.6, -2.5)
    assert more is False
