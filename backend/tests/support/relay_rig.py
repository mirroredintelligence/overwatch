"""Test doubles and helpers for the outbox relay tests (I03).

Fakes here stand in for external providers only (the bus, the cache) or wrap the real unit of work
to inject one fault or to record the scope each unit opened under. Nothing here stores a record: the
outbox and the scheduled work are always the real Neo4j ones.

Each failing double fails at one call only (lesson L128), so a removed guard cannot hide behind
another one.
"""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from types import TracebackType
from typing import Any, Self

from neo4j import AsyncDriver

from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.cache import Cache, Lock, scoped_names
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.tenancy import ScopeId, current_tenant
from diucs.application.work import ScheduledWork, WorkKind
from diucs.domain.rules.london_time import london_to_utc
from tests.support.neo4j import node_props

# 14:16 London on 2026-10-23 (BST, UTC+1), and the due time ten minutes later.
NOW = london_to_utc(date(2026, 10, 23), time(14, 16))
DUE = london_to_utc(date(2026, 10, 23), time(14, 26))
ABOUT = "HealthcareService/svc-ucr-west"
SECRET_TEXT = "SECRET-PAYLOAD-TEXT"


def outbox_message(
    message_id: str,
    minute: int = 0,
    *,
    topic: str = "booking.events",
    event_type: str = "BookingRequested",
    payload: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> OutboxMessage:
    return OutboxMessage(
        id=message_id,
        topic=topic,
        event_type=event_type,
        payload={"reference": "4821", "note": SECRET_TEXT} if payload is None else payload,
        created_at=datetime(2026, 10, 23, 9, minute, tzinfo=UTC),
        session_id=session_id,
    )


async def add_messages(factory: UnitOfWorkFactory, *messages: OutboxMessage) -> None:
    async with factory() as uow:
        for message in messages:
            await uow.outbox.add(message)
        await uow.commit()


class ListIds:
    """Identifiers from a fixed list, so a test can name the work and the message it makes."""

    def __init__(self, *ids: str) -> None:
        self._ids = list(ids)

    def new_id(self) -> str:
        return self._ids.pop(0)


async def add_scheduled(
    factory: UnitOfWorkFactory,
    work_id: str,
    outbox_id: str,
    *,
    due_at: datetime = DUE,
    now: datetime = NOW,
    about_id: str = ABOUT,
) -> ScheduledWork:
    """Write one ScheduledWork row and its ScheduleWork message through schedule_work (U03)."""
    async with factory() as uow:
        work = await schedule_work(
            uow,
            ListIds(work_id, outbox_id),
            kind=WorkKind.PROMPT_DUE,
            about_id=about_id,
            due_at=due_at,
            now=now,
        )
        await uow.commit()
    return work


async def outbox_node(
    driver: AsyncDriver, message_id: str, *, scope: str | None = None
) -> dict[str, Any]:
    """The outbox row of the tenant bound now, or of `scope` (the other tenant's)."""
    return await node_props(driver, "OutboxMessage", scope=scope, id=message_id)


async def work_node(
    driver: AsyncDriver, work_id: str, *, scope: str | None = None
) -> dict[str, Any]:
    return await node_props(driver, "ScheduledWork", scope=scope, id=work_id)


def instant(value: Any) -> datetime:
    """A stored datetime as a UTC datetime (lesson L123: compare after astimezone)."""
    native: datetime = value.to_native()
    return native.astimezone(UTC)


class SpyBus:
    """A ManualEventBus that records every call and can fail chosen ones. `failures` maps a
    message id to the errors raised, one per publish or schedule call of that id; once the list is
    empty the call goes through. `always_fail` is a set of ids that always fail."""

    def __init__(self, inner: ManualEventBus) -> None:
        self.inner = inner
        self.calls: list[tuple[Any, ...]] = []
        self.failures: dict[str, list[Exception]] = {}
        self.always_fail: dict[str, Exception] = {}
        # Awaited at the start of every publish or schedule call, before it can fail.
        self.on_call: Callable[[], Awaitable[None]] | None = None

    @property
    def published(self) -> list[BusMessage]:
        return self.inner.published

    async def _maybe_fail(self, message_id: str) -> None:
        if self.on_call is not None:
            await self.on_call()
        if message_id in self.always_fail:
            raise self.always_fail[message_id]
        pending = self.failures.get(message_id)
        if pending:
            raise pending.pop(0)

    async def publish(self, message: BusMessage) -> None:
        self.calls.append(("publish", message.id))
        await self._maybe_fail(message.id)
        await self.inner.publish(message)

    async def enqueue(self, queue: str, message: BusMessage) -> None:
        self.calls.append(("enqueue", queue, message.id))
        await self.inner.enqueue(queue, message)

    async def schedule(self, queue: str, message: BusMessage, enqueue_at: datetime) -> int:
        self.calls.append(("schedule", message.id))
        await self._maybe_fail(message.id)
        number = await self.inner.schedule(queue, message, enqueue_at)
        self.calls[-1] = ("schedule", message.id, number)
        return number

    async def cancel(self, queue: str, sequence_number: int) -> None:
        self.calls.append(("cancel", sequence_number))
        await self.inner.cancel(queue, sequence_number)

    def calls_of(self, kind: str) -> list[tuple[Any, ...]]:
        return [call for call in self.calls if call[0] == kind]


class _OutboxFault:
    """Delegates to the real outbox; `mark_published` raises for the chosen ids, once each."""

    def __init__(self, target: Any, fail_ids: set[str], fail_counting: set[str]) -> None:
        self._target = target
        self._fail_ids = fail_ids
        self._fail_counting = fail_counting

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)

    async def mark_published(self, id: str, at: datetime) -> None:
        if id in self._fail_ids:
            self._fail_ids.discard(id)
            raise RuntimeError("the store went away")
        await self._target.mark_published(id, at)

    async def mark_failed(self, id: str, error: str) -> None:
        if id in self._fail_counting:
            self._fail_counting.discard(id)
            raise RuntimeError("the store went away")
        await self._target.mark_failed(id, error)


