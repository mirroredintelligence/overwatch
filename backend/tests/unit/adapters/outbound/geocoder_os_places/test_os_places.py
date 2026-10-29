"""The OS Places geocoder (I12). httpx MockTransport, no network, no Docker.

Field names follow the prompt (DPA: ADDRESS, UPRN, POSTCODE, POST_TOWN, LAT, LNG). They are not yet
verified against the OS documentation, which is unreachable from this session (open item).
The key is a query parameter, so it must never reach a log line or an error (DEC-047).
"""

import json
import logging
from typing import Any

import httpx
import pytest

from diucs.adapters.outbound.geocoder_os_places.os_places import OsPlacesGeocoder, parse_os_places
from diucs.application.ports.outbound.geo import AddressCandidate, LatLon
from diucs.application.ports.outbound.lookups import TransientLookupError

KEY = "test-os-places-key-0123456789"
SAMPLE: dict[str, Any] = {
    "header": {"totalresults": 2},
    "results": [
        {
            "DPA": {
                "UPRN": "100000000001",
                "ADDRESS": "1 EXAMPLE CLOSE, DORCHESTER, DT1 1AA",
                "POSTCODE": "DT1 1AA",
                "POST_TOWN": "DORCHESTER",
                "LAT": 50.7100,
                "LNG": -2.4450,
            }
        },
        {
            "DPA": {
                "UPRN": "100000000002",
                "ADDRESS": "2 EXAMPLE CLOSE, DORCHESTER, DT1 1AA",
                "POSTCODE": "DT1 1AA",
                "POST_TOWN": "DORCHESTER",
                "LAT": 50.7101,
                "LNG": -2.4449,
            }
        },
    ],
}
FIRST = AddressCandidate(
    uprn="100000000001",
    line="1 EXAMPLE CLOSE, DORCHESTER, DT1 1AA",
    town="DORCHESTER",
    postcode="DT1 1AA",
    position=LatLon(50.7100, -2.4450),
)


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- 1: parsing -----------------------------------------------------------------------------------


def test_parse_returns_each_address_with_uprn_line_town_postcode_and_position() -> None:
    candidates = parse_os_places(SAMPLE)

    assert len(candidates) == 2
    assert candidates[0] == FIRST
    assert candidates[1].uprn == "100000000002"


def test_parse_of_an_empty_result_list_is_no_candidates() -> None:
    assert parse_os_places({"results": []}) == []


@pytest.mark.parametrize("bad", [{}, {"results": "not a list"}, {"results": [{"DPA": {}}]}])
def test_parse_refuses_a_response_without_the_fields_it_needs(bad: Any) -> None:
    with pytest.raises(TransientLookupError):
        parse_os_places(bad)


# --- 2: the request -------------------------------------------------------------------------------


async def test_the_request_uses_the_normalised_postcode_and_the_wgs84_dataset_parameters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=SAMPLE)

    geocoder = OsPlacesGeocoder(_client(handler), KEY)
    await geocoder.find_addresses("dt1  1aa")

    assert len(seen) == 1
    url = seen[0].url
    assert url.host == "api.os.uk"
    assert url.path == "/search/places/v1/postcode"
    assert url.params["postcode"] == "DT11AA"
    assert url.params["output_srs"] == "WGS84"
    assert url.params["dataset"] == "DPA"
    assert url.params["key"] == KEY


async def test_the_key_is_never_in_a_log_record_or_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    geocoder = OsPlacesGeocoder(_client(handler), KEY)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(TransientLookupError) as failed:
        await geocoder.find_addresses("DT1 1AA")

    assert KEY not in str(failed.value)
    assert all(KEY not in record.getMessage() for record in caplog.records)


async def test_a_postcode_that_is_not_full_is_not_sent_at_all() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("an invalid postcode must not reach the service")

    geocoder = OsPlacesGeocoder(_client(handler), KEY)

    assert await geocoder.find_addresses("DT4 8") == []


# --- 3: the answers -------------------------------------------------------------------------------


async def test_a_400_no_results_answer_is_an_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"statuscode": 400, "message": "No results found"}}
        )

    geocoder = OsPlacesGeocoder(_client(handler), KEY)

    assert await geocoder.find_addresses("DT1 1AA") == []


async def test_a_500_answer_is_a_transient_lookup_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    geocoder = OsPlacesGeocoder(_client(handler), KEY)

    with pytest.raises(TransientLookupError):
        await geocoder.find_addresses("DT1 1AA")


async def test_a_network_failure_is_a_transient_lookup_error_without_the_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    geocoder = OsPlacesGeocoder(_client(handler), KEY)

    with pytest.raises(TransientLookupError) as failed:
        await geocoder.find_addresses("DT1 1AA")

    assert KEY not in str(failed.value)


async def test_a_successful_answer_is_parsed_into_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(SAMPLE).encode())

    geocoder = OsPlacesGeocoder(_client(handler), KEY)

    candidates = await geocoder.find_addresses("DT1 1AA")

    assert candidates[0] == FIRST
