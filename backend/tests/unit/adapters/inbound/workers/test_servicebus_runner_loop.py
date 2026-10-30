"""The runner's receive loop against a fake client (I04, DEC-012): session receivers, the
reconnect backoff, and the pause that keeps a short outage from burning delivery attempts
(hazard H-27). No Docker and no Service Bus: the client, receivers and consumer are fakes, and
the pause is recorded instead of slept."""

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from azure.servicebus import NEXT_AVAILABLE_SESSION
from azure.servicebus.exceptions import (
    OperationTimeoutError,
    ServiceBusConnectionError,
    ServiceBusError,
)

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.application.ports.outbound.event_bus import BusMessage

BLOCK = "block"  # a script item: receive_messages waits until the task is cancelled


def _raw(message_id: str) -> Any:
    # As the adapter sends it (TEN-020): the id is qualified and the tenant is a property.
    return SimpleNamespace(
        message_id=f"tenant-a:{message_id}",
        body=[b"{}"],
        subject="CapacityReported",
        session_id=None,
        application_properties={"tenantId": "tenant-a"},
        delivery_count=1,
    )


def _local(raw: Any) -> str:
    """The message id without its tenant: what the test named it."""
    return str(raw.message_id).partition(":")[2]


class _World:
    """One shared record of what the fake client, receivers, consumer and pause did."""

    def __init__(self, script: list[Any], stop: asyncio.Event) -> None:
        self.script = script
        self.stop = stop
        self.log: list[tuple[Any, ...]] = []
        self.opens: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.open_failures: list[BaseException | None] = []
        self.redeliver: list[Any] = []
        self.redelivers = False  # an abandoned message comes back, as the bus does
        self.receivers = 0


class _Receiver:
    def __init__(self, world: _World, failure: BaseException | None) -> None:
        world.receivers += 1
        self.number = world.receivers
        self._world = world
        self._failure = failure

    async def __aenter__(self) -> _Receiver:
        await asyncio.sleep(0)  # lets every loop open its receiver before any one receives
        if self._failure is not None:
            raise self._failure
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._world.log.append(("close", self.number))

    async def receive_messages(self, max_message_count: int, max_wait_time: float) -> list[Any]:
        world = self._world
        world.log.append(("receive", self.number, max_message_count))
        if world.redeliver:
            batch, world.redeliver[:] = list(world.redeliver), []
            return batch
        if not world.script:
            world.stop.set()
            return []
        item = world.script.pop(0)
        if item == BLOCK:
            await asyncio.Event().wait()
        if isinstance(item, BaseException):
            raise item
        return list(item)

    async def complete_message(self, raw: Any) -> None:
        self._world.log.append(("complete", _local(raw), self.number))

    async def abandon_message(self, raw: Any) -> None:
        self._world.log.append(("abandon", _local(raw), self.number))
        if self._world.redelivers:
            self._world.redeliver.append(raw)

    async def dead_letter_message(
        self, raw: Any, reason: str | None = None, error_description: str | None = None
    ) -> None:
        self._world.log.append(("dead-letter", _local(raw), self.number))


