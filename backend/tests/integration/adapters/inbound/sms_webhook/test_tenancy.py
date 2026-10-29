"""Tenant isolation of the Twilio webhook (I07, DEC-130, DEC-131).

The number called and the AccountSid pick the subaccount whose token verifies the signature; only a
verified request binds a tenant, and nothing the caller controls can change which one. Refusals do
not say whether a number or an account exists.

Tenant-pending: the allow-list statement (Q-PERSON-PHONE-FIND) is not converted yet, so the person
lookup is not filtered by tenant in Neo4j. What these tests prove is the edge: the tenant is bound
for that read, and a queue message, a replay marker and a verification never cross tenants.
"""

import dataclasses
from collections.abc import Awaitable, Callable

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from neo4j import AsyncDriver

from diucs.adapters.inbound.sms_webhook.routes import SmsWebhookDeps
from diucs.adapters.testing.fixed_inbound_lines import FixedInboundLines
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET
from diucs.application.ports.outbound.tenant_lines import InboundLine
from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.application.tenancy import ScopeId, current_scope_or_none
from diucs.bootstrap.container import Container
from tests.integration.adapters.inbound.sms_webhook.conftest import seed_practitioner
from tests.support.sms import (
    INTERNAL_REPLY_URL,
    PHONE_HASH_KEY,
    SENDER_E164,
    TENANT_A,
    TENANT_B,
    post_signed,
    reply_params,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

SID = "SM" + "1" * 32
# Tenant B's own reporter. The person lookup (Q-PERSON-PHONE-FIND) is not converted yet and finds a
# phone across tenants, so one number held in both tenants would be ambiguous (Conflict); each
# tenant has its own reporter with its own number until TEN-011 (known-issues).
SENDER_B_E164 = "+447700900789"
QUEUE = "inbound.replies"


async def test_the_number_called_decides_the_tenant_of_the_queue_message(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None, neo4j_driver: AsyncDriver
) -> None:
    # A reporter of each organisation texts that organisation's number (DEC-131 item 3).
    await seed_practitioner(neo4j_driver, "p-reporter-b", SENDER_B_E164, TENANT_B.tenant_id)
    to_a = await post_signed(sms_client, reply_params(TENANT_A, sid=SID))
    to_b = await post_signed(
        sms_client, reply_params(TENANT_B, sid=SID, sender=SENDER_B_E164), token=TENANT_B.token
    )

    assert (to_a.status_code, to_b.status_code) == (200, 200)
    queued = {message.tenant_id: message for message in sms_bus.enqueued_to(QUEUE)}
    assert set(queued) == {"tenant-a", "tenant-b"}
    assert queued["tenant-a"].payload["provider_message_id"] == SID
    assert queued["tenant-b"].payload["provider_message_id"] == SID


async def test_the_same_message_sid_in_two_tenants_is_not_a_replay_but_a_repeat_is(
    sms_client: AsyncClient,
    sms_bus: ManualEventBus,
    sms_cache: InMemoryCache,
    reporter: None,
    neo4j_driver: AsyncDriver,
) -> None:
    await seed_practitioner(neo4j_driver, "p-reporter-b", SENDER_B_E164, TENANT_B.tenant_id)
    params_b = reply_params(TENANT_B, sid=SID, sender=SENDER_B_E164)
    await post_signed(sms_client, reply_params(TENANT_A, sid=SID))
    await post_signed(sms_client, params_b, token=TENANT_B.token)
    await post_signed(sms_client, reply_params(TENANT_A, sid=SID))
    await post_signed(sms_client, params_b, token=TENANT_B.token)

    tenants = sorted(str(m.tenant_id) for m in sms_bus.enqueued_to(QUEUE))
    assert tenants == ["tenant-a", "tenant-b"]
    assert await sms_cache.get(f"idem:sms:tenant-a:{SID}") == "1"
    assert await sms_cache.get(f"idem:sms:tenant-b:{SID}") == "1"


async def test_a_tenant_in_the_body_a_header_or_the_host_changes_nothing(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    params = {
        **reply_params(TENANT_A, sid=SID),
        "tenantId": "tenant-b",
        "tenant": "tenant-b",
        "TenantId": "tenant-b",
    }
    response = await post_signed(
        sms_client,
        params,
        headers={
            "X-Tenant-Id": "tenant-b",
            "X-Tenant": "tenant-b",
            "X-Forwarded-Host": "tenant-b.diucs.example",
            "Host": "tenant-b.diucs.example",
            "Authorization": "Bearer tenant-b",
        },
    )

    assert response.status_code == 200
    [queued] = sms_bus.enqueued_to(QUEUE)
    assert queued.tenant_id == "tenant-a"
    assert "tenantId" not in queued.payload


async def test_a_signature_made_with_the_other_tenants_token_is_refused_on_both_numbers(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    a_with_b = await post_signed(sms_client, reply_params(TENANT_A, sid=SID), token=TENANT_B.token)
    b_with_a = await post_signed(sms_client, reply_params(TENANT_B, sid=SID), token=TENANT_A.token)

    assert (a_with_b.status_code, b_with_a.status_code) == (403, 403)
    assert sms_bus.enqueued_to(QUEUE) == []


async def test_a_number_under_the_other_tenants_account_is_refused(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    # B's number with A's AccountSid, signed with A's token (which a caller could not hold) and
    # with B's: neither names a line.
    params = {**reply_params(TENANT_B, sid=SID), "AccountSid": TENANT_A.account_sid}
    with_a = await post_signed(sms_client, params, token=TENANT_A.token)
    with_b = await post_signed(sms_client, params, token=TENANT_B.token)

    assert (with_a.status_code, with_b.status_code) == (403, 403)
    assert sms_bus.enqueued_to(QUEUE) == []


def _refusal_cases() -> dict[str, Callable[[AsyncClient], Awaitable[Response]]]:
    async def unknown_number(client: AsyncClient) -> Response:
        params = {**reply_params(TENANT_A, sid=SID), "To": "+447700900777"}
        return await post_signed(client, params, token=TENANT_A.token)

    async def unknown_account(client: AsyncClient) -> Response:
        params = {**reply_params(TENANT_A, sid=SID), "AccountSid": "AC" + "7" * 32}
        return await post_signed(client, params, token=TENANT_A.token)

    async def wrong_account_for_number(client: AsyncClient) -> Response:
        params = {**reply_params(TENANT_A, sid=SID), "AccountSid": TENANT_B.account_sid}
        return await post_signed(client, params, token=TENANT_B.token)

    async def bad_signature(client: AsyncClient) -> Response:
        return await post_signed(client, reply_params(TENANT_A, sid=SID), token=b"wrong")

    async def no_signature(client: AsyncClient) -> Response:
        return await client.post(INTERNAL_REPLY_URL, data=reply_params(TENANT_A, sid=SID))

    async def no_to(client: AsyncClient) -> Response:
        params = reply_params(TENANT_A, sid=SID)
        del params["To"]
        return await post_signed(client, params, token=TENANT_A.token)

    async def no_account(client: AsyncClient) -> Response:
        params = reply_params(TENANT_A, sid=SID)
        del params["AccountSid"]
        return await post_signed(client, params, token=TENANT_A.token)

    async def malformed_fields(client: AsyncClient) -> Response:
        params = {**reply_params(TENANT_A, sid=SID), "To": "not a number", "AccountSid": "AC 1"}
        return await post_signed(client, params, token=TENANT_A.token)

    return {
        "unknown-number": unknown_number,
        "unknown-account": unknown_account,
        "wrong-account-for-number": wrong_account_for_number,
        "bad-signature": bad_signature,
        "no-signature": no_signature,
        "no-to": no_to,
        "no-account": no_account,
        "malformed-fields": malformed_fields,
    }


async def test_every_refusal_looks_the_same_so_nothing_says_which_numbers_or_tenants_exist(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    seen: dict[str, tuple[int, dict[str, str], str]] = {}
    for name, send in _refusal_cases().items():
        response = await send(sms_client)
        seen[name] = (response.status_code, dict(response.headers), response.text)

    assert {outcome[0] for outcome in seen.values()} == {403}
    assert len({repr(outcome) for outcome in seen.values()}) == 1, seen
    assert "tenant" not in repr(seen).lower()
    assert sms_bus.enqueued_to(QUEUE) == []


async def test_no_unit_of_work_is_opened_for_a_request_that_is_refused(
    sms_app: FastAPI, sms_client: AsyncClient, test_container: Container, reporter: None
) -> None:
    opened: list[object] = []

    def counting() -> UnitOfWork:
        opened.append(current_scope_or_none())
        return test_container.uow_factory()

    sms_app.state.container = dataclasses.replace(test_container, uow_factory=counting)

    for send in _refusal_cases().values():
        await send(sms_client)
    assert opened == []

    await post_signed(sms_client, reply_params(TENANT_A, sid=SID))
    assert opened == [ScopeId.tenant("tenant-a")]


async def test_the_tenant_is_bound_for_the_allow_list_read_and_the_scope_is_restored_afterwards(
    sms_app: FastAPI, sms_client: AsyncClient, test_container: Container, reporter: None
) -> None:
    # The harness may bind a run tenant for the whole test (TEN-003); what must hold is that the
    # webhook's own binding does not leak, so the scope after is the scope before.
    before = current_scope_or_none()
    bound: list[ScopeId | None] = []

    def watching() -> UnitOfWork:
        bound.append(current_scope_or_none())
        return test_container.uow_factory()

    sms_app.state.container = dataclasses.replace(test_container, uow_factory=watching)

    await post_signed(sms_client, reply_params(TENANT_A, sid=SID))
    await post_signed(sms_client, reply_params(TENANT_B, sid=SID), token=TENANT_B.token)

    assert bound == [ScopeId.tenant("tenant-a"), ScopeId.tenant("tenant-b")]
    assert current_scope_or_none() == before


async def test_a_line_whose_tenant_id_is_not_valid_is_refused_like_an_unknown_number(
    sms_app: FastAPI, sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    deps: SmsWebhookDeps = sms_app.state.sms_webhook
    bad = InboundLine("Not A Tenant!", TENANT_A.token_secret)
    sms_app.state.sms_webhook = dataclasses.replace(
        deps, lines=FixedInboundLines([(TENANT_A.number, TENANT_A.account_sid, bad)])
    )

    response = await post_signed(sms_client, reply_params(TENANT_A, sid=SID))

    assert (response.status_code, response.text) == (403, "Forbidden")
    assert sms_bus.enqueued_to(QUEUE) == []


async def test_a_line_whose_token_secret_is_missing_is_refused_like_an_unknown_number(
    sms_app: FastAPI, sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    deps: SmsWebhookDeps = sms_app.state.sms_webhook
    sms_app.state.sms_webhook = dataclasses.replace(
        deps, secrets=FixedSecretStore({PHONE_HASH_SECRET: PHONE_HASH_KEY})
    )

    response = await post_signed(sms_client, reply_params(TENANT_A, sid=SID))

    assert (response.status_code, response.text) == (403, "Forbidden")
    assert sms_bus.enqueued_to(QUEUE) == []


async def test_the_sender_number_is_not_what_picks_the_tenant(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    # A text from a sender that is also the other tenant's number still goes by `To`.
    params = reply_params(TENANT_A, sid=SID, sender=TENANT_B.number)
    await post_signed(sms_client, params)
    assert sms_bus.enqueued_to(QUEUE) == []  # not an allow-listed reporter, and never tenant-b

    params = reply_params(TENANT_A, sid="SM" + "5" * 32, sender=SENDER_E164)
    await post_signed(sms_client, params)
    assert [m.tenant_id for m in sms_bus.enqueued_to(QUEUE)] == ["tenant-a"]
