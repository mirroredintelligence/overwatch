"""TEMPORARY DEMO (DEC-1320): texts to the platform's shared number, routed to one demo tenant.

With `OVERWATCH_DEMO_INBOUND_TENANT` unset a text, or a delivery receipt, on the shared number is
the same 403 as before and queues nothing. With it set, a request for the platform account on the
shared number, signed with the PLATFORM token, is handled as if it had arrived on that one tenant's
own line. Everything else (another number, another account, a tenant's own number, a wrong
signature, a demo tenant that is unknown or offboarded) is refused or handled exactly as today.

Real webhook, real `DirectoryInboundLines` and `DemoInboundLines`; fakes for the registry, the bus,
the cache, the secrets and the unit of work. No network. Every value is invented.
"""

import base64
import hashlib
import hmac
import logging
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
from overwatch.application.ports.outbound.tenants import (
    TenantLine,
    TenantRecordInvalid,
    twilio_token_ref,
)
from overwatch.application.tenancy import current_tenant
from overwatch.application.tenant_resolution import DemoInboundLines, DirectoryInboundLines
from overwatch.bootstrap.tenant_senders import PLATFORM_SMS_TOKEN_SECRET
from overwatch.domain.model.tenant import TenantStatus
from tests.support.tenant_samples import SAMPLE_ID, make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

BASE = "https://overwatch.example.test"
FORM = {"content-type": "application/x-www-form-urlencoded"}
SHARED = "+447700900000"
PLATFORM_SID = "AC" + "9" * 32
PLATFORM_TOKEN = b"token-of-the-platform-account-0123456"
DEMO_ID = "demo-trust"
OWN_ID = SAMPLE_ID  # a different tenant, with a number of its own
OWN = "+447700900123"
OWN_SID = "AC" + "1" * 32
OWN_TOKEN = b"token-of-the-tenants-own-subaccount-01"
SENDER = "+447700900456"
SENDER_PERSON = SimpleNamespace(id="person-1")


class _RegistryDirectory:
    """The registry as it answers: only a tenant's own ACTIVE number with its own account; and the
    tenant records by id (`get`)."""

    def __init__(self, demo_status: TenantStatus | None, *, record_fault: bool = False) -> None:
        self._line = TenantLine(
            tenant=make_tenant(),
            number=OWN,
            account_sid=OWN_SID,
            secret_ref=twilio_token_ref(OWN_ID),
        )
        self._demo_status = demo_status
        self._fault = record_fault

    async def by_inbound_number(self, to_number: str, account_sid: str) -> TenantLine | None:
        held = (to_number, account_sid) == (self._line.number, self._line.account_sid)
        return self._line if held else None

    async def by_account_sid(self, account_sid: str) -> TenantLine | None:
        return self._line if account_sid == self._line.account_sid else None

    async def get(self, tenant_id: str) -> Any:
        if self._fault:
            raise TenantRecordInvalid("damaged")
        if tenant_id == DEMO_ID and self._demo_status is not None:
            return make_tenant(self._demo_status, id=DEMO_ID)
        if tenant_id == OWN_ID:
            return make_tenant()
        return None


class _SpyHasher:
    """The real hasher, recording the tenant that was bound when it was asked."""

    def __init__(self, inner: HmacPhoneHasher) -> None:
        self._inner = inner
        self.asked_under: list[str] = []

    def hash(self, phone: str) -> str:
        self.asked_under.append(current_tenant())
        return self._inner.hash(phone)


class _Uow:
    """A unit of work whose allow-list holds one sender, and whose communications hold the given
    provider ids. It records the tenant bound and the hash it was asked for."""

    def __init__(self, rig: _Rig) -> None:
        self._rig = rig

        async def find(phone_hash: str) -> Any:
            rig.lookups.append((current_tenant(), phone_hash))
            return SENDER_PERSON if phone_hash == rig.known_hash else None

        async def by_provider_id(provider_id: str) -> Any:
            rig.receipt_lookups.append((current_tenant(), provider_id))
            return object() if provider_id in rig.known_messages else None

        self.people = SimpleNamespace(find_by_phone_hash=find)
        self.communications = SimpleNamespace(by_provider_id=by_provider_id)

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _sign(url: str, params: Mapping[str, str], token: bytes) -> str:
    data = url + "".join(name + params[name] for name in sorted(params))
    return base64.b64encode(hmac.new(token, data.encode(), hashlib.sha1).digest()).decode()