class _Client:
    def __init__(self, world: _World) -> None:
        self._world = world

    def _receiver(self, kind: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> _Receiver:
        self._world.opens.append((kind, args, kwargs))
        failure = self._world.open_failures.pop(0) if self._world.open_failures else None
        return _Receiver(self._world, failure)

    def get_queue_receiver(self, *args: Any, **kwargs: Any) -> _Receiver:
        return self._receiver("queue", args, kwargs)

    def get_subscription_receiver(self, *args: Any, **kwargs: Any) -> _Receiver:
        return self._receiver("subscription", args, kwargs)


class _Consumer:
    name = "board-projector"
    binds_tenant = True  # the runner serves only a consumer that binds the tenant (TEN-025)

    def __init__(self, world: _World, outcomes: dict[str, list[Outcome]] | None = None) -> None:
        self._world = world
        self._outcomes = outcomes or {}
        self.default = Outcome("completed")

    async def handle(self, message: BusMessage) -> Outcome:
        self._world.log.append(("start", message.id))
        await asyncio.sleep(0)
        self._world.log.append(("end", message.id))
        queued = self._outcomes.get(message.id)
        return queued.pop(0) if queued else self.default


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    script: list[Any],
    *,
    subscription: str | None = None,
    sessions: bool = False,
    max_concurrency: int = 4,
    outcomes: dict[str, list[Outcome]] | None = None,
) -> tuple[ServiceBusRunner, _World, asyncio.Event]:
    stop = asyncio.Event()
    world = _World(script, stop)
    runner = ServiceBusRunner(
        client=_Client(world),  # type: ignore[arg-type]
        entity="capacity.events",
        subscription=subscription,
        consumer=_Consumer(world, outcomes),  # type: ignore[arg-type]
        sessions=sessions,
        max_concurrency=max_concurrency,
    )

    async def pause(stop_event: asyncio.Event, seconds: float) -> None:
        world.log.append(("pause", seconds))
        await asyncio.sleep(0)

    monkeypatch.setattr(runner, "_pause", pause)
    return runner, world, stop


def _pauses(world: _World) -> list[float]:
    return [entry[1] for entry in world.log if entry[0] == "pause"]


def _actions(world: _World, *names: str) -> list[tuple[Any, ...]]:
    return [entry for entry in world.log if entry[0] in names]


async def _run(runner: ServiceBusRunner, stop: asyncio.Event) -> None:
    await asyncio.wait_for(runner.run(stop), timeout=10)


# --- session receivers -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subscription", "kind", "args"),
    [
        (None, "queue", ("capacity.events",)),
        ("board-projector", "subscription", ("capacity.events", "board-projector")),
    ],
    ids=["queue", "subscription"],
)
async def test_sessions_open_one_next_available_session_receiver_per_unit_of_concurrency(
    monkeypatch: pytest.MonkeyPatch, subscription: str | None, kind: str, args: tuple[str, ...]
) -> None:
    runner, world, stop = _setup(
        monkeypatch, [], subscription=subscription, sessions=True, max_concurrency=3
    )
    await _run(runner, stop)
    assert world.opens[:3] == [(kind, args, {"session_id": NEXT_AVAILABLE_SESSION})] * 3


@pytest.mark.parametrize("subscription", [None, "board-projector"], ids=["queue", "subscription"])
async def test_without_sessions_exactly_one_receiver_is_opened_for_the_whole_batch(
    monkeypatch: pytest.MonkeyPatch, subscription: str | None
) -> None:
    runner, world, stop = _setup(
        monkeypatch, [[_raw("a")]], subscription=subscription, sessions=False, max_concurrency=4
    )
    await _run(runner, stop)
    assert len(world.opens) == 1
    assert "session_id" not in world.opens[0][2]
    assert _actions(world, "receive")[0][2] == 4


async def test_a_session_reads_one_message_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, world, stop = _setup(monkeypatch, [[_raw("a")]], sessions=True, max_concurrency=3)
    await _run(runner, stop)
    assert _actions(world, "receive")[0][2] == 1


async def test_a_sessions_messages_are_handled_in_order_one_after_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, world, stop = _setup(
        monkeypatch, [[_raw("a"), _raw("b"), _raw("c")]], sessions=True, max_concurrency=1
    )
    await _run(runner, stop)
    handled = [entry[:2] for entry in _actions(world, "start", "end")]
    assert handled == [
        ("start", "a"),
        ("end", "a"),
        ("start", "b"),
        ("end", "b"),
        ("start", "c"),
        ("end", "c"),
    ]


async def test_without_sessions_a_batch_is_handled_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, world, stop = _setup(monkeypatch, [[_raw("a"), _raw("b")]], max_concurrency=2)
    await _run(runner, stop)
    handled = [entry[:2] for entry in _actions(world, "start", "end")]
    assert handled[:2] == [("start", "a"), ("start", "b")]


