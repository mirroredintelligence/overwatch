"""The one-tap capacity link pages' API (L01, DEC-167), through the real app on the real Neo4j.

The first eight tests are the ones the task prompt lists. The rest pin what makes a bearer token
sent by text safe to leave open to the world: the tenant comes from the host and nowhere else, every
failure has one fixed body, nothing is read before the CSRF token is checked, and neither a token, a
hash, a figure nor an address is ever in a body, a header or a log. These tests run with no tenant
bound: the route must bind it. Values are synthetic: no patient data.
"""

import json
import logging
import re
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.link_pages.capacity_links import (
    LINK_PAGE_PATH,
    SEND_THE_NUMBER_TEXT,
    LinkPagesDeps,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.use_cases import link_access
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import ReportSource, ReportType
from diucs.domain.model.tenant import TenantStatus
from tests.integration.adapters.inbound.link_pages.conftest import client_for, seed_tenant_host
from tests.support.ladder_rig import SECRET, london
from tests.support.link_rig import (
    ANSWER_AT,
    BASE_URL_A,
    HOST_A,
    REPLY_BY,
    LinkRig,
    token_hash_of,
)

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.no_tenant]

EXPIRED_BODY = {"state": "expired"}


async def _prompted(links: LinkRig, **seed: Any) -> str:
    """The service, its reporter, a figure of 3 as of 08:15 and the link of the 10:00 prompt. The
    clock is left at 10:05, inside the reply window."""
    await links.seed(**seed)
    token = await links.prompt()
    links.clock.set(ANSWER_AT)
    return token


def _post(client: AsyncClient, token: str, body: Any, links: LinkRig, **headers: str) -> Any:
    sent = {"X-CSRF-Token": links.csrf(token), **headers}
    return client.post(f"/links/{token}", json=body, headers=sent)


def _no_trace(response: Response, *secrets: str) -> None:
    """Nothing the caller must not learn is in the response: a secret, the hash or the CSRF token of
    a link, and the usual wording of a service or an error text from the server."""
    text = response.text + "".join(f"{k}: {v}" for k, v in response.headers.items())
    for secret in secrets:
        assert secret not in text
    assert "Traceback" not in text and "OperationOutcome" not in text


# -- the eight tests of the prompt -----------------------------------------------------------------


