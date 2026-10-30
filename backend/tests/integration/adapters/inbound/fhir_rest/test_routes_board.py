"""$board and $confirm-capacity over HTTP (R05), on the harness Neo4j through api_client.

UCR West (accepting, 4 at 14:03) and Ward A are seeded through the Neo4j repositories, with one
requested booking for UCR West. What a test asserts is what was really stored, read back through a
fresh session (DEC-004). Clock: Friday 23 October 2026, 14:12 London (13:12Z). Synthetic values
only: no patient data.

Tenancy (transitional rule): no tenant exists in the model yet, so there is no two-tenant test.
The scope tests here are the within-tenant ones: a reporter confirms only their own service, and
another service's id answers with the same 404 as an unknown id.
"""

import json
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.parameters import Parameters
from httpx import AsyncClient, Response
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.bootstrap.container import Container
from diucs.domain.codes import (
    BookingStatus,
    Cadence,
    Channel,
    Measure,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
)
from diucs.domain.model.booking import Booking
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.integration.application.test_query_board import WEST, WEST_REPORT
from tests.support.neo4j import count_nodes, read_tx, run_nodes

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD = "/fhir/HealthcareService/$board"
CONFIRM_WEST = "/fhir/HealthcareService/svc-ucr-west/$confirm-capacity"
CONFIRM_WARD = "/fhir/HealthcareService/svc-ward-a/$confirm-capacity"
JSON_TYPE = {"Content-Type": "application/fhir+json"}
EMPTY_PARAMETERS = json.dumps({"resourceType": "Parameters"})
BOARD_ROLES = (Role.WALL, Role.ADVISOR, Role.CLINICAL, Role.LEAD, Role.EXEC, Role.OWNER)
NOT_BOARD_ROLES = (Role.REPORTER, Role.ANONYMOUS_LINK, Role.SUPPORT, Role.AUDIT)

