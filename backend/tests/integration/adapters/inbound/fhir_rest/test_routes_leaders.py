"""The leadership list for the deputy picker (W7A-B7, DEC-776) against real Neo4j.

`GET /fhir/Practitioner?role=leadership` answers the active shift leads and clinical leads of the
caller's tenant, each as an id and a display name and nothing else, never the caller, in order of
name. An executive and a lead read it; the picker on the alert set-up chooses the deputy from it.
Another tenant's leads are never in it. Sample values only.
"""

from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.model.people import Practitioner, PractitionerRole
from tests.integration.adapters.inbound.fhir_rest.test_routes_alerts import (
    DEPUTY,
    LEAD,
    NOW,
    alert_world,
    test_container,
)
from tests.support.api import token_headers

__all__ = ["alert_world", "test_container"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

LEADERS = "/fhir/Practitioner"
CLINICAL_LEAD = "prac-clinical-lead"
FORMER = "prac-former-lead"
INACTIVE = "prac-inactive-lead"
REPORTER = "prac-a-coordinator"
B_LEAD = "prac-b-lead"


async def _person(
    factory: UnitOfWorkFactory,
    person: str,
    name: str,
    code: PractitionerRoleCode,
    *,
    active: bool = True,
    ended: bool = False,
) -> None:
    async with factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id=person, active=active, display_name=name, phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id=f"role-{person}",
                practitioner_id=person,
                service_id=None,
                code=code,
                active=True,
                channel=None,
                period_start=NOW - timedelta(days=30),
                period_end=(NOW - timedelta(days=1)) if ended else None,
            )
        )
        await uow.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def leaders_world(
    alert_world: None, uow_factory_a: UnitOfWorkFactory, uow_factory_b: UnitOfWorkFactory
) -> None:
    """On top of alert_world's deputy (an active shift lead named Deputy): a clinical lead, the
    caller (a shift lead), a former shift lead (the role ended), an inactive shift lead, a reporter,
    and a shift lead of the second tenant."""
    await _person(uow_factory_a, CLINICAL_LEAD, "Alex Clinical", PractitionerRoleCode.CLINICAL_LEAD)
    await _person(uow_factory_a, LEAD, "Caller Lead", PractitionerRoleCode.SHIFT_LEAD)
    await _person(uow_factory_a, FORMER, "Former Lead", PractitionerRoleCode.SHIFT_LEAD, ended=True)
    await _person(
        uow_factory_a, INACTIVE, "Inactive Lead", PractitionerRoleCode.SHIFT_LEAD, active=False
    )
    await _person(uow_factory_a, REPORTER, "A Coordinator", PractitionerRoleCode.COORDINATOR)
    await _person(uow_factory_b, B_LEAD, "Other Tenant Lead", PractitionerRoleCode.SHIFT_LEAD)


async def _read(client: AsyncClient, tenant: str, role: Role = Role.LEAD, sub: str = LEAD) -> Any:
    return await client.get(
        LEADERS, params={"role": "leadership"}, headers=token_headers(tenant, role, sub=sub)
    )


def _people(response: Any) -> list[tuple[str, str]]:
    return [
        (entry["resource"]["id"], entry["resource"]["name"][0]["text"])
        for entry in response.json().get("entry", [])
    ]


async def test_a_lead_reads_the_other_leaders_by_name_and_never_themselves(
    api_client: AsyncClient, leaders_world: None, tenant_id: str
) -> None:
    response = await _read(api_client, tenant_id)

    assert response.status_code == 200, response.text
    assert _people(response) == [(CLINICAL_LEAD, "Alex Clinical"), (DEPUTY, "Deputy")]
    assert response.json()["total"] == 2
    assert response.headers["cache-control"] == "no-store"


async def test_an_executive_reads_every_leader_including_the_lead(
    api_client: AsyncClient, leaders_world: None, tenant_id: str
) -> None:
    response = await _read(api_client, tenant_id, Role.EXEC, "prac-exec")

    assert _people(response) == [
        (CLINICAL_LEAD, "Alex Clinical"),
        (LEAD, "Caller Lead"),
        (DEPUTY, "Deputy"),
    ]


async def test_each_entry_holds_an_id_and_a_name_and_nothing_else(
    api_client: AsyncClient, leaders_world: None, tenant_id: str
) -> None:
    response = await _read(api_client, tenant_id)

    for entry in response.json()["entry"]:
        assert set(entry) == {"resource"}
        assert set(entry["resource"]) == {"resourceType", "id", "name"}
        assert set(entry["resource"]["name"][0]) == {"text"}
    for hidden in ("phone", "email", "role", "period", FORMER, INACTIVE, REPORTER):
        assert hidden not in response.text, hidden


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL, Role.REPORTER, Role.OWNER])
async def test_it_is_for_an_executive_or_a_lead_only(
    api_client: AsyncClient, leaders_world: None, tenant_id: str, role: Role
) -> None:
    response = await _read(api_client, tenant_id, role, LEAD)

    assert response.status_code == 404, role


async def test_a_search_that_is_not_for_leadership_is_a_400(
    api_client: AsyncClient, leaders_world: None, tenant_id: str
) -> None:
    for params in ({}, {"role": "reporter"}):
        response = await api_client.get(
            LEADERS, params=params, headers=token_headers(tenant_id, Role.LEAD, sub=LEAD)
        )

        assert response.status_code == 400, params


async def test_the_other_tenants_leaders_are_not_in_the_list_and_ours_are_not_theirs(
    api_client: AsyncClient, leaders_world: None, tenant_id: str, other_tenant_id: str
) -> None:
    mine = await _read(api_client, tenant_id)
    theirs = await _read(api_client, other_tenant_id, Role.EXEC, "prac-b-exec")

    assert B_LEAD not in mine.text
    assert "Other Tenant Lead" not in mine.text
    assert _people(theirs) == [(B_LEAD, "Other Tenant Lead")]
    for answer in (mine, theirs):
        assert answer.status_code == 200
