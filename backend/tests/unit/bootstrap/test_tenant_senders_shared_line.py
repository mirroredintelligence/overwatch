"""The sender of one line for a test text, and the shared sending line (DEC-1319).

Fakes only: a stub directory, `FixedSecretStore` and an httpx MockTransport. Invented values.
"""

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from overwatch.adapters.outbound.sms_twilio.twilio_sms import TwilioSms
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.application.ports.outbound.sender_resolver import ChannelUnavailable
from overwatch.application.ports.outbound.tenant_registry import TenantNumberRecord
from overwatch.application.ports.outbound.tenants import (
    TenantLine,
    TenantRecordInvalid,
    twilio_token_ref,
)
from overwatch.application.tenancy import bind_tenant
from overwatch.bootstrap.settings import Settings
from overwatch.bootstrap.tenant_senders import (
    PLATFORM_EMAIL_TOKEN_SECRET,
    PLATFORM_SMS_TOKEN_SECRET,
    PlatformSmsIdentity,
    TenantSenderResolver,
    platform_sms_identity,
)
from overwatch.domain.model.tenant import TenantStatus
from tests.support.tenant_samples import SAMPLE_ID, make_tenant

OWN = "+447700900123"
OWN_SID = "AC" + "1" * 32
OWN_TOKEN = b"token-of-the-tenants-own-subaccount-01"
SHARED = "+447700900000"
PLATFORM_SID = "AC" + "9" * 32
PLATFORM_TOKEN = b"token-of-the-platform-account-0123456"
STATUS_URL = "https://overwatch.example.test/webhooks/sms/twilio/status"
PLATFORM = PlatformSmsIdentity(PLATFORM_SID, SHARED)


class _Directory:
    def __init__(
        self,
        line: TenantLine | None = None,
        status: TenantStatus = TenantStatus.ACTIVE,
        error: Exception | None = None,
    ) -> None:
        self._line = line
        self._status = status
        self._error = error
        self.asked: list[str] = []

    async def active_line(self, tenant_id: str) -> TenantLine | None:
        self.asked.append(tenant_id)
        if self._error is not None:
            raise self._error
        return self._line

    async def get(self, tenant_id: str) -> Any:
        return make_tenant(self._status)


def _own_line() -> TenantLine:
    return TenantLine(
        tenant=make_tenant(),
        number=OWN,
        account_sid=OWN_SID,
        secret_ref=twilio_token_ref(SAMPLE_ID),
    )


def _number(**fields: Any) -> TenantNumberRecord:
    base = {"e164": OWN, "account_sid": OWN_SID, "secret_ref": twilio_token_ref(SAMPLE_ID)}
    return TenantNumberRecord(**{**base, **fields})


def _secrets(*, own: bool = True, platform: bool = True) -> FixedSecretStore:
    values: dict[str, bytes] = {}
    if own:
        values[twilio_token_ref(SAMPLE_ID)] = OWN_TOKEN
    if platform:
        values[PLATFORM_SMS_TOKEN_SECRET] = PLATFORM_TOKEN
    return FixedSecretStore(values)