class _Rig:
    def __init__(
        self,
        *,
        demo: bool,
        demo_status: TenantStatus | None = TenantStatus.ACTIVE,
        record_fault: bool = False,
    ) -> None:
        clock = FixedClock(datetime(2026, 11, 2, 9, 0, tzinfo=UTC))
        directory = _RegistryDirectory(demo_status, record_fault=record_fault)
        base = DirectoryInboundLines(directory)  # type: ignore[arg-type]
        lines = (
            DemoInboundLines(
                base,
                directory,  # type: ignore[arg-type]
                tenant_id=DEMO_ID,
                shared_number=SHARED,
                account_sid=PLATFORM_SID,
                token_secret=PLATFORM_SMS_TOKEN_SECRET,
            )
            if demo
            else base
        )
        self.bus = ManualEventBus(clock)
        secrets = FixedSecretStore(
            {
                PHONE_HASH_SECRET: b"unit-test-phone-hash-key",
                twilio_token_ref(OWN_ID): OWN_TOKEN,
                PLATFORM_SMS_TOKEN_SECRET: PLATFORM_TOKEN,
            }
        )
        self.hasher = _SpyHasher(HmacPhoneHasher(secrets))
        self.known_hash = self.hasher._inner.hash(SENDER)
        self.lookups: list[tuple[str, str]] = []
        self.receipt_lookups: list[tuple[str, str]] = []
        self.known_messages: set[str] = set()
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.state.sms_webhook = SmsWebhookDeps(
            cache=InMemoryCache(clock),
            event_bus=self.bus,
            hasher=self.hasher,  # type: ignore[arg-type]
            secrets=secrets,
            lines=lines,
            public_base_url=BASE,
        )
        self.app.state.container = SimpleNamespace(clock=clock, uow_factory=lambda: _Uow(self))

    async def post(self, path: str, params: dict[str, str], token: bytes) -> Any:
        headers = {**FORM, "X-Twilio-Signature": _sign(BASE + path, params, token)}
        async with AsyncClient(
            transport=ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://internal:8000",
        ) as client:
            return await client.post(path, data=params, headers=headers)


def _text(to: str, account: str) -> dict[str, str]:
    return {
        "AccountSid": account,
        "MessageSid": "SM" + "2" * 32,
        "From": SENDER,
        "To": to,
        "Body": "4",
        "NumMedia": "0",
    }


def _receipt(account: str = PLATFORM_SID, sender: str = SHARED) -> dict[str, str]:
    return {
        "AccountSid": account,
        "MessageSid": "SM" + "3" * 32,
        "MessageStatus": "delivered",
        "From": sender,
        "To": SENDER,
    }


def _refused(response: Any) -> bool:
    return response.status_code == 403 and response.content == b"Forbidden"


# ------------------------------------------------------------ the setting unset: as today


async def test_unset_a_text_to_the_shared_number_is_refused_and_queues_nothing() -> None:
    rig = _Rig(demo=False)

    response = await rig.post(REPLY_PATH, _text(SHARED, PLATFORM_SID), PLATFORM_TOKEN)

    assert _refused(response)
    assert rig.bus.enqueued_to("inbound.replies") == [] and rig.lookups == []


async def test_unset_a_receipt_on_the_shared_number_is_refused() -> None:
    rig = _Rig(demo=False)

    response = await rig.post(STATUS_PATH, _receipt(), PLATFORM_TOKEN)

    assert _refused(response)
    assert rig.bus.enqueued_to("inbound.receipts") == []


# ------------------------------------------------------------ the setting set: the demo route


async def test_set_a_text_to_the_shared_number_reaches_the_demo_tenants_handling() -> None:
    rig = _Rig(demo=True)

    response = await rig.post(REPLY_PATH, _text(SHARED, PLATFORM_SID), PLATFORM_TOKEN)

    assert response.status_code == 200 and b"Forbidden" not in response.content
    # The sender is looked up by its phone hash, in the demo tenant, with that tenant's hasher.
    assert rig.lookups == [(DEMO_ID, rig.known_hash)]
    assert rig.hasher.asked_under == [DEMO_ID]
    queued = rig.bus.enqueued_to("inbound.replies")
    assert [message.tenant_id for message in queued] == [DEMO_ID]
    assert queued[0].payload["phone_hash"] == rig.known_hash


@pytest.mark.parametrize("status", [TenantStatus.PROVISIONING, TenantStatus.ACTIVE])
async def test_set_a_provisioning_or_active_demo_tenant_is_accepted(status: TenantStatus) -> None:
    rig = _Rig(demo=True, demo_status=status)

    response = await rig.post(REPLY_PATH, _text(SHARED, PLATFORM_SID), PLATFORM_TOKEN)

    assert response.status_code == 200
    assert len(rig.bus.enqueued_to("inbound.replies")) == 1


@pytest.mark.parametrize("token", [b"a-wrong-token", OWN_TOKEN], ids=["wrong", "tenant-token"])
async def test_set_a_wrong_signature_including_a_tenants_token_is_refused(token: bytes) -> None:
    rig = _Rig(demo=True)

    response = await rig.post(REPLY_PATH, _text(SHARED, PLATFORM_SID), token)

    assert _refused(response)
    assert rig.bus.enqueued_to("inbound.replies") == [] and rig.lookups == []


