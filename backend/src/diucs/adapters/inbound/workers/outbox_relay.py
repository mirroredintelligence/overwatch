"""Outbox relay worker (I03, DEC-157): publishes the outbox messages that use cases wrote, and turns
the ScheduleWork and CancelWork ones into scheduled Service Bus messages.

At least once. A message is published first and marked published in a new unit of work afterwards,
so a crash in between publishes the same id again; Service Bus duplicate detection and the
idempotent consumers (I04) absorb that. A message is never marked published before the bus call
returns. A bus call that hangs is given up after PUBLISH_TIMEOUT_SECONDS and counted as a failed
attempt. A scheduled message that the bus took before a crash is scheduled again, with the same
message id, so the scheduled-work consumer (which marks an id processed once) absorbs the second
(KI-88).

The relay is a worker, so it has no request and no token. It takes the tenants from a directory
(DEC-134 item 9: it iterates tenants and is not a global statement), and for each one in turn binds
that tenant, takes the single-flight lock, and reads and relays only that tenant's rows in units of
work that open under that tenant (DEC-146). Every message it publishes or schedules carries the
tenant it was read under (`BusMessage.tenant_id`, sent as the `tenantId` property). One tenant's
failures wait on their own backoff and never slow another's round.

Per batch it holds the cache lock `outbox-relay` (30 s) for the tenant bound at that moment: the
cache adapter puts the tenant in front of the name (DEC-130 item 7), so the lock is per tenant once
that adapter change is made and one lock for the whole relay until then. A batch stops before the
lock can have run out, and a lock whose fencing token is not above the last one this relay held is
refused (hazard H-26).

Nothing here logs a payload, an error text or a tenant's data. A failure is recorded by its class
name; a dead message is logged by id, topic and tenant only.

This module is an inbound adapter: ports come in through the constructor, and it imports no
outbound adapter, no driver and no framework.
"""

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol

from diucs.application.idempotency import parse_instant
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.event_bus import BusMessage, EventBus
from diucs.application.ports.outbound.outbox import MAX_ATTEMPTS, OutboxMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.scheduling import CANCEL_WORK, SCHEDULE_WORK, SCHEDULED_WORK_TOPIC
from diucs.application.tenancy import ScopeId, ScopeInvalid, bind_scope
from diucs.application.work import CANCELLED

logger = logging.getLogger(__name__)

LOCK_NAME: Final = "outbox-relay"
LOCK_TTL: Final = timedelta(seconds=30)
# A batch stops this long before the lock runs out: past that point nothing shows that this relay
# still holds it, and a second relay may have started.
LOCK_MARGIN: Final = timedelta(seconds=5)
BATCH_SIZE: Final = 100
POLL_INTERVAL_SECONDS: Final = 1.0
PUBLISH_TIMEOUT_SECONDS: Final = 10.0
"""The longest one bus call may take. A call that hangs is given up and counted as a failed attempt
(`TimeoutError`), and the batch goes on (KI-103). It is well under the lock a batch holds."""
BACKOFF_START_SECONDS: Final = 1.0
BACKOFF_CAP_SECONDS: Final = 60.0
SCHEDULED_WORK_DUE: Final = "ScheduledWorkDue"


@dataclass(frozen=True, slots=True)
class RelayResult:
    """What one round did, over every tenant. `skipped_no_lock` is True when at least one tenant's
    round was left because another holder had its lock (or its lock was refused, H-26)."""

    published: int
    failed: int
    skipped_no_lock: bool


class ActiveTenants(Protocol):
    """The tenants whose outbox this relay serves (the tenant directory, TEN-007). The ids come
    from the platform's own records, never from a request."""

    async def active_tenant_ids(self) -> Sequence[str]: ...


class StaticTenants:
    """A fixed list of tenant ids: the tenant directory for tests, and the configured list the
    process entry uses until the directory adapter exists."""

    def __init__(self, tenant_ids: Sequence[str]) -> None:
        self._tenant_ids = tuple(tenant_ids)

    async def active_tenant_ids(self) -> Sequence[str]:
        return self._tenant_ids


class _Backoff:
    """start, then doubling up to the cap; reset() starts again."""

    def __init__(self, start: float, cap: float) -> None:
        self._start = start
        self._cap = cap
        self._next = start

    def next(self) -> float:
        delay = self._next
        self._next = min(delay * 2, self._cap)
        return delay

    def reset(self) -> None:
        self._next = self._start


@dataclass(slots=True)
class _Wait:
    backoff: _Backoff
    not_before: datetime


class _Outcome(StrEnum):
    PUBLISHED = "published"
    FAILED = "failed"  # the message stays pending and counts an attempt
    STORE_DOWN = "store-down"  # the result could not be written: stop this tenant's batch


@dataclass(frozen=True, slots=True)
class _TenantRound:
    published: int = 0
    failed: int = 0
    skipped_no_lock: bool = False
    trouble: bool = False  # a failure: this tenant waits before its next round


