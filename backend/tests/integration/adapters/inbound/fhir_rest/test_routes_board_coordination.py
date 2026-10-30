"""The duty coordinator's number on the board answer (W7A-B8, DEC-777) against real Neo4j.

`$board` answers a `coordinationPhone` part when the tenant's configuration holds a coordination
phone (an organisational role number, never a person's). A tenant with none sends no part, and no
number is made up. Another tenant's number is never in this tenant's board. Sample numbers only.
"""

from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Role
from diucs.domain.model.tenant import ContactKind, TenantContact
from tests.support.api import token_headers

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD = "/fhir/HealthcareService/$board"
PHONE_A = "01234 567890"
PHONE_B = "01234 111222"


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def board_state(api_app: Any, clean_graph: None) -> None:
    """The BFF secret the tokens are checked with."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})


def _phone(response: object) -> list[str]:
    return [
        part["valueString"]
        for part in response.json()["parameter"]  # type: ignore[attr-defined]
        if part["name"] == "coordinationPhone"
    ]


async def _set_phone(factory: UnitOfWorkFactory, phone: str, kind: ContactKind) -> None:
    async with factory() as uow:
        await uow.tenant_config.put_contact(TenantContact(kind, "Coordination", phone))
        await uow.commit()


@pytest.mark.parametrize(
    "role", [Role.WALL, Role.ADVISOR, Role.CLINICAL, Role.LEAD, Role.EXEC, Role.OWNER]
)
async def test_every_board_role_reads_the_coordination_phone(
    api_client: AsyncClient,
    clean_graph: None,
    uow_factory_a: UnitOfWorkFactory,
    tenant_id: str,
    role: Role,
) -> None:
    await _set_phone(uow_factory_a, PHONE_A, ContactKind.COORDINATION_PHONE)

    response = await api_client.get(BOARD, headers=token_headers(tenant_id, role, sub="prac-1"))

    assert response.status_code == 200, response.text
    assert _phone(response) == [PHONE_A]


async def test_a_tenant_with_no_coordination_phone_sends_no_part(
    api_client: AsyncClient, clean_graph: None, tenant_id: str
) -> None:
    response = await api_client.get(BOARD, headers=token_headers(tenant_id, Role.LEAD))

    assert response.status_code == 200, response.text
    assert _phone(response) == []
    assert "coordinationPhone" not in response.text


async def test_another_kind_of_contact_is_not_the_coordination_phone(
    api_client: AsyncClient,
    clean_graph: None,
    uow_factory_a: UnitOfWorkFactory,
    tenant_id: str,
) -> None:
    await _set_phone(uow_factory_a, "01234 999000", ContactKind.SHIFT_LEAD_ESCALATION)

    response = await api_client.get(BOARD, headers=token_headers(tenant_id, Role.LEAD))

    assert _phone(response) == []
    assert "01234 999000" not in response.text


async def test_each_tenant_reads_its_own_number_and_never_the_others(
    api_client: AsyncClient,
    clean_graph: None,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _set_phone(uow_factory_a, PHONE_A, ContactKind.COORDINATION_PHONE)
    await _set_phone(uow_factory_b, PHONE_B, ContactKind.COORDINATION_PHONE)

    mine = await api_client.get(BOARD, headers=token_headers(tenant_id, Role.LEAD))
    theirs = await api_client.get(BOARD, headers=token_headers(other_tenant_id, Role.LEAD))

    assert _phone(mine) == [PHONE_A]
    assert _phone(theirs) == [PHONE_B]
    assert PHONE_B not in mine.text
    assert PHONE_A not in theirs.text
