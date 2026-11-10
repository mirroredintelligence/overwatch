"""A delivery receipt that meets a failing queue is tried again, then answered 503 and logged.

Receipts are applied by status and are safe to apply again, so after every attempt fails the answer
is a 503 (Twilio shows it in its debugger) and the log says `sms receipt lost` with the step. Every
value is invented.
"""

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from overwatch.adapters.inbound.sms_webhook import routes
from overwatch.adapters.inbound.sms_webhook.routes import STATUS_PATH, SmsWebhookDeps, router
from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.adapters.testing.memory_cache import InMemoryCache
from overwatch.adapters.testing.memory_event_bus import ManualEventBus
from overwatch.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from overwatch.application.ports.outbound.tenants import twilio_token_ref
from overwatch.application.tenant_resolution import DirectoryInboundLines
from tests.support.tenant_samples import SAMPLE_ID
from tests.unit.adapters.inbound.sms_webhook.test_shared_line import (
    BASE,
    FORM,
    OWN_SID,
    OWN_TOKEN,
    _RegistryDirectory,
    _sign,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _Rig:
    def __init__(self, failures: int) -> None:
        clock = FixedClock(datetime(2026, 11, 10, 10, 2, tzinfo=UTC))
        self.failures = failures
        self.calls = 0
        secrets = FixedSecretStore(
            {PHONE_HASH_SECRET: b"unit-test-phone-hash-key", twilio_token_ref(SAMPLE_ID): OWN_TOKEN}
        )
        self.bus = ManualEventBus(clock)
        real = self.bus.enqueue

        async def enqueue(*args: Any, **kwargs: Any) -> None:
            self.calls += 1
            if self.calls <= self.failures:
                raise ConnectionError("connection reset")
            await real(*args, **kwargs)

        self.bus.enqueue = enqueue  # type: ignore[method-assign]
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.state.sms_webhook = SmsWebhookDeps(
            cache=InMemoryCache(clock),
            event_bus=self.bus,
            hasher=HmacPhoneHasher(secrets),
            secrets=secrets,
            lines=DirectoryInboundLines(_RegistryDirectory()),  # type: ignore[arg-type]
            public_base_url=BASE,
        )
        self.app.state.container = SimpleNamespace(clock=clock, uow_factory=None)

    async def receipt(self) -> Any:
        params = {
            "AccountSid": OWN_SID,
            "MessageSid": "SM" + "5" * 32,
            "MessageStatus": "delivered",
            "From": "+447700900123",
            "To": "+447700900456",
        }
        headers = {**FORM, "X-Twilio-Signature": _sign(BASE + STATUS_PATH, params, OWN_TOKEN)}
        async with AsyncClient(
            transport=ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://internal:8000",
        ) as client:
            return await client.post(STATUS_PATH, data=params, headers=headers)


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(routes.asyncio, "sleep", instant)


async def test_a_queue_that_fails_once_does_not_lose_the_receipt() -> None:
    rig = _Rig(failures=1)

    response = await rig.receipt()

    assert response.status_code == 200
    assert len(rig.bus.enqueued_to("inbound.receipts")) == 1


async def test_a_queue_that_always_fails_is_a_503_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = _Rig(failures=99)

    with caplog.at_level(logging.INFO):
        response = await rig.receipt()

    assert response.status_code == 503
    assert rig.calls == routes.ATTEMPTS
    assert any("sms receipt lost: step=receipt-enqueue" in r.getMessage() for r in caplog.records)
