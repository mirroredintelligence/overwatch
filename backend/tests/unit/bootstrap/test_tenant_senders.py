"""The production sender resolver (I10, DEC-131): fail-closed behaviour with fakes. No Docker, no
network: the directory is a stub returning a line (the real directory query is an integration test,
verified in the verification stage), the secret store is FixedSecretStore, and the HTTP calls go to
an httpx MockTransport. Sample values only; the tenant is a made-up organisation.
"""

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from diucs.adapters.outbound.sms_twilio.twilio_sms import TwilioSms
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.sender_resolver import ChannelUnavailable
from diucs.application.ports.outbound.tenants import (
    TenantLine,
    TenantRecordInvalid,
    twilio_token_ref,
)
from diucs.application.tenancy import TenancyError, bind_tenant
from diucs.bootstrap.settings import Settings
from diucs.bootstrap.tenant_senders import TenantSenderResolver, status_callback_url
from tests.support.tenant_samples import SAMPLE_ID, make_tenant

NUMBER = "+447700900123"
SID = "AC" + "1" * 32
TOKEN = b"token-for-the-example-subaccount-0123"
STATUS_URL = "https://diucs.example/webhooks/sms/twilio/status"


class _Directory:
    """A stub of the tenant directory's one lookup: it answers the line it is given, or raises."""

    def __init__(self, line: TenantLine | None = None, error: Exception | None = None) -> None:
        self._line = line
        self._error = error
        self.asked: list[str] = []

    async def active_line(self, tenant_id: str) -> TenantLine | None:
        self.asked.append(tenant_id)
        if self._error is not None:
            raise self._error
        return self._line


def _line(tenant_id: str = SAMPLE_ID) -> TenantLine:
    return TenantLine(
        tenant=make_tenant(id=tenant_id) if tenant_id != SAMPLE_ID else make_tenant(),
        number=NUMBER,
        account_sid=SID,
        secret_ref=twilio_token_ref(SAMPLE_ID),
    )


def _resolver(directory: _Directory, secrets: FixedSecretStore, http: httpx.AsyncClient) -> Any:
    return TenantSenderResolver(directory, secrets, http, STATUS_URL)


def _secrets(token: bytes | None = TOKEN) -> FixedSecretStore:
    if token is None:
        return FixedSecretStore({})
    return FixedSecretStore({twilio_token_ref(SAMPLE_ID): token})


def _http(seen: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"sid": "SM-1"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_an_active_number_resolves_to_a_text_sender_on_its_own_subaccount() -> None:
    seen: list[httpx.Request] = []
    directory = _Directory(_line())
    resolver = _resolver(directory, _secrets(), _http(seen))

    with bind_tenant(SAMPLE_ID):
        sender = await resolver.sms_for()
        receipt = await sender.send("07700 900123", "How many referrals?", "outbox-1")

    assert isinstance(sender, TwilioSms)
    assert receipt.accepted and receipt.provider_message_id == "SM-1"
    [request] = seen
    assert f"/Accounts/{SID}/Messages.json" in str(request.url)
    form = parse_qs(request.content.decode())
    assert form["From"] == [NUMBER]
    assert request.headers["Authorization"].startswith("Basic ")


async def test_the_directory_is_asked_only_for_the_bound_tenant() -> None:
    directory = _Directory(_line())
    resolver = _resolver(directory, _secrets(), _http([]))

    with bind_tenant(SAMPLE_ID):
        await resolver.sms_for()

    assert directory.asked == [SAMPLE_ID]


async def test_only_the_tenants_own_secret_reference_is_read_and_never_the_value() -> None:
    secrets = _secrets()
    resolver = _resolver(_Directory(_line()), secrets, _http([]))

    with bind_tenant(SAMPLE_ID):
        await resolver.sms_for()

    assert secrets.requested == (twilio_token_ref(SAMPLE_ID),)


@pytest.mark.parametrize(
    "directory",
    [
        _Directory(None),  # no number, or a suspended or quarantined one: the directory lists none
        _Directory(error=TenantRecordInvalid("registry fault")),
    ],
)
async def test_a_tenant_without_an_active_number_fails_closed_and_names_only_the_tenant(
    directory: _Directory,
) -> None:
    secrets = _secrets()
    resolver = _resolver(directory, secrets, _http([]))

    with bind_tenant(SAMPLE_ID), pytest.raises(ChannelUnavailable) as refused:
        await resolver.sms_for()

    assert SAMPLE_ID in str(refused.value)
    assert NUMBER not in str(refused.value)
    assert secrets.requested == ()


async def test_a_line_that_belongs_to_another_tenant_is_never_used() -> None:
    other = _Directory(_line("other-example-icb"))
    secrets = _secrets()
    resolver = _resolver(other, secrets, _http([]))

    with bind_tenant(SAMPLE_ID), pytest.raises(ChannelUnavailable) as refused:
        await resolver.sms_for()

    assert NUMBER not in str(refused.value)
    assert secrets.requested == ()


async def test_a_missing_secret_fails_closed_without_naming_the_reference() -> None:
    resolver = _resolver(_Directory(_line()), _secrets(token=None), _http([]))

    with bind_tenant(SAMPLE_ID), pytest.raises(ChannelUnavailable) as refused:
        await resolver.sms_for()

    assert SAMPLE_ID in str(refused.value)
    assert "auth-token" not in str(refused.value)


@pytest.mark.parametrize("token", [b"", b"   ", b"\xff\xfe"])
async def test_a_secret_that_is_empty_or_not_text_fails_closed(token: bytes) -> None:
    resolver = _resolver(_Directory(_line()), _secrets(token=token), _http([]))

    with bind_tenant(SAMPLE_ID), pytest.raises(ChannelUnavailable):
        await resolver.sms_for()


async def test_no_email_channel_exists_so_every_email_fails_closed() -> None:
    resolver = _resolver(_Directory(_line()), _secrets(), _http([]))

    with bind_tenant(SAMPLE_ID), pytest.raises(ChannelUnavailable) as refused:
        await resolver.email_for()

    assert SAMPLE_ID in str(refused.value)


async def test_with_no_tenant_bound_the_resolver_refuses_instead_of_choosing_one() -> None:
    directory = _Directory(_line())
    resolver = _resolver(directory, _secrets(), _http([]))

    with pytest.raises(TenancyError):
        await resolver.sms_for()

    assert directory.asked == []


def test_the_status_callback_is_the_inbound_webhook_of_this_deployment() -> None:
    assert status_callback_url(Settings(base_url="https://diucs.example/")) == STATUS_URL
    assert status_callback_url(Settings(base_url="https://diucs.example")) == STATUS_URL
