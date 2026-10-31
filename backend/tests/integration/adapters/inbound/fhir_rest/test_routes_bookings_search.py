"""The search of booking Tasks (WB4): the bookings of a case, so a card survives a reload (W8A-K1,
H-531), and the withdrawals and not-reached reports nobody has acknowledged, so an advisor who is
not on the card sees the alert (H-496); and what a booking read now says of its request message
(H-494) and of its phone prompt time (H-493). Against real Neo4j through the API client.

    GET /fhir/Task?focus=ServiceRequest/<case id>    the case's bookings, newest first
    GET /fhir/Task?alert=open                        withdrawn or not-reached, not acknowledged

Roles: advisor and clinical; every other role reads the one 404 of an unknown id. Two tenants: the
other tenant's token reads empty bundles for this tenant's case and alerts. Clock: the route tests'
clock is moved to the scenario's times with set(). Synthetic values only: UCR West, case 1001.
"""

from collections.abc import AsyncIterator
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
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import Role
from tests.support.api import R01_TEST_NOW, TEST_PHONE_HASH_SECRET, token_headers
from tests.support.booking_rig import CASE_ID, SERVICE_ID, at, request, seed_world
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.uow import ensure_audit_heads

EMPTY_PARAMETERS = {"resourceType": "Parameters"}

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


def _keyed(headers: dict[str, str], key: str) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key}


def _parameters(*parts: tuple[str, str]) -> dict[str, Any]:
    return {
        "resourceType": "Parameters",
        "parameter": [{"name": name, "valueCode": value} for name, value in parts],
    }


CASE_SEARCH = f"/fhir/Task?focus=ServiceRequest/{CASE_ID}"
ALERT_SEARCH = "/fhir/Task?alert=open"
STAFF = (Role.ADVISOR, Role.CLINICAL)
ALL_ROLES = tuple(role for role in Role if role is not Role.PLATFORM_OPERATOR)


def _ids(bundle: dict[str, Any]) -> list[str]:
    return [entry["resource"]["id"] for entry in bundle.get("entry", [])]


def _output(task: dict[str, Any], code: str) -> Any:
    for entry in task.get("output", []):
        if entry["type"]["coding"][0]["code"] == code:
            return entry.get("valueString") or entry.get("valueDateTime")
    return None


async def _confirm(api_client: AsyncClient, booking_id: str, key: str) -> None:
    response = await api_client.post(
        f"/fhir/Task/{booking_id}/$respond",
        json=_parameters(("decision", "confirm")),
        headers=_keyed(_reporter(), key),
    )
    assert response.status_code == 200, response.text


async def _withdraw(api_client: AsyncClient, booking_id: str, key: str) -> None:
    response = await api_client.post(
        f"/fhir/Task/{booking_id}/$withdraw",
        json=_parameters(("reason", "staffing")),
        headers=_keyed(_reporter(), key),
    )
    assert response.status_code == 200, response.text


async def _booked(factory: UnitOfWorkFactory, driver: AsyncDriver, key: str) -> str:
    return (await request(factory, driver, key, now=at(14, 16))).booking_id


# -- the role matrix ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ALL_ROLES, ids=lambda r: r.value)
@pytest.mark.parametrize("search", [CASE_SEARCH, ALERT_SEARCH], ids=["case", "alerts"])
async def test_only_an_advisor_or_a_clinician_searches_bookings(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
    role: Role,
    search: str,
) -> None:
    await _booked(uow_factory_a, neo4j_driver, f"wb4-role-{role.value}")

    response = await api_client.get(
        search, headers=token_headers(role=role, services=[SERVICE_ID], sub="prac-1")
    )

    assert response.status_code == (200 if role in STAFF else 404), (role, response.text)
    if role not in STAFF:
        assert "4821" not in response.text and CASE_ID not in response.text


async def test_a_search_with_no_token_is_401(
    api_client: AsyncClient, api: Any, world: None
) -> None:
    assert (await api_client.get(CASE_SEARCH)).status_code == 401


# -- the bookings of a case --------------------------------------------------------------------


async def test_the_bookings_of_a_case_come_back_newest_first_as_a_search_bundle(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
    test_container: Container,
) -> None:
    first = await _booked(uow_factory_a, neo4j_driver, "wb4-case-1")
    test_container.clock.set(at(14, 19))
    declined = await api_client.post(
        f"/fhir/Task/{first}/$respond",
        json=_parameters(("decision", "decline")),
        headers=_keyed(_reporter(), "wb4-case-1-d"),
    )
    assert declined.status_code == 200, declined.text
    second = (await request(uow_factory_a, neo4j_driver, "wb4-case-2", now=at(14, 30))).booking_id

    response = await api_client.get(CASE_SEARCH, headers=_advisor())

    assert response.status_code == 200, response.text
    bundle = response.json()
    assert bundle["resourceType"] == "Bundle" and bundle["type"] == "searchset"
    assert bundle["total"] == 2
    assert _ids(bundle) == [second, first]
    assert response.headers["cache-control"] == "no-store"


async def test_a_case_with_no_booking_and_an_unknown_case_are_both_an_empty_bundle(
    api_client: AsyncClient, api: Any, world: None
) -> None:
    for case in (CASE_ID, "no-such-case"):
        response = await api_client.get(
            f"/fhir/Task?focus=ServiceRequest/{case}", headers=_advisor()
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0 and _ids(response.json()) == []


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?focus=Patient/case-1001",
        "?focus=ServiceRequest/",
        "?focus=ServiceRequest/a%20b",
        "?focus=ServiceRequest/case-1001&alert=open",
        "?alert=closed",
        "?alert=open&focus=",
        "?status=requested",
    ],
)
async def test_a_search_that_names_neither_a_case_nor_the_open_alerts_is_400(
    api_client: AsyncClient, api: Any, world: None, query: str
) -> None:
    response = await api_client.get(f"/fhir/Task{query}", headers=_advisor())

    assert response.status_code == 400, (query, response.text)


