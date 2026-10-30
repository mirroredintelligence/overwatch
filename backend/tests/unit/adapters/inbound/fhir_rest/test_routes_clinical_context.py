"""The role boundary of the two clinician reads of a held request (W9G): what the advisor saw and
the way to reach the advisor. Refused before any read; the stored answers, and the refusal of a
clinician who does not hold the request, are in tests/integration/adapters/inbound/fhir_rest/.
"""

from datetime import UTC, datetime

from diucs.adapters.inbound.fhir_rest.clinical_mapping import contact_json, seen_json
from diucs.application.use_cases.clinical_context import (
    SEEN_NONE,
    SEEN_SHOWN,
    AdvisorContact,
    SeenLine,
    WhatAdvisorSaw,
)
from diucs.domain.codes import Role
from tests.support.route_unit import assert_role_matrix, bearer, route_client

CLINICAL = frozenset({Role.CLINICAL})
SEEN = "/clinical/requests/req-1/seen"
CONTACT = "/clinical/requests/req-1/advisor-contact"


async def test_what_the_advisor_saw_is_for_a_clinical_advisor_only() -> None:
    async with route_client() as client:
        await assert_role_matrix(client, "GET", SEEN, CLINICAL)


async def test_the_way_to_reach_the_advisor_is_for_a_clinical_advisor_only() -> None:
    async with route_client() as client:
        await assert_role_matrix(client, "GET", CONTACT, CLINICAL)


async def test_neither_read_can_be_written_to() -> None:
    async with route_client() as client:
        for path in (SEEN, CONTACT):
            for method in ("POST", "PUT", "DELETE"):
                response = await client.request(
                    method, path, json={}, headers=bearer(Role.CLINICAL)
                )
                assert response.status_code == 405, (method, path)


def test_what_was_seen_is_sent_as_lines_with_the_time_and_no_identifier() -> None:
    saw = WhatAdvisorSaw(
        state=SEEN_SHOWN,
        shown_at=datetime(2026, 10, 23, 13, 13, 20, tzinfo=UTC),
        lines=(
            SeenLine(
                "UCR West", "option", "accepting", "Accepting", "4", "9 min old", False, None, 3
            ),
            SeenLine(
                "UCR East",
                "not-suitable",
                "not-accepting",
                "Not accepting",
                None,
                "3 min old",
                False,
                "Not accepting",
                3,
            ),
        ),
    )

    assert seen_json(saw) == {
        "state": "shown",
        "shownAt": "2026-10-23T13:13:20Z",
        "options": 1,
        "noneFitted": False,
        "lines": [
            {
                "service": "UCR West",
                "shownAs": "option",
                "status": "accepting",
                "statusText": "Accepting",
                "figure": "4",
                "age": "9 min old",
                "stale": False,
                "why": None,
                "criteriaVersion": 3,
            },
            {
                "service": "UCR East",
                "shownAs": "not-suitable",
                "status": "not-accepting",
                "statusText": "Not accepting",
                "figure": None,
                "age": "3 min old",
                "stale": False,
                "why": "Not accepting",
                "criteriaVersion": 3,
            },
        ],
    }


def test_a_display_where_nothing_fitted_says_so_and_still_lists_what_was_considered() -> None:
    saw = WhatAdvisorSaw(
        state=SEEN_SHOWN,
        shown_at=datetime(2026, 10, 23, 13, 13, tzinfo=UTC),
        lines=(
            SeenLine(
                "UCR East",
                "not-suitable",
                "not-accepting",
                "Not accepting",
                None,
                "3 min old",
                False,
                "Not accepting",
                3,
            ),
        ),
    )

    body = seen_json(saw)

    assert body["options"] == 0
    assert body["noneFitted"] is True
    assert len(body["lines"]) == 1


def test_no_display_recorded_is_not_the_same_as_nothing_fitted() -> None:
    body = seen_json(WhatAdvisorSaw(state=SEEN_NONE, shown_at=None, lines=()))

    assert body == {
        "state": "none",
        "shownAt": None,
        "options": 0,
        "noneFitted": False,
        "lines": [],
    }


def test_the_contact_is_the_number_whole_with_the_way_it_was_found() -> None:
    assert contact_json(AdvisorContact(via="work-phone", phone="07700 900123", name="Sample")) == {
        "available": True,
        "via": "work-phone",
        "phone": "07700 900123",
        "name": "Sample",
    }
    assert contact_json(AdvisorContact(via="advisor-line", phone="01305 000000", name=None)) == {
        "available": True,
        "via": "advisor-line",
        "phone": "01305 000000",
        "name": None,
    }


def test_no_contact_says_so_and_sends_no_number() -> None:
    assert contact_json(AdvisorContact(via=None, phone=None, name=None)) == {
        "available": False,
        "via": None,
        "phone": None,
        "name": None,
    }