def _http(seen: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"sid": "SM-1"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _resolver(
    directory: _Directory,
    secrets: FixedSecretStore,
    seen: list[httpx.Request] | None = None,
    *,
    platform: PlatformSmsIdentity | None = PLATFORM,
    shared: bool | None = None,
) -> Any:
    async def has_shared() -> bool:
        return bool(shared)

    return TenantSenderResolver(
        directory,
        secrets,
        _http([] if seen is None else seen),
        STATUS_URL,
        platform_sms=platform,
        shared_line=None if shared is None else has_shared,
    )


def test_the_platform_sms_token_is_the_one_the_platform_email_already_uses() -> None:
    assert PLATFORM_SMS_TOKEN_SECRET == PLATFORM_EMAIL_TOKEN_SECRET == "twilio-auth-token"


def test_the_platform_identity_is_built_from_the_account_and_the_shared_number_settings() -> None:
    settings = Settings(platform_twilio_account_sid=PLATFORM_SID, platform_sms_from=SHARED)
    assert platform_sms_identity(settings) == PLATFORM


@pytest.mark.parametrize(
    "fields",
    [
        {"platform_twilio_account_sid": None, "platform_sms_from": SHARED},
        {"platform_twilio_account_sid": PLATFORM_SID, "platform_sms_from": None},
        {"platform_twilio_account_sid": PLATFORM_SID, "platform_sms_from": ""},
        {"platform_twilio_account_sid": PLATFORM_SID, "platform_sms_from": "07700900000"},
        {"platform_twilio_account_sid": "not-a-sid", "platform_sms_from": SHARED},
    ],
)
def test_there_is_no_platform_identity_unless_both_settings_are_good(
    fields: dict[str, Any],
) -> None:
    assert platform_sms_identity(Settings(**fields)) is None


def test_the_shared_number_setting_is_read_from_the_environment_name_the_bicep_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OVERWATCH_PLATFORM_SMS_FROM", SHARED)
    assert Settings().platform_sms_from == SHARED


# ------------------------------------------------------------------ one line, for a test text


async def test_an_own_number_is_tested_on_its_own_account_and_token_with_no_directory_lookup() -> (
    None
):
    seen: list[httpx.Request] = []
    directory = _Directory(None, status=TenantStatus.PROVISIONING)
    secrets = _secrets()
    resolver = _resolver(directory, secrets, seen)

    with bind_tenant(SAMPLE_ID):
        sender = await resolver.provisioning_sms_for(_number())
        receipt = await sender.send("07700 900456", "A test", "test-1")

    assert isinstance(sender, TwilioSms) and receipt.accepted
    [request] = seen
    assert f"/Accounts/{OWN_SID}/Messages.json" in str(request.url)
    assert parse_qs(request.content.decode())["From"] == [OWN]
    assert secrets.requested == (twilio_token_ref(SAMPLE_ID),)
    assert directory.asked == []  # a tenant being provisioned has no active line to ask for


async def test_an_own_number_naming_another_tenants_token_is_never_read() -> None:
    secrets = _secrets()
    resolver = _resolver(_Directory(), secrets)
    other = _number(secret_ref="twilio/other-example-icb/auth-token")

    with bind_tenant(SAMPLE_ID), pytest.raises(ChannelUnavailable) as refused:
        await resolver.provisioning_sms_for(other)

    assert secrets.requested == ()
    assert "other-example-icb" not in str(refused.value) and OWN not in str(refused.value)


async def test_an_own_number_with_no_token_in_the_store_is_unavailable_without_naming_it() -> None:
    resolver = _resolver(_Directory(), _secrets(own=False))

    with bind_tenant(SAMPLE_ID), pytest.raises(ChannelUnavailable) as refused:
        await resolver.provisioning_sms_for(_number())

    assert "auth-token" not in str(refused.value) and OWN not in str(refused.value)


async def test_the_shared_line_sends_from_the_platform_account_number_and_token() -> None:
    seen: list[httpx.Request] = []
    secrets = _secrets()
    resolver = _resolver(_Directory(), secrets, seen)

    with bind_tenant(SAMPLE_ID):
        sender = await resolver.provisioning_sms_for(None)
        await sender.send("07700 900456", "A test", "test-1")

    [request] = seen
    assert f"/Accounts/{PLATFORM_SID}/Messages.json" in str(request.url)
    assert parse_qs(request.content.decode())["From"] == [SHARED]
    assert secrets.requested == (PLATFORM_SMS_TOKEN_SECRET,)
    assert twilio_token_ref(SAMPLE_ID) not in secrets.requested


@pytest.mark.parametrize(
    ("platform", "secrets"),
    [(None, _secrets()), (PLATFORM, _secrets(platform=False))],
    ids=["no-platform-identity", "no-platform-token"],
)
async def test_the_shared_line_is_unavailable_without_the_platform_identity_or_token(
    platform: PlatformSmsIdentity | None, secrets: FixedSecretStore
) -> None:
    resolver = _resolver(_Directory(), secrets, platform=platform)

    with bind_tenant(SAMPLE_ID), pytest.raises(ChannelUnavailable) as refused:
        await resolver.provisioning_sms_for(None)

    assert SHARED not in str(refused.value) and PLATFORM_SID not in str(refused.value)


# ------------------------------------------------------- the normal sender and the shared line


async def test_a_tenant_with_its_own_active_number_never_uses_the_shared_line() -> None:
    seen: list[httpx.Request] = []
    resolver = _resolver(_Directory(_own_line()), _secrets(), seen, shared=True)

    with bind_tenant(SAMPLE_ID):
        sender = await resolver.sms_for()
        await sender.send("07700 900456", "Hello", "outbox-1")

    assert OWN_SID in str(seen[0].url)
    assert parse_qs(seen[0].content.decode())["From"] == [OWN]


async def test_a_tenant_with_no_own_number_and_an_active_shared_line_sends_from_the_platform() -> (
    None
):
    seen: list[httpx.Request] = []
    secrets = _secrets()
    resolver = _resolver(_Directory(None), secrets, seen, shared=True)

    with bind_tenant(SAMPLE_ID):
        sender = await resolver.sms_for()
        await sender.send("07700 900456", "Hello", "outbox-1")

    assert PLATFORM_SID in str(seen[0].url)
    assert parse_qs(seen[0].content.decode())["From"] == [SHARED]
    assert secrets.requested == (PLATFORM_SMS_TOKEN_SECRET,)


@pytest.mark.parametrize(
    ("directory", "shared"),
    [
        (_Directory(None), False),  # no shared line chosen
        (_Directory(None), None),  # no shared-line check wired
        (_Directory(None, status=TenantStatus.SUSPENDED), True),  # a suspended tenant sends nothing
        (_Directory(None, status=TenantStatus.PROVISIONING), True),
        (_Directory(error=TenantRecordInvalid("registry fault")), True),  # a fault is not a gap
    ],
    ids=["not-chosen", "not-wired", "suspended", "provisioning", "registry-fault"],
)
async def test_the_shared_line_is_used_only_by_an_active_tenant_that_chose_it(
    directory: _Directory, shared: bool | None
) -> None:
    resolver = _resolver(directory, _secrets(), shared=shared)

    with bind_tenant(SAMPLE_ID), pytest.raises(ChannelUnavailable) as refused:
        await resolver.sms_for()

    assert SAMPLE_ID in str(refused.value)
    assert SHARED not in str(refused.value) and PLATFORM_SID not in str(refused.value)


async def test_the_shared_line_with_no_platform_token_fails_closed() -> None:
    resolver = _resolver(_Directory(None), _secrets(platform=False), shared=True)

    with bind_tenant(SAMPLE_ID), pytest.raises(ChannelUnavailable):
        await resolver.sms_for()