async def test_a_fresh_link_shows_ucr_west_with_3_as_of_0815_and_changes_nothing(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _prompted(links)
    before = await links.counts()

    response = await link_client.get(f"/links/{token}")

    assert response.status_code == 200
    assert response.json() == {
        "state": "ok",
        "purpose": "capacity-reply",
        "serviceName": "UCR West",
        "unitLabel": "referrals in the next 2 hrs",
        "recordedValue": 3,
        "asOf": "2026-10-23T07:15:00Z",
        "usualMin": 0,
        "usualMax": 8,
        "replyBy": "2026-10-23T09:30:00Z",
        "nextDue": "2026-10-23T11:00:00Z",
        "csrfToken": links.csrf(token),
    }
    assert response.headers["content-type"] == "application/json"
    assert await links.counts() == before  # no Observation, no audit entry, nothing
    node = await links.token_node(token)
    assert "usedAt" not in node  # the token is not used


async def test_a_confirm_with_the_right_csrf_token_records_a_confirmed_figure_and_burns_the_link(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _prompted(links)

    response = await _post(link_client, token, {"action": "confirm"}, links)

    assert response.status_code == 200
    assert response.json() == {
        "serviceName": "UCR West",
        "value": 3,
        "unitLabel": "referrals in the next 2 hrs",
        "recordedAt": "2026-10-23T09:05:00Z",
        "nextDue": "2026-10-23T11:00:00Z",
    }
    latest = await links.latest()
    assert (latest.report_type, latest.source) == (ReportType.CONFIRMED, ReportSource.LINK)
    assert (await links.token_node(token))["usedAt"] is not None


async def test_a_post_without_a_csrf_token_is_403_and_records_nothing(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _prompted(links)
    before = await links.counts()

    response = await link_client.post(f"/links/{token}", json={"action": "confirm"})

    assert response.status_code == 403
    assert response.json() == {"state": "forbidden"}
    assert await links.counts() == before


async def test_a_second_post_is_410_used(link_client: AsyncClient, links: LinkRig) -> None:
    token = await _prompted(links)
    assert (
        await _post(link_client, token, {"action": "number", "value": 5}, links)
    ).status_code == 200
    before = await links.counts()

    response = await _post(link_client, token, {"action": "number", "value": 6}, links)

    assert response.status_code == 410
    assert response.json() == {"state": "used"}
    assert await links.counts() == before


async def test_a_get_after_the_reply_by_time_is_410_expired_with_no_service_name(
    link_client: AsyncClient, links: LinkRig, link_clock: FixedClock
) -> None:
    token = await _prompted(links)
    link_clock.set(REPLY_BY)

    response = await link_client.get(f"/links/{token}")

    assert response.status_code == 410
    assert response.json() == EXPIRED_BODY
    assert "UCR" not in response.text


async def test_an_unknown_token_gets_the_same_410_body_as_an_expired_one(
    link_client: AsyncClient, links: LinkRig, link_clock: FixedClock
) -> None:
    token = await _prompted(links)
    link_clock.set(REPLY_BY)
    expired = await link_client.get(f"/links/{token}")

    unknown = await link_client.get(f"/links/{'A' * 23}")

    assert (unknown.status_code, unknown.content) == (expired.status_code, expired.content)
    assert dict(unknown.headers) == dict(expired.headers)


async def test_a_number_outside_the_usual_range_is_422_and_is_recorded_when_confirmed(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _prompted(links)
    before = await links.counts()

    refused = await _post(link_client, token, {"action": "number", "value": 40}, links)

    assert refused.status_code == 422
    assert refused.json() == {"state": "out-of-range", "usualMin": 0, "usualMax": 8}
    assert await links.counts() == before

    recorded = await _post(
        link_client,
        token,
        {"action": "number", "value": 40, "confirmOutOfRange": True},
        links,
    )

    assert recorded.status_code == 200
    assert recorded.json()["value"] == 40
    assert (await links.latest()).value == 40


async def test_a_renew_is_202_and_queues_one_c1_in_the_outbox(
    link_client: AsyncClient, links: LinkRig, link_clock: FixedClock
) -> None:
    token = await _prompted(links)
    link_clock.set(REPLY_BY + timedelta(minutes=3))
    before = [m.id for m in await links.rig.events("SendMessage")]

    response = await link_client.post(f"/links/{token}/renew")

    assert response.status_code == 202
    assert response.json() == {"state": "accepted"}
    queued = [m for m in await links.rig.events("SendMessage") if m.id not in before]
    assert [m.payload["message_id"] for m in queued] == ["C1"]
    text = str(links.rig.opened(queued[0])["text"])
    assert f"{BASE_URL_A}/" in text and LINK_PAGE_PATH == "/l"


# -- the answers a button can get ------------------------------------------------------------------


async def test_a_y_that_cannot_be_used_is_409_please_send_the_number_and_the_link_stays_open(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _prompted(links, figure_at=london(7, 30))  # too old to confirm at 10:00 (H-31)
    before = await links.counts()

    response = await _post(link_client, token, {"action": "confirm"}, links)

    assert response.status_code == 409
    assert response.json() == {
        "state": "send-number",
        "reason": "stale",
        "message": SEND_THE_NUMBER_TEXT,
    }
    assert SEND_THE_NUMBER_TEXT == "Please send the number"
    assert await links.counts() == before
    assert (
        await _post(link_client, token, {"action": "number", "value": 4}, links)
    ).status_code == 200


async def test_a_third_y_in_a_row_is_409_with_the_limit(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _prompted(links)
    await links.text_confirm("confirm-1", london(10, 1))
    await links.text_confirm("confirm-2", london(10, 2))
    links.clock.set(ANSWER_AT)

    response = await _post(link_client, token, {"action": "confirm"}, links)

    assert response.status_code == 409
    assert response.json()["reason"] == "limit"


async def test_closed_records_the_figure_zero(link_client: AsyncClient, links: LinkRig) -> None:
    token = await _prompted(links)

    response = await _post(link_client, token, {"action": "closed"}, links)

    assert response.status_code == 200
    assert response.json()["value"] == 0


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"[]",
        b'"confirm"',
        b"null",
        b"{}",
        b'{"action": 5}',
        b'{"action": "approve"}',
        b'{"action": "number"}',
        b'{"action": "number", "value": 3.5}',
        b'{"action": "number", "value": "3"}',
        b'{"action": "number", "value": 1000}',
        b'{"action": "number", "value": -1}',
        b'{"action": "number", "value": true}',
        b'{"action": "confirm", "value": 3}',
        b'{"action": "closed", "value": 0}',
        b'{"action": "number", "value": 4, "confirmOutOfRange": "yes"}',
        b'{"action": "confirm", "confirmOutOfRange": true}',
        b'{"action": "confirm", "tenantId": "someone-else"}',
        b'{"action": "confirm", "tenant": "someone-else"}',
        b'{"action": "confirm", "extra": 1}',
        b'{"action": "confirm", "pad": "' + b"x" * 2000 + b'"}',
    ],
)
async def test_a_malformed_answer_is_400_invalid_and_changes_nothing(
    link_client: AsyncClient, links: LinkRig, raw: bytes
) -> None:
    token = await _prompted(links)
    before = await links.counts()

    response = await link_client.post(
        f"/links/{token}",
        content=raw,
        headers={"X-CSRF-Token": links.csrf(token), "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {"state": "invalid"}
    _no_trace(response, token)
    assert await links.counts() == before


async def test_a_body_without_a_length_that_grows_past_the_limit_is_refused(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _prompted(links)

    async def chunks() -> Any:
        yield b'{"action": "confirm", "pad": "'
        for _ in range(8):
            yield b"x" * 512
        yield b'"}'

    response = await link_client.post(
        f"/links/{token}",
        content=chunks(),
        headers={"X-CSRF-Token": links.csrf(token), "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert (await links.latest()).report_type is ReportType.NUMBER


async def test_a_content_length_that_is_not_a_number_is_refused(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _prompted(links)

    response = await link_client.post(
        f"/links/{token}",
        content=b'{"action": "confirm"}',
        headers={
            "X-CSRF-Token": links.csrf(token),
            "Content-Type": "application/json",
            "Content-Length": "12abc",
        },
    )

    assert response.status_code == 400
    assert (await links.latest()).report_type is ReportType.NUMBER


@pytest.mark.parametrize(
    "token",
    ["A" * 23, "A" * 22, "x" * 300, "bad%20token", "bad.token", "a-b_c" * 4],
)
async def test_every_kind_of_unknown_token_gets_the_one_expired_answer(
    link_client: AsyncClient, links: LinkRig, token: str
) -> None:
    await links.seed()

    got = await link_client.get(f"/links/{token}")
    posted = await link_client.post(
        f"/links/{token}", json={"action": "confirm"}, headers={"X-CSRF-Token": "0" * 64}
    )
    renewed = await link_client.post(f"/links/{token}/renew")

    assert (got.status_code, got.json()) == (410, EXPIRED_BODY)
    assert posted.status_code == 403  # the CSRF token of an unknown link cannot be right
    assert (renewed.status_code, renewed.json()) == (202, {"state": "accepted"})


# -- the tenant: from the host, and nowhere else ---------------------------------------------------


async def test_a_host_the_directory_does_not_know_answers_as_an_unknown_link(
    link_app: FastAPI, links: LinkRig, hosts: None
) -> None:
    token = await _prompted(links)
    async with client_for(link_app, "charlie.example.org") as client:
        got = await client.get(f"/links/{token}")
        posted = await _post(client, token, {"action": "confirm"}, links)
        renewed = await client.post(f"/links/{token}/renew")

    assert (got.status_code, got.json()) == (410, EXPIRED_BODY)
    assert posted.status_code == 403
    assert renewed.status_code == 202
    assert (await links.latest()).report_type is ReportType.NUMBER


@pytest.mark.parametrize(
    "status", [TenantStatus.SUSPENDED, TenantStatus.PROVISIONING, TenantStatus.OFFBOARDING]
)
async def test_a_tenant_that_is_not_active_does_not_serve_links(
    link_app: FastAPI,
    links: LinkRig,
    neo4j_driver: Any,
    tenant_id: str,
    status: TenantStatus,
) -> None:
    token = await _prompted(links)
    await seed_tenant_host(neo4j_driver, tenant_id, "dormant.example.org", status)
    async with client_for(link_app, "dormant.example.org") as client:
        got = await client.get(f"/links/{token}")

    assert (got.status_code, got.json()) == (410, EXPIRED_BODY)


async def test_the_host_is_read_without_its_port_and_in_lower_case(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _prompted(links)

    response = await link_client.get(f"/links/{token}", headers={"Host": f"{HOST_A.upper()}:8443"})

    assert response.status_code == 200


async def test_a_damaged_tenant_record_fails_closed_as_an_unknown_link(
    link_app: FastAPI, links: LinkRig, neo4j_driver: Any, tenant_id: str, hosts: None
) -> None:
    token = await _prompted(links)
    await seed_tenant_host(
        neo4j_driver, "damaged-tenant", "damaged.example.org", damage={"status": "bogus"}
    )

    async with client_for(link_app, "damaged.example.org") as client:
        response = await client.get(f"/links/{token}")

    assert (response.status_code, response.json()) == (410, EXPIRED_BODY)


# -- what the responses and the logs never hold ----------------------------------------------------


async def test_every_answer_is_not_stored_not_cached_and_sends_no_referrer(
    link_client: AsyncClient, links: LinkRig
) -> None:
    token = await _prompted(links)

    answers = [
        await link_client.get(f"/links/{token}"),
        await link_client.get(f"/links/{'A' * 23}"),
        await link_client.post(f"/links/{token}", json={"action": "confirm"}),
        await _post(link_client, token, {"action": "number", "value": 40}, links),
        await _post(link_client, token, {"action": "confirm"}, links),
        await _post(link_client, token, {"action": "confirm"}, links),
        await link_client.post(f"/links/{token}/renew"),
    ]

    assert [a.status_code for a in answers] == [200, 410, 403, 422, 200, 410, 202]
    for answer in answers:
        assert answer.headers["cache-control"] == "no-store"
        assert answer.headers["referrer-policy"] == "no-referrer"
        assert answer.headers["x-content-type-options"] == "nosniff"
        _no_trace(answer, token, token_hash_of(token))
    assert links.csrf(token) not in "".join(a.text for a in answers[1:])  # only the page shows it


async def test_no_token_hash_figure_or_address_reaches_a_log(
    link_client: AsyncClient,
    links: LinkRig,
    caplog: pytest.LogCaptureFixture,
    link_clock: FixedClock,
) -> None:
    token = await _prompted(links)
    caplog.set_level(logging.DEBUG, logger="diucs")

    await link_client.get(f"/links/{token}")
    await link_client.get(f"/links/{'A' * 23}")
    await link_client.post(f"/links/{token}", json={"action": "confirm"})
    await _post(link_client, token, {"action": "number", "value": 407}, links)
    await _post(
        link_client, token, {"action": "number", "value": 407, "confirmOutOfRange": True}, links
    )
    link_clock.set(REPLY_BY + timedelta(minutes=3))
    await link_client.post(f"/links/{token}/renew")
    await link_client.get("/links/anything", headers={"Host": "charlie.example.org"})

    # What the test's own client logs (the URL it asked for) is not the app's log.
    text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith(("httpx", "httpcore"))
    )
    for secret in (token, token_hash_of(token), links.csrf(token), "A" * 23, "407", "198.51.100"):
        assert secret not in text
    assert "127.0.0.1" not in text


async def test_a_failure_the_page_did_not_expect_is_a_fixed_500_and_no_detail(
    link_container: Container, link_cache: Any, links: LinkRig, hosts: None
) -> None:
    token = await _prompted(links)
    # The CSRF secret is missing: a configuration fault, which must not be a different answer.
    broken = build_for_tests(
        clock=link_container.clock,
        ids=link_container.ids,
        neo4j=link_container.neo4j,
        secrets=FixedSecretStore({LINK_TOKEN_SECRET: SECRET}),
    )
    app = create_app(broken)
    app.state.link_pages = LinkPagesDeps(cache=link_cache, sealer=links.sealer)

    async with client_for(app) as client:
        response = await client.get(f"/links/{token}")

    assert (response.status_code, response.json()) == (500, {"state": "error"})
    _no_trace(response, token, "link-csrf")


async def test_an_app_with_no_link_pages_configured_refuses_every_request(
    link_container: Container, links: LinkRig, hosts: None
) -> None:
    token = await _prompted(links)
    app = create_app(link_container)  # app.state.link_pages is not set

    async with client_for(app) as client:
        response = await client.get(f"/links/{token}")

    assert (response.status_code, response.json()) == (500, {"state": "error"})


# -- limits ----------------------------------------------------------------------------------------


async def test_a_tenant_over_its_budget_gets_429_with_retry_after(
    link_client: AsyncClient, links: LinkRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(link_access, "REQUESTS_PER_WINDOW", 2)
    token = await _prompted(links)

    statuses = [(await link_client.get(f"/links/{token}")).status_code for _ in range(3)]
    limited = await link_client.get(f"/links/{token}")

    assert statuses == [200, 200, 429]
    assert limited.status_code == 429
    assert limited.json() == {"state": "rate-limited"}
    assert limited.headers["retry-after"] == "60"


# -- the app ---------------------------------------------------------------------------------------


async def test_the_link_routes_are_mounted_on_the_fhir_app_and_the_methods_are_fixed(
    link_client: AsyncClient,
) -> None:
    allowed = {"GET": "/links/x", "POST": "/links/x"}
    assert (await link_client.request("DELETE", "/links/x")).status_code == 405
    assert (await link_client.request("PATCH", "/links/x")).status_code == 405
    assert allowed and re.fullmatch(r"/links/[a-z]", allowed["GET"])
    assert json.loads((await link_client.get("/health")).text) == {"status": "ok"}
