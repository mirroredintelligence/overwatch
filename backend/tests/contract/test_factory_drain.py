"""The Service Bus factory clears leftovers before a case, even one it cannot read (I02).

A leftover written by another run on the shared emulator may not be the contract's JSON. The
drain must remove it and move on, not stop the case in setup. The fakes stand in for the SDK
receiver (an external provider)."""

from typing import Any

from tests.contract.factories import _drain


class _Message:
    def __init__(self, body: bytes) -> None:
        self.body = [body]
        self.message_id = "leftover"
        self.subject = "svc-1 update"
        self.session_id = None


class _LeftoverReceiver:
    """Holds one message that is not JSON, then nothing."""

    def __init__(self, queue: list[_Message], completed: list[_Message]) -> None:
        self._queue = queue
        self._completed = completed

    async def __aenter__(self) -> _LeftoverReceiver:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def receive_messages(self, **kwargs: Any) -> list[_Message]:
        return [self._queue.pop()] if self._queue else []

    async def complete_message(self, message: _Message) -> None:
        self._completed.append(message)


class _FakeClient:
    def __init__(self, leftovers: list[_Message]) -> None:
        self.queue = leftovers
        self.completed: list[_Message] = []

    def get_queue_receiver(self, *args: Any, **kwargs: Any) -> _LeftoverReceiver:
        return _LeftoverReceiver(self.queue, self.completed)

    def get_subscription_receiver(self, *args: Any, **kwargs: Any) -> _LeftoverReceiver:
        return _LeftoverReceiver(self.queue, self.completed)


async def test_the_drain_removes_a_leftover_it_cannot_read() -> None:
    client = _FakeClient([_Message(b"svc-1 update")])
    await _drain(client, client, ("scheduled.work",))  # type: ignore[arg-type]
    assert len(client.completed) == 1
    assert client.queue == []


async def test_the_drain_stops_when_nothing_is_waiting() -> None:
    client = _FakeClient([])
    await _drain(client, client, ("scheduled.work",))  # type: ignore[arg-type]
    assert client.completed == []
