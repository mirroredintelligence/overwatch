"""The routes behind a reporter's bearer token (W7C, DEC-814 to DEC-824, H-452 to H-458): the
services with their state, a prompt, a report (a confirm, a number, closed), the day's history,
several confirms in one call, the settings, a cover number, the channel, the answer to a service
the lead added, the set-up summary, a test push, and a booking read and decision by its reference.

The role matrix first: no token, a role that is not a reporter, and a reporter whose phone was
signed out. Then what each route answers and what was really stored (DEC-004). The reporter's token
names both services; the routes must ask the graph what the person holds (a cover that began after
the token was made takes effect at once). Samples only: UCR West and East, sample numbers.
"""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.identity import HmacPhoneHasher
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.request_booking import need_text, urgency_wording
from diucs.bootstrap.container import Container
from diucs.domain.codes import (
    BookingStatus,
    Channel,
    PractitionerRoleCode,
    ReportType,
    Role,
)
from diucs.domain.model.booking import Booking
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.tenant import ContactKind, TenantContact
from tests.integration.adapters.inbound.fhir_rest.reporter_rig import (
    COVER_MOBILE,
    DEVICE,
    EAST,
    MOBILE,
    NOW,
    OTHER_DEVICE,
    PERSON,
    WEST,
    bearer,
    build_app,
    client_for,
    open_container,
    profile,
    seed_host_and_head,
    seed_invitation,
    seed_world,
)
from tests.support.booking_rig import open_case
from tests.support.link_rig import HOST_A
from tests.support.neo4j import ThrowawayNeo4j, count_nodes, node_props

pytestmark = pytest.mark.asyncio(loop_scope="session")

SPOA_PHONE = "01305 000111"
BOOKING_REFERENCE = "1001"
BOOKING_ID = "bk-1"
KEY = "reporter-key-0001"


@pytest_asyncio.fixture(loop_scope="session")
async def container(
    harness_container: ThrowawayNeo4j, clean_graph: None, tenant_id: str
) -> AsyncIterator[Container]:
    async for opened in open_container(harness_container, FixedClock(NOW), tenant_id):
        yield opened


@pytest_asyncio.fixture(loop_scope="session")
async def world(container: Container, neo4j_driver: AsyncDriver, tenant_id: str) -> Container:
    await seed_host_and_head(neo4j_driver, tenant_id, HOST_A)
    await seed_world(container, tenant_id)
    return container


@pytest_asyncio.fixture(loop_scope="session")
async def api(world: Container) -> AsyncIterator[AsyncClient]:
    async with client_for(await build_app(world), HOST_A) as client:
        yield client


def advance(container: Container, delta: timedelta) -> None:
    container.clock.advance(delta)  # type: ignore[attr-defined]


async def seed_north(container: Container, tenant: str) -> None:
    """A third service the reporter holds, with no report ever: it is due."""
    with bind_tenant(tenant):
        async with container.uow_factory() as uow:
            await uow.services.save(profile("ucr-north", "UCR North"))
            await uow.people.save_role(
                PractitionerRole(
                    id="role-north",
                    practitioner_id=PERSON,
                    service_id="ucr-north",
                    code=PractitionerRoleCode.DUTY_MANAGER,
                    active=True,
                    channel=Channel.TEXT,
                    period_start=NOW - timedelta(days=30),
                )
            )
            await uow.commit()


async def seed_stranger(container: Container, tenant: str) -> None:
    """Another reporter, with a service of their own, that PERSON does not hold."""
    with bind_tenant(tenant):
        async with container.uow_factory() as uow:
            await uow.services.save(profile("ucr-other", "UCR Other"))
            await uow.people.save_practitioner(
                Practitioner(
                    id="prac-9",
                    active=True,
                    display_name="Other Reporter",
                    phone_hash=HmacPhoneHasher(container.secrets).hash("07700 900999"),
                )
            )
            await uow.people.save_role(
                PractitionerRole(
                    id="role-other",
                    practitioner_id="prac-9",
                    service_id="ucr-other",
                    code=PractitionerRoleCode.DUTY_MANAGER,
                    active=True,
                    channel=Channel.TEXT,
                    period_start=NOW - timedelta(days=30),
                )
            )
            await uow.commit()


async def seed_booking(container: Container, tenant: str, service_id: str = WEST) -> None:
    with bind_tenant(tenant):
        async with container.uow_factory() as uow:
            await uow.cases.add(open_case())
            await uow.contacts.put_phone("role-lead", "+447700900001")
            await uow.tenant_config.put_contact(
                TenantContact(ContactKind.COORDINATION_PHONE, "SPOA", SPOA_PHONE)
            )
            await uow.bookings.add(
                Booking(
                    id=BOOKING_ID,
                    reference=BOOKING_REFERENCE,
                    service_id=service_id,
                    case_id="case-1001",
                    requester_id="advisor-1",
                    status=BookingStatus.REQUESTED,
                    requested_at=NOW - timedelta(minutes=5),
                    reply_by=NOW + timedelta(minutes=25),
                )
            )
            await uow.commit()


