"""The check-in page's API (DEC-1346), through the real app on the real Neo4j.

The use cases are tested in tests/integration/application/test_service_checkin.py; these tests pin
what the route adds: the tenant comes from the host, a write needs the CSRF token, the answer to
"text me a code" is the same for every number, and every failure has one fixed body. They run with
no tenant bound: the route must bind it. Values are synthetic."""

import pytest
from httpx import AsyncClient

from overwatch.application.actor import Actor
from overwatch.application.use_cases.service_checkin import IssueServiceCheckIn
from overwatch.domain.codes import Role
from overwatch.domain.model.people import Practitioner
from tests.support.link_rig import LinkRig

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.no_tenant]

GONE = {"state": "gone"}


async def _code(links: LinkRig) -> str:
    """The service, and the printed code a lead makes for it."""
    await links.seed()
    async with links.factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-lead", active=True, display_name="Shift lead", phone_hash=None)
        )
        await uow.commit()
    lead = Actor(
        role=Role.LEAD,
        practitioner_id="prac-lead",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=links.tenant,
    )
    return await IssueServiceCheckIn(links.factory, links.clock, links.secrets).execute(
        lead, links.service_id
    )


async def test_a_printed_code_names_its_service_and_gives_the_page_a_csrf_token(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _code(links)

    response = await link_client.get(f"/checkin/{token}")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "UCR West"
    assert body["csrfToken"] == links.csrf(token)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert token not in response.text


async def test_a_code_of_one_tenant_is_gone_on_the_host_of_another(
    other_client: AsyncClient, links: LinkRig
) -> None:
    token = await _code(links)

    response = await other_client.get(f"/checkin/{token}")

    assert (response.status_code, response.json()) == (410, GONE)


async def test_an_unknown_code_is_gone(link_client: AsyncClient, links: LinkRig) -> None:
    await _code(links)

    response = await link_client.get(f"/checkin/{'A' * 23}")

    assert (response.status_code, response.json()) == (410, GONE)


async def test_a_write_without_the_csrf_token_is_forbidden(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _code(links)

    code = await link_client.post(f"/checkin/{token}/code", json={"mobile": "07700 900111"})
    confirm = await link_client.post(
        f"/checkin/{token}/confirm",
        json={"mobile": "07700 900111", "code": "123456", "action": "on"},
    )

    assert (code.status_code, code.json()) == (403, {"state": "forbidden"})
    assert (confirm.status_code, confirm.json()) == (403, {"state": "forbidden"})


async def test_asking_for_a_code_answers_the_same_for_a_number_that_is_not_on_the_roster(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _code(links)

    response = await link_client.post(
        f"/checkin/{token}/code",
        json={"mobile": "07700 900999"},
        headers={"X-CSRF-Token": links.csrf(token)},
    )

    assert (response.status_code, response.json()) == (202, {"state": "sent"})
    assert "07700" not in response.text and token not in response.text


async def test_a_wrong_code_is_403_with_a_fixed_body(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _code(links)

    response = await link_client.post(
        f"/checkin/{token}/confirm",
        json={"mobile": "07700 900999", "code": "000000", "action": "on"},
        headers={"X-CSRF-Token": links.csrf(token)},
    )

    assert (response.status_code, response.json()) == (403, {"state": "code-wrong"})


async def test_a_body_with_a_field_the_page_does_not_take_is_invalid(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _code(links)

    response = await link_client.post(
        f"/checkin/{token}/code",
        json={"mobile": "07700 900111", "extra": 1},
        headers={"X-CSRF-Token": links.csrf(token)},
    )

    assert (response.status_code, response.json()) == (400, {"state": "invalid"})
