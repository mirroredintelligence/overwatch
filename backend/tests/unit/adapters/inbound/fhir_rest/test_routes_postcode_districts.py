"""The district check route (DEC-1329), through the app on the rig's stand-ins: a shift lead checks
a district and gets its postcode count; a narrowed prefix counts its own postcodes; an unknown
district is refused; a directory that cannot answer is a 503, never a count; a reporter gets the
non-revealing 404. Sample values only."""

from typing import Any

from overwatch.application.ports.outbound.lookups import TransientLookupError
from overwatch.domain.codes import Role
from tests.support.w7b_rig import LEAD, Rig, bearer, client

CHECK = "/postcode-districts/check"
CHECK_DOWNLOAD = "/postcode-districts/download"
LEAD_AUTH = bearer(Role.LEAD, LEAD)
REPORTER_AUTH = bearer(Role.REPORTER, "prac-reporter")


async def test_a_lead_checks_a_district_and_gets_its_postcode_count() -> None:
    async with client(Rig()) as http:
        response = await http.get(f"{CHECK}?text=dt4", headers=LEAD_AUTH)
    assert response.status_code == 200, response.text
    assert response.json() == {"prefix": "DT4", "postcodes": 2}
    assert response.headers["cache-control"] == "no-store"


async def test_a_typed_inward_start_narrows_the_count() -> None:
    async with client(Rig()) as http:
        response = await http.get(f"{CHECK}?text=DT4%200", headers=LEAD_AUTH)
    assert response.status_code == 200, response.text
    assert response.json() == {"prefix": "DT4 0", "postcodes": 2}


async def test_an_unknown_district_is_refused_without_echoing_the_input() -> None:
    async with client(Rig()) as http:
        response = await http.get(f"{CHECK}?text=ZZ99", headers=LEAD_AUTH)
    assert response.status_code == 400
    assert "ZZ99" not in response.text


async def test_a_directory_that_cannot_answer_is_a_503_and_never_a_count() -> None:
    class _Down:
        async def count(self, prefix: str) -> int:
            raise TransientLookupError

        async def postcodes(self, prefix: str) -> list[Any]:
            raise TransientLookupError

    rig = Rig()
    rig.postcode_directory = _Down()  # type: ignore[assignment]
    async with client(rig) as http:
        response = await http.get(f"{CHECK}?text=DT4", headers=LEAD_AUTH)
    assert response.status_code == 503


async def test_only_the_shift_lead_checks_a_district() -> None:
    async with client(Rig()) as http:
        response = await http.get(f"{CHECK}?text=DT4", headers=REPORTER_AUTH)
    assert response.status_code == 404


async def test_a_lead_queues_a_confirmed_district_and_nothing_is_downloaded_in_the_request() -> (
    None
):
    rig = Rig()
    async with client(rig) as http:
        response = await http.post(f"{CHECK_DOWNLOAD}?text=dt4", headers=LEAD_AUTH, json={})
    assert response.status_code == 202, response.text
    assert response.json() == {"prefix": "DT4", "status": "queued"}
    assert list(rig.postcode_queue.rows) == ["DT4"]
    assert rig.postcode_queue.rows["DT4"]["status"] == "queued"


async def test_a_download_request_that_is_not_a_district_is_refused_and_queues_nothing() -> None:
    rig = Rig()
    async with client(rig) as http:
        response = await http.post(f"{CHECK_DOWNLOAD}?text=DT4%20ABC", headers=LEAD_AUTH, json={})
    assert response.status_code == 400
    assert rig.postcode_queue.rows == {}


async def test_only_the_shift_lead_requests_a_download() -> None:
    rig = Rig()
    async with client(rig) as http:
        response = await http.post(f"{CHECK_DOWNLOAD}?text=DT4", headers=REPORTER_AUTH, json={})
    assert response.status_code == 404
    assert rig.postcode_queue.rows == {}
