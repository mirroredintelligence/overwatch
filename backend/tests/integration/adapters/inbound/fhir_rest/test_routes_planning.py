"""`GET /planning` (W51, U43) against real Neo4j through the API client.

The decision snapshots are written through the real audit log with the shapes the use cases write
(as tests/integration/application/test_planning_analysis.py does). Two tenants: each reads its own
decisions and never the other's. A count under 10 never leaves the route. Sample values only.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Role
from tests.integration.adapters.inbound.fhir_rest.test_routes_clinical import (
    clinical_world,
    test_container,
)
from tests.support.api import token_headers

__all__ = ["clinical_world", "test_container"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

THURSDAY = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)  # Thursday 13:00 London
NEEDS = ["fall-no-injury", "frailty"]
BEST = "svc-ucr-west"
OTHER = "svc-ward-b"


def _actor(tenant: str) -> Actor:
    return Actor(
        role=Role.LEAD,
        practitioner_id="prac-lead-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def _rows() -> list[dict[str, Any]]:
    return [
        {
            "id": BEST,
            "status": "not-accepting",
            "number": 0,
            "data_age_seconds": 60,
            "criteria_version": 1,
            "shown_as": "option",
        },
        {
            "id": OTHER,
            "status": "accepting",
            "number": 5,
            "data_age_seconds": 60,
            "criteria_version": 1,
            "shown_as": "option",
        },
    ]


def _case(key: str, opened: datetime, actor: Actor) -> list[AuditEntry]:
    snapshot = {"age_band": "80+", "needs": NEEDS, "urgency": "within-2-hrs"}
    return [
        AuditEntry(
            action="C",
            use_case="OpenCase",
            actor=actor,
            entity_ids=(key,),
            snapshot={"reference": key[-4:], "referrer_type": "ambulance-crew", **snapshot},
            at=opened,
        ),
        AuditEntry(
            action="R",
            use_case="FilterOptions",
            actor=actor,
            entity_ids=(key, BEST, OTHER),
            snapshot={"reference": key[-4:], "services": _rows()},
            at=opened + timedelta(minutes=1),
        ),
        AuditEntry(
            action="U",
            use_case="RecordOutcome",
            actor=actor,
            entity_ids=(key, OTHER),
            snapshot={
                "reference": key[-4:],
                **snapshot,
                "opened_at": opened.isoformat(),
                "destination_service_id": OTHER,
            },
            at=opened + timedelta(minutes=10),
        ),
    ]


async def _seed(factory: UnitOfWorkFactory, tenant: str, cases: int) -> None:
    actor = _actor(tenant)
    async with factory() as uow:
        for number in range(cases):
            for entry in _case(
                f"case-{tenant[-4:]}{number:04d}", THURSDAY + timedelta(minutes=number), actor
            ):
                await uow.audit.append(entry)
        await uow.commit()


async def _get(client: AsyncClient, tenant: str, role: Role = Role.LEAD) -> Any:
    return await client.get("/planning?period=30d&need=all", headers=token_headers(tenant, role))


async def test_twelve_cases_with_the_best_fit_full_show_their_flow_and_the_busiest_cell(
    api_client: AsyncClient, clinical_world: None, tenant_id: str, uow_factory_a: UnitOfWorkFactory
) -> None:
    await _seed(uow_factory_a, tenant_id, 12)

    response = await _get(api_client, tenant_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["referrals"] == {"count": 12, "suppressed": False}
    assert body["bestFitUnavailable"]["count"] == 12
    assert body["grid"][3][2] == 12
    assert body["busiest"] == {"day": 3, "band": 2, "count": 12}
    assert "case-" not in response.text


async def test_nine_cases_are_not_shown_anywhere(
    api_client: AsyncClient, clinical_world: None, tenant_id: str, uow_factory_a: UnitOfWorkFactory
) -> None:
    await _seed(uow_factory_a, tenant_id, 9)

    body = (await _get(api_client, tenant_id)).json()

    assert body["referrals"] == {"count": None, "suppressed": True}
    assert body["bestFitUnavailable"]["count"] is None
    assert all(cell is None for row in body["grid"] for cell in row)
    assert body["busiest"] is None
    assert all(flow["suppressed"] for flow in body["flows"])


async def test_each_tenant_reads_its_own_decisions_and_never_the_others(
    api_client: AsyncClient,
    clinical_world: None,
    tenant_id: str,
    other_tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    await _seed(uow_factory_a, tenant_id, 12)
    await _seed(uow_factory_b, other_tenant_id, 30)

    a = (await _get(api_client, tenant_id)).json()
    b = (await _get(api_client, other_tenant_id)).json()

    assert a["referrals"]["count"] == 12
    assert b["referrals"]["count"] == 30


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL, Role.OWNER, Role.REPORTER])
async def test_other_roles_read_the_same_404_as_an_unknown_route(
    api_client: AsyncClient, clinical_world: None, tenant_id: str, role: Role
) -> None:
    assert (await _get(api_client, tenant_id, role)).status_code == 404
