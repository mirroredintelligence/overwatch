"""The problem report route (W7A-B4, U41) against real Neo4j through the API client.

`POST /help/problems` takes a category, an optional text of at most 280 characters, and whether the
session was shared. The answer is the report's id: never the text. The text is kept in the
protected store, not in the readable graph. A wall screen and an anonymous link are refused (404).
Two tenants: a report is the poster's tenant's, and the same key in the other tenant is another
report. Sample values only.
"""

import pytest
from httpx import AsyncClient

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Role
from tests.integration.adapters.inbound.fhir_rest.test_routes_clinical import (
    clinical_world,
    test_container,
)
from tests.support.api import token_headers

__all__ = ["clinical_world", "test_container"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

PROBLEM = "/help/problems"
TEXT = "The sample board took a long time to load."
BODY = {"category": "screen-slow", "text": TEXT, "sessionShared": True}


def _as(tenant: str, role: Role = Role.REPORTER, sub: str = "prac-reporter") -> dict[str, str]:
    return token_headers(tenant, role, sub=sub)


async def _post(
    client: AsyncClient, tenant: str, key: str, body: dict = BODY, role: Role = Role.REPORTER
) -> object:
    return await client.post(
        PROBLEM, json=body, headers={**_as(tenant, role), "Idempotency-Key": key}
    )


async def test_a_reporter_sends_a_problem_and_the_text_is_not_in_the_answer(
    api_client: AsyncClient,
    clinical_world: None,
    tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    response = await _post(api_client, tenant_id, "problem-0001")

    assert response.status_code == 201, response.text
    report_id = response.json()["id"]
    assert TEXT not in response.text
    async with uow_factory_a() as uow:
        stored = await uow.safety_reports.get(report_id)
        assert stored is not None
        assert stored.category == "screen-slow"
        assert stored.session_shared is True
        assert stored.text_handle is not None
        assert TEXT not in repr(stored)
        assert await uow.protected_text.get(stored.text_handle) == TEXT


async def test_a_report_without_text_is_stored_without_a_handle(
    api_client: AsyncClient,
    clinical_world: None,
    tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
) -> None:
    response = await _post(
        api_client, tenant_id, "problem-0002", {"category": "figure-looks-wrong"}
    )

    assert response.status_code == 201, response.text
    async with uow_factory_a() as uow:
        stored = await uow.safety_reports.get(response.json()["id"])
    assert stored is not None
    assert stored.text_handle is None
    assert stored.session_shared is False


async def test_a_repeat_with_the_same_key_is_the_same_report_and_another_body_is_a_conflict(
    api_client: AsyncClient, clinical_world: None, tenant_id: str
) -> None:
    first = await _post(api_client, tenant_id, "problem-0003")
    again = await _post(api_client, tenant_id, "problem-0003")
    changed = await _post(
        api_client, tenant_id, "problem-0003", {"category": "button-does-not-work"}
    )

    assert first.status_code == 201
    assert again.json() == first.json()
    assert changed.status_code == 422  # the key was used for another body


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL, Role.LEAD, Role.EXEC, Role.OWNER])
async def test_any_signed_in_person_may_report_a_problem(
    api_client: AsyncClient, clinical_world: None, tenant_id: str, role: Role
) -> None:
    response = await _post(api_client, tenant_id, f"problem-role-{role.value}", role=role)

    assert response.status_code == 201, (role, response.text)


@pytest.mark.parametrize("role", [Role.WALL, Role.ANONYMOUS_LINK])
async def test_a_wall_screen_and_an_anonymous_link_are_refused_with_the_404(
    api_client: AsyncClient, clinical_world: None, tenant_id: str, role: Role
) -> None:
    response = await _post(api_client, tenant_id, "problem-0004", role=role)

    assert response.status_code == 404


async def test_a_report_is_its_tenants_and_the_same_key_in_the_other_tenant_is_another_report(
    api_client: AsyncClient,
    clinical_world: None,
    tenant_id: str,
    other_tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    mine = await _post(api_client, tenant_id, "problem-shared-key")
    theirs = await _post(api_client, other_tenant_id, "problem-shared-key")

    assert mine.status_code == 201, mine.text
    assert theirs.status_code == 201, theirs.text
    assert mine.json()["id"] != theirs.json()["id"]
    async with uow_factory_a() as uow:
        assert await uow.safety_reports.get(mine.json()["id"]) is not None
        assert await uow.safety_reports.get(theirs.json()["id"]) is None
    async with uow_factory_b() as uow:
        assert await uow.safety_reports.get(theirs.json()["id"]) is not None
        assert await uow.safety_reports.get(mine.json()["id"]) is None
