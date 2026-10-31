"""The practitioner app's routes (DEC-1306 to DEC-1309): the role boundary, the refusals that come
before any read, and the shape of the answers the front end parses (frontend/lib/practitioner). The
stored answers and the tenant boundary are in tests/integration/. Values are synthetic.
"""

from datetime import UTC, datetime

import pytest

from overwatch.adapters.inbound.fhir_rest.routes_practitioner import shift_json, visit_json
from overwatch.application.use_cases.visit_offers import (
    NextVisit,
    OfferSummary,
    RoundItem,
    ShiftView,
    VisitView,
)
from overwatch.domain.codes import Role
from overwatch.domain.model.visit import LocationChoice, ShiftStatus, VisitState
from tests.support.route_unit import KEY, assert_role_matrix, bearer, route_client

AT = datetime(2026, 10, 31, 14, 30, tzinfo=UTC)
OFFER = {
    "bookingId": "bk-1",
    "postcode": "DT4 8AB",
    "address": "1 Synthetic Street",
    "contact": "Daughter",
}
PRACTITIONER = frozenset({Role.REPORTER})


async def test_the_reads_are_for_a_signed_in_practitioner_only() -> None:
    async with route_client() as client:
        await assert_role_matrix(client, "GET", "/practitioner/shift", PRACTITIONER)
        await assert_role_matrix(client, "GET", "/practitioner/visits/vo-1", PRACTITIONER)


async def test_the_writes_are_for_a_signed_in_practitioner_only() -> None:
    async with route_client() as client:
        await assert_role_matrix(
            client,
            "PUT",
            "/practitioner/settings",
            PRACTITIONER,
            body={"location": "travel"},
        )
        for action, body in (
            ("accept", {}),
            ("decline", {}),
            ("status", {"status": "arrived"}),
        ):
            await assert_role_matrix(
                client,
                "POST",
                f"/practitioner/visits/vo-1/{action}",
                PRACTITIONER,
                body=body,
                headers=KEY,
            )


async def test_an_offer_is_made_by_an_advisor_or_a_clinician_only() -> None:
    async with route_client() as client:
        await assert_role_matrix(
            client, "POST", "/visits/offers", frozenset({Role.ADVISOR, Role.CLINICAL}), body=OFFER
        )


@pytest.mark.parametrize(
    "body",
    [
        {**OFFER, "tenant": "other"},
        {**OFFER, "practitionerId": "p-9"},
        {"bookingId": "bk-1"},
        {**OFFER, "postcode": ""},
        {**OFFER, "address": "x" * 401},
    ],
)
async def test_an_offer_body_that_names_more_or_less_than_the_four_answers_is_a_400(
    body: dict[str, str],
) -> None:
    async with route_client() as client:
        response = await client.post("/visits/offers", json=body, headers=bearer(Role.ADVISOR))

    assert response.status_code in (400, 422)
    assert "1 Synthetic Street" not in response.text
    assert "DT4 8AB" not in response.text


@pytest.mark.parametrize(
    "body",
    [{"status": "arrived", "tenant": "t"}, {"status": "arrived", "etaMinutes": "10"}, {}],
)
async def test_a_status_body_with_anything_else_is_a_400(body: dict[str, str]) -> None:
    async with route_client() as client:
        response = await client.post(
            "/practitioner/visits/vo-1/status", json=body, headers={**bearer(Role.REPORTER), **KEY}
        )

    assert response.status_code in (400, 422)


async def test_a_settings_body_with_anything_else_is_a_400() -> None:
    async with route_client() as client:
        response = await client.put(
            "/practitioner/settings",
            json={"location": "travel", "latitude": 51.0},
            headers=bearer(Role.REPORTER),
        )

    assert response.status_code in (400, 422)


async def test_a_status_word_that_is_not_in_the_list_is_a_400_before_anything_is_read() -> None:
    async with route_client() as client:
        for word in ("accepted", "banana"):
            response = await client.post(
                "/practitioner/visits/vo-1/status",
                json={"status": word},
                headers={**bearer(Role.REPORTER), **KEY},
            )
            assert response.status_code == 400


async def test_an_accept_without_an_idempotency_key_is_a_400() -> None:
    async with route_client() as client:
        response = await client.post(
            "/practitioner/visits/vo-1/accept", json={}, headers=bearer(Role.REPORTER)
        )

    assert response.status_code == 400


def test_the_shift_answer_has_the_shape_the_screen_reads() -> None:
    body = shift_json(
        ShiftView(
            status=ShiftStatus.AVAILABLE,
            location=LocationChoice.NEVER,
            visits_today=4,
            next_visit=NextVisit("vo-1", "DT4 8", AT, "within 2 hrs"),
            offers=(OfferSummary("vo-2", "Fall, no injury", "DT4 8", "today", AT),),
            round=(RoundItem("vo-1", "DT4 8", VisitState.ACCEPTED, AT, "within 2 hrs"),),
        )
    )

    assert body == {
        "status": "available",
        "location": "never",
        "visitsToday": 4,
        "next": {
            "id": "vo-1",
            "sector": "DT4 8",
            "dueBy": "2026-10-31T14:30:00Z",
            "wantedWithin": "within 2 hrs",
        },
        "offers": [
            {
                "id": "vo-2",
                "need": "Fall, no injury",
                "sector": "DT4 8",
                "wantedWithin": "today",
                "expiresAt": "2026-10-31T14:30:00Z",
            }
        ],
        "round": [
            {
                "id": "vo-1",
                "sector": "DT4 8",
                "state": "accepted",
                "dueBy": "2026-10-31T14:30:00Z",
                "wantedWithin": "within 2 hrs",
            }
        ],
    }


def test_a_shift_with_nothing_set_is_nulls_and_empties() -> None:
    body = shift_json(ShiftView(None, LocationChoice.NEVER, 0, None, ()))

    assert body["status"] is None and body["next"] is None
    assert body["offers"] == [] and body["round"] == []


def _visit(**changes: object) -> VisitView:
    base: dict[str, object] = {
        "id": "vo-1",
        "reference": "4821",
        "state": VisitState.OFFERED,
        "need": "Fall, no injury",
        "sector": "DT4 8",
        "wanted_within": "within 2 hrs",
        "expires_at": AT,
        "fits_minutes": None,
        "address": None,
        "contact": None,
        "eta_at": None,
        "location": LocationChoice.NEVER,
    }
    return VisitView(**{**base, **changes})  # type: ignore[arg-type]


def test_an_offer_answer_has_no_address_and_no_contact_key_at_all() -> None:
    body = visit_json(_visit())

    assert "address" not in body and "contact" not in body
    assert body["fitsMinutes"] is None


def test_an_accepted_visit_answer_carries_the_address_and_contact() -> None:
    body = visit_json(
        _visit(
            state=VisitState.ACCEPTED,
            address="1 Synthetic Street",
            contact="Daughter",
            eta_at=AT,
        )
    )

    assert (body["address"], body["contact"], body["etaAt"]) == (
        "1 Synthetic Street",
        "Daughter",
        "2026-10-31T14:30:00Z",
    )
    assert body["state"] == "accepted"


def test_an_answer_with_only_one_of_the_two_carries_neither() -> None:
    body = visit_json(_visit(address="1 Synthetic Street"))

    assert "address" not in body and "contact" not in body
