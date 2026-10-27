"""The session receive window in the Service Bus factory stays inside the contract budget (I02).

The fakes below stand in for the SDK receiver (an external provider): they raise the open timeout
the emulator raises, and record the window the factory asked for."""

from datetime import timedelta
from typing import Any

import pytest
from azure.servicebus.exceptions import OperationTimeoutError

from tests.contract.factories import _receive_from, session_open_window


def test_a_session_open_window_never_exceeds_the_budget() -> None:
    assert session_open_window(timedelta(hours=1)) == 10.0


def test_a_short_wait_gets_the_minimum_session_open_window() -> None:
    assert session_open_window(timedelta(milliseconds=200)) == 5.0


class _TimingOutReceiver:
    """Opening the link times out, as it does on the emulator when nothing is waiting."""

    async def __aenter__(self) -> _TimingOutReceiver:
        raise OperationTimeoutError(message="no session is waiting")

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeClient:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def get_subscription_receiver(self, *args: Any, **kwargs: Any) -> _TimingOutReceiver:
        self.kwargs = kwargs
        return _TimingOutReceiver()

    def get_queue_receiver(self, *args: Any, **kwargs: Any) -> _TimingOutReceiver:
        self.kwargs = kwargs
        return _TimingOutReceiver()


async def test_a_timed_out_topic_session_open_is_no_message() -> None:
    client = _FakeClient()
    assert await _receive_from(client, client, "capacity.events", timedelta(seconds=2)) is None  # type: ignore[arg-type]


async def test_a_timed_out_queue_open_is_raised_not_swallowed() -> None:
    client = _FakeClient()
    with pytest.raises(OperationTimeoutError):
        await _receive_from(client, client, "scheduled.work", timedelta(seconds=2))  # type: ignore[arg-type]


async def test_the_factory_passes_a_bounded_window_to_the_session_receiver() -> None:
    client = _FakeClient()
    await _receive_from(client, client, "capacity.events", timedelta(hours=1))  # type: ignore[arg-type]
    assert client.kwargs["max_wait_time"] == 10.0