class OutboxRelay:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        bus: EventBus,
        cache: Cache,
        clock: Clock,
        tenants: ActiveTenants,
        batch_size: int = BATCH_SIZE,
        *,
        poll_interval_s: float = POLL_INTERVAL_SECONDS,
        backoff_start_s: float = BACKOFF_START_SECONDS,
        publish_timeout_s: float = PUBLISH_TIMEOUT_SECONDS,
    ) -> None:
        self._uow_factory = uow_factory
        self._bus = bus
        self._cache = cache
        self._clock = clock
        self._tenants = tenants
        self._batch_size = batch_size
        self._poll_interval_s = poll_interval_s
        self._backoff_start_s = backoff_start_s
        self._publish_timeout_s = publish_timeout_s
        self._waits: dict[str, _Wait] = {}
        self._last_token: dict[str, int] = {}
        self._invalid_seen: set[str] = set()

    async def run_once(self) -> RelayResult:
        """One round over every tenant the directory lists, in that order. An error reading the
        directory is raised; every other failure is the tenant's own and is absorbed here."""
        published = failed = 0
        skipped_no_lock = False
        for tenant_id in dict.fromkeys(await self._tenants.active_tenant_ids()):
            scope = self._scope_of(tenant_id)
            if scope is None:
                continue
            tenant_round = await self._relay_tenant(scope)
            published += tenant_round.published
            failed += tenant_round.failed
            skipped_no_lock = skipped_no_lock or tenant_round.skipped_no_lock
        return RelayResult(published, failed, skipped_no_lock)

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Rounds until `stop` is set. It waits a poll interval when a round published nothing, and
        backs off (1 s doubling to 60 s) after a round that failed as a whole, so an outage of the
        directory or the store is waited out and no work is lost (DEC-012)."""
        outage = _Backoff(self._backoff_start_s, BACKOFF_CAP_SECONDS)
        while not stop.is_set():
            try:
                result = await self.run_once()
            except Exception as error:
                logger.error("outbox relay round failed: %s", type(error).__name__)
                await _pause(stop, outage.next())
                continue
            outage.reset()
            if result.published == 0:
                await _pause(stop, self._poll_interval_s)

    def _scope_of(self, tenant_id: str) -> ScopeId | None:
        try:
            return ScopeId.tenant(tenant_id)
        except ScopeInvalid:
            if tenant_id not in self._invalid_seen:
                self._invalid_seen.add(tenant_id)
                logger.error("the tenant directory listed an id that is not a tenant id; skipped")
            return None

    # One tenant

    async def _relay_tenant(self, scope: ScopeId) -> _TenantRound:
        tenant = scope.value
        wait = self._waits.get(tenant)
        if wait is not None and self._clock.now() < wait.not_before:
            return _TenantRound()
        try:
            with bind_scope(scope):
                tenant_round = await self._locked_round(tenant)
        except Exception as error:
            logger.error(
                "outbox relay round failed for tenant %s: %s", tenant, type(error).__name__
            )
            tenant_round = _TenantRound(trouble=True)
        self._settle_wait(tenant, tenant_round)
        return tenant_round

    def _settle_wait(self, tenant: str, tenant_round: _TenantRound) -> None:
        if tenant_round.skipped_no_lock:
            return
        if not tenant_round.trouble:
            self._waits.pop(tenant, None)
            return
        wait = self._waits.get(tenant)
        if wait is None:
            wait = _Wait(_Backoff(self._backoff_start_s, BACKOFF_CAP_SECONDS), self._clock.now())
            self._waits[tenant] = wait
        wait.not_before = self._clock.now() + timedelta(seconds=wait.backoff.next())

    async def _locked_round(self, tenant: str) -> _TenantRound:
        started = self._clock.now()
        lock = await self._cache.acquire_lock(LOCK_NAME, LOCK_TTL)
        if lock is None:
            return _TenantRound(skipped_no_lock=True)
        try:
            if lock.fencing_token <= self._last_token.get(tenant, 0):
                # Hazard H-26: the lock was issued after a clock step back or a loss of the cache.
                # It cannot be trusted, so nothing is relayed until a higher token is issued.
                logger.error("outbox relay lock refused for tenant %s: stale fencing token", tenant)
                return _TenantRound(skipped_no_lock=True)
            self._last_token[tenant] = lock.fencing_token
            return await self._batch(tenant, started)
        finally:
            try:
                await self._cache.release_lock(lock)
            except Exception as error:
                logger.error("outbox relay could not release its lock: %s", type(error).__name__)

    async def _batch(self, tenant: str, started: datetime) -> _TenantRound:
        async with self._uow_factory() as uow:
            pending = await uow.outbox.pending(self._batch_size)
        published = failed = 0
        store_down = False
        for message in pending:
            if self._clock.now() - started >= LOCK_TTL - LOCK_MARGIN:
                break
            outcome = await self._relay_one(tenant, message)
            if outcome is _Outcome.PUBLISHED:
                published += 1
                continue
            failed += 1
            if outcome is _Outcome.STORE_DOWN:
                store_down = True
                break
        # The tenant waits when the store is down or when its round published nothing at all (the
        # bus is down). A round that published some and failed one row has a row of its own that
        # fails: that row counts its attempts and the tenant's other rows are not held back by it
        # (KI-103).
        trouble = store_down or (failed > 0 and published == 0)
        return _TenantRound(published=published, failed=failed, trouble=trouble)

    # One message

    async def _relay_one(self, tenant: str, message: OutboxMessage) -> _Outcome:
        try:
            async with asyncio.timeout(self._publish_timeout_s):
                sequence = await self._send(tenant, message)
        except Exception as error:
            return await self._record_failure(tenant, message, error)
        try:
            await self._record_published(message, sequence)
        except Exception as error:
            # The bus has the message and the store does not know. The row stays pending, so the
            # next round publishes the same id again, which the consumers absorb. It is not a
            # failed publish, so no attempt is counted.
            logger.error(
                "outbox message %s on %s published but not marked: %s",
                message.id,
                message.topic,
                type(error).__name__,
            )
            return _Outcome.STORE_DOWN
        return _Outcome.PUBLISHED

    async def _send(self, tenant: str, message: OutboxMessage) -> int | None:
        """The bus call for one message. Returns the sequence number of a scheduled message."""
        if message.topic == SCHEDULED_WORK_TOPIC and message.event_type == SCHEDULE_WORK:
            return await self._schedule(tenant, message)
        if message.topic == SCHEDULED_WORK_TOPIC and message.event_type == CANCEL_WORK:
            await self._cancel(message)
            return None
        await self._bus.publish(
            BusMessage(
                id=message.id,
                topic=message.topic,
                event_type=message.event_type,
                payload=message.payload,
                session_id=message.session_id,
                tenant_id=tenant,
            )
        )
        return None

    async def _schedule(self, tenant: str, message: OutboxMessage) -> int:
        payload = message.payload
        work_id = str(payload["work_id"])
        enqueue_at = parse_instant(str(payload["enqueue_at"]))
        async with self._uow_factory() as uow:
            work = await uow.scheduled_work.get(work_id)
        number = await self._bus.schedule(
            SCHEDULED_WORK_TOPIC,
            BusMessage(
                id=message.id,
                topic=SCHEDULED_WORK_TOPIC,
                event_type=SCHEDULED_WORK_DUE,
                payload={
                    "work_id": work_id,
                    "kind": payload["kind"],
                    "about_id": payload["about_id"],
                },
                tenant_id=tenant,
            ),
            enqueue_at,
        )
        if work.status == CANCELLED:
            # Cancelled before it was ever scheduled: schedule and cancel at once (the number is
            # still stored, so a CancelWork that comes later finds it).
            await self._bus.cancel(SCHEDULED_WORK_TOPIC, number)
        return number

    async def _cancel(self, message: OutboxMessage) -> None:
        async with self._uow_factory() as uow:
            work = await uow.scheduled_work.get(str(message.payload["work_id"]))
        # No number means the ScheduleWork has not been relayed yet, and it will cancel itself when
        # it finds the work cancelled.
        if work.sequence_number is not None:
            await self._bus.cancel(SCHEDULED_WORK_TOPIC, work.sequence_number)

    async def _record_published(self, message: OutboxMessage, sequence: int | None) -> None:
        """Mark the message published and, for a scheduled one, store the number on its work, in
        one unit of work."""
        async with self._uow_factory() as uow:
            await uow.outbox.mark_published(message.id, self._clock.now())
            if sequence is not None:
                stored = await uow.scheduled_work.get(str(message.payload["work_id"]))
                await uow.scheduled_work.save(replace(stored, sequence_number=sequence))
            await uow.commit()

    async def _record_failure(
        self, tenant: str, message: OutboxMessage, error: Exception
    ) -> _Outcome:
        """Count the attempt in a unit of work of its own. Only the class of the error is kept: its
        text may hold the payload."""
        try:
            async with self._uow_factory() as uow:
                await uow.outbox.mark_failed(message.id, type(error).__name__)
                await uow.commit()
        except Exception as store_error:
            logger.error(
                "outbox message %s on %s failed and the attempt could not be counted: %s",
                message.id,
                message.topic,
                type(store_error).__name__,
            )
            return _Outcome.STORE_DOWN
        if message.attempts + 1 >= MAX_ATTEMPTS:
            logger.error(
                "outbox message dead: id=%s topic=%s tenant=%s", message.id, message.topic, tenant
            )
        return _Outcome.FAILED


async def _pause(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)