WARD_A = ServiceProfile(
    id="svc-ward-a",
    name="Ward A",
    category=ServiceCategory.INPATIENT_BEDS,
    measure=Measure.FREE_BEDS,
    unit_label="beds",
    established_capacity=20,
    can_exceed_established=False,
    usual_range=(0, 20),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day_all_day(),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
WARD_REPORT = CapacityReport(
    id="obs-ward-a-1305",
    service_id=WARD_A.id,
    value=2,
    measure=WARD_A.measure,
    effective_at=datetime(2026, 10, 23, 13, 5, tzinfo=UTC),
    source=ReportSource.TEXT,
    report_type=ReportType.NUMBER,
)
# A service nobody has reported for, so there is no figure to confirm.
QUIET = ServiceProfile(
    id="svc-quiet",
    name="Quiet service",
    category=ServiceCategory.REABLEMENT,
    measure=Measure.FREE_SLOTS,
    unit_label="slots",
    established_capacity=6,
    can_exceed_established=False,
    usual_range=(0, 6),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.weekdays(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
WEST_BOOKING = Booking(
    id="bk-4821",
    reference="4821",
    service_id=WEST.id,
    case_id="case-4821",
    requester_id="prac-advisor-1",
    status=BookingStatus.REQUESTED,
    requested_at=datetime(2026, 10, 23, 13, 10, tzinfo=UTC),
    reply_by=datetime(2026, 10, 23, 13, 40, tzinfo=UTC),
)


def _bearer(role: Role, services: tuple[str, ...] = (), sub: str = "prac-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, services, sub)}"}


def _west_reporter() -> dict[str, str]:
    return _bearer(Role.REPORTER, ("svc-ucr-west",), "prac-reporter-west")


@pytest_asyncio.fixture(loop_scope="session")
async def board_app(
    api_app: FastAPI, test_container: Container, neo4j_driver: AsyncDriver
) -> FastAPI:
    # The audit chain head exists after startup. test_container ran clean_graph, so this is after
    # the wipe (lesson L133): a confirmation writes an audit entry.
    await ensure_audit_head(neo4j_driver)
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)
    return api_app


@pytest.fixture
def clock(test_container: Container) -> FixedClock:
    assert isinstance(test_container.clock, FixedClock)
    return test_container.clock


@pytest.fixture
def factory(test_container: Container) -> UnitOfWorkFactory:
    return test_container.uow_factory


async def _seed(
    factory: UnitOfWorkFactory,
    profiles: tuple[ServiceProfile, ...],
    reports: tuple[CapacityReport, ...],
    bookings: tuple[Booking, ...] = (),
) -> None:
    async with factory() as uow:
        for profile in profiles:
            await uow.services.save(profile)
        for report in reports:
            await uow.capacity.add(report)
        for booking in bookings:
            await uow.bookings.add(booking)
        await uow.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(board_app: FastAPI, factory: UnitOfWorkFactory) -> None:
    await _seed(factory, (WEST, WARD_A), (WEST_REPORT, WARD_REPORT), (WEST_BOOKING,))


def _entries(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in body["parameter"]:
        if item["name"] == "entry":
            parts = {part["name"]: part for part in item["part"]}
            result[parts["serviceId"]["valueString"]] = parts
    return result


def _diagnostics(response: Response) -> str:
    return str(response.json()["issue"][0]["diagnostics"])


async def _observations(driver: AsyncDriver) -> int:
    return await count_nodes(driver, "Observation")


async def _confirm(
    client: AsyncClient,
    path: str,
    headers: dict[str, str],
    key: str | None = "key-1",
) -> Response:
    sent = {**headers, **JSON_TYPE}
    if key is not None:
        sent["Idempotency-Key"] = key
    return await client.post(path, headers=sent, content=EMPTY_PARAMETERS)


async def _derived_from(driver: AsyncDriver, report_id: str) -> list[str]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (o:Observation)-[:DERIVED_FROM]->(:Observation {id: $id}) RETURN o.id AS id",
            id=report_id,
        )
        return await result.data()

    return [str(row["id"]) for row in await read_tx(driver, work)]


# $board


@pytest.mark.usefixtures("seeded")
async def test_a_wall_token_reads_the_board_from_the_graph(api_client: AsyncClient) -> None:
    response = await api_client.get(BOARD, headers=_bearer(Role.WALL, (), "device-wall-1"))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/fhir+json")
    Parameters.model_validate(response.json())
    entries = _entries(response.json())
    assert set(entries) == {"svc-ucr-west", "svc-ward-a"}
    west = entries["svc-ucr-west"]
    assert west["name"]["valueString"] == "UCR West"
    assert west["status"]["valueCode"] == "accepting"
    assert west["effectiveAvailable"]["valueInteger"] == 4
    assert west["pending"]["valueInteger"] == 1
    assert west["reportedAt"]["valueDateTime"] == "2026-10-23T13:03:00Z"
    ward = entries["svc-ward-a"]
    assert ward["effectiveAvailable"]["valueInteger"] == 2
    assert ward["pending"]["valueInteger"] == 0


@pytest.mark.usefixtures("seeded")
async def test_the_board_carries_the_top_level_parameters_and_the_clock_time(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get(BOARD, headers=_bearer(Role.WALL, (), "device-wall-1"))

    top = {item["name"]: item for item in response.json()["parameter"] if item["name"] != "entry"}
    assert set(top) == {"pressure", "allLimitedOrWorse", "generatedAt"}
    assert top["pressure"]["valueCode"] == "normal"
    assert top["allLimitedOrWorse"]["valueBoolean"] is False
    assert top["generatedAt"]["valueDateTime"] == "2026-10-23T13:12:00Z"


@pytest.mark.usefixtures("seeded")
async def test_the_board_is_never_cached(api_client: AsyncClient) -> None:
    response = await api_client.get(BOARD, headers=_bearer(Role.WALL, (), "device-wall-1"))

    assert response.headers["cache-control"] == "no-store"


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("role", BOARD_ROLES)
async def test_every_board_role_reads_the_board(api_client: AsyncClient, role: Role) -> None:
    response = await api_client.get(BOARD, headers=_bearer(role))

    assert response.status_code == 200


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("role", NOT_BOARD_ROLES)
async def test_any_other_role_gets_the_not_found_answer(
    api_client: AsyncClient, role: Role
) -> None:
    allowed = await api_client.get(BOARD, headers=_bearer(Role.WALL, (), "device-wall-1"))
    refused = await api_client.get(BOARD, headers=_bearer(role, ("svc-ucr-west",)))
    missing = await api_client.get("/fhir/nothing-here", headers=_bearer(Role.WALL))

    assert allowed.status_code == 200  # the route exists: the refusal below is the role check
    assert refused.status_code == 404
    assert refused.json()["resourceType"] == "OperationOutcome"
    assert refused.json() == missing.json()


@pytest.mark.usefixtures("seeded")
async def test_a_reporter_token_is_refused_with_not_found(api_client: AsyncClient) -> None:
    allowed = await api_client.get(BOARD, headers=_bearer(Role.ADVISOR))
    response = await api_client.get(BOARD, headers=_west_reporter())

    assert allowed.status_code == 200
    assert response.status_code == 404
    assert response.json()["resourceType"] == "OperationOutcome"
    assert response.json()["issue"][0]["code"] == "not-found"


@pytest.mark.usefixtures("seeded")
async def test_no_token_is_login(api_client: AsyncClient) -> None:
    response = await api_client.get(BOARD)

    assert response.status_code == 401
    assert response.json()["issue"][0]["code"] == "login"


@pytest.mark.usefixtures("seeded")
async def test_the_board_body_holds_no_patient_word(api_client: AsyncClient) -> None:
    response = await api_client.get(BOARD, headers=_bearer(Role.WALL, (), "device-wall-1"))

    assert response.status_code == 200
    # "inpatient-beds" is a service category code, so it is taken out before the check; any other
    # "patient" in any case (a part name, a value) fails it.
    text = response.text.lower().replace("inpatient-beds", "")
    assert "postcode" not in text
    assert "servicerequest" not in text
    assert "patient" not in text


@pytest.mark.usefixtures("seeded")
async def test_the_board_follows_the_graph_and_writes_nothing(
    api_client: AsyncClient,
    factory: UnitOfWorkFactory,
    clock: FixedClock,
    neo4j_driver: AsyncDriver,
) -> None:
    headers = _bearer(Role.WALL, (), "device-wall-1")
    before = await api_client.get(BOARD, headers=headers)
    nodes_before = await _node_count(neo4j_driver)
    async with factory() as uow:
        await uow.capacity.add(
            CapacityReport(
                id="obs-west-1310",
                service_id=WEST.id,
                value=1,
                measure=WEST.measure,
                effective_at=datetime(2026, 10, 23, 13, 10, tzinfo=UTC),
                source=ReportSource.TEXT,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()
    nodes_with_report = await _node_count(neo4j_driver)

    after = await api_client.get(BOARD, headers=headers)

    assert _entries(before.json())["svc-ucr-west"]["effectiveAvailable"]["valueInteger"] == 4
    assert _entries(after.json())["svc-ucr-west"]["effectiveAvailable"]["valueInteger"] == 1
    assert nodes_with_report > nodes_before
    assert await _node_count(neo4j_driver) == nodes_with_report


async def _node_count(driver: AsyncDriver) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        result = await run_nodes(tx, "count(n) AS nodes")
        record = await result.single()
        assert record is not None
        return int(record["nodes"])

    return await read_tx(driver, work)


# $confirm-capacity


@pytest.mark.usefixtures("seeded")
async def test_the_reporter_confirms_and_a_derived_confirmed_observation_is_stored(
    api_client: AsyncClient, neo4j_driver: AsyncDriver, factory: UnitOfWorkFactory
) -> None:
    response = await _confirm(api_client, CONFIRM_WEST, _west_reporter())

    assert response.status_code == 200
    body = response.json()
    Observation.model_validate(body)
    assert body["derivedFrom"] == [{"reference": "Observation/obs-west-1403"}]
    assert body["focus"] == [{"reference": "HealthcareService/svc-ucr-west"}]
    assert body["valueQuantity"]["value"] == 4
    assert body["effectiveDateTime"] == "2026-10-23T13:12:00Z"
    assert [e["valueString"] for e in body["extension"]] == ["confirmed"]
    assert await _derived_from(neo4j_driver, "obs-west-1403") == [body["id"]]
    async with factory() as uow:
        stored = await uow.capacity.latest("svc-ucr-west")
    assert stored is not None
    assert stored.id == body["id"]
    assert stored.report_type is ReportType.CONFIRMED
    assert stored.derived_from == "obs-west-1403"
    assert stored.source is ReportSource.APP
    assert stored.value == 4


@pytest.mark.usefixtures("seeded")
async def test_a_lead_confirms_any_service_as_advisor_phoned(
    api_client: AsyncClient, factory: UnitOfWorkFactory
) -> None:
    response = await _confirm(api_client, CONFIRM_WARD, _bearer(Role.LEAD, (), "lead-1"))

    assert response.status_code == 200
    async with factory() as uow:
        stored = await uow.capacity.latest("svc-ward-a")
    assert stored is not None
    assert stored.report_type is ReportType.CONFIRMED
    assert stored.source is ReportSource.ADVISOR_PHONED
    assert stored.derived_from == "obs-ward-a-1305"


@pytest.mark.usefixtures("seeded")
async def test_a_third_confirm_in_a_row_is_refused_and_writes_nothing(
    api_client: AsyncClient, neo4j_driver: AsyncDriver, clock: FixedClock
) -> None:
    headers = _west_reporter()
    first = await _confirm(api_client, CONFIRM_WEST, headers, "key-1")
    clock.advance(timedelta(minutes=1))
    second = await _confirm(api_client, CONFIRM_WEST, headers, "key-2")
    clock.advance(timedelta(minutes=1))
    stored_before = await _observations(neo4j_driver)

    third = await _confirm(api_client, CONFIRM_WEST, headers, "key-3")

    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 409
    assert third.json()["resourceType"] == "OperationOutcome"
    issue = third.json()["issue"][0]
    assert issue["code"] == "business-rule"
    assert "UCR West" in issue["diagnostics"]
    assert issue["diagnostics"] == "Send the number for UCR West."
    assert stored_before == 4  # two seeded numbers and two confirmations
    assert await _observations(neo4j_driver) == stored_before


@pytest.mark.usefixtures("seeded")
async def test_a_number_after_two_confirms_lets_the_reporter_confirm_again(
    api_client: AsyncClient, factory: UnitOfWorkFactory, clock: FixedClock
) -> None:
    headers = _west_reporter()
    for index in range(2):
        clock.advance(timedelta(minutes=1))
        assert (await _confirm(api_client, CONFIRM_WEST, headers, f"c-{index}")).status_code == 200
    clock.advance(timedelta(minutes=1))
    async with factory() as uow:
        await uow.capacity.add(
            CapacityReport(
                id="obs-west-new",
                service_id=WEST.id,
                value=3,
                measure=WEST.measure,
                effective_at=clock.now(),
                source=ReportSource.APP,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()
    clock.advance(timedelta(minutes=1))

    response = await _confirm(api_client, CONFIRM_WEST, headers, "c-after-number")

    assert response.status_code == 200
    assert response.json()["valueQuantity"]["value"] == 3


@pytest.mark.usefixtures("seeded")
async def test_a_missing_idempotency_key_is_400_and_writes_nothing(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await _confirm(api_client, CONFIRM_WEST, _west_reporter(), key=None)

    assert response.status_code == 400
    assert response.json()["issue"][0]["code"] == "required"
    assert await _observations(neo4j_driver) == 2


@pytest.mark.usefixtures("seeded")
async def test_an_invalid_idempotency_key_is_400_and_writes_nothing(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    response = await _confirm(api_client, CONFIRM_WEST, _west_reporter(), key="not valid")

    assert response.status_code == 400
    assert response.json()["issue"][0]["code"] == "invalid"
    assert await _observations(neo4j_driver) == 2


@pytest.mark.usefixtures("seeded")
async def test_a_reporter_cannot_confirm_another_service_and_learns_nothing(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    own = await _confirm(api_client, CONFIRM_WEST, _west_reporter(), "key-0")
    other = await _confirm(api_client, CONFIRM_WARD, _west_reporter(), "key-1")
    unknown = await _confirm(
        api_client,
        "/fhir/HealthcareService/svc-nobody/$confirm-capacity",
        _west_reporter(),
        "key-2",
    )

    assert own.status_code == 200  # the route exists: the refusals below are the scope check
    assert other.status_code == 404
    assert other.json()["resourceType"] == "OperationOutcome"
    assert other.json() == unknown.json()
    assert await _observations(neo4j_driver) == 3  # two seeded numbers and the one confirmation


@pytest.mark.usefixtures("seeded")
async def test_a_lead_confirming_an_unknown_service_gets_not_found(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    lead = _bearer(Role.LEAD, (), "lead-1")
    known = await _confirm(api_client, CONFIRM_WEST, lead, "key-0")
    response = await _confirm(
        api_client, "/fhir/HealthcareService/svc-nobody/$confirm-capacity", lead, "key-1"
    )

    assert known.status_code == 200
    assert response.status_code == 404
    assert await _observations(neo4j_driver) == 3


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("role", [Role.WALL, Role.ADVISOR, Role.EXEC, Role.CLINICAL, Role.OWNER])
async def test_other_roles_cannot_confirm(
    api_client: AsyncClient, neo4j_driver: AsyncDriver, role: Role
) -> None:
    own = await _confirm(api_client, CONFIRM_WEST, _west_reporter(), "key-0")
    response = await _confirm(api_client, CONFIRM_WEST, _bearer(role, ("svc-ucr-west",)), "key-1")

    assert own.status_code == 200  # the route exists: the refusal below is the role check
    assert response.status_code == 404
    assert await _observations(neo4j_driver) == 3


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("role", [Role.WALL, Role.ADVISOR, Role.EXEC, Role.CLINICAL, Role.OWNER])
async def test_a_role_that_may_not_confirm_is_refused_even_with_a_key_that_was_used_before(
    api_client: AsyncClient, neo4j_driver: AsyncDriver, role: Role
) -> None:
    # The replay cache answers before the use case runs, and it is keyed by the token's sub. The
    # same sub, key and body that a lead used must not be answered from that cached 200 once the
    # token's role is one that may not confirm: only the route's role check refuses it.
    lead = await _confirm(api_client, CONFIRM_WEST, _bearer(Role.LEAD, (), "shared-sub"), "key-k")
    observations = await _observations(neo4j_driver)

    refused = await _confirm(
        api_client, CONFIRM_WEST, _bearer(role, ("svc-ucr-west",), "shared-sub"), "key-k"
    )

    assert lead.status_code == 200
    assert refused.status_code == 404
    assert refused.json()["resourceType"] == "OperationOutcome"
    assert refused.json()["issue"][0]["code"] == "not-found"
    assert "idempotent-replay" not in refused.headers
    assert await _observations(neo4j_driver) == observations


@pytest.mark.usefixtures("seeded")
async def test_a_reporter_who_lost_the_service_is_refused_even_with_a_key_used_before(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    # Same reasoning as above, for the service scope: the new token for the same sub no longer
    # lists svc-ucr-west, so only ensure_can_act_for refuses the cached request.
    first = await _confirm(api_client, CONFIRM_WEST, _west_reporter(), "key-k")
    observations = await _observations(neo4j_driver)
    moved = _bearer(Role.REPORTER, ("svc-ward-a",), "prac-reporter-west")

    refused = await _confirm(api_client, CONFIRM_WEST, moved, "key-k")
    elsewhere = await _confirm(
        api_client, CONFIRM_WEST, _bearer(Role.REPORTER, (), "prac-reporter-west"), "key-k"
    )

    assert first.status_code == 200
    assert refused.status_code == 404
    assert refused.json()["resourceType"] == "OperationOutcome"
    assert "idempotent-replay" not in refused.headers
    assert elsewhere.status_code == 404
    assert await _observations(neo4j_driver) == observations


@pytest.mark.usefixtures("seeded")
async def test_a_reporter_for_another_service_with_no_key_gets_not_found_not_a_key_error(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    # The scope check runs before the key check, so a refusal says nothing about the request.
    control = await _confirm(api_client, CONFIRM_WEST, _west_reporter(), key=None)

    refused = await _confirm(api_client, CONFIRM_WARD, _west_reporter(), key=None)

    assert control.status_code == 400  # the key check exists: it answers for the own service
    assert refused.status_code == 404
    assert refused.json()["resourceType"] == "OperationOutcome"
    assert refused.json()["issue"][0]["code"] == "not-found"
    assert await _observations(neo4j_driver) == 2


@pytest.mark.usefixtures("seeded")
async def test_no_token_cannot_confirm(api_client: AsyncClient, neo4j_driver: AsyncDriver) -> None:
    response = await _confirm(api_client, CONFIRM_WEST, {})

    assert response.status_code == 401
    assert await _observations(neo4j_driver) == 2


@pytest.mark.usefixtures("board_app")
async def test_a_service_with_no_report_cannot_be_confirmed(
    api_client: AsyncClient, factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await _seed(factory, (QUIET,), ())

    response = await _confirm(
        api_client,
        "/fhir/HealthcareService/svc-quiet/$confirm-capacity",
        _bearer(Role.LEAD, (), "lead-1"),
    )

    assert response.status_code == 409
    assert response.json()["resourceType"] == "OperationOutcome"
    issue = response.json()["issue"][0]
    assert issue["code"] == "business-rule"
    assert issue["diagnostics"] == "Send the number for Quiet service."
    assert await _observations(neo4j_driver) == 0


@pytest.mark.usefixtures("seeded")
async def test_the_same_key_and_request_is_answered_from_the_cache_and_stores_one(
    api_client: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    first = await _confirm(api_client, CONFIRM_WEST, _west_reporter(), "same-key")

    again = await _confirm(api_client, CONFIRM_WEST, _west_reporter(), "same-key")

    assert first.status_code == again.status_code == 200
    assert again.json() == first.json()
    assert again.headers["idempotent-replay"] == "true"
    assert "idempotent-replay" not in first.headers
    assert await _observations(neo4j_driver) == 3


@pytest.mark.usefixtures("seeded")
async def test_the_stored_key_answers_the_repeat_after_the_cache_is_lost(
    api_client: AsyncClient,
    board_app: FastAPI,
    test_container: Container,
    neo4j_driver: AsyncDriver,
) -> None:
    first = await _confirm(api_client, CONFIRM_WEST, _west_reporter(), "same-key")
    board_app.state.cache = InMemoryCache(test_container.clock)

    again = await _confirm(api_client, CONFIRM_WEST, _west_reporter(), "same-key")

    assert again.status_code == 200
    assert again.json() == first.json()
    assert await _observations(neo4j_driver) == 3


@pytest.mark.usefixtures("seeded")
async def test_one_key_cannot_confirm_two_services(
    api_client: AsyncClient, factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    lead = _bearer(Role.LEAD, (), "lead-1")
    first = await _confirm(api_client, CONFIRM_WEST, lead, "shared-key")

    second = await _confirm(api_client, CONFIRM_WARD, lead, "shared-key")

    assert first.status_code == 200
    assert second.status_code == 409
    assert "idempotent-replay" not in second.headers
    assert await _observations(neo4j_driver) == 3
    async with factory() as uow:
        ward = await uow.capacity.latest("svc-ward-a")
    assert ward is not None
    assert ward.id == "obs-ward-a-1305"


@pytest.mark.usefixtures("seeded")
async def test_a_refused_confirm_is_not_cached_so_it_can_be_retried(
    api_client: AsyncClient, factory: UnitOfWorkFactory, clock: FixedClock
) -> None:
    async with factory() as uow:
        await uow.services.save(QUIET)
        await uow.commit()
    path = "/fhir/HealthcareService/svc-quiet/$confirm-capacity"
    lead = _bearer(Role.LEAD, (), "lead-1")
    refused = await _confirm(api_client, path, lead, "retry-key")
    clock.advance(timedelta(minutes=1))
    async with factory() as uow:
        await uow.capacity.add(
            CapacityReport(
                id="obs-quiet-1",
                service_id=QUIET.id,
                value=3,
                measure=QUIET.measure,
                effective_at=clock.now(),
                source=ReportSource.APP,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()
    clock.advance(timedelta(minutes=1))

    retried = await _confirm(api_client, path, lead, "retry-key")

    assert refused.status_code == 409
    assert retried.status_code == 200
    assert retried.json()["derivedFrom"] == [{"reference": "Observation/obs-quiet-1"}]


@pytest.mark.usefixtures("seeded")
async def test_the_response_and_the_log_carry_no_token_or_secret(
    api_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    headers = _west_reporter()
    with caplog.at_level("DEBUG"):
        response = await _confirm(api_client, CONFIRM_WEST, headers)

    token = headers["Authorization"].removeprefix("Bearer ")
    assert response.status_code == 200
    assert token not in response.text
    assert token not in caplog.text
    assert TEST_BFF_SECRET.decode() not in caplog.text
