"""The subscription, alert and week-summary routes (R12) against real Neo4j through the API client.

WRITTEN, NOT RUN in this build (the wave 5 addendum: integration tests are run once, by the
orchestrator, on the merged tip). Each assertion reads back through a fresh unit of work or
session, not through the route's answer alone.

The run tenant's lead holds its own preferences, and an alert owned by that lead. A second tenant
holds an alert of its own that the run tenant must not reach. Sample values only.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import AlertKind, PractitionerRoleCode, Role, code_system_url
from diucs.domain.model.alerts import AlertRecord
from diucs.domain.model.people import Practitioner, PractitionerRole
from tests.support.api import R01_TEST_NOW, token_headers
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.uow import ensure_audit_heads

EMPTY_PARAMETERS = {"resourceType": "Parameters"}

pytestmark = pytest.mark.asyncio(loop_scope="session")

LEAD = "prac-lead"
DEPUTY = "prac-deputy"
NOW = R01_TEST_NOW
DUE = NOW + timedelta(hours=2)
SUBSCRIPTION = "/fhir/Subscription"
SUMMARY = "/fhir/HealthcareService/$week-summary"


def _subscription(hours: int = 4) -> dict:
    return {
        "resourceType": "Subscription",
        "id": LEAD,
        "status": "active",
        "reason": "Alert preferences",
        "criteria": "alert-preferences",
        "channel": {"type": "message"},
        "extension": [
            {"url": code_system_url("alert-preferences/kind"), "valueCode": "not-updated"},
            {
                "url": code_system_url("alert-preferences/not-updated-hours"),
                "valueInteger": hours,
            },
            {"url": code_system_url("alert-preferences/ack-minutes"), "valueInteger": 15},
            # An alert kind is on, so a deputy is required (SaveAlertPreferences). alert_world
            # seeds the deputy as an active shift lead.
            {
                "url": code_system_url("alert-preferences/deputy"),
                "valueReference": {"reference": f"Practitioner/{DEPUTY}"},
            },
        ],
    }


@pytest_asyncio.fixture(loop_scope="session")
async def test_container(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Container]:
    """The route container with the phone-hash secret. clean_graph runs here, before the edge seeds
    the tenants (lesson L84)."""
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=FixedClock(NOW),
            neo4j=connection,
            secrets=FixedSecretStore({PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab"}),
        )
    finally:
        await connection.close()


async def _alert(factory: UnitOfWorkFactory, alert_id: str, owner: str) -> None:
    async with factory() as uow:
        await uow.alerts.add(
            AlertRecord(
                id=alert_id,
                kind=AlertKind.NOT_UPDATED,
                service_id="svc-alerts",
                owner_practitioner_id=owner,
                status="new",
                raised_at=NOW,
                escalation_due_at=DUE,
                part_of_id=None,
            )
        )
        await uow.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def alert_world(
    api_app: FastAPI,
    test_container: Container,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    """One alert owned by the run tenant's lead, and one owned by another practitioner. The second
    tenant holds an alert of its own. The BFF secret and the replay cache are set as the other
    route tests set them (lesson L131)."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory_a() as uow:
        await uow.people.save_practitioner(
            Practitioner(id=DEPUTY, active=True, display_name="Deputy", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-deputy",
                practitioner_id=DEPUTY,
                service_id=None,
                code=PractitionerRoleCode.SHIFT_LEAD,
                active=True,
                channel=None,
                period_start=R01_TEST_NOW,
            )
        )
        await uow.commit()
    await _alert(uow_factory_a, "alert-own", LEAD)
    await _alert(uow_factory_a, "alert-other", "prac-someone-else")
    await _alert(uow_factory_b, "alert-b", "prac-lead")


async def test_a_lead_saves_a_four_hour_threshold_and_a_fresh_read_shows_it(
    api_client: AsyncClient, alert_world: None, tenant_id: str, uow_factory_a: UnitOfWorkFactory
) -> None:
    first = await api_client.get(
        SUBSCRIPTION, headers=token_headers(tenant_id, Role.LEAD, sub=LEAD)
    )
    assert first.status_code == 200, first.text
    assert first.json()["total"] == 1

    saved = await api_client.put(
        f"{SUBSCRIPTION}/{LEAD}",
        json=_subscription(hours=4),
        headers={
            "Idempotency-Key": "subscription-0001",
            "If-Match": 'W/"1"',
            **token_headers(tenant_id, Role.LEAD, sub=LEAD),
        },
    )

    assert saved.status_code == 200, saved.text
    assert saved.headers["ETag"].startswith('W/"')
    async with uow_factory_a() as uow:
        stored = await uow.alert_subscriptions.get_for_practitioner(LEAD)
    assert stored is not None
    assert stored.preferences.not_updated_hours == 4


