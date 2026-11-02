"""TEMPORARY DEMO (DEC-1320): the reply to a text that came in on the shared line goes out from it.

The demo tenant's texts are sent from the platform's shared line, whether or not that tenant has an
active shared channel or a number of its own. Any other tenant is unchanged. Fakes only.
"""

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.application.ports.outbound.sender_resolver import ChannelUnavailable
from overwatch.application.ports.outbound.tenants import TenantLine, twilio_token_ref
from overwatch.application.tenancy import bind_tenant
from overwatch.bootstrap.tenant_senders import (
    PLATFORM_SMS_TOKEN_SECRET,
    PlatformSmsIdentity,
    TenantSenderResolver,
)
from overwatch.domain.model.tenant import TenantStatus
from tests.support.tenant_samples import SAMPLE_ID, make_tenant

DEMO_ID = "demo-trust"
SHARED = "+447700900000"
PLATFORM_SID = "AC" + "9" * 32
PLATFORM_TOKEN = b"token-of-the-platform-account-0123456"
OWN = "+447700900123"
OWN_SID = "AC" + "1" * 32
OWN_TOKEN = b"token-of-the-tenants-own-subaccount-01"
STATUS_URL = "https://overwatch.example.test/webhooks/sms/twilio/status"
PLATFORM = PlatformSmsIdentity(PLATFORM_SID, SHARED)


class _Directory:
    def __init__(self, status: TenantStatus | None, own_line_of: str | None = None) -> None:
        self._status = status
        self._own = own_line_of

    async def active_line(self, tenant_id: str) -> TenantLine | None:
        if tenant_id != self._own:
            return None
        return TenantLine(
            tenant=make_tenant(id=tenant_id),
            number=OWN,
            account_sid=OWN_SID,
            secret_ref=twilio_token_ref(tenant_id),
        )

    async def get(self, tenant_id: str) -> Any:
        if self._status is None:
            return None
        return make_tenant(self._status, id=tenant_id)


def _resolver(
    directory: _Directory,
    seen: list[httpx.Request],
    *,
    demo: str | None = DEMO_ID,
    platform: PlatformSmsIdentity | None = PLATFORM,
    shared_channel: bool = False,
) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"sid": "SM-1"})

    async def has_shared() -> bool:
        return shared_channel

    secrets = FixedSecretStore(
        {
            PLATFORM_SMS_TOKEN_SECRET: PLATFORM_TOKEN,
            twilio_token_ref(DEMO_ID): OWN_TOKEN,
            twilio_token_ref(SAMPLE_ID): OWN_TOKEN,
        }
    )
    return TenantSenderResolver(
        directory,  # type: ignore[arg-type]
        secrets,
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        STATUS_URL,
        platform_sms=platform,
        shared_line=has_shared,
        demo_tenant=demo,
    )


async def _send_from(resolver: Any, tenant: str) -> str:
    with bind_tenant(tenant):
        sender = await resolver.sms_for()
        await sender.send("07700 900456", "Thanks, received", "reply-1")
    return ""


@pytest.mark.parametrize("status", [TenantStatus.PROVISIONING, TenantStatus.ACTIVE])
async def test_the_demo_tenant_with_no_shared_channel_replies_from_the_shared_line(
    status: TenantStatus,
) -> None:
    seen: list[httpx.Request] = []
    resolver = _resolver(_Directory(status), seen, shared_channel=False)

    await _send_from(resolver, DEMO_ID)

    [request] = seen
    assert f"/Accounts/{PLATFORM_SID}/Messages.json" in str(request.url)
    assert parse_qs(request.content.decode())["From"] == [SHARED]


async def test_the_demo_tenant_with_a_number_of_its_own_still_replies_from_the_shared_line() -> (
    None
):
    seen: list[httpx.Request] = []
    resolver = _resolver(_Directory(TenantStatus.ACTIVE, own_line_of=DEMO_ID), seen)

    await _send_from(resolver, DEMO_ID)

    assert parse_qs(seen[0].content.decode())["From"] == [SHARED]


@pytest.mark.parametrize(
    "status",
    [
        None,
        TenantStatus.SUSPENDED,
        TenantStatus.OFFBOARDING,
        TenantStatus.OFFBOARDED,
        TenantStatus.PURGED,
    ],
)
async def test_an_unusable_demo_tenant_sends_nothing(status: TenantStatus | None) -> None:
    seen: list[httpx.Request] = []
    resolver = _resolver(_Directory(status), seen)

    with bind_tenant(DEMO_ID), pytest.raises(ChannelUnavailable):
        await resolver.sms_for()

    assert seen == []


async def test_with_no_platform_identity_the_demo_tenant_has_no_line_either() -> None:
    seen: list[httpx.Request] = []
    resolver = _resolver(_Directory(TenantStatus.ACTIVE), seen, platform=None)

    with bind_tenant(DEMO_ID), pytest.raises(ChannelUnavailable):
        await resolver.sms_for()


async def test_another_tenant_is_unchanged_no_line_and_no_shared_channel_is_unavailable() -> None:
    seen: list[httpx.Request] = []
    resolver = _resolver(_Directory(TenantStatus.ACTIVE), seen)

    with bind_tenant(SAMPLE_ID), pytest.raises(ChannelUnavailable):
        await resolver.sms_for()

    assert seen == []


async def test_another_tenant_with_its_own_line_still_sends_from_it() -> None:
    seen: list[httpx.Request] = []
    resolver = _resolver(_Directory(TenantStatus.ACTIVE, own_line_of=SAMPLE_ID), seen)

    await _send_from(resolver, SAMPLE_ID)

    assert parse_qs(seen[0].content.decode())["From"] == [OWN]


async def test_with_the_setting_unset_the_demo_tenant_is_an_ordinary_tenant() -> None:
    seen: list[httpx.Request] = []
    resolver = _resolver(_Directory(TenantStatus.ACTIVE), seen, demo=None)

    with bind_tenant(DEMO_ID), pytest.raises(ChannelUnavailable):
        await resolver.sms_for()
