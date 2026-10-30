"""What the advisor saw, and the way to reach the advisor (W9G), against real Neo4j through the API
client.

`GET /clinical/requests/{id}/seen` answers the display of the options the advisor had when they
asked, to the clinician who holds the request (or advised it) and to no one else.
`GET /clinical/requests/{id}/advisor-contact` answers the number to phone the advisor on, to the
clinician who holds the request and to no one else: the advisor's work phone if the tenant holds
one, else the tenant's advisor line, else it says there is none. Both: another clinician, the
advisor, every other role, another tenant and an unknown id read the same 404. No postcode, no
identifier of a person, and a number only in the contact answer, never in the audit. Sample values
only (`07700 900xxx`, `DT4`).
"""

import json
from datetime import datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import (
    AgeBand,
    Cadence,
    Channel,
    Measure,
    NeedCategory,
    ReferrerType,
    Role,
    ServiceCategory,
    Urgency,
)
from diucs.domain.model.case import Case
from diucs.domain.model.clinical import ClinicalAdvice, ClinicalRequestRecord
from diucs.domain.model.people import Practitioner, work_contact_key
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant import ContactKind, TenantContact
from diucs.domain.rules.clinical_queue import ClinicalRequest
from tests.integration.adapters.inbound.fhir_rest.test_routes_clinical import (
    clinical_world,
    test_container,
)
from tests.support.api import R01_TEST_NOW, token_headers
from tests.support.uow import ensure_audit_heads

