"""A reply that meets a failing service is tried again, then reported, never silently lost.

The case that began it: a "Y" to a capacity prompt reached Twilio and the webhook, a connection to
a service failed, the webhook answered 500 and Twilio does not call a text webhook again, so the
reply vanished and the log said only `ConnectionError`. Now each call that reaches another service
(the sender lookup, the replay marker, the queue) is tried again; each failure is logged with its
traceback and the step's name; when every attempt fails the sender is told to send it again, the
replay marker is released so that second try is accepted, and the log carries `sms reply lost`.
Every value is invented.
"""

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from overwatch.adapters.inbound.sms_webhook import routes
from overwatch.adapters.inbound.sms_webhook.routes import REPLY_PATH, SmsWebhookDeps, router
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
    OWN,
    OWN_SID,
    OWN_TOKEN,
    _RegistryDirectory,
    _sign,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

SID = "SM" + "4" * 32


class _Flaky:
    """Fails the first `failures` calls with a ConnectionError, then works."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def maybe_fail(self) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("connection reset")


class _Rig:
    def __init__(self, *, lookup: int = 0, cache: int = 0, bus: int = 0) -> None:
        clock = FixedClock(datetime(2026, 11, 10, 10, 1, tzinfo=UTC))
        self.lookup = _Flaky(lookup)
        self.cache_faults = _Flaky(cache)
        self.bus_faults = _Flaky(bus)
        secrets = FixedSecretStore(
            {PHONE_HASH_SECRET: b"unit-test-phone-hash-key", twilio_token_ref(SAMPLE_ID): OWN_TOKEN}
        )
        memory = InMemoryCache(clock)
        self.memory = memory
        real_set = memory.set_if_absent

        async def set_if_absent(*args: Any, **kwargs: Any) -> bool:
            self.cache_faults.maybe_fail()
            return await real_set(*args, **kwargs)

        memory.set_if_absent = set_if_absent  # type: ignore[method-assign]
        self.bus = ManualEventBus(clock)
        real_enqueue = self.bus.enqueue

        async def enqueue(*args: Any, **kwargs: Any) -> None:
            self.bus_faults.maybe_fail()
            await real_enqueue(*args, **kwargs)

        self.bus.enqueue = enqueue  # type: ignore[method-assign]
        lookup_faults = self.lookup

        async def find(phone_hash: str) -> object:
            lookup_faults.maybe_fail()
            return object()

        class Unit:
            people = SimpleNamespace(find_by_phone_hash=find)

            async def __aenter__(self) -> Unit:
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

        self.app = FastAPI()
        self.app.include_router(router)
        self.app.state.sms_webhook = SmsWebhookDeps(
            cache=memory,
            event_bus=self.bus,
            hasher=HmacPhoneHasher(secrets),
            secrets=secrets,
            lines=DirectoryInboundLines(_RegistryDirectory()),  # type: ignore[arg-type]
            public_base_url=BASE,
        )
        self.app.state.container = SimpleNamespace(clock=clock, uow_factory=Unit)

    async def reply(self) -> Any:
        params = {
            "AccountSid": OWN_SID,
            "MessageSid": SID,
            "From": "+447700900456",
            "To": OWN,
            "Body": "Y",
            "NumMedia": "0",
        }
        headers = {**FORM, "X-Twilio-Signature": _sign(BASE + REPLY_PATH, params, OWN_TOKEN)}
        async with AsyncClient(
            transport=ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://internal:8000",
        ) as client:
            return await client.post(REPLY_PATH, data=params, headers=headers)


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(routes.asyncio, "sleep", instant)


@pytest.mark.parametrize("which", ["lookup", "cache", "bus"])
async def test_a_service_that_fails_once_does_not_lose_the_reply(which: str) -> None:
    rig = _Rig(**{which: 1})

    response = await rig.reply()

    assert response.status_code == 200 and b"Message" not in response.content
    assert len(rig.bus.enqueued_to("inbound.replies")) == 1


@pytest.mark.parametrize("which", ["lookup", "cache", "bus"])
async def test_a_service_that_fails_every_time_tells_the_sender_to_try_again_and_is_logged(
    which: str, caplog: pytest.LogCaptureFixture
) -> None:
    rig = _Rig(**{which: 99})

    with caplog.at_level(logging.INFO):
        response = await rig.reply()

    assert response.status_code == 200 and b"send it again" in response.content
    assert rig.bus.enqueued_to("inbound.replies") == []
    lost = [r for r in caplog.records if "sms reply lost" in r.getMessage()]
    assert len(lost) == 1 and SID in lost[0].getMessage()
    failed = [r for r in caplog.records if "sms reply step failed" in r.getMessage()]
    assert len(failed) == routes.ATTEMPTS
    assert all(r.exc_info is not None for r in failed)  # the traceback names the service


async def test_a_reply_lost_at_the_queue_can_be_sent_again_and_is_not_taken_for_a_replay() -> None:
    rig = _Rig(bus=routes.ATTEMPTS)  # the first reply's every attempt fails, then the queue is well

    first = await rig.reply()
    second = await rig.reply()

    assert b"send it again" in first.content
    assert second.status_code == 200 and b"Message" not in second.content
    assert len(rig.bus.enqueued_to("inbound.replies")) == 1


async def test_an_unhandled_error_is_logged_with_its_place_and_never_its_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from overwatch.adapters.inbound.fhir_rest.errors import _where

    def deep() -> None:
        raise ConnectionError("secret-host-name.example and a patient name")

    try:
        deep()
    except ConnectionError as error:
        place = _where(error)

    assert "deep" in place and "test_reply_retries.py" in place
    assert "secret-host-name" not in place and "patient" not in place
