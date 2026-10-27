"""Characterisation of two harness values that the emulator and the timing decide (DEC-102 item 9).

Each test fails if its value is reverted. Neither can be red before its change: the emulator
timing is measured against a live emulator, and the retry setting is observable only through the
client the factory builds."""

from datetime import timedelta
from typing import Any

import pytest

from tests.contract import factories
from tests.contract.test_event_bus_contract import CANCEL_DELAY

# The smallest due time the emulator 2.0.1 held after a cancel (DEC-102 item 3: 17 s held,
# 10 s delivered). A CANCEL_DELAY below this lets the emulator deliver a cancelled message.
MEASURED_HELD_FROM = timedelta(seconds=17)


def test_the_cancel_delay_is_past_the_emulator_window() -> None:
    assert CANCEL_DELAY >= MEASURED_HELD_FROM


class _RecordingClient:
    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_the_session_client_fails_fast_and_the_send_client_keeps_its_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[_RecordingClient] = []

    def fake_client(**options: Any) -> _RecordingClient:
        client = _RecordingClient(options)
        built.append(client)
        return client

    async def no_drain(*args: Any) -> None:
        return None

    monkeypatch.setattr(factories, "servicebus_client", fake_client)
    monkeypatch.setattr(factories, "_drain", no_drain)
    harness = await factories.make_servicebus_event_bus()
    await harness.close()

    assert {"retry_total": 0} in [client.options for client in built]
    assert {} in [client.options for client in built]