async def test_the_search_names_no_patient_postcode_or_case_in_what_it_returns_for_the_service(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    await _booked(uow_factory_a, neo4j_driver, "wb4-privacy")

    text = (await api_client.get(CASE_SEARCH, headers=_advisor())).text

    assert "DT4" not in text and "Patient/" not in text


# -- the open alerts ---------------------------------------------------------------------------


async def test_a_withdrawal_is_an_open_alert_until_an_advisor_acknowledges_it(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
    test_container: Container,
) -> None:
    booking_id = await _booked(uow_factory_a, neo4j_driver, "wb4-alert-1")
    test_container.clock.set(at(14, 19))
    await _confirm(api_client, booking_id, "wb4-alert-1-c")
    assert _ids((await api_client.get(ALERT_SEARCH, headers=_advisor())).json()) == []
    test_container.clock.set(at(14, 41))
    await _withdraw(api_client, booking_id, "wb4-alert-1-w")

    open_now = (await api_client.get(ALERT_SEARCH, headers=_advisor())).json()

    assert _ids(open_now) == [booking_id]
    task = open_now["entry"][0]["resource"]
    assert task["businessStatus"]["coding"][0]["code"] == "withdrawn"
    assert _output(task, "reason") == "staffing"

    test_container.clock.set(at(14, 45))
    acknowledged = await api_client.post(
        f"/fhir/Task/{booking_id}/$acknowledge",
        json={"resourceType": "Parameters"},
        headers=_keyed(token_headers(role=Role.CLINICAL, sub="clin-1"), "wb4-alert-1-a"),
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert _ids((await api_client.get(ALERT_SEARCH, headers=_advisor())).json()) == []
    read = (await api_client.get(f"/fhir/Task/{booking_id}", headers=_advisor())).json()
    assert _output(read, "acknowledged-by") == "clin-1"
    assert _output(read, "acknowledged-at") == "2026-10-29T14:45:00Z"


async def test_a_not_reached_report_is_an_open_alert_and_acknowledging_it_closes_it(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
    test_container: Container,
) -> None:
    booking_id = await _booked(uow_factory_a, neo4j_driver, "wb4-alert-2")
    test_container.clock.set(at(14, 19))
    await _confirm(api_client, booking_id, "wb4-alert-2-c")
    test_container.clock.set(at(14, 41))
    reached = await api_client.post(
        f"/fhir/Task/{booking_id}/$not-reached",
        json=_parameters(("reason", "no-answer")),
        headers=_keyed(_reporter(), "wb4-alert-2-n"),
    )
    assert reached.status_code == 200, reached.text
    assert _ids((await api_client.get(ALERT_SEARCH, headers=_advisor())).json()) == [booking_id]

    await api_client.post(
        f"/fhir/Task/{booking_id}/$acknowledge",
        json={"resourceType": "Parameters"},
        headers=_keyed(_advisor(), "wb4-alert-2-a"),
    )

    assert _ids((await api_client.get(ALERT_SEARCH, headers=_advisor())).json()) == []


# -- what a read of one booking says now -------------------------------------------------------


async def test_a_booking_read_carries_the_delivery_state_of_its_request_and_the_phone_prompt_time(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _booked(uow_factory_a, neo4j_driver, "wb4-read")
    read = (await api_client.get(f"/fhir/Task/{booking_id}", headers=_advisor())).json()

    assert _output(read, "request-delivery") == "queued"
    assert _output(read, "phone-prompt-at") == "2026-10-29T14:21:00Z"


async def test_a_reporter_reads_neither_the_message_id_nor_the_delivery_state(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    booking_id = await _booked(uow_factory_a, neo4j_driver, "wb4-read-rep")

    read = (await api_client.get(f"/fhir/Task/{booking_id}", headers=_reporter())).json()

    for code in ("request-message", "request-delivery", "acknowledged-by", "acknowledged-at"):
        assert _output(read, code) is None


# -- two tenants (DEC-130 to DEC-132) ----------------------------------------------------------


async def test_another_tenant_searches_empty_for_this_tenants_case_and_alerts(
    api_client: AsyncClient,
    api: Any,
    world: None,
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
    other_tenant_id: str,
    test_container: Container,
) -> None:
    booking_id = await _booked(uow_factory_a, neo4j_driver, "wb4-tenant")
    test_container.clock.set(at(14, 19))
    await _confirm(api_client, booking_id, "wb4-tenant-c")
    test_container.clock.set(at(14, 41))
    await _withdraw(api_client, booking_id, "wb4-tenant-w")
    advisor_b = token_headers(tenant=other_tenant_id, role=Role.ADVISOR, sub="advisor-b")

    mine_case = (await api_client.get(CASE_SEARCH, headers=_advisor())).json()
    mine_alerts = (await api_client.get(ALERT_SEARCH, headers=_advisor())).json()
    theirs_case = await api_client.get(CASE_SEARCH, headers=advisor_b)
    theirs_alerts = await api_client.get(ALERT_SEARCH, headers=advisor_b)

    assert _ids(mine_case) == [booking_id] and _ids(mine_alerts) == [booking_id]
    assert (theirs_case.status_code, theirs_alerts.status_code) == (200, 200)
    assert _ids(theirs_case.json()) == [] and _ids(theirs_alerts.json()) == []
