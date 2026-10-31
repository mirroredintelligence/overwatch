"""The booking links (L02) through the link API on real Neo4j, on the run tenant's host.

WRITTEN, NOT RUN (wave 5 addendum): the orchestrator runs this file on the merged tree.

Shapes follow L01, not the prompt where they differ (lesson L172): an expired or closed link is
410 with `{state}` alone, a refused booking answer is 409 `{state}`. The prompt's "POST then
409" for an expired booking is therefore 410 here, because the link has expired by then.

Clock: 29 October 2026, 14:16 UTC (the booking is requested then; reply by 14:26). Synthetic values
only: UCR West, reporter prac-1, booking reference from the sequence. No patient data.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.link_pages.booking_links import REQUEST_PURPOSE
from diucs.application.ports.outbound.tokens import LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.request_booking import RequestBookingCommand
from diucs.bootstrap.container import Container
from diucs.domain.codes import BookingStatus
from diucs.domain.model.tenant import ContactKind, TenantContact
from tests.support.booking_rig import (
    ADVISOR,
    CASE_ID,
    SERVICE_ID,
    at,
    request_use_case,
    seed_world,
)
from tests.support.ladder_rig import PHONE_HASH_1
from tests.support.link_rig import HOST_A  # noqa: F401  (the host the link client is on)
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

COORDINATION_PHONE = "01234 567890"


@pytest_asyncio.fixture(loop_scope="session")
async def booked(
    link_container: Container,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
    hosts: None,
) -> AsyncIterator[UnitOfWorkFactory]:
    """UCR West with a reporter and an open case; one booking requested at 14:16, and its request
    link issued with the container's secrets. Yields the run tenant's factory."""
    link_container.clock.set(at(14, 16))
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    factory = tenant_uow_factory(neo4j_driver, tenant_id, link_container.clock)
    await seed_world(factory, neo4j_driver)
    async with factory() as uow:
        await uow.tenant_config.put_contact(
            TenantContact(ContactKind.COORDINATION_PHONE, "Coordination", COORDINATION_PHONE)
        )
        await uow.commit()
    yield factory


async def _request(
    factory: UnitOfWorkFactory, driver: AsyncDriver, container: Container, key: str
) -> str:
    """A booking request through RequestBooking, then its request link issued with the container's
    secrets, as RequestBooking issues it. Returns the booking id."""
    command = RequestBookingCommand(
        idempotency_key=key, actor=ADVISOR, case_id=CASE_ID, service_id=SERVICE_ID
    )
    result = await request_use_case(factory, driver, container.clock.now(), prefix=key).execute(
        command
    )
    return result.booking_id


async def _link_for(factory: UnitOfWorkFactory, container: Container, booking_id: str) -> str:
    async with factory() as uow:
        token = await LinkTokenService(uow.link_tokens, container.secrets, container.clock).issue(
            REQUEST_PURPOSE, booking_id, PHONE_HASH_1, at(14, 26)
        )
        await uow.commit()
    return token


async def _status(factory: UnitOfWorkFactory, booking_id: str) -> BookingStatus:
    async with factory() as uow:
        booking = await uow.bookings.get(booking_id)
    assert booking is not None
    return booking.status


def _csrf(page: dict[str, Any]) -> dict[str, str]:
    return {"X-CSRF-Token": page["csrfToken"]}


async def test_a_request_link_shows_the_booking_and_changes_nothing(
    link_client: AsyncClient,
    booked: UnitOfWorkFactory,
    link_container: Container,
    neo4j_driver: AsyncDriver,
) -> None:
    booking_id = await _request(booked, neo4j_driver, link_container, "l02-view")
    token = await _link_for(booked, link_container, booking_id)
    response = await link_client.get(f"/links/{token}")
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["state"] == "ok" and page["purpose"] == REQUEST_PURPOSE
    assert page["serviceName"] == "UCR West"
    assert page["ageBand"] == "80+"
    assert page["need"] == "fall, no injury and frailty"
    assert page["urgency"] == "within 2 hrs"
    assert "14:26" in page["replyBy"]
    assert page["bookingStatus"] == "requested"
    assert await _status(booked, booking_id) is BookingStatus.REQUESTED


async def test_a_confirm_records_the_booking_and_gives_a_change_link_once(
    link_client: AsyncClient,
    booked: UnitOfWorkFactory,
    link_container: Container,
    neo4j_driver: AsyncDriver,
) -> None:
    booking_id = await _request(booked, neo4j_driver, link_container, "l02-confirm")
    token = await _link_for(booked, link_container, booking_id)
    page = (await link_client.get(f"/links/{token}")).json()
    response = await link_client.post(
        f"/links/{token}", json={"action": "confirm"}, headers=_csrf(page)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bookingStatus"] == "confirmed"
    assert body["changeToken"]
    assert body["confirmedAt"] == "2026-10-29T14:16:00Z"
    assert await _status(booked, booking_id) is BookingStatus.CONFIRMED
    again = await link_client.post(
        f"/links/{token}", json={"action": "confirm"}, headers=_csrf(page)
    )
    assert again.status_code == 410
    assert again.json() == {
        "state": "used",
        "kind": "booking",
        "closedAt": "2026-10-29T14:16:00Z",
        "confirmedAt": "2026-10-29T14:16:00Z",
        "coordinationPhone": COORDINATION_PHONE,
    }


async def test_a_decline_records_its_reason(
    link_client: AsyncClient,
    booked: UnitOfWorkFactory,
    link_container: Container,
    neo4j_driver: AsyncDriver,
) -> None:
    booking_id = await _request(booked, neo4j_driver, link_container, "l02-decline")
    token = await _link_for(booked, link_container, booking_id)
    page = (await link_client.get(f"/links/{token}")).json()
    response = await link_client.post(
        f"/links/{token}",
        json={"action": "decline", "reason": "outside-criteria"},
        headers=_csrf(page),
    )
    assert response.status_code == 200, response.text
    assert response.json()["bookingStatus"] == "declined"
    async with booked() as uow:
        stored = await uow.bookings.get(booking_id)
    assert stored is not None and stored.status is BookingStatus.DECLINED
    assert stored.reason == "outside-criteria"


async def test_a_closed_booking_shows_expired_and_refuses_an_answer(
    link_client: AsyncClient,
    booked: UnitOfWorkFactory,
    link_container: Container,
    neo4j_driver: AsyncDriver,
) -> None:
    booking_id = await _request(booked, neo4j_driver, link_container, "l02-expired")
    token = await _link_for(booked, link_container, booking_id)
    link_container.clock.set(at(14, 30))
    response = await link_client.get(f"/links/{token}")
    assert response.status_code == 410
    assert response.json() == {
        "state": "expired",
        "kind": "booking",
        "closedAt": "2026-10-29T14:26:00Z",
        "coordinationPhone": COORDINATION_PHONE,
    }
    answer = await link_client.post(
        f"/links/{token}", json={"action": "confirm"}, headers={"X-CSRF-Token": "x"}
    )
    assert answer.status_code != 200
    assert await _status(booked, booking_id) is BookingStatus.REQUESTED


async def test_a_change_link_withdraws_a_confirmed_booking(
    link_client: AsyncClient,
    booked: UnitOfWorkFactory,
    link_container: Container,
    neo4j_driver: AsyncDriver,
) -> None:
    booking_id = await _request(booked, neo4j_driver, link_container, "l02-withdraw")
    token = await _link_for(booked, link_container, booking_id)
    page = (await link_client.get(f"/links/{token}")).json()
    change = (
        await link_client.post(f"/links/{token}", json={"action": "confirm"}, headers=_csrf(page))
    ).json()["changeToken"]
    change_page = (await link_client.get(f"/links/{change}")).json()
    response = await link_client.post(
        f"/links/{change}",
        json={"action": "withdraw", "reason": "staffing"},
        headers=_csrf(change_page),
    )
    assert response.status_code == 200, response.text
    assert response.json()["bookingStatus"] == "withdrawn"
    assert await _status(booked, booking_id) is BookingStatus.WITHDRAWN
    twice = await link_client.post(
        f"/links/{change}",
        json={"action": "withdraw", "reason": "staffing"},
        headers=_csrf(change_page),
    )
    assert twice.status_code == 410


async def test_the_request_page_body_holds_no_service_request_patient_or_postcode(
    link_client: AsyncClient,
    booked: UnitOfWorkFactory,
    link_container: Container,
    neo4j_driver: AsyncDriver,
) -> None:
    booking_id = await _request(booked, neo4j_driver, link_container, "l02-privacy")
    token = await _link_for(booked, link_container, booking_id)
    text = (await link_client.get(f"/links/{token}")).text
    assert "ServiceRequest" not in text
    assert "Patient" not in text
    assert "DT4" not in text
    assert CASE_ID not in text


async def _confirmed_change_link(
    link_client: AsyncClient,
    booked: UnitOfWorkFactory,
    container: Container,
    driver: AsyncDriver,
    key: str,
) -> tuple[str, str]:
    """A confirmed booking and its change token, through the request link."""
    booking_id = await _request(booked, driver, container, key)
    token = await _link_for(booked, container, booking_id)
    page = (await link_client.get(f"/links/{token}")).json()
    answered = await link_client.post(
        f"/links/{token}", json={"action": "confirm"}, headers=_csrf(page)
    )
    return booking_id, answered.json()["changeToken"]


async def test_the_change_page_says_when_the_booking_was_confirmed(
    link_client: AsyncClient,
    booked: UnitOfWorkFactory,
    link_container: Container,
    neo4j_driver: AsyncDriver,
) -> None:
    _, change = await _confirmed_change_link(
        link_client, booked, link_container, neo4j_driver, "wb4-confirmed-at"
    )
    page = (await link_client.get(f"/links/{change}")).json()
    assert page["confirmedAt"] == "2026-10-29T14:16:00Z"
    assert page["coordinationPhone"] == COORDINATION_PHONE
    assert page["need"] == "fall, no injury and frailty"


async def test_a_change_link_of_a_cancelled_booking_says_when_it_was_confirmed_and_cancelled(
    link_client: AsyncClient,
    booked: UnitOfWorkFactory,
    link_container: Container,
    neo4j_driver: AsyncDriver,
) -> None:
    booking_id, change = await _confirmed_change_link(
        link_client, booked, link_container, neo4j_driver, "wb4-cancelled"
    )
    link_container.clock.set(at(14, 40))
    async with booked() as uow:
        booking = await uow.bookings.get(booking_id)
        assert booking is not None
        await uow.bookings.save(booking.with_status(BookingStatus.CANCELLED_AFTER, at(14, 40)))
        await uow.commit()
    response = await link_client.get(f"/links/{change}")
    assert response.status_code == 410
    assert response.json() == {
        "state": "cancelled",
        "kind": "booking",
        "closedAt": "2026-10-29T14:40:00Z",
        "confirmedAt": "2026-10-29T14:16:00Z",
        "cancelledAt": "2026-10-29T14:40:00Z",
        "coordinationPhone": COORDINATION_PHONE,
    }


async def test_a_withdrawal_answers_with_the_state_and_the_time_it_was_recorded(
    link_client: AsyncClient,
    booked: UnitOfWorkFactory,
    link_container: Container,
    neo4j_driver: AsyncDriver,
) -> None:
    _, change = await _confirmed_change_link(
        link_client, booked, link_container, neo4j_driver, "wb4-withdraw-time"
    )
    link_container.clock.set(at(14, 22))
    page = (await link_client.get(f"/links/{change}")).json()
    answered = await link_client.post(
        f"/links/{change}", json={"action": "withdraw", "reason": "staffing"}, headers=_csrf(page)
    )
    assert answered.status_code == 200
    assert answered.json() == {"bookingStatus": "withdrawn", "respondedAt": "2026-10-29T14:22:00Z"}


async def test_an_unknown_link_and_another_tenants_link_say_nothing_but_the_state_word(
    link_client: AsyncClient,
    other_client: AsyncClient,
    booked: UnitOfWorkFactory,
    link_container: Container,
    neo4j_driver: AsyncDriver,
) -> None:
    """No number, no time and no kind: nothing tells which links exist, or whose they are."""
    booking_id = await _request(booked, neo4j_driver, link_container, "wb4-other-tenant")
    token = await _link_for(booked, link_container, booking_id)
    unknown = await link_client.get("/links/NoSuchLinkTokenAbcdefghijklmnopq")
    foreign = await other_client.get(f"/links/{token}")
    assert (unknown.status_code, unknown.json()) == (410, {"state": "expired"})
    assert (foreign.status_code, foreign.json()) == (410, {"state": "expired"})