class _InstrumentedUnit:
    """Delegates to a real unit of work. It records the scope the unit opened under, and may swap
    in an outbox whose mark_published fails."""

    def __init__(
        self,
        unit: UnitOfWork,
        scopes: list[ScopeId | None],
        fail_ids: set[str],
        fail_counting: set[str],
    ) -> None:
        self._unit = unit
        self._scopes = scopes
        self._fail_ids = fail_ids
        self._fail_counting = fail_counting

    def __getattr__(self, name: str) -> Any:
        return getattr(self._unit, name)

    @property
    def outbox(self) -> Any:
        return _OutboxFault(self._unit.outbox, self._fail_ids, self._fail_counting)

    async def __aenter__(self) -> Self:
        await self._unit.__aenter__()
        self._scopes.append(self._unit.unit_scope)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._unit.__aexit__(exc_type, exc, tb)


class InstrumentedFactory:
    """A unit of work factory over a real one. `scopes` lists the scope of every unit opened, in
    order. `fail_mark_published` names outbox ids whose first mark_published raises."""

    def __init__(
        self,
        factory: UnitOfWorkFactory,
        *,
        fail_mark_published: set[str] | None = None,
        fail_mark_failed: set[str] | None = None,
    ):
        self._factory = factory
        self.scopes: list[ScopeId | None] = []
        self.fail_mark_published = set() if fail_mark_published is None else fail_mark_published
        self.fail_mark_failed = set() if fail_mark_failed is None else fail_mark_failed

    def __call__(self) -> UnitOfWork:
        return _InstrumentedUnit(
            self._factory(), self.scopes, self.fail_mark_published, self.fail_mark_failed
        )  # type: ignore[return-value]


class TenantPrefixedCache:
    """What the Redis adapter will do once it takes its prefix from the bound tenant (TEN-C06): a
    lock name gets the tenant in front of it, and a call with no tenant bound is an error. Used to
    show that the relay asks for its lock while a tenant is bound."""

    def __init__(self, inner: Cache) -> None:
        self.inner = inner
        self.names: list[str] = []

    def _name(self, name: str) -> str:
        prefixed = f"{current_tenant()}:{name}"
        self.names.append(prefixed)
        return prefixed

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        return await self.inner.acquire_lock(self._name(name), ttl)

    async def release_lock(self, lock: Lock) -> None:
        await self.inner.release_lock(lock)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


class ScriptedTokenCache(InMemoryCache):
    """An in-memory cache whose lock tokens come from a list (a lock issued after a clock step or a
    Redis data loss, hazard H-26). The holder it records carries the scripted token, so a release
    with that token frees the lock."""

    def __init__(self, clock: Clock, tokens: list[int]) -> None:
        super().__init__(clock)
        self._script = list(tokens)

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        lock = await super().acquire_lock(name, ttl)
        if lock is None:
            return None
        token = self._script.pop(0)
        holder_name = scoped_names().lock(name)
        self._holders[holder_name] = replace(self._holders[holder_name], token=token)
        return Lock(name=name, fencing_token=token, scope=scoped_names().segment)


class FlakyLockCache:
    """A cache whose lock calls can fail once: `acquire_fails` and `release_fails` hold the tenant
    ids (taken from the bound tenant) whose next call to that method raises."""

    def __init__(self, inner: Cache) -> None:
        self.inner = inner
        self.acquire_fails: set[str] = set()
        self.release_fails: set[str] = set()

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        tenant = current_tenant()
        if tenant in self.acquire_fails:
            self.acquire_fails.discard(tenant)
            raise ConnectionError(f"the cache is down {SECRET_TEXT}")
        return await self.inner.acquire_lock(name, ttl)

    async def release_lock(self, lock: Lock) -> None:
        tenant = current_tenant()
        if tenant in self.release_fails:
            self.release_fails.discard(tenant)
            raise ConnectionError(f"the cache is down {SECRET_TEXT}")
        await self.inner.release_lock(lock)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)
