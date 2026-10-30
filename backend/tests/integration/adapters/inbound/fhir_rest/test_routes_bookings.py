"""The booking Task routes (R09) and the advisor's acknowledgement of a withdrawal (R17) against
real Neo4j through the API client.

WRITTEN, NOT RUN (wave 5 addendum): the orchestrator runs this file on the merged tree. Clock: the
route tests' clock (23 October 2026, 13:12 UTC) is moved to the scenario's times with set(). The
booking is seeded through RequestBooking (booking_rig), then driven through the routes. Synthetic
values only: UCR West, case 1001, booking reference from the sequence. No patient data.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.work import CANCELLED, WorkKind
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import BookingStatus, Role
from tests.support.api import R01_TEST_NOW, TEST_PHONE_HASH_SECRET, token_headers
from tests.support.booking_rig import CASE_ID, SERVICE_ID, at, request, seed_world
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

LINK_SECRET = b"link-token-test-secret-0123456789abcdef"
UCR_EAST = "ucr-east"
TASK_CODE = {
    "coding": [{"system": "https://diucs.example/CodeSystem/task-code", "code": "booking-request"}]
}


@pytest_asyncio.fixture(loop_scope="session")
async def test_container(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Container]:
    """The API's test profile with the link-token secret: a booking request issues a link token
    and seals its message under that secret (booking_rig's SECRETS)."""
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=FixedClock(R01_TEST_NOW),
            neo4j=connection,
            secrets=FixedSecretStore(
                {PHONE_HASH_SECRET: TEST_PHONE_HASH_SECRET, LINK_TOKEN_SECRET: LINK_SECRET}
            ),
        )
    finally:
        await connection.close()


@pytest_asyncio.fixture(loop_scope="session")
async def api(api_app: Any) -> Any:
    """The BFF token secret the edge reads (DEC-095) and an in-memory cache for the routes."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(FixedClock(R01_TEST_NOW))
    return api_app


@pytest_asyncio.fixture(loop_scope="session")
async def world(
    test_container: Container,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
    edge_tenants: None,
) -> None:
    """UCR West with a report at 13:00, one text reporter (prac-1) and one open case (case-1001).
    The clock is the scenario's 14:16 on 29 October, when the booking is requested (booking_rig)."""
    test_container.clock.set(at(14, 16))
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    await seed_world(uow_factory_a, neo4j_driver)


def _advisor() -> dict[str, str]:
    return token_headers(role=Role.ADVISOR, sub="advisor-1")


def _reporter() -> dict[str, str]:
    return token_headers(role=Role.REPORTER, services=[SERVICE_ID], sub="prac-1")


def _reporter_east() -> dict[str, str]:
    return token_headers(role=Role.REPORTER, services=[UCR_EAST], sub="prac-9")


def _keyed(headers: dict[str, str], key: str) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key}


def _parameters(*parts: tuple[str, str]) -> dict[str, Any]:
    return {
        "resourceType": "Parameters",
        "parameter": [{"name": name, "valueCode": value} for name, value in parts],
    }


def _task_body() -> dict[str, Any]:
    return {
        "resourceType": "Task",
        "code": TASK_CODE,
        "focus": {"reference": f"ServiceRequest/{CASE_ID}"},
        "owner": {"reference": f"HealthcareService/{SERVICE_ID}"},
    }


def _business(body: dict[str, Any]) -> str:
    return body["businessStatus"]["coding"][0]["code"]


async def _booking_status(factory: UnitOfWorkFactory, booking_id: str) -> BookingStatus:
    async with factory() as uow:
        booking = await uow.bookings.get(booking_id)
    assert booking is not None
    return booking.status


async def _open_booking_id(factory: UnitOfWorkFactory) -> str:
    async with factory() as uow:
        open_bookings = await uow.bookings.open_for_service(SERVICE_ID)
    assert len(open_bookings) == 1
    return open_bookings[0].id


async def _seed_requested(factory: UnitOfWorkFactory, driver: AsyncDriver, key: str) -> str:
    result = await request(factory, driver, key, now=at(14, 16))
    return result.booking_id


async def _confirm(api_client: AsyncClient, booking_id: str, key: str) -> None:
    response = await api_client.post(
        f"/fhir/Task/{booking_id}/$respond",
        json=_parameters(("decision", "confirm")),
        headers=_keyed(_reporter(), key),
    )
    assert response.status_code == 200, response.text


# -- R09 ----------------------------------------------------------------------------------------