def keyed(key: str = KEY, **kwargs: Any) -> dict[str, str]:
    return bearer(key=key, **kwargs)


# ----------------------------------------------------------------------------- the role matrix

ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/reporter/services", None),
    ("GET", f"/reporter/services/{WEST}/prompt", None),
    ("GET", f"/reporter/services/{WEST}/history", None),
    ("POST", f"/reporter/services/{WEST}/report", {"kind": "confirm"}),
    ("POST", "/reporter/reports/batch", {"items": [{"serviceId": WEST, "kind": "confirm"}]}),
    ("GET", "/reporter/settings", None),
    ("POST", "/reporter/cover", {"phone": COVER_MOBILE}),
    ("POST", "/reporter/channel", {"channel": "text"}),
    ("POST", f"/reporter/services/{WEST}/cover", {"phone": COVER_MOBILE, "until": "tonight"}),
    ("POST", f"/reporter/services/{WEST}/accept", {"accept": True}),
    ("GET", "/reporter/setup-summary", None),
    ("POST", "/reporter/push-test", {}),
    ("GET", f"/reporter/bookings/{BOOKING_REFERENCE}", None),
    ("POST", f"/reporter/bookings/{BOOKING_REFERENCE}/respond", {"decision": "confirm"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_no_token_is_refused_with_the_one_401(
    api: AsyncClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    response = await api.request(method, path, json=body, headers={"Idempotency-Key": KEY})

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
@pytest.mark.parametrize("role", [role for role in Role if role is not Role.REPORTER])
async def test_a_role_that_is_not_a_reporter_reads_nothing_and_writes_nothing(
    api: AsyncClient,
    world: Container,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    role: Role,
) -> None:
    # All thirteen roles (W9H): every role but a reporter is refused, with one body. The executive
    # is admitted to the test notification only (DEC-1040); there it is answered by the person check
    # (no person record for the sample subject: 401), never the 404 of a refused role.
    await seed_booking(world, tenant_id)
    before = await count_nodes(neo4j_driver, "Observation")

    response = await api.request(
        method, path, json=body, headers=keyed(role=role, person="advisor-1", device=None)
    )

    if role is Role.PLATFORM_OPERATOR:
        assert response.status_code == 401
    elif role is Role.EXEC and path == "/reporter/push-test":
        assert response.status_code == 401
    else:
        assert response.status_code == 404
        assert response.json()["issue"][0]["code"] == "not-found"
    assert await count_nodes(neo4j_driver, "Observation") == before


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_a_reporter_whose_phone_was_signed_out_is_refused_at_once(
    api: AsyncClient,
    world: Container,
    tenant_id: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            await uow.devices.revoke_all(PERSON)
            await uow.commit()

    response = await api.request(method, path, json=body, headers=keyed())

    assert response.status_code == 401


# ----------------------------------------------------------------------------- services


async def test_the_services_are_listed_by_name_with_their_state(api: AsyncClient) -> None:
    response = await api.get("/reporter/services", headers=bearer())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "services": [
            {
                "id": EAST,
                "name": "UCR East",
                "state": "confirmed",
                "recordedValue": 2,
                "unitLabel": "referrals in the next 2 hrs",
                "at": "2026-10-29T13:58:00Z",
                "nextDue": "2026-10-30T08:00:00Z",
                "pendingAcceptance": False,
            },
            {
                "id": WEST,
                "name": "UCR West",
                "state": "due",
                "recordedValue": 4,
                "unitLabel": "referrals in the next 2 hrs",
                "at": "2026-10-29T12:10:00Z",
                "nextDue": "2026-10-29T16:00:00Z",
                "replyBy": "2026-10-29T14:30:00Z",
                "pendingAcceptance": False,
            },
        ]
    }


async def test_services_due_together_carry_the_letters_of_a_grouped_prompt(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await seed_north(world, tenant_id)

    rows = (await api.get("/reporter/services", headers=bearer())).json()["services"]

    by_id = {row["id"]: row for row in rows}
    assert by_id["ucr-north"]["letter"] == "A"
    assert by_id[WEST]["letter"] == "B"
    assert "letter" not in by_id[EAST]
    assert by_id["ucr-north"]["recordedValue"] is None


async def test_a_suspended_service_is_paused_and_a_service_not_live_is_not_listed(
    api: AsyncClient, world: Container, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            await uow.flags.set_service_flag(
                ServiceFlag(WEST, SERVICE_FLAG_SUSPENDED, True, "away", "lead-1", NOW)
            )
            await uow.commit()
    await seed_invitation(world, tenant_id)  # a service that is not live yet, for another person

    rows = (await api.get("/reporter/services", headers=bearer())).json()["services"]

    assert {row["id"]: row["state"] for row in rows} == {EAST: "confirmed", WEST: "paused"}


async def test_the_services_come_from_the_graph_not_from_the_tokens_claim(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    # PERSON's post on UCR West is covered by prac-2 until tomorrow: the token still names both.
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            await uow.people.save_practitioner(
                Practitioner(
                    id="prac-2",
                    active=True,
                    display_name="Cover",
                    phone_hash=HmacPhoneHasher(world.secrets).hash(COVER_MOBILE),
                )
            )
            role = await uow.people.get_role("role-west")
            assert role is not None
            await uow.people.save_role(
                replace(
                    role, covered_by_practitioner_id="prac-2", covered_until=NOW + timedelta(days=1)
                )
            )
            await uow.commit()

    rows = (await api.get("/reporter/services", headers=bearer())).json()["services"]
    prompt = await api.get(f"/reporter/services/{WEST}/prompt", headers=bearer())

    assert [row["id"] for row in rows] == [EAST]
    assert prompt.status_code == 404


# ----------------------------------------------------------------------------- prompt


async def test_the_prompt_of_a_due_service_shows_the_figure_the_range_and_the_reply_by(
    api: AsyncClient,
) -> None:
    response = await api.get(f"/reporter/services/{WEST}/prompt", headers=bearer())

    assert response.status_code == 200
    assert response.json() == {
        "service": "UCR West",
        "unitLabel": "referrals in the next 2 hrs",
        "recordedValue": 4,
        "asOf": "2026-10-29T12:10:00Z",
        "low": 0,
        "high": 8,
        "replyBy": "2026-10-29T14:30:00Z",
        "nextDue": "2026-10-29T16:00:00Z",
    }


async def test_the_prompt_of_a_service_that_is_up_to_date_has_no_reply_by(api: AsyncClient) -> None:
    body = (await api.get(f"/reporter/services/{EAST}/prompt", headers=bearer())).json()

    assert body["replyBy"] is None
    assert body["nextDue"] == "2026-10-30T08:00:00Z"


async def test_an_unknown_service_and_another_reporters_service_are_the_same_404(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await seed_stranger(world, tenant_id)

    unknown = await api.get("/reporter/services/ucr-nowhere/prompt", headers=bearer())
    other = await api.get("/reporter/services/ucr-other/prompt", headers=bearer())

    assert unknown.status_code == other.status_code == 404
    assert unknown.json() == other.json()


# ----------------------------------------------------------------------------- report


async def latest_of(container: Container, tenant: str, service: str) -> Any:
    with bind_tenant(tenant):
        async with container.uow_factory() as uow:
            return await uow.capacity.latest(service)


async def test_a_confirm_is_recorded_from_the_app_for_the_post_that_confirmed(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    response = await api.post(
        f"/reporter/services/{WEST}/report", json={"kind": "confirm"}, headers=keyed()
    )

    assert response.status_code == 200
    assert response.json() == {
        "result": "recorded",
        "serviceName": "UCR West",
        "value": 4,
        "recordedAt": "2026-10-29T14:00:00Z",
        "nextDue": "2026-10-29T16:00:00Z",
    }
    latest = await latest_of(world, tenant_id, WEST)
    assert latest.report_type is ReportType.CONFIRMED
    assert (latest.value, latest.source.value, latest.performer_role_id) == (4, "app", "role-west")
    assert latest.derived_from == "rep-west-1"


async def test_a_number_in_range_is_recorded_and_closed_is_a_figure_of_zero(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    number = await api.post(
        f"/reporter/services/{WEST}/report", json={"kind": "number", "value": 5}, headers=keyed()
    )
    advance(world, timedelta(minutes=1))
    closed = await api.post(
        f"/reporter/services/{WEST}/report", json={"kind": "closed"}, headers=keyed("key-closed-1")
    )

    assert (number.json()["result"], number.json()["value"]) == ("recorded", 5)
    assert (closed.json()["result"], closed.json()["value"]) == ("recorded", 0)
    latest = await latest_of(world, tenant_id, WEST)
    assert (latest.report_type, latest.value) == (ReportType.NUMBER, 0)


async def test_a_number_out_of_range_is_asked_for_again_and_the_second_send_is_flagged(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    first = await api.post(
        f"/reporter/services/{WEST}/report", json={"kind": "number", "value": 12}, headers=keyed()
    )

    assert first.status_code == 200
    assert first.json() == {
        "result": "outOfRange",
        "serviceName": "UCR West",
        "value": 12,
        "low": 0,
        "high": 8,
    }
    assert (await latest_of(world, tenant_id, WEST)).value == 4

    advance(world, timedelta(minutes=1))
    second = await api.post(
        f"/reporter/services/{WEST}/report",
        json={"kind": "number", "value": 12, "confirmOutOfRange": True},
        headers=keyed("key-second-1"),
    )

    assert (second.json()["result"], second.json()["value"]) == ("recorded", 12)
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            flags = await uow.flags.open_report_flags(WEST)
    assert len(flags) == 1


async def test_a_third_confirm_in_a_row_is_refused_with_the_limit(
    api: AsyncClient, world: Container
) -> None:
    answers = []
    for index in range(3):
        answers.append(
            await api.post(
                f"/reporter/services/{WEST}/report",
                json={"kind": "confirm"},
                headers=keyed(f"key-confirm-{index}"),
            )
        )
        advance(world, timedelta(minutes=1))

    assert [a.status_code for a in answers] == [200, 200, 409]
    assert answers[2].json() == {"result": "confirmLimit", "serviceName": "UCR West"}


async def test_a_confirm_of_a_figure_older_than_two_hours_asks_for_the_number(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    advance(world, timedelta(minutes=30))  # the figure is now 2 hours 20 minutes old (H-31)

    response = await api.post(
        f"/reporter/services/{WEST}/report", json={"kind": "confirm"}, headers=keyed()
    )

    assert response.status_code == 409
    assert response.json() == {"result": "sendNumber", "serviceName": "UCR West", "reason": "stale"}
    assert (await latest_of(world, tenant_id, WEST)).report_type is ReportType.NUMBER


async def test_a_confirm_with_no_figure_on_record_asks_for_the_number(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await seed_north(world, tenant_id)

    response = await api.post(
        "/reporter/services/ucr-north/report", json={"kind": "confirm"}, headers=keyed()
    )

    assert response.status_code == 409
    assert response.json()["reason"] == "no-figure"


async def test_the_same_key_records_one_report_whatever_is_sent_again(
    api: AsyncClient, world: Container, neo4j_driver: AsyncDriver
) -> None:
    first = await api.post(
        f"/reporter/services/{WEST}/report", json={"kind": "number", "value": 5}, headers=keyed()
    )
    again = await api.post(
        f"/reporter/services/{WEST}/report", json={"kind": "number", "value": 5}, headers=keyed()
    )
    other = await api.post(
        f"/reporter/services/{WEST}/report", json={"kind": "number", "value": 6}, headers=keyed()
    )

    assert first.json() == again.json()
    assert other.status_code in (409, 422)
    assert await count_nodes(neo4j_driver, "Observation") == 3  # the two seeded and one new


async def test_a_report_needs_an_idempotency_key(api: AsyncClient) -> None:
    response = await api.post(
        f"/reporter/services/{WEST}/report", json={"kind": "confirm"}, headers=bearer()
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "reject"},
        {"kind": "number"},
        {"kind": "number", "value": 1000},
        {"kind": "number", "value": -1},
        {"kind": "confirm", "value": 3},
        {"kind": "confirm", "confirmOutOfRange": True},
        {"kind": "confirm", "tenant": "other"},
        {},
    ],
)
async def test_a_report_the_screens_cannot_send_is_refused_and_stores_nothing(
    api: AsyncClient, neo4j_driver: AsyncDriver, body: dict[str, Any]
) -> None:
    response = await api.post(f"/reporter/services/{WEST}/report", json=body, headers=keyed())

    assert response.status_code == 400
    assert await count_nodes(neo4j_driver, "Observation") == 2


async def test_a_report_for_a_service_the_reporter_does_not_hold_is_a_404_and_stores_nothing(
    api: AsyncClient, world: Container, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    await seed_stranger(world, tenant_id)

    response = await api.post(
        "/reporter/services/ucr-other/report", json={"kind": "number", "value": 2}, headers=keyed()
    )

    assert response.status_code == 404
    assert await count_nodes(neo4j_driver, "Observation") == 2


# ----------------------------------------------------------------------------- history


async def test_the_days_reports_are_listed_newest_first_and_yesterdays_are_left_out(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await api.post(f"/reporter/services/{WEST}/report", json={"kind": "confirm"}, headers=keyed())
    clock = world.clock
    assert isinstance(clock, FixedClock)
    yesterday = NOW - timedelta(hours=20)
    clock.set(yesterday)
    from tests.integration.adapters.inbound.fhir_rest.reporter_rig import report

    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            await uow.capacity.add(report("rep-old", WEST, 7, yesterday))
            await uow.commit()
    clock.set(NOW)

    response = await api.get(f"/reporter/services/{WEST}/history?day=today", headers=bearer())

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"at": "2026-10-29T14:00:00Z", "value": 4, "kind": "confirmed"},
            {"at": "2026-10-29T12:10:00Z", "value": 4, "kind": "number"},
        ]
    }


async def test_history_is_for_today_only(api: AsyncClient) -> None:
    refused = await api.get(f"/reporter/services/{WEST}/history?day=yesterday", headers=bearer())
    default = await api.get(f"/reporter/services/{WEST}/history", headers=bearer())

    assert refused.status_code == 400
    assert default.status_code == 200


async def test_the_history_of_a_service_the_reporter_does_not_hold_is_a_404(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await seed_stranger(world, tenant_id)

    response = await api.get("/reporter/services/ucr-other/history", headers=bearer())

    assert response.status_code == 404


# ----------------------------------------------------------------------------- batch


async def test_several_services_on_one_phone_are_confirmed_in_one_call(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    response = await api.post(
        "/reporter/reports/batch",
        json={
            "items": [
                {"serviceId": WEST, "kind": "confirm"},
                {"serviceId": EAST, "kind": "confirm"},
            ]
        },
        headers=keyed(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {"serviceId": WEST, "result": "recorded", "at": "2026-10-29T14:00:00Z"},
            {"serviceId": EAST, "result": "recorded", "at": "2026-10-29T14:00:00Z"},
        ]
    }
    for service in (WEST, EAST):
        assert (await latest_of(world, tenant_id, service)).report_type is ReportType.CONFIRMED


async def test_a_service_that_must_send_a_number_does_not_stop_the_others(
    api: AsyncClient, world: Container
) -> None:
    advance(world, timedelta(minutes=30))  # West's figure is now too old to confirm

    response = await api.post(
        "/reporter/reports/batch",
        json={
            "items": [
                {"serviceId": WEST, "kind": "confirm"},
                {"serviceId": EAST, "kind": "confirm"},
            ]
        },
        headers=keyed(),
    )

    results = {item["serviceId"]: item for item in response.json()["results"]}
    assert results[WEST] == {"serviceId": WEST, "result": "sendNumber", "reason": "stale"}
    assert results[EAST]["result"] == "recorded"


async def test_a_batch_with_a_service_the_reporter_does_not_hold_writes_nothing(
    api: AsyncClient, world: Container, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    await seed_stranger(world, tenant_id)

    response = await api.post(
        "/reporter/reports/batch",
        json={
            "items": [
                {"serviceId": WEST, "kind": "confirm"},
                {"serviceId": "ucr-other", "kind": "confirm"},
            ]
        },
        headers=keyed(),
    )

    assert response.status_code == 404
    assert await count_nodes(neo4j_driver, "Observation") == 2


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"serviceId": WEST, "kind": "number", "value": 3}],
        [{"serviceId": WEST, "kind": "confirm"}, {"serviceId": WEST, "kind": "confirm"}],
        [{"serviceId": f"s-{n}", "kind": "confirm"} for n in range(11)],
        [{"serviceId": WEST}],
    ],
)
async def test_a_batch_is_only_confirms_of_one_to_ten_different_services(
    api: AsyncClient, neo4j_driver: AsyncDriver, items: list[dict[str, Any]]
) -> None:
    response = await api.post("/reporter/reports/batch", json={"items": items}, headers=keyed())

    assert response.status_code == 400
    assert await count_nodes(neo4j_driver, "Observation") == 2


async def test_a_batch_sent_again_with_its_key_records_each_confirm_once(
    api: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    body = {
        "items": [{"serviceId": WEST, "kind": "confirm"}, {"serviceId": EAST, "kind": "confirm"}]
    }

    first = await api.post("/reporter/reports/batch", json=body, headers=keyed())
    again = await api.post("/reporter/reports/batch", json=body, headers=keyed())

    assert first.json() == again.json()
    assert await count_nodes(neo4j_driver, "Observation") == 4


# ----------------------------------------------------------------------------- settings


async def test_the_settings_are_masked_and_say_when_the_text_code_is_next_needed(
    api: AsyncClient,
) -> None:
    response = await api.get("/reporter/settings", headers=bearer())

    assert response.status_code == 200
    assert response.json() == {
        "channel": "text",
        "maskedPhone": "07xxx xxx123",
        "maskedCover": None,
        "reverifyInDays": 27,
        "otherDevices": 0,
    }
    for secret in (MOBILE, MOBILE.replace(" ", ""), "7700900123"):
        assert secret not in response.text


async def test_the_settings_count_the_other_phones_that_are_signed_in(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            await uow.devices.register(PERSON, OTHER_DEVICE, NOW)
            await uow.commit()

    body = (await api.get("/reporter/settings", headers=bearer())).json()

    assert body["otherDevices"] == 1


# ----------------------------------------------------------------------------- cover


async def test_a_cover_number_hands_every_post_to_the_cover_until_the_end_of_the_week(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    response = await api.post("/reporter/cover", json={"phone": COVER_MOBILE}, headers=bearer())

    assert response.status_code == 200
    assert response.json() == {"coveredUntil": "2026-11-01T23:59:00Z", "services": 2}
    cover_hash = HmacPhoneHasher(world.secrets).hash(COVER_MOBILE)
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            cover = await uow.people.find_by_phone_hash(cover_hash)
            role = await uow.people.get_role("role-west")
            stored = await uow.contacts.get_phone("cover-role-west")
            own = await uow.contacts.get_phone("role-west")
    assert cover is not None and role is not None
    assert role.covered_by_practitioner_id == cover.id
    assert stored == "+447700900456"
    assert own == "+447700900123"  # the post's own number is untouched
    assert COVER_MOBILE not in response.text
    settings = (await api.get("/reporter/settings", headers=bearer())).json()
    assert settings["maskedCover"] == "07xxx xxx456"
    assert (await api.get("/reporter/services", headers=bearer())).json() == {"services": []}


@pytest.mark.parametrize(
    ("body", "until"),
    [
        ({"until": "tonight"}, "2026-10-29T23:59:00Z"),
        ({"until": "this-week"}, "2026-11-01T23:59:00Z"),
        ({"until": "date", "date": "2026-11-05"}, "2026-11-05T23:59:00Z"),
    ],
)
async def test_a_cover_ends_at_the_end_of_the_day_chosen(
    api: AsyncClient, body: dict[str, Any], until: str
) -> None:
    response = await api.post(
        "/reporter/cover", json={"phone": COVER_MOBILE, **body}, headers=bearer()
    )

    assert response.json()["coveredUntil"] == until


@pytest.mark.parametrize(
    "body",
    [
        {"phone": "07700 900123"},  # the reporter's own number
        {"phone": "020 7946 0000"},
        {"phone": "not a number"},
        {"phone": COVER_MOBILE, "until": "forever"},
        {"phone": COVER_MOBILE, "until": "date"},
        {"phone": COVER_MOBILE, "until": "date", "date": "2026-12-01"},
        {"phone": COVER_MOBILE, "until": "date", "date": "2026-10-28"},
        {"phone": COVER_MOBILE, "tenant": "other"},
    ],
)
async def test_a_cover_that_cannot_be_set_is_refused_and_changes_nothing(
    api: AsyncClient, world: Container, tenant_id: str, body: dict[str, Any]
) -> None:
    response = await api.post("/reporter/cover", json=body, headers=bearer())

    assert response.status_code == 400
    assert "7700 900456" not in response.text
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            role = await uow.people.get_role("role-west")
    assert role is not None and role.covered_by_practitioner_id is None


async def test_a_cover_for_one_service_leaves_the_others_with_the_reporter(
    api: AsyncClient,
) -> None:
    response = await api.post(
        f"/reporter/services/{WEST}/cover",
        json={"phone": COVER_MOBILE, "until": "tonight"},
        headers=bearer(),
    )

    assert response.json() == {"coveredUntil": "2026-10-29T23:59:00Z", "services": 1}
    rows = (await api.get("/reporter/services", headers=bearer())).json()["services"]
    assert [row["id"] for row in rows] == [EAST]


async def test_a_post_that_is_already_covered_can_be_handed_to_another_cover(
    api: AsyncClient,
) -> None:
    await api.post(
        f"/reporter/services/{WEST}/cover",
        json={"phone": COVER_MOBILE, "until": "tonight"},
        headers=bearer(),
    )

    again = await api.post(
        f"/reporter/services/{WEST}/cover",
        json={"phone": "07700 900654", "until": "this-week"},
        headers=bearer(),
    )

    assert (again.status_code, again.json()) == (
        200,
        {"coveredUntil": "2026-11-01T23:59:00Z", "services": 1},
    )


async def test_a_cover_for_a_service_the_reporter_does_not_hold_is_a_404(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await seed_stranger(world, tenant_id)

    response = await api.post(
        "/reporter/services/ucr-other/cover",
        json={"phone": COVER_MOBILE, "until": "tonight"},
        headers=bearer(),
    )

    assert response.status_code == 404


async def test_the_cover_number_is_in_no_log_line(
    api: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")

    await api.post("/reporter/cover", json={"phone": COVER_MOBILE}, headers=bearer())

    for secret in (COVER_MOBILE, COVER_MOBILE.replace(" ", ""), "7700900456"):
        assert secret not in caplog.text


# ----------------------------------------------------------------------------- channel


async def test_the_channel_is_set_on_every_post_of_the_reporter(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    response = await api.post("/reporter/channel", json={"channel": "app"}, headers=bearer())

    assert (response.status_code, response.json()) == (200, {"channel": "app"})
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            roles = [await uow.people.get_role("role-west"), await uow.people.get_role("role-east")]
    assert all(role is not None and role.channel is Channel.PUSH for role in roles)
    settings = (await api.get("/reporter/settings", headers=bearer())).json()
    assert settings["channel"] == "app"


async def test_an_email_channel_needs_an_address_on_record(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    refused = await api.post("/reporter/channel", json={"channel": "email"}, headers=bearer())
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            await uow.contacts.put_email("role-west", "reporter@sample.example")
            await uow.contacts.put_email("role-east", "reporter@sample.example")
            await uow.commit()
    allowed = await api.post("/reporter/channel", json={"channel": "email"}, headers=bearer())

    assert refused.status_code == 400
    assert allowed.status_code == 200


@pytest.mark.parametrize("channel", ["push", "sms", "", "APP"])
async def test_a_channel_the_screens_do_not_offer_is_refused(
    api: AsyncClient, channel: str
) -> None:
    response = await api.post("/reporter/channel", json={"channel": channel}, headers=bearer())

    assert response.status_code == 400


# ----------------------------------------------------------------------------- accept


async def test_yes_to_a_service_the_lead_added_is_recorded_and_changes_no_post(
    api: AsyncClient,
) -> None:
    response = await api.post(
        f"/reporter/services/{WEST}/accept", json={"accept": True}, headers=bearer()
    )

    assert (response.status_code, response.json()) == (200, {"accepted": True})
    rows = (await api.get("/reporter/services", headers=bearer())).json()["services"]
    assert [row["id"] for row in rows] == [EAST, WEST]


async def test_no_ends_the_reporters_own_post_on_that_service_only(
    api: AsyncClient, world: Container, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    response = await api.post(
        f"/reporter/services/{WEST}/accept", json={"accept": False}, headers=bearer()
    )

    assert (response.status_code, response.json()) == (200, {"accepted": False})
    rows = (await api.get("/reporter/services", headers=bearer())).json()["services"]
    assert [row["id"] for row in rows] == [EAST]
    role = await node_props(neo4j_driver, "PractitionerRole", id="role-west")
    assert role["active"] is False


@pytest.mark.parametrize("body", [{}, {"accept": "yes"}, {"accept": 1}, {"accept": True, "x": 1}])
async def test_an_answer_that_is_not_yes_or_no_is_refused(
    api: AsyncClient, body: dict[str, Any]
) -> None:
    response = await api.post(f"/reporter/services/{WEST}/accept", json=body, headers=bearer())

    assert response.status_code == 400


async def test_an_answer_for_a_service_the_reporter_does_not_hold_is_a_404(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await seed_stranger(world, tenant_id)

    response = await api.post(
        "/reporter/services/ucr-other/accept", json={"accept": False}, headers=bearer()
    )

    assert response.status_code == 404


# ----------------------------------------------------------------------------- setup summary


async def test_the_set_up_summary_names_the_service_and_when_the_next_update_is_due(
    api: AsyncClient,
) -> None:
    response = await api.get("/reporter/setup-summary", headers=bearer())

    assert response.status_code == 200
    assert response.json() == {
        "service": "UCR East",
        "contactBy": "text",
        "maskedPhone": "07xxx xxx123",
        "nextUpdateDue": "2026-10-30T08:00:00Z",
        "textCodeInDays": 27,
    }


async def test_the_set_up_summary_of_a_new_reporter_names_a_service_that_is_not_live_yet(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    token = await seed_invitation(world, tenant_id)
    from tests.integration.adapters.inbound.fhir_rest.reporter_rig import (
        CODE,
        INVITEE_MOBILE,
        hold_code,
    )

    await hold_code(world, tenant_id, INVITEE_MOBILE)
    new_device = "device-cccccccccccccccccccccc"
    await api.post(
        f"/identity/invitations/{token}/code/verify", json={"code": CODE, "deviceId": new_device}
    )

    response = await api.get(
        "/reporter/setup-summary",
        headers=bearer("invitee-1", services=("ucr-new",), device=new_device),
    )

    assert response.status_code == 200
    assert response.json()["service"] == "UCR New"
    assert response.json()["maskedPhone"] == "07xxx xxx321"
    assert response.json()["textCodeInDays"] == 30


# ----------------------------------------------------------------------------- push test


async def test_a_test_push_needs_a_saved_subscription(api: AsyncClient) -> None:
    response = await api.post("/reporter/push-test", json={}, headers=bearer())

    assert response.status_code == 409
    assert response.json() == {"code": "no-subscription"}


async def test_a_test_push_is_queued_for_the_reporters_phone_with_no_link_and_no_service_data(
    api: AsyncClient, world: Container, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    saved = await api.post(
        "/identity/push-subscription",
        json={
            "subscription": {
                "endpoint": "https://push.example/sample-endpoint",
                "keys": {"p256dh": "sample-p256dh", "auth": "sample-auth"},
            },
            "wordingVersion": "v1",
            "deviceId": DEVICE,
        },
        headers=keyed("key-push-save"),
    )
    assert saved.status_code == 200

    response = await api.post("/reporter/push-test", json={}, headers=bearer())

    assert (response.status_code, response.json()) == (200, {"queued": True})
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            queued = await uow.outbox.pending(10)
    pushes = [m for m in queued if m.payload.get("channel") == "push"]
    assert len(pushes) == 1
    assert pushes[0].event_type == "SendMessage"
    assert pushes[0].payload["recipient_role_id"] in {"role-east", "role-west"}
    assert "sealed_content" in pushes[0].payload
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            communication = await uow.communications.get(pushes[0].payload["communication_id"])
    assert communication is not None
    assert communication.channel is Channel.PUSH
    assert communication.about_id in {WEST, EAST}
    assert "http" not in communication.payload_text


async def test_a_test_push_is_limited_to_three_in_ten_minutes(
    api: AsyncClient, world: Container
) -> None:
    await api.post(
        "/identity/push-subscription",
        json={
            "subscription": {
                "endpoint": "https://push.example/sample-endpoint",
                "keys": {"p256dh": "sample-p256dh", "auth": "sample-auth"},
            },
            "wordingVersion": "v1",
            "deviceId": DEVICE,
        },
        headers=keyed("key-push-save"),
    )

    answers = [await api.post("/reporter/push-test", json={}, headers=bearer()) for _ in range(4)]

    assert [a.status_code for a in answers] == [200, 200, 200, 429]


# ----------------------------------------------------------------------------- bookings


async def test_a_booking_is_read_by_its_reference_with_the_task_id_it_maps_to(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await seed_booking(world, tenant_id)

    response = await api.get(f"/reporter/bookings/{BOOKING_REFERENCE}", headers=bearer())

    case = open_case()
    assert response.status_code == 200
    assert response.json() == {
        "reference": BOOKING_REFERENCE,
        "taskId": BOOKING_ID,
        "service": "UCR West",
        "ageBand": case.age_band.value,  # type: ignore[union-attr]
        "need": need_text(case),
        "urgency": urgency_wording(case.urgency),  # type: ignore[arg-type]
        "replyBy": "2026-10-29T14:25:00Z",
        "status": "requested",
        "bookingStatus": "requested",
        "multiService": True,
        "spoaPhone": SPOA_PHONE,
    }
    for private in ("case-1001", "DT4", "postcode", "advisor-1"):
        assert private not in response.text


async def test_a_booking_of_a_service_the_reporter_does_not_hold_or_an_unknown_reference_is_a_404(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await seed_stranger(world, tenant_id)
    await seed_booking(world, tenant_id, service_id="ucr-other")

    other = await api.get(f"/reporter/bookings/{BOOKING_REFERENCE}", headers=bearer())
    unknown = await api.get("/reporter/bookings/9999", headers=bearer())

    assert other.status_code == unknown.status_code == 404
    assert other.json() == unknown.json()


@pytest.mark.parametrize("reference", ["abc", "123", "12345", "10 01", "1001/x"])
async def test_a_reference_that_is_not_four_digits_is_a_404(
    api: AsyncClient, reference: str
) -> None:
    response = await api.get(f"/reporter/bookings/{reference}", headers=bearer())

    assert response.status_code == 404


async def test_a_confirm_by_reference_answers_the_booking_on_the_task_it_maps_to(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await seed_booking(world, tenant_id)

    response = await api.post(
        f"/reporter/bookings/{BOOKING_REFERENCE}/respond",
        json={"decision": "confirm"},
        headers=keyed(),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "confirmed", "confirmedAt": "2026-10-29T14:00:00Z"}
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            booking = await uow.bookings.get(BOOKING_ID)
    assert booking is not None and booking.status is BookingStatus.CONFIRMED
    read = (await api.get(f"/reporter/bookings/{BOOKING_REFERENCE}", headers=bearer())).json()
    assert read["status"] == "confirmed"
    assert read["confirmedAt"] == "2026-10-29T14:00:00Z"


async def test_a_decline_takes_a_reason_from_the_screens_list_and_a_second_answer_is_a_conflict(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await seed_booking(world, tenant_id)

    bad = await api.post(
        f"/reporter/bookings/{BOOKING_REFERENCE}/respond",
        json={"decision": "decline", "reason": "no-reason-like-this"},
        headers=keyed(),
    )
    declined = await api.post(
        f"/reporter/bookings/{BOOKING_REFERENCE}/respond",
        json={"decision": "decline", "reason": "full"},
        headers=keyed("key-decline-1"),
    )
    again = await api.post(
        f"/reporter/bookings/{BOOKING_REFERENCE}/respond",
        json={"decision": "confirm"},
        headers=keyed("key-confirm-2"),
    )

    assert bad.status_code == 400
    assert (declined.status_code, declined.json()) == (200, {"status": "declined"})
    assert again.status_code == 409


async def test_a_decision_for_a_booking_of_another_service_changes_nothing(
    api: AsyncClient, world: Container, tenant_id: str
) -> None:
    await seed_stranger(world, tenant_id)
    await seed_booking(world, tenant_id, service_id="ucr-other")

    response = await api.post(
        f"/reporter/bookings/{BOOKING_REFERENCE}/respond",
        json={"decision": "confirm"},
        headers=keyed(),
    )

    assert response.status_code == 404
    with bind_tenant(tenant_id):
        async with world.uow_factory() as uow:
            booking = await uow.bookings.get(BOOKING_ID)
    assert booking is not None and booking.status is BookingStatus.REQUESTED
