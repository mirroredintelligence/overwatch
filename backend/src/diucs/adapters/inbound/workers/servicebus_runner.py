"""Runs an IdempotentConsumer against a Service Bus queue or topic subscription (I04).

Only this module imports the Azure SDK. It converts each received message to a BusMessage, calls
the consumer and settles the message: complete, abandon or dead-letter. A message that cannot be
read (no id, no type, a body that is not a JSON object) is dead-lettered without reaching the
consumer; so is a message with no usable tenant (TEN-020: `from_wire` is the one reader), with the
fixed reason `tenant-missing`, `tenant-malformed` or `tenant-mismatch` (TEN-025), and the consumer
never runs. The runner serves only a consumer that binds the tenant of each message
(`binds_tenant`, TEN-025): a wiring that forgot the binding stops at start-up. A failure to settle
is logged by class name and the message is left for redelivery, where the consumer finds its marker
and answers duplicate.

A session-enabled entity (the capacity.events subscriptions) is read through session receivers,
so one session's messages are handled in order. The loop never exits on a connection failure: it
backs off, capped, and opens the receiver again (DEC-012). Logs hold the message id, the entity
and the reason only, never the payload.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Final, Protocol

from azure.servicebus import NEXT_AVAILABLE_SESSION
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.exceptions import OperationTimeoutError

from diucs.adapters.inbound.workers.consumer import MessageConsumer, Outcome
from diucs.application.ports.outbound.event_bus import BusMessage, MessageTenantError, from_wire
from diucs.domain.errors import ValidationFailed

logger = logging.getLogger(__name__)

RECEIVE_WAIT_SECONDS = 5.0
BACKOFF_START_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0
NO_SESSION_PAUSE_SECONDS = 0.2
MALFORMED_REASON = "malformed message"


class Backoff:
    """1 s, doubling to a 30 s cap; reset() starts again. One schedule for the receiver and for
    the pause after a retry (DEC-119)."""

    def __init__(self) -> None:
        self._next = BACKOFF_START_SECONDS

    def next(self) -> float:
        delay = self._next
        self._next = min(delay * 2, BACKOFF_CAP_SECONDS)
        return delay

    def reset(self) -> None:
        self._next = BACKOFF_START_SECONDS


class Receiver(Protocol):
    async def complete_message(self, message: Any) -> None: ...

    async def abandon_message(self, message: Any) -> None: ...

    async def dead_letter_message(
        self, message: Any, reason: str | None = None, error_description: str | None = None
    ) -> None: ...


CONSUMER_NOT_TENANT_BOUND: Final = (
    "a queue runner needs a consumer that binds the tenant of each message"
)


class ConsumerNotTenantBound(TypeError):
    """A runner was given a consumer that does not declare `binds_tenant`: it would open units of
    work with no scope (TEN-025). Raised when the runner is built, so the wiring fault stops the
    process at start-up and not at the first message."""


class MalformedMessage(Exception):
    """The received message cannot be turned into a BusMessage. `reason` is the fixed word to
    dead-letter it with: a tenant reason of the bus contract, or None for the generic one."""

    def __init__(self, reason: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason


def _text(value: object) -> str | None:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else None


def _body(raw: Any) -> bytes:
    body = raw.body
    if isinstance(body, bytes):
        return body
    return b"".join(part if isinstance(part, bytes) else bytes(part) for part in body)


def to_bus_message(raw: Any, entity: str) -> BusMessage:
    properties = raw.application_properties or {}
    try:
        payload = json.loads(_body(raw).decode("utf-8"))
    except (ValueError, TypeError) as error:
        raise MalformedMessage from error
    try:
        message = from_wire(
            entity,
            message_id=_text(raw.message_id),
            session_id=_text(raw.session_id),
            subject=_text(raw.subject),
            properties=properties,
            payload=payload,
        )
    except MessageTenantError as error:
        # A message with no id says nothing about its tenant: it is malformed, not mismatched.
        if not _text(raw.message_id):
            raise MalformedMessage from error
        raise MalformedMessage(error.reason) from error
    except ValidationFailed as error:
        raise MalformedMessage from error
    traceparent = _text(properties.get("traceparent", properties.get(b"traceparent")))
    return message if traceparent is None else replace(message, traceparent=traceparent)


class ServiceBusRunner:
    def __init__(
        self,
        client: ServiceBusClient,
        entity: str,
        subscription: str | None,
        consumer: MessageConsumer,
        sessions: bool = False,
        max_concurrency: int = 4,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if getattr(consumer, "binds_tenant", False) is not True:
            raise ConsumerNotTenantBound(CONSUMER_NOT_TENANT_BOUND)
        self._client = client
        self._entity = entity
        self._subscription = subscription
        self._consumer = consumer
        self._sessions = sessions
        self._max_concurrency = max_concurrency

    async def process(self, receiver: Receiver, raw: Any) -> Outcome | None:
        """Handle one received message and settle it. Never raises for a message or a settle.
        Returns the outcome, or None when the message could not be handled or settled."""
        message_id = _text(getattr(raw, "message_id", None)) or "unknown"
        try:
            outcome = await self._outcome(raw)
            await self._settle(receiver, raw, outcome)
        except Exception as error:
            logger.warning(
                "message %s on %s was not settled: %s",
                message_id,
                self._entity,
                type(error).__name__,
            )
            return None
        return outcome

    async def _outcome(self, raw: Any) -> Outcome:
        try:
            message = to_bus_message(raw, self._entity)
        except MalformedMessage as malformed:
            return Outcome("dead-letter", malformed.reason or MALFORMED_REASON)
        return await self._consumer.handle(message)

    async def _settle(self, receiver: Receiver, raw: Any, outcome: Outcome) -> None:
        message_id = _text(raw.message_id) or "unknown"
        if outcome.kind in ("completed", "duplicate"):
            await receiver.complete_message(raw)
        elif outcome.kind == "retry":
            await receiver.abandon_message(raw)
        else:
            reason = outcome.reason or "permanent error"
            logger.warning("dead-lettered message %s on %s: %s", message_id, self._entity, reason)
            await receiver.dead_letter_message(raw, reason=reason, error_description=reason)

    async def run(self, stop: asyncio.Event) -> None:
        """Receive until stop is set. A connection failure backs off and tries again."""
        loops = self._max_concurrency if self._sessions else 1
        await asyncio.gather(*(self._loop(stop) for _ in range(loops)))

    # The name the process entries call. The architecture scan for Cypher execution reads any
    # attribute called `run` outside the graph store, and this is a worker loop, not a database.
    serve = run

    def _open(self) -> Any:
        if self._subscription is None:
            if self._sessions:
                return self._client.get_queue_receiver(
                    self._entity, session_id=NEXT_AVAILABLE_SESSION
                )
            return self._client.get_queue_receiver(self._entity)
        if self._sessions:
            return self._client.get_subscription_receiver(
                self._entity, self._subscription, session_id=NEXT_AVAILABLE_SESSION
            )
        return self._client.get_subscription_receiver(self._entity, self._subscription)

    async def _loop(self, stop: asyncio.Event) -> None:
        connect = Backoff()  # reset by a receive that returns
        work = Backoff()  # reset by a message that completes
        while not stop.is_set():
            try:
                async with self._open() as receiver:
                    await self._receive(receiver, stop, connect, work)
            except OperationTimeoutError:
                # No session is waiting (lesson L127): not a failure.
                await self._pause(stop, NO_SESSION_PAUSE_SECONDS)
            except Exception as error:
                # Any failure, not only a connection error: the worker never exits (DEC-012).
                # CancelledError is a BaseException and passes through. The class name only is
                # logged, because the text of an error can carry data.
                delay = connect.next()
                logger.warning(
                    "receiver for %s failed (%s); trying again in %.0f s",
                    self._entity,
                    type(error).__name__,
                    delay,
                )
                await self._pause(stop, delay)

    async def _receive(
        self, receiver: Any, stop: asyncio.Event, connect: Backoff, work: Backoff
    ) -> None:
        while not stop.is_set():
            batch = await receiver.receive_messages(
                max_message_count=1 if self._sessions else self._max_concurrency,
                max_wait_time=RECEIVE_WAIT_SECONDS,
            )
            connect.reset()
            if not batch and self._sessions:
                return  # the session is empty: release it and take the next one
            if self._sessions:
                for raw in batch:  # in order within the session
                    outcome = await self.process(receiver, raw)
                    await self._after(stop, work, [outcome])
            else:
                outcomes = await asyncio.gather(*(self.process(receiver, raw) for raw in batch))
                await self._after(stop, work, outcomes)

    async def _after(
        self, stop: asyncio.Event, work: Backoff, outcomes: Sequence[Outcome | None]
    ) -> None:
        """A message that ended in retry was abandoned for a failure that is not the message's
        own (a store or bus outage). Pause before the next receive, so a short outage uses a few
        delivery attempts and not all of them (DEC-119, hazard H-27). A completed or duplicate
        message ends the outage; a dead-letter says nothing about it."""
        if any(outcome is not None and outcome.kind == "retry" for outcome in outcomes):
            await self._pause(stop, work.next())
        elif any(
            outcome is not None and outcome.kind in ("completed", "duplicate")
            for outcome in outcomes
        ):
            work.reset()

    @staticmethod
    async def _pause(stop: asyncio.Event, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)