async def test_set_another_number_under_the_platform_account_is_refused() -> None:
    rig = _Rig(demo=True)

    response = await rig.post(REPLY_PATH, _text("+447700900777", PLATFORM_SID), PLATFORM_TOKEN)

    assert _refused(response)
    assert rig.lookups == []


async def test_set_the_shared_number_under_another_account_is_refused() -> None:
    rig = _Rig(demo=True)

    for token in (PLATFORM_TOKEN, OWN_TOKEN):
        response = await rig.post(REPLY_PATH, _text(SHARED, OWN_SID), token)
        assert _refused(response)
    assert rig.lookups == []


async def test_set_a_tenants_own_number_is_unaffected_and_never_takes_the_demo_route() -> None:
    rig = _Rig(demo=True)

    own = await rig.post(REPLY_PATH, _text(OWN, OWN_SID), OWN_TOKEN)
    # The platform's token and account on a tenant's number are no way in.
    via_platform_token = await rig.post(REPLY_PATH, _text(OWN, OWN_SID), PLATFORM_TOKEN)
    via_platform_account = await rig.post(REPLY_PATH, _text(OWN, PLATFORM_SID), PLATFORM_TOKEN)

    assert own.status_code == 200
    assert _refused(via_platform_token) and _refused(via_platform_account)
    assert [tenant for tenant, _ in rig.lookups] == [OWN_ID]  # never the demo tenant


@pytest.mark.parametrize(
    "status",
    [
        None,
        TenantStatus.SUSPENDED,
        TenantStatus.OFFBOARDING,
        TenantStatus.OFFBOARDED,
        TenantStatus.PURGED,
    ],
    ids=lambda value: "unknown" if value is None else value.value,
)
async def test_set_an_unusable_demo_tenant_is_the_plain_403_with_one_warning_and_no_id(
    status: TenantStatus | None, caplog: pytest.LogCaptureFixture
) -> None:
    rig = _Rig(demo=True, demo_status=status)

    with caplog.at_level(logging.WARNING):
        response = await rig.post(REPLY_PATH, _text(SHARED, PLATFORM_SID), PLATFORM_TOKEN)

    assert _refused(response)
    assert rig.bus.enqueued_to("inbound.replies") == [] and rig.lookups == []
    assert DEMO_ID not in response.text
    demo_warnings = [r for r in caplog.records if "demo" in r.getMessage().lower()]
    assert len(demo_warnings) == 1 and DEMO_ID not in demo_warnings[0].getMessage()


async def test_set_a_damaged_demo_tenant_record_is_refused_the_same_way() -> None:
    rig = _Rig(demo=True, record_fault=True)

    response = await rig.post(REPLY_PATH, _text(SHARED, PLATFORM_SID), PLATFORM_TOKEN)

    assert _refused(response)
    assert rig.bus.enqueued_to("inbound.replies") == []


# ------------------------------------------------------------ delivery receipts


async def test_set_a_receipt_for_a_message_of_the_demo_tenant_is_applied() -> None:
    rig = _Rig(demo=True)
    rig.known_messages.add("SM" + "3" * 32)

    response = await rig.post(STATUS_PATH, _receipt(), PLATFORM_TOKEN)

    assert response.status_code == 200
    queued = rig.bus.enqueued_to("inbound.receipts")
    assert [message.tenant_id for message in queued] == [DEMO_ID]


async def test_set_a_receipt_no_demo_message_matches_is_answered_200_and_ignored() -> None:
    rig = _Rig(demo=True)

    response = await rig.post(STATUS_PATH, _receipt(), PLATFORM_TOKEN)

    assert response.status_code == 200 and b"Forbidden" not in response.content
    assert rig.bus.enqueued_to("inbound.receipts") == []
    assert rig.receipt_lookups == [(DEMO_ID, "SM" + "3" * 32)]


async def test_set_a_receipt_from_another_number_or_with_another_token_is_refused() -> None:
    rig = _Rig(demo=True)
    rig.known_messages.add("SM" + "3" * 32)

    other_number = await rig.post(STATUS_PATH, _receipt(sender="+447700900777"), PLATFORM_TOKEN)
    wrong_token = await rig.post(STATUS_PATH, _receipt(), OWN_TOKEN)

    assert _refused(other_number) and _refused(wrong_token)
    assert rig.bus.enqueued_to("inbound.receipts") == []


async def test_set_a_tenants_own_receipt_still_goes_to_that_tenant() -> None:
    rig = _Rig(demo=True)

    response = await rig.post(STATUS_PATH, _receipt(account=OWN_SID, sender=OWN), OWN_TOKEN)

    assert response.status_code == 200
    assert [m.tenant_id for m in rig.bus.enqueued_to("inbound.receipts")] == [OWN_ID]
