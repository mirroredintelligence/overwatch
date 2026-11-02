"""A text to the platform's shared line identifies no tenant (DEC-1319, DEC-131).

The shared line is outgoing only: its number is the platform's, never a tenant's, so it is on no
`TenantNumber` registry node and the inbound webhook can find no tenant for it. This builds the real
webhook over the real `DirectoryInboundLines`, on a directory that answers only what the registry
would (an active number of a tenant, with the account that carries it), and checks that a text to
the shared number, signed with the platform's own token or a tenant's, is the same 403 as an unknown
number, binds nothing and queues nothing. The registry statements themselves are in
`tests/integration/graph_store/test_tenant_directory.py`. Every value is invented.
"""

import base64
import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from overwatch.adapters.inbound.sms_webhook.routes import (
    REPLY_PATH,
    STATUS_PATH,
    SmsWebhookDeps,
    router,
)
from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.adapters.testing.memory_cache import InMemoryCache
from overwatch.adapters.testing.memory_event_bus import ManualEventBus
from overwatch.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from overwatch.application.ports.outbound.tenants import TenantLine, twilio_token_ref
from overwatch.application.tenant_resolution import DirectoryInboundLines
from overwatch.bootstrap.tenant_senders import PLATFORM_SMS_TOKEN_SECRET
from tests.support.tenant_samples import SAMPLE_ID, make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

BASE = "https://overwatch.example.test"
OWN = "+447700900123"
OWN_SID = "AC" + "1" * 32
OWN_TOKEN = b"token-of-the-tenants-own-subaccount-01"
SHARED = "+447700900000"
PLATFORM_SID = "AC" + "9" * 32
PLATFORM_TOKEN = b"token-of-the-platform-account-0123456"
FORM = {"content-type": "application/x-www-form-urlencoded"}


class _RegistryDirectory:
    """Answers as the registry does: only a tenant's own ACTIVE number, with its own account. The
    shared number is on no node, so it is never answered, whatever account is asked about."""

    def __init__(self) -> None:
        self._line = TenantLine(
            tenant=make_tenant(),
            number=OWN,
            account_sid=OWN_SID,
            secret_ref=twilio_token_ref(SAMPLE_ID),
        )
        self.asked: list[tuple[str, str]] = []

    async def by_inbound_number(self, to_number: str, account_sid: str) -> TenantLine | None:
        self.asked.append((to_number, account_sid))
        held = (to_number, account_sid) == (self._line.number, self._line.account_sid)
        return self._line if held else None

    async def by_account_sid(self, account_sid: str) -> TenantLine | None:
        return self._line if account_sid == self._line.account_sid else None


class _NobodyOnTheList:
    """A unit of work whose allow-list holds nobody: a verified text is dropped, not queued."""

    def __init__(self) -> None:
        async def nobody(phone_hash: str) -> None:
            return None

        self.people = SimpleNamespace(find_by_phone_hash=nobody)

    async def __aenter__(self) -> _NobodyOnTheList:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _sign(url: str, params: Mapping[str, str], token: bytes) -> str:
    data = url + "".join(name + params[name] for name in sorted(params))
    return base64.b64encode(hmac.new(token, data.encode(), hashlib.sha1).digest()).decode()


class _Rig:
    def __init__(self) -> None:
        clock = FixedClock(datetime(2026, 11, 2, 9, 0, tzinfo=UTC))
        self.directory = _RegistryDirectory()
        self.bus = ManualEventBus(clock)
        secrets = FixedSecretStore(
            {
                PHONE_HASH_SECRET: b"unit-test-phone-hash-key",
                twilio_token_ref(SAMPLE_ID): OWN_TOKEN,
                PLATFORM_SMS_TOKEN_SECRET: PLATFORM_TOKEN,
            }
        )
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.state.sms_webhook = SmsWebhookDeps(
            cache=InMemoryCache(clock),
            event_bus=self.bus,
            hasher=HmacPhoneHasher(secrets),
            secrets=secrets,
            lines=DirectoryInboundLines(self.directory),  # type: ignore[arg-type]
            public_base_url=BASE,
        )
        self.app.state.container = SimpleNamespace(clock=clock, uow_factory=_NobodyOnTheList)

    async def post(self, path: str, params: dict[str, str], token: bytes) -> Any:
        headers = {**FORM, "X-Twilio-Signature": _sign(BASE + path, params, token)}
        async with AsyncClient(
            transport=ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://internal:8000",
        ) as client:
            return await client.post(path, data=params, headers=headers)


def _reply(to: str, account: str) -> dict[str, str]:
    return {
        "AccountSid": account,
        "MessageSid": "SM" + "2" * 32,
        "From": "+447700900456",
        "To": to,
        "Body": "4",
        "NumMedia": "0",
    }


async def test_a_text_to_the_shared_number_identifies_no_tenant_and_queues_nothing() -> None:
    rig = _Rig()

    # Signed with the platform's own token, as Twilio would sign a text to the platform's account.
    response = await rig.post(REPLY_PATH, _reply(SHARED, PLATFORM_SID), PLATFORM_TOKEN)

    assert response.status_code == 403 and response.content == b"Forbidden"
    assert rig.bus.enqueued_to("inbound.replies") == []


async def test_it_is_the_same_refusal_as_for_a_number_nobody_holds() -> None:
    rig = _Rig()

    shared = await rig.post(REPLY_PATH, _reply(SHARED, PLATFORM_SID), PLATFORM_TOKEN)
    unknown = await rig.post(REPLY_PATH, _reply("+447700900777", PLATFORM_SID), PLATFORM_TOKEN)

    assert (shared.status_code, shared.content, dict(shared.headers)) == (
        unknown.status_code,
        unknown.content,
        dict(unknown.headers),
    )


@pytest.mark.parametrize(
    "token", [OWN_TOKEN, PLATFORM_TOKEN], ids=["tenant-token", "platform-token"]
)
async def test_a_tenants_account_with_the_shared_number_called_is_still_no_tenant(
    token: bytes,
) -> None:
    rig = _Rig()

    response = await rig.post(REPLY_PATH, _reply(SHARED, OWN_SID), token)

    assert response.status_code == 403
    assert rig.bus.enqueued_to("inbound.replies") == []


async def test_a_tenants_own_number_still_finds_the_tenant_so_the_refusal_is_about_the_number() -> (
    None
):
    rig = _Rig()

    response = await rig.post(REPLY_PATH, _reply(OWN, OWN_SID), OWN_TOKEN)

    # Verified: the tenant is bound and the text is dropped only because nobody on its list sent it.
    assert response.status_code == 200 and b"Forbidden" not in response.content


async def test_a_receipt_from_the_platform_account_is_refused_not_given_to_a_tenant() -> None:
    rig = _Rig()
    params = {
        "AccountSid": PLATFORM_SID,
        "MessageSid": "SM" + "3" * 32,
        "MessageStatus": "delivered",
        "From": SHARED,
        "To": "+447700900456",
    }

    response = await rig.post(STATUS_PATH, params, PLATFORM_TOKEN)

    assert response.status_code == 403
    assert rig.bus.enqueued_to("inbound.receipts") == []