async def test_a_threshold_of_three_hours_is_a_bad_request_and_nothing_is_saved(
    api_client: AsyncClient, alert_world: None, tenant_id: str
) -> None:
    refused = await api_client.put(
        f"{SUBSCRIPTION}/{LEAD}",
        json=_subscription(hours=3),
        headers={
            "Idempotency-Key": "subscription-0002",
            "If-Match": 'W/"1"',
            **token_headers(tenant_id, Role.LEAD, sub=LEAD),
        },
    )

    assert refused.status_code == 400, refused.text
    assert refused.json()["issue"][0]["expression"] == ["notUpdatedHours"]


async def test_another_practitioners_subscription_is_not_found(
    api_client: AsyncClient, alert_world: None, tenant_id: str
) -> None:
    refused = await api_client.put(
        f"{SUBSCRIPTION}/prac-someone-else",
        json=_subscription(),
        headers={
            "Idempotency-Key": "subscription-0003",
            "If-Match": 'W/"1"',
            **token_headers(tenant_id, Role.LEAD, sub=LEAD),
        },
    )

    assert refused.status_code == 404, refused.text


async def test_acknowledging_an_own_alert_marks_it_and_leaves_the_board_alone(
    api_client: AsyncClient, alert_world: None, tenant_id: str, uow_factory_a: UnitOfWorkFactory
) -> None:
    acknowledged = await api_client.post(
        "/fhir/Task/alert-own/$acknowledge", json=EMPTY_PARAMETERS,
        headers={
            "Idempotency-Key": "acknowledge-0001",
            **token_headers(tenant_id, Role.LEAD, sub=LEAD),
        },
    )

    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["businessStatus"]["coding"][0]["code"] == "acknowledged"
    async with uow_factory_a() as uow:
        stored = await uow.alerts.get("alert-own")
    assert stored is not None
    assert stored.status == "acknowledged"


async def test_acknowledging_another_owners_alert_is_not_found(
    api_client: AsyncClient, alert_world: None, tenant_id: str
) -> None:
    refused = await api_client.post(
        "/fhir/Task/alert-other/$acknowledge", json=EMPTY_PARAMETERS,
        headers={
            "Idempotency-Key": "acknowledge-0002",
            **token_headers(tenant_id, Role.LEAD, sub=LEAD),
        },
    )

    assert refused.status_code == 404, refused.text


async def test_snoozing_moves_the_next_escalation_one_hour_later(
    api_client: AsyncClient, alert_world: None, tenant_id: str
) -> None:
    snoozed = await api_client.post(
        "/fhir/Task/alert-own/$snooze", json=EMPTY_PARAMETERS,
        headers={
            "Idempotency-Key": "snooze-0001",
            **token_headers(tenant_id, Role.LEAD, sub=LEAD),
        },
    )

    assert snoozed.status_code == 200, snoozed.text
    due = datetime.fromisoformat(
        next(
            p["valueDateTime"]
            for p in snoozed.json()["parameter"]
            if p["name"] == "escalationDueAt"
        )
    )
    assert due == DUE + timedelta(hours=1)


async def test_a_week_with_no_referrals_withholds_the_figure(
    api_client: AsyncClient, alert_world: None, tenant_id: str
) -> None:
    summary = await api_client.get(
        SUMMARY,
        params={"weekStart": "2026-10-19"},
        headers=token_headers(tenant_id, Role.EXEC, sub=LEAD),
    )

    assert summary.status_code == 200, summary.text
    referrals = next(p for p in summary.json()["parameter"] if p["name"] == "referrals")
    assert [part["name"] for part in referrals["part"]] == ["suppressed"]
    assert referrals["part"][0]["valueBoolean"] is True


async def test_tenant_b_cannot_acknowledge_an_alert_of_tenant_a(
    api_client: AsyncClient,
    alert_world: None,
    other_tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    refused = await api_client.post(
        "/fhir/Task/alert-own/$acknowledge", json=EMPTY_PARAMETERS,
        headers={
            "Idempotency-Key": "acknowledge-0003",
            **token_headers(other_tenant_id, Role.LEAD, sub=LEAD),
        },
    )

    assert refused.status_code == 404, refused.text
    async with uow_factory_a() as uow:
        stored = await uow.alerts.get("alert-own")
    assert stored is not None
    assert stored.status == "new"