async def test_an_empty_batch_releases_the_session_and_the_next_one_is_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, world, stop = _setup(
        monkeypatch, [[_raw("a")], [], [_raw("b")]], sessions=True, max_concurrency=1
    )
    await _run(runner, stop)
    assert len(world.opens) >= 2
    assert ("complete", "a", 1) in world.log
    assert ("close", 1) in world.log
    assert ("complete", "b", 2) in world.log
    assert world.log.index(("close", 1)) < world.log.index(("complete", "b", 2))


async def test_without_sessions_an_empty_batch_keeps_the_receiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, world, stop = _setup(monkeypatch, [[], [_raw("a")]])
    await _run(runner, stop)
    assert len(world.opens) == 1
    assert ("complete", "a", 1) in world.log


@pytest.mark.parametrize("bad", [0, -1])
def test_max_concurrency_below_one_is_refused(bad: int) -> None:
    with pytest.raises(ValueError, match="max_concurrency"):
        ServiceBusRunner(None, "q", None, None, max_concurrency=bad)  # type: ignore[arg-type]


# --- reconnect and backoff ---------------------------------------------------------------------


async def test_the_receiver_backoff_doubles_and_stops_at_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures = [ServiceBusConnectionError(message="down")] * 7
    runner, world, stop = _setup(monkeypatch, failures)
    await _run(runner, stop)
    assert _pauses(world) == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


async def test_the_receiver_backoff_starts_again_after_a_successful_receive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = [
        ServiceBusError(message="a"),
        ServiceBusError(message="b"),
        ServiceBusError(message="c"),
        [_raw("m")],
    ]
    script += [ServiceBusError(message="d"), ServiceBusError(message="e")]
    runner, world, stop = _setup(monkeypatch, script)
    await _run(runner, stop)
    assert _pauses(world) == [1.0, 2.0, 4.0, 1.0, 2.0]


async def test_a_failure_to_open_the_receiver_backs_off_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, world, stop = _setup(monkeypatch, [[_raw("m")]])
    world.open_failures[:] = [ServiceBusConnectionError(message="down"), OSError("no")]
    await _run(runner, stop)
    assert _pauses(world) == [1.0, 2.0]
    assert ("complete", "m", 3) in world.log


async def test_a_timeout_opening_a_session_is_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = [
        OperationTimeoutError(message="t"),
        OperationTimeoutError(message="t"),
        ServiceBusError(message="x"),
    ]
    runner, world, stop = _setup(monkeypatch, script, sessions=True, max_concurrency=1)
    await _run(runner, stop)
    # Two short pauses for the timeouts, then the first real failure starts at 1 s.
    assert _pauses(world) == [0.2, 0.2, 1.0]


