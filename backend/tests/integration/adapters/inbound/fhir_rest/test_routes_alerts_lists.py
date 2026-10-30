"""The acknowledged and closed alert lists (W7A-B6, R12) against real Neo4j through the API client.

`GET /fhir/Task?code=acknowledge-alert&owner=me&status=acknowledged|closed` lists the caller's own
alerts in that state, the latest first, with when each was acknowledged. The open list is as it was.
Another owner's alerts and the other tenant's alerts are never in a list. Sample values only.
"""

from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import AlertKind, Role, code_system_url
from diucs.domain.model.alerts import AlertRecord
from tests.integration.adapters.inbound.fhir_rest.test_routes_alerts import (
    LEAD,
    NOW,
    alert_world,
    test_container,
)
from tests.support.api import token_headers

__all__ = ["alert_world", "test_container"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

TASKS = "/fhir/Task"
ACKNOWLEDGED_AT = code_system_url("alert-acknowledged-at")


def _alert(
    alert_id: str, owner: str, status: str, raised_minutes_ago: int, acknowledged: bool
) -> AlertRecord:
    raised = NOW - timedelta(minutes=raised_minutes_ago)
    return AlertRecord(
        id=alert_id,
        kind=AlertKind.NOT_UPDATED,
        service_id="svc-alerts",
        owner_practitioner_id=owner,
        status=status,
        raised_at=raised,
        escalation_due_at=None,
        part_of_id=None,
        acknowledged_at=(raised + timedelta(minutes=20)) if acknowledged else None,
    )


@pytest_asyncio.fixture(loop_scope="session")
async def lists_world(
    alert_world: None, uow_factory_a: UnitOfWorkFactory, uow_factory_b: UnitOfWorkFactory
) -> None:
    """On top of the open alerts of alert_world: two acknowledged alerts of the lead (the later
    raised one first), one closed, one acknowledged alert of another owner, and an acknowledged and
    a closed alert of the second tenant's lead (the same practitioner id)."""
    async with uow_factory_a() as uow:
        await uow.alerts.add(_alert("ack-older", LEAD, "acknowledged", 120, True))
        await uow.alerts.add(_alert("ack-newer", LEAD, "acknowledged", 60, True))
        await uow.alerts.add(_alert("closed-1", LEAD, "closed", 90, True))
        await uow.alerts.add(_alert("ack-other", "prac-someone-else", "acknowledged", 30, True))
        await uow.commit()
    async with uow_factory_b() as uow:
        await uow.alerts.add(_alert("b-ack", LEAD, "acknowledged", 45, True))
        await uow.alerts.add(_alert("b-closed", LEAD, "closed", 50, True))
        await uow.commit()


async def _list(
    client: AsyncClient, tenant: str, status: str, role: Role = Role.LEAD, sub: str = LEAD
) -> Any:
    return await client.get(
        TASKS,
        params={"code": "acknowledge-alert", "owner": "me", "status": status},
        headers=token_headers(tenant, role, sub=sub),
    )


def _ids(response: Any) -> list[str]:
    return [entry["resource"]["id"] for entry in response.json().get("entry", [])]


async def test_acknowledged_lists_the_callers_acknowledged_alerts_latest_first(
    api_client: AsyncClient, lists_world: None, tenant_id: str
) -> None:
    response = await _list(api_client, tenant_id, "acknowledged")

    assert response.status_code == 200, response.text
    assert _ids(response) == ["ack-newer", "ack-older"]
    assert response.json()["total"] == 2
    task = response.json()["entry"][0]["resource"]
    assert task["status"] == "completed"
    assert task["businessStatus"]["coding"][0]["code"] == "acknowledged"
    acknowledged = [e for e in task["extension"] if e["url"] == ACKNOWLEDGED_AT]
    assert acknowledged == [{"url": ACKNOWLEDGED_AT, "valueDateTime": "2026-10-23T12:32:00+00:00"}]
    assert response.headers["cache-control"] == "no-store"


async def test_closed_lists_the_callers_closed_alerts(
    api_client: AsyncClient, lists_world: None, tenant_id: str
) -> None:
    response = await _list(api_client, tenant_id, "closed")

    assert _ids(response) == ["closed-1"]
    assert response.json()["entry"][0]["resource"]["businessStatus"]["coding"][0]["code"] == (
        "closed"
    )


async def test_the_open_list_is_as_it_was_and_holds_no_acknowledged_alert(
    api_client: AsyncClient, lists_world: None, tenant_id: str
) -> None:
    response = await _list(api_client, tenant_id, "new")

    assert _ids(response) == ["alert-own"]


async def test_no_escalated_alert_is_an_empty_list(
    api_client: AsyncClient, lists_world: None, tenant_id: str
) -> None:
    response = await _list(api_client, tenant_id, "escalated")

    assert response.status_code == 200
    assert _ids(response) == []
    assert response.json()["total"] == 0


async def test_an_executive_reads_their_own_lists_and_not_the_leads(
    api_client: AsyncClient, lists_world: None, tenant_id: str
) -> None:
    response = await _list(api_client, tenant_id, "acknowledged", Role.EXEC, "prac-exec")

    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL, Role.REPORTER, Role.OWNER])
async def test_the_lists_are_for_an_executive_or_a_lead_only(
    api_client: AsyncClient, lists_world: None, tenant_id: str, role: Role
) -> None:
    for status in ("acknowledged", "closed"):
        response = await _list(api_client, tenant_id, status, role, LEAD)

        assert response.status_code == 404, (role, status)


async def test_a_status_that_is_not_listed_is_a_400(
    api_client: AsyncClient, lists_world: None, tenant_id: str
) -> None:
    response = await _list(api_client, tenant_id, "snoozed")

    assert response.status_code == 400


async def test_the_other_tenants_lead_with_the_same_id_reads_only_their_own_alerts(
    api_client: AsyncClient, lists_world: None, tenant_id: str, other_tenant_id: str
) -> None:
    mine = await _list(api_client, tenant_id, "acknowledged")
    theirs = await _list(api_client, other_tenant_id, "acknowledged")
    their_closed = await _list(api_client, other_tenant_id, "closed")

    assert _ids(mine) == ["ack-newer", "ack-older"]
    assert _ids(theirs) == ["b-ack"]
    assert _ids(their_closed) == ["b-closed"]