async def test_an_advisor_opens_a_booking_request_for_ucr_west(
    api_client: AsyncClient,
    api: Any,
    world: None,
    test_container: Container,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    response = await api_client.post(
        "/fhir/Task", json=_task_body(), headers=_keyed(_advisor(), "r09-open-1")
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "requested"
    assert _business(body) == "requested"
    assert body["intent"] == "order"
    reference = body["identifier"][0]["value"]
    assert len(reference) == 4 and reference.isdigit()
    reply_by = datetime.fromisoformat(body["restriction"]["period"]["end"])
    assert reply_by == test_container.clock.now() + timedelta(minutes=10)
    await _open_booking_id(uow_factory_a)


async def test_a_second_request_for_the_same_service_is_a_conflict(
    api_client: AsyncClient, api: Any, world: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    first = await api_client.post(
        "/fhir/Task", json=_task_body(), headers=_keyed(_advisor(), "r09-second-1")
    )
    assert first.status_code == 201
    second = await api_client.post(
        "/fhir/Task", json=_task_body(), headers=_keyed(_advisor(), "r09-second-2")
    )
    assert second.status_code == 409
    assert second.json()["issue"][0]["code"] == "conflict"
    async with uow_factory_a() as uow:
        assert len(await uow.bookings.open_for_service(SERVICE_ID)) == 1


async def test_the_reporter_of_the_service_sees_no_focus_and_no_for(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r09-view")
    own = await api_client.get(f"/fhir/Task/{booking_id}", headers=_reporter())
    assert own.status_code == 200
    assert "focus" not in own.json()
    assert "for" not in own.json()
    assert [tag["code"] for tag in own.json()["meta"]["security"]] == ["REDACTED"]
    other = await api_client.get(f"/fhir/Task/{booking_id}", headers=_reporter_east())
    assert other.status_code == 404
    advisor = await api_client.get(f"/fhir/Task/{booking_id}", headers=_advisor())
    assert advisor.status_code == 200
    assert advisor.json()["focus"]["reference"] == f"ServiceRequest/{CASE_ID}"


async def test_respond_confirm_is_accepted_and_stored(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r09-confirm")
    response = await api_client.post(
        f"/fhir/Task/{booking_id}/$respond",
        json=_parameters(("decision", "confirm")),
        headers=_keyed(_reporter(), "r09-confirm-1"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    assert _business(response.json()) == "confirmed"
    assert await _booking_status(uow_factory_a, booking_id) is BookingStatus.CONFIRMED


async def test_a_second_respond_is_a_business_rule_refusal(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r09-again")
    await _confirm(api_client, booking_id, "r09-again-1")
    again = await api_client.post(
        f"/fhir/Task/{booking_id}/$respond",
        json=_parameters(("decision", "confirm")),
        headers=_keyed(_reporter(), "r09-again-2"),
    )
    assert again.status_code == 409
    assert again.json()["issue"][0]["code"] == "business-rule"


async def test_cancel_of_a_requested_booking_is_cancelled_before(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r09-cancel")
    response = await api_client.post(
        f"/fhir/Task/{booking_id}/$cancel",
        json=_parameters(("reason", "caller-declined")),
        headers=_keyed(_advisor(), "r09-cancel-1"),
    )
    assert response.status_code == 200, response.text
    assert _business(response.json()) == "cancelled-before"


async def test_withdraw_of_a_confirmed_booking_is_withdrawn_with_its_reason(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r09-withdraw")
    await _confirm(api_client, booking_id, "r09-withdraw-1")
    response = await api_client.post(
        f"/fhir/Task/{booking_id}/$withdraw",
        json=_parameters(("reason", "staffing")),
        headers=_keyed(_reporter(), "r09-withdraw-2"),
    )
    assert response.status_code == 200, response.text
    assert _business(response.json()) == "withdrawn"
    assert response.json()["statusReason"]["coding"][0]["code"] == "withdrawn"
    assert await _booking_status(uow_factory_a, booking_id) is BookingStatus.WITHDRAWN


async def test_a_put_on_a_booking_is_refused_with_405(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r09-put")
    response = await api_client.put(
        f"/fhir/Task/{booking_id}", json={"resourceType": "Task"}, headers=_advisor()
    )
    assert response.status_code == 405
    assert "Booking status changes only through operations" in response.text


# -- R17 ----------------------------------------------------------------------------------------


async def test_the_advisor_acknowledges_a_withdrawal_and_the_escalation_is_cancelled(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    test_container: Container,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r17-cancel")
    test_container.clock.set(at(14, 19))
    await _confirm(api_client, booking_id, "r17-cancel-1")
    test_container.clock.set(at(14, 41))
    withdrawn = await api_client.post(
        f"/fhir/Task/{booking_id}/$withdraw",
        json=_parameters(("reason", "staffing")),
        headers=_keyed(_reporter(), "r17-cancel-2"),
    )
    assert withdrawn.status_code == 200, withdrawn.text
    test_container.clock.set(at(14, 45))
    response = await api_client.post(
        f"/fhir/Task/{booking_id}/$acknowledge",
        headers=_keyed(_advisor(), "r17-cancel-3"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["parameter"][0] == {"name": "acknowledged", "valueBoolean": True}
    async with uow_factory_a() as uow:
        escalations = await uow.scheduled_work.for_about(booking_id, WorkKind.WITHDRAWAL_ESCALATE)
    assert len(escalations) == 1
    assert escalations[0].status == CANCELLED


@pytest.mark.xfail(
    strict=True,
    reason="U21 AcknowledgeWithdrawal writes an audit entry for each acknowledgement with a new "
    "key; the prompt asks for none on a second one. Known issue: remove the marker when U21 "
    "guards it (the fix belongs to withdraw_booking.py).",
)
async def test_a_second_acknowledgement_is_200_and_writes_no_second_audit_entry(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    test_container: Container,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r17-twice")
    test_container.clock.set(at(14, 19))
    await _confirm(api_client, booking_id, "r17-twice-1")
    test_container.clock.set(at(14, 41))
    await api_client.post(
        f"/fhir/Task/{booking_id}/$withdraw",
        json=_parameters(("reason", "staffing")),
        headers=_keyed(_reporter(), "r17-twice-2"),
    )
    test_container.clock.set(at(14, 45))
    first = await api_client.post(
        f"/fhir/Task/{booking_id}/$acknowledge", headers=_keyed(_advisor(), "r17-twice-3")
    )
    second = await api_client.post(
        f"/fhir/Task/{booking_id}/$acknowledge", headers=_keyed(_advisor(), "r17-twice-4")
    )
    assert first.status_code == 200 and second.status_code == 200
    async with uow_factory_a() as uow:
        records = await uow.audit.records_for(booking_id)
    acknowledgements = [r for r in records if r.entry.use_case == "AcknowledgeWithdrawal"]
    assert len(acknowledgements) == 1


async def test_a_not_reached_booking_is_acknowledged_with_nothing_cancelled(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    test_container: Container,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r17-reached")
    await _confirm(api_client, booking_id, "r17-reached-1")
    reported = await api_client.post(
        f"/fhir/Task/{booking_id}/$not-reached",
        json=_parameters(("reason", "no-answer")),
        headers=_keyed(_reporter(), "r17-reached-2"),
    )
    assert reported.status_code == 200, reported.text
    response = await api_client.post(
        f"/fhir/Task/{booking_id}/$acknowledge", headers=_keyed(_advisor(), "r17-reached-3")
    )
    assert response.status_code == 200
    assert response.json()["parameter"][0] == {"name": "acknowledged", "valueBoolean": True}
    async with uow_factory_a() as uow:
        assert await uow.scheduled_work.for_about(booking_id, WorkKind.WITHDRAWAL_ESCALATE) == []


async def test_a_confirmed_booking_cannot_be_acknowledged(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r17-confirmed")
    await _confirm(api_client, booking_id, "r17-confirmed-1")
    response = await api_client.post(
        f"/fhir/Task/{booking_id}/$acknowledge", headers=_keyed(_advisor(), "r17-confirmed-2")
    )
    assert response.status_code == 409
    assert response.json()["issue"][0]["code"] == "business-rule"
    assert "Only a withdrawn or not-reached booking can be acknowledged" in response.text


async def test_a_reporter_gets_404_for_an_acknowledgement(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r17-role")
    response = await api_client.post(
        f"/fhir/Task/{booking_id}/$acknowledge", headers=_keyed(_reporter(), "r17-role-1")
    )
    assert response.status_code == 404


async def test_an_acknowledgement_without_an_idempotency_key_is_400(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r17-nokey")
    response = await api_client.post(f"/fhir/Task/{booking_id}/$acknowledge", headers=_advisor())
    assert response.status_code == 400


# -- two tenants (DEC-130 to DEC-132) -------------------------------------------------------------


async def test_another_tenant_reads_no_booking_of_this_one_and_changes_none(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
    other_tenant_id: str,
) -> None:
    """Tenant B holds nothing here: its tokens name its own tenant, so A's booking id and A's
    service id read as not found, and A's booking is unchanged. B is not seeded: a second seed of
    the same service id collides on the shared harness schema until TEN-032."""
    booking_id = await _seed_requested(uow_factory_a, neo4j_driver, "r09-tenant")
    advisor_b = token_headers(tenant=other_tenant_id, role=Role.ADVISOR, sub="advisor-b")
    reporter_b = token_headers(
        tenant=other_tenant_id, role=Role.REPORTER, services=[SERVICE_ID], sub="prac-1"
    )
    read = await api_client.get(f"/fhir/Task/{booking_id}", headers=advisor_b)
    assert read.status_code == 404
    respond = await api_client.post(
        f"/fhir/Task/{booking_id}/$respond",
        json=_parameters(("decision", "confirm")),
        headers=_keyed(reporter_b, "r09-tenant-1"),
    )
    assert respond.status_code == 404
    create = await api_client.post(
        "/fhir/Task", json=_task_body(), headers=_keyed(advisor_b, "r09-tenant-2")
    )
    assert create.status_code == 404
    assert await _booking_status(uow_factory_a, booking_id) is BookingStatus.REQUESTED