@pytest.mark.parametrize(
    "error",
    [ServiceBusConnectionError(message="down"), OSError("reset"), ServiceBusError(message="x")],
)
async def test_the_loop_reconnects_after_a_connection_error(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    runner, world, stop = _setup(monkeypatch, [error, [_raw("m")]])
    await _run(runner, stop)
    assert ("complete", "m", 2) in world.log
    assert len(world.opens) >= 2


async def test_any_other_error_from_the_receiver_does_not_end_the_worker(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    runner, world, stop = _setup(monkeypatch, [RuntimeError("boom for 4821"), [_raw("m")]])
    with caplog.at_level(logging.DEBUG):
        await _run(runner, stop)
    assert ("complete", "m", 2) in world.log
    assert _pauses(world)[0] == 1.0
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in text
    assert "4821" not in text


async def test_any_error_opening_the_receiver_does_not_end_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, world, stop = _setup(monkeypatch, [[_raw("m")]])
    world.open_failures[:] = [RuntimeError("no")]
    await _run(runner, stop)
    assert ("complete", "m", 2) in world.log


async def test_cancelling_the_runner_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, world, stop = _setup(monkeypatch, [BLOCK])
    task = asyncio.create_task(runner.run(stop))
    while not _actions(world, "receive"):
        await asyncio.sleep(0)
    opened = len(world.opens)
    marker = len(world.log)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
    # A swallowed cancellation keeps the loop running: it would pause, open a receiver and
    # receive again. The gather still re-raises at the end, so the raise alone cannot tell.
    assert len(world.opens) == opened
    assert not [entry for entry in world.log[marker:] if entry[0] == "receive"]


async def test_the_stop_signal_ends_a_pause_at_once() -> None:
    stop = asyncio.Event()
    stop.set()
    await asyncio.wait_for(ServiceBusRunner._pause(stop, 30.0), timeout=1)


async def test_a_pause_lasts_its_time_when_nothing_stops_it() -> None:
    stop = asyncio.Event()
    started = asyncio.get_running_loop().time()
    await ServiceBusRunner._pause(stop, 0.05)
    assert asyncio.get_running_loop().time() - started >= 0.04
    assert not stop.is_set()


# --- short outages must not burn delivery attempts (H-27) ---------------------------------------


def _retry(reason: str = "ConnectionError") -> Outcome:
    return Outcome("retry", reason)


async def test_a_retry_pauses_before_the_next_receive_and_the_message_is_still_abandoned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, world, stop = _setup(monkeypatch, [[_raw("a")]], outcomes={"a": [_retry()]})
    await _run(runner, stop)
    order = [entry[:2] for entry in world.log if entry[0] in ("receive", "abandon", "pause")]
    assert order[:4] == [("receive", 1), ("abandon", "a"), ("pause", 1.0), ("receive", 1)]


async def test_the_retry_pause_grows_to_the_cap_and_starts_again_after_a_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = [f"m{n}" for n in range(9)]
    outcomes = {name: [_retry()] for name in ids}
    outcomes["m6"] = [Outcome("completed")]
    outcomes["m8"] = [Outcome("duplicate")]
    script = [[_raw(name)] for name in ids] + [[_raw("last")]]
    runner, world, stop = _setup(monkeypatch, script, outcomes={**outcomes, "last": [_retry()]})
    await _run(runner, stop)
    # m0..m5 retry: 1, 2, 4, 8, 16, 30; m6 completes and resets; m7 retries: 1; m8 duplicate
    # resets; "last" retries: 1.
    assert _pauses(world) == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 1.0, 1.0]


async def test_a_dead_letter_neither_pauses_nor_resets_the_retry_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = {
        "a": [_retry()],
        "b": [Outcome("dead-letter", "unknown kind")],
        "c": [_retry()],
    }
    script = [[_raw("a")], [_raw("b")], [_raw("c")]]
    runner, world, stop = _setup(monkeypatch, script, outcomes=outcomes)
    await _run(runner, stop)
    assert _pauses(world) == [1.0, 2.0]
    assert ("dead-letter", "b", 1) in world.log


async def test_a_batch_with_retries_pauses_once(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = {"a": [_retry()], "b": [_retry()], "c": [_retry()]}
    runner, world, stop = _setup(
        monkeypatch, [[_raw("a"), _raw("b")], [_raw("c")]], outcomes=outcomes
    )
    await _run(runner, stop)
    assert _pauses(world) == [1.0, 2.0]


async def test_a_session_pauses_between_its_messages_after_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, world, stop = _setup(
        monkeypatch,
        [[_raw("a"), _raw("b")]],
        sessions=True,
        max_concurrency=1,
        outcomes={"a": [_retry()]},
    )
    await _run(runner, stop)
    order = [entry[:2] for entry in world.log if entry[0] in ("abandon", "pause", "start")]
    assert order[:4] == [("start", "a"), ("abandon", "a"), ("pause", 1.0), ("start", "b")]


async def test_a_short_outage_spaces_the_attempts_and_dead_letters_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The store is down for the first four deliveries of one message; the bus redelivers it
    # each time it is abandoned. The pauses space the attempts out: 1 + 2 + 4 + 8 seconds.
    runner, world, stop = _setup(
        monkeypatch, [[_raw("a")]], outcomes={"a": [_retry(), _retry(), _retry(), _retry()]}
    )
    world.redelivers = True
    await _run(runner, stop)
    assert len(_actions(world, "abandon")) == 4
    assert _pauses(world)[:4] == [1.0, 2.0, 4.0, 8.0]
    assert _actions(world, "dead-letter") == []
    assert ("complete", "a", 1) in world.log
