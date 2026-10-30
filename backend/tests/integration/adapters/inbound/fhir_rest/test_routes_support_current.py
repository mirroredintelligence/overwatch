"""The state of the person's support code (W7A-B5, DEC-772) against real Neo4j.

A code is shown once, when it is made; only its hash is stored (O06). So a reload cannot show the
code again, but it can show whether one is live and until when: `GET /support/codes/current` answers
`{"active": true, "expiresAt": ...}` or `{"active": false}`, never the code. Only the person who
shared the session reads it. Two tenants: the same session id shared in the other tenant is another
session, and neither reads the other's state.
"""

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.testing.tokens import issue_test_token
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Role
from diucs.domain.model.people import Practitioner
from tests.integration.adapters.inbound.fhir_rest.test_routes_support import (
    CODE_PATTERN,
    NOW,
    SESSION,
    _create_code,
    _headers,
    client,
    support_app,
)
from tests.support.api import seed_edge_tenants

__all__ = ["client", "support_app"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

CURRENT = f"/support/codes/current?sessionId={SESSION}"
EXPIRES = "2026-10-29T13:00:00Z"  # four hours after the fixed clock


async def _state(
    client: AsyncClient, role: Role = Role.REPORTER, sub: str = "prac-reporter"
) -> Any:
    return await client.get(CURRENT, headers=_headers(role, sub, "k-state"))


async def test_no_code_yet_reads_as_inactive(client: AsyncClient) -> None:
    response = await _state(client)

    assert response.status_code == 200, response.text
    assert response.json() == {"active": False}
    assert response.headers["cache-control"] == "no-store"


async def test_a_live_code_reads_as_active_until_its_end_and_never_shows_the_code(
    client: AsyncClient,
) -> None:
    created = await _create_code(client, key="k-current-1")

    response = await _state(client)

    assert response.json() == {"active": True, "expiresAt": EXPIRES}
    assert created["code"] not in response.text
    assert not CODE_PATTERN.search(response.text)


async def test_a_stopped_code_reads_as_inactive_again(client: AsyncClient) -> None:
    await _create_code(client, key="k-current-2")
    await client.delete(
        CURRENT, headers=_headers(Role.REPORTER, "prac-reporter", "k-current-2-stop")
    )

    response = await _state(client)

    assert response.json() == {"active": False}


async def test_another_person_does_not_read_the_state_of_a_session_they_did_not_share(
    client: AsyncClient,
) -> None:
    await _create_code(client, key="k-current-3")

    response = await _state(client, Role.LEAD, "p-lead")

    assert response.status_code == 200
    assert response.json() == {"active": False}


async def test_the_support_role_cannot_read_it(client: AsyncClient) -> None:
    response = await _state(client, Role.SUPPORT, "prac-support")

    assert response.status_code == 404


async def test_a_session_id_that_is_not_a_session_id_is_a_400(client: AsyncClient) -> None:
    response = await client.get(
        "/support/codes/current?sessionId=not-hex",
        headers=_headers(Role.REPORTER, "prac-reporter", "k-state-bad"),
    )

    assert response.status_code == 400


async def test_the_other_tenants_code_for_the_same_session_id_is_not_this_tenants(
    client: AsyncClient,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    await seed_edge_tenants(neo4j_driver, tenant_id, other_tenant_id)
    async with uow_factory_b() as uow:
        await uow.people.save_practitioner(
            Practitioner(
                id="prac-reporter", active=True, display_name="Sample Reporter", phone_hash=None
            )
        )
        await uow.commit()
    token = issue_test_token(
        Role.REPORTER,
        (),
        "prac-reporter",
        tenant=other_tenant_id,
        expires_at=NOW + timedelta(hours=8),
    )
    b_headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "k-b-code"}
    body = {"sessionId": SESSION, "deviceType": "phone", "appMode": "browser", "release": "1.4.2"}
    made = await client.post("/support/codes", json=body, headers=b_headers)
    assert made.status_code == 201, made.text

    mine = await _state(client)
    theirs = await client.get(CURRENT, headers={**b_headers, "Idempotency-Key": "k-b-state"})

    assert mine.json() == {"active": False}
    assert theirs.json() == {"active": True, "expiresAt": EXPIRES}