__all__ = ["clinical_world", "test_container"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

CASE = "case-first"
OTHER_CASE = "case-second"
REFERENCE = "4821"
ADVISOR_1 = "adv-1"
ADVISOR_2 = "adv-2"
ADVISOR_OFF = "adv-off"
ADVISOR_NONE = "adv-none"
CLIN_1 = "clin-1"
CLIN_2 = "clin-2"
WEST = "svc-ucr-west"
HOME = "svc-hospital-at-home"
EAST = "svc-ucr-east"
GONE = "svc-gone-0001"
WORK_PHONE = "07700 900123"
OTHER_WORK_PHONE = "07700 900456"
LINE = "01305 900000"
B_WORK_PHONE = "07700 900789"
B_LINE = "01305 900999"
SHOWN_AT = R01_TEST_NOW - timedelta(minutes=5)
SEEN = "/clinical/requests/{}/seen"
CONTACT = "/clinical/requests/{}/advisor-contact"


def _row(service_id: str, status: str, number: int | None, age: int | None, **more: Any) -> Any:
    row: dict[str, Any] = {
        "id": service_id,
        "status": status,
        "number": number,
        "data_age_seconds": age,
        "criteria_version": 3,
        "shown_as": "option",
        "over_by": None,
    }
    row.update(more)
    return row


def _actor(tenant: str, role: Role, practitioner: str) -> Actor:
    return Actor(
        role=role,
        practitioner_id=practitioner,
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def _profile(service_id: str, name: str) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=name,
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.every_day_all_day(),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


def _case(case_id: str, reference: str) -> Case:
    return Case(
        id=case_id,
        reference=reference,
        referrer_type=ReferrerType.GP,
        age_band=AgeBand.A80_PLUS,
        postcode="DT4",
        needs=(NeedCategory.FRAILTY,),
        urgency=Urgency.WITHIN_2_HRS,
        scores=(),
        opened_at=R01_TEST_NOW - timedelta(hours=1),
    )


def _request(
    request_id: str,
    *,
    requester: str = ADVISOR_1,
    taken_by: str | None = CLIN_1,
    taken_minutes_ago: int = 3,
    advised: bool = False,
    snapshot_ref: str | None = None,
    case_id: str = CASE,
) -> ClinicalRequestRecord:
    taken_at = None if taken_by is None else R01_TEST_NOW - timedelta(minutes=taken_minutes_ago)
    advised_at = R01_TEST_NOW - timedelta(minutes=1) if advised else None
    advice = None
    if advised and taken_by is not None:
        advice = ClinicalAdvice(
            choice="go-ahead",
            reason=None,
            note_handle=None,
            clinician_id=taken_by,
            at=R01_TEST_NOW - timedelta(minutes=1),
        )
    return ClinicalRequestRecord(
        request=ClinicalRequest(
            id=request_id,
            case_id=case_id,
            urgency="now",
            requested_at=R01_TEST_NOW - timedelta(minutes=8),
            taken_by=taken_by,
            taken_at=taken_at,
            advised_at=advised_at,
        ),
        requester_id=requester,
        why="borderline-criteria",
        snapshot_ref=snapshot_ref,
        advice=advice,
    )


async def _audit(
    factory: UnitOfWorkFactory,
    tenant: str,
    use_case: str,
    case_id: str,
    snapshot: dict[str, Any],
    at: datetime = SHOWN_AT,
) -> str:
    async with factory() as uow:
        record = await uow.audit.append(
            AuditEntry(
                action="R",
                use_case=use_case,
                actor=_actor(tenant, Role.ADVISOR, ADVISOR_1),
                entity_ids=(case_id,),
                snapshot=snapshot,
                at=at,
            )
        )
        await uow.commit()
    return record.id


@pytest_asyncio.fixture(loop_scope="session")
async def world(
    clinical_world: None,
    uow_factory_a: UnitOfWorkFactory,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> dict[str, str]:
    """Four advisors (one with a work phone, one inactive with one, one with a work phone of the
    other advisor's tenant only, one with none), two clinicians, a case with a display of three
    services (a fourth is no longer listed), and the requests of the tests below."""
    await ensure_audit_heads(neo4j_driver, tenant_id)
    shown = {
        "reference": REFERENCE,
        "services": [
            _row(WEST, "accepting", 4, 9 * 60),
            _row(HOME, "over-capacity", 14, 14 * 60, over_by=2),
            _row(
                EAST,
                "not-accepting",
                0,
                3 * 60,
                shown_as="not-suitable",
                reason="not-accepting",
            ),
            _row(GONE, "accepting", 5, 2 * 3600 + 10 * 60),
        ],
    }
    refs: dict[str, str] = {}
    refs["display"] = await _audit(uow_factory_a, tenant_id, "FilterOptions", CASE, shown)
    # A display after the request was made must never be what the clinician reads.
    refs["later"] = await _audit(
        uow_factory_a,
        tenant_id,
        "FilterOptions",
        CASE,
        {"reference": REFERENCE, "services": [_row(WEST, "not-accepting", 0, 60)]},
        R01_TEST_NOW,
    )
    refs["other-case"] = await _audit(uow_factory_a, tenant_id, "FilterOptions", OTHER_CASE, shown)
    refs["open-case"] = await _audit(uow_factory_a, tenant_id, "OpenCase", CASE, {})
    refs["broken"] = await _audit(
        uow_factory_a,
        tenant_id,
        "FilterOptions",
        CASE,
        {"reference": REFERENCE, "services": [_row(WEST, "made-up", 4, 60)]},
    )
    async with uow_factory_a() as uow:
        for person, active in (
            (ADVISOR_1, True),
            (ADVISOR_2, True),
            (ADVISOR_OFF, False),
            (ADVISOR_NONE, True),
            (CLIN_2, True),
        ):
            await uow.people.save_practitioner(
                Practitioner(
                    id=person, active=active, display_name=f"Sample {person}", phone_hash=None
                )
            )
        await uow.contacts.put_phone(work_contact_key(ADVISOR_1), WORK_PHONE)
        await uow.contacts.put_phone(work_contact_key(ADVISOR_OFF), OTHER_WORK_PHONE)
        await uow.services.save(_profile(WEST, "UCR West"))
        await uow.services.save(_profile(HOME, "Hospital at home"))
        await uow.services.save(_profile(EAST, "UCR East"))
        await uow.cases.add(_case(CASE, REFERENCE))
        await uow.cases.add(_case(OTHER_CASE, "4822"))
        for record in (
            _request("t1", snapshot_ref=refs["display"]),
            _request("t-none"),
            _request("t-gone", snapshot_ref="no-such-audit-record"),
            _request("t-other-case", snapshot_ref=refs["other-case"]),
            _request("t-open-case", snapshot_ref=refs["open-case"]),
            _request("t-broken", snapshot_ref=refs["broken"]),
            _request("t2", taken_by=CLIN_2, snapshot_ref=refs["display"]),
            _request("w1", taken_by=None, snapshot_ref=refs["display"]),
            _request("lapsed", taken_minutes_ago=11, snapshot_ref=refs["display"]),
            _request("a1", advised=True, snapshot_ref=refs["display"]),
            _request("t-adv2", requester=ADVISOR_2),
            _request("t-off", requester=ADVISOR_OFF),
            _request("t-nophone", requester=ADVISOR_NONE),
        ):
            await uow.clinical_requests.add(record)
        await uow.commit()
    return refs


def _as(tenant_id: str, role: Role, sub: str) -> dict[str, str]:
    return token_headers(tenant_id, role, sub=sub)


async def _get(
    client: AsyncClient, tenant_id: str, path: str, request_id: str, role: Role, sub: str
) -> Any:
    return await client.get(path.format(request_id), headers=_as(tenant_id, role, sub))


async def _seen(client: AsyncClient, tenant_id: str, request_id: str, sub: str = CLIN_1) -> Any:
    return await _get(client, tenant_id, SEEN, request_id, Role.CLINICAL, sub)


async def _contact(client: AsyncClient, tenant_id: str, request_id: str, sub: str = CLIN_1) -> Any:
    return await _get(client, tenant_id, CONTACT, request_id, Role.CLINICAL, sub)


# What the advisor saw.


async def test_the_clinician_who_holds_the_request_reads_what_the_advisor_saw(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str
) -> None:
    response = await _seen(api_client, tenant_id, "t1")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["state"] == "shown"
    assert body["shownAt"] == "2026-10-23T13:07:00Z"
    assert body["options"] == 3
    assert body["noneFitted"] is False
    assert [line["service"] for line in body["lines"]] == [
        "UCR West",
        "Hospital at home",
        "UCR East",
        "A service that is no longer listed",
    ]
    west, home, east, gone = body["lines"]
    assert (west["status"], west["statusText"], west["figure"], west["age"]) == (
        "accepting",
        "Accepting",
        "4",
        "9 min old",
    )
    assert (home["statusText"], home["figure"], home["age"]) == (
        "Over capacity",
        "+2",
        "14 min old",
    )
    assert (east["shownAs"], east["figure"], east["why"]) == (
        "not-suitable",
        None,
        "Not accepting",
    )
    assert gone["stale"] is True
    assert gone["age"] == "2 hrs 10 min old"
    assert west["criteriaVersion"] == 3


async def test_what_was_seen_is_the_display_pinned_when_asked_and_not_a_later_one(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str
) -> None:
    body = (await _seen(api_client, tenant_id, "t1")).json()

    # The later display said UCR West was not accepting, with 60 seconds of age.
    assert body["lines"][0]["statusText"] == "Accepting"
    assert body["lines"][0]["age"] == "9 min old"


async def test_what_was_seen_holds_no_postcode_no_identifier_and_no_number(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str
) -> None:
    response = await _seen(api_client, tenant_id, "t1")

    text = response.text
    for hidden in (
        "DT4",
        ADVISOR_1,
        CLIN_1,
        WEST,
        HOME,
        EAST,
        GONE,
        WORK_PHONE,
        REFERENCE,
        "criteria-",
        world["display"],
    ):
        assert hidden not in text, hidden


async def test_no_display_kept_is_said_and_is_not_nothing_fitted(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str
) -> None:
    body = (await _seen(api_client, tenant_id, "t-none")).json()

    assert body == {
        "state": "none",
        "shownAt": None,
        "options": 0,
        "noneFitted": False,
        "lines": [],
    }


@pytest.mark.parametrize("request_id", ["t-gone", "t-other-case", "t-open-case", "t-broken"])
async def test_a_display_that_cannot_be_read_is_said_and_shows_no_lines(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str, request_id: str
) -> None:
    response = await _seen(api_client, tenant_id, request_id)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "state": "unreadable",
        "shownAt": None,
        "options": 0,
        "noneFitted": False,
        "lines": [],
    }


async def test_a_clinician_who_advised_the_request_still_reads_what_the_advisor_saw(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str
) -> None:
    response = await _seen(api_client, tenant_id, "a1")

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "shown"


@pytest.mark.parametrize("path", [SEEN, CONTACT])
@pytest.mark.parametrize(
    ("request_id", "role", "sub"),
    [
        ("t1", Role.CLINICAL, CLIN_2),  # another clinician
        ("t2", Role.CLINICAL, CLIN_1),  # held by another clinician
        ("w1", Role.CLINICAL, CLIN_1),  # waiting: nobody holds it
        ("lapsed", Role.CLINICAL, CLIN_1),  # the lock lapsed: it is back in the queue
        ("t1", Role.ADVISOR, ADVISOR_1),  # the advisor who asked
        ("t1", Role.ADVISOR, ADVISOR_2),
        ("t1", Role.LEAD, "prac-lead"),
        ("t1", Role.EXEC, "prac-exec"),
        ("t1", Role.REPORTER, "prac-reporter"),
        ("t1", Role.OWNER, "prac-owner"),
        ("t1", Role.AUDIT, "prac-audit"),
        ("t1", Role.SUPPORT, "prac-support"),
        ("t1", Role.WALL, "wall-1"),
        ("t1", Role.TENANT_ADMIN, "prac-admin"),
    ],
)
async def test_no_one_but_the_holding_clinician_reads_either_and_the_answer_is_the_unknown_ids(
    api_client: AsyncClient,
    world: dict[str, str],
    tenant_id: str,
    path: str,
    request_id: str,
    role: Role,
    sub: str,
) -> None:
    refused = await _get(api_client, tenant_id, path, request_id, role, sub)
    unknown = await _get(api_client, tenant_id, path, "no-such-request", role, sub)

    assert refused.status_code == 404, (path, request_id, role)
    assert refused.json() == unknown.json()
    for hidden in (WORK_PHONE, LINE, "UCR West", "Accepting"):
        assert hidden not in refused.text


async def test_an_unknown_request_is_a_404_for_the_clinician(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str
) -> None:
    for path in (SEEN, CONTACT):
        response = await _get(api_client, tenant_id, path, "no-such-request", Role.CLINICAL, CLIN_1)

        assert response.status_code == 404, path


async def test_tenant_bs_request_reads_as_the_same_404_in_tenant_a(
    api_client: AsyncClient,
    world: dict[str, str],
    tenant_id: str,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    async with uow_factory_b() as uow:
        await uow.people.save_practitioner(
            Practitioner(id=ADVISOR_1, active=True, display_name="Sample B", phone_hash=None)
        )
        await uow.contacts.put_phone(work_contact_key(ADVISOR_1), B_WORK_PHONE)
        await uow.cases.add(_case("case-b", "7391"))
        await uow.clinical_requests.add(_request("b-only", case_id="case-b"))
        await uow.commit()

    seen = await _seen(api_client, tenant_id, "b-only")
    contact = await _contact(api_client, tenant_id, "b-only")
    unknown = await _seen(api_client, tenant_id, "no-such-request")

    assert seen.status_code == 404
    assert contact.status_code == 404
    assert seen.json() == unknown.json()
    assert B_WORK_PHONE not in seen.text + contact.text
    assert "7391" not in seen.text + contact.text


async def test_tenant_bs_service_names_never_reach_tenant_as_lines(
    api_client: AsyncClient,
    world: dict[str, str],
    tenant_id: str,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    """Tenant B holds the same service ids under other names; tenant A's lines use A's."""
    async with uow_factory_b() as uow:
        await uow.services.save(_profile(WEST, "B Clinic West"))
        await uow.commit()

    body = (await _seen(api_client, tenant_id, "t1")).json()

    assert body["lines"][0]["service"] == "UCR West"
    assert "B Clinic" not in json.dumps(body)


# The way to reach the advisor.


async def test_the_holder_gets_the_advisors_work_phone_whole_and_their_name(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str
) -> None:
    response = await _contact(api_client, tenant_id, "t1")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "available": True,
        "via": "work-phone",
        "phone": WORK_PHONE,
        "name": f"Sample {ADVISOR_1}",
    }


async def test_with_no_work_phone_the_tenants_advisor_line_is_given_and_no_name(
    api_client: AsyncClient,
    world: dict[str, str],
    tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    async with uow_factory_a() as uow:
        await uow.tenant_config.put_contact(
            TenantContact(ContactKind.ADVISOR_LINE, "Advisor line", LINE)
        )
        await uow.commit()

    own = await _contact(api_client, tenant_id, "t1")
    no_phone = await _contact(api_client, tenant_id, "t-nophone")

    assert own.json()["via"] == "work-phone"
    assert own.json()["phone"] == WORK_PHONE
    assert no_phone.json() == {
        "available": True,
        "via": "advisor-line",
        "phone": LINE,
        "name": None,
    }
    assert "Sample" not in no_phone.text


async def test_an_advisor_who_has_left_is_not_phoned_on_the_number_they_had(
    api_client: AsyncClient,
    world: dict[str, str],
    tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    async with uow_factory_a() as uow:
        await uow.tenant_config.put_contact(
            TenantContact(ContactKind.ADVISOR_LINE, "Advisor line", LINE)
        )
        await uow.commit()

    response = await _contact(api_client, tenant_id, "t-off")

    assert response.json()["via"] == "advisor-line"
    assert OTHER_WORK_PHONE not in response.text
    assert "Sample" not in response.text


async def test_with_no_number_at_all_the_answer_says_there_is_none(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str
) -> None:
    response = await _contact(api_client, tenant_id, "t-nophone")

    assert response.status_code == 200, response.text
    assert response.json() == {"available": False, "via": None, "phone": None, "name": None}


async def test_the_contact_is_not_given_once_the_request_is_advised(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str
) -> None:
    response = await _contact(api_client, tenant_id, "a1")

    assert response.status_code == 404


async def test_another_advisors_number_is_not_given_for_this_request(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str
) -> None:
    response = await _contact(api_client, tenant_id, "t-adv2")

    assert response.json()["available"] is False
    assert WORK_PHONE not in response.text


async def test_opening_the_contact_is_audited_without_the_number(
    api_client: AsyncClient,
    world: dict[str, str],
    tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    await _contact(api_client, tenant_id, "t1")
    await _contact(api_client, tenant_id, "t-nophone")

    async with uow_factory_a() as uow:
        records = await uow.audit.records()
    read = [r for r in records if r.entry.use_case == "ReadAdvisorContact"]
    assert [r.entry.snapshot for r in read] == [{"via": "work-phone"}, {"via": "none"}]
    assert all(r.entry.actor.role is Role.CLINICAL for r in read)
    assert all(r.entry.entity_ids == (e,) for r, e in zip(read, ("t1", "t-nophone"), strict=True))
    everything = " ".join(repr(r.entry) for r in records)
    assert WORK_PHONE not in everything
    assert LINE not in everything


async def test_tenant_bs_numbers_never_reach_tenant_a(
    api_client: AsyncClient,
    world: dict[str, str],
    tenant_id: str,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    """Tenant B holds a work phone under the same advisor id and an advisor line; tenant A's
    advisor who has no number of their own gets none of B's."""
    async with uow_factory_b() as uow:
        await uow.contacts.put_phone(work_contact_key(ADVISOR_NONE), B_WORK_PHONE)
        await uow.tenant_config.put_contact(
            TenantContact(ContactKind.ADVISOR_LINE, "B advisor line", B_LINE)
        )
        await uow.commit()

    response = await _contact(api_client, tenant_id, "t-nophone")

    assert response.json() == {"available": False, "via": None, "phone": None, "name": None}
    assert B_WORK_PHONE not in response.text
    assert B_LINE not in response.text


async def test_a_wall_screen_has_no_clinical_seat_and_gets_nothing(
    api_client: AsyncClient, world: dict[str, str], tenant_id: str
) -> None:
    for path in (SEEN, CONTACT):
        response = await api_client.get(
            path.format("t1"), headers=_as(tenant_id, Role.WALL, "wall-1")
        )

        assert response.status_code == 404
