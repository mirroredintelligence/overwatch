"""TenantBoundConsumer (I08, DEC-165): the tenant of a message is bound from its own property, and
only for a tenant the directory lists as active, before the inner consumer opens a unit of work. A
message with no tenant, an invalid one, a network id, an unknown or suspended tenant is
dead-lettered and never reaches the inner consumer. No Docker: the inner consumer is a stub that
records which scope was bound when it ran."""

import contextlib
from collections.abc import Iterator, Sequence

import pytest

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.tenant_binding import (
    BAD_TENANT,
    NO_TENANT,
    UNKNOWN_TENANT,
    TenantBoundConsumer,
)
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.tenancy import current_scope_or_none
from tests.support.bus import message_with_tenant

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


def _message(tenant_id: str | None, message_id: str = "SM1") -> BusMessage:
    # The tenant is set without the constructor's check: a message built by a path that bypasses
    # validation must still not be handled (defence in depth; TEN-020 made it unreachable).
    return message_with_tenant(
        tenant_id,
        id=message_id,
        topic="inbound.replies",
        event_type="SmsReceived",
        payload={"text": "SECRET-PAYLOAD-TEXT"},
    )


class _Inner:
    """Records the scope bound at the moment it is asked to handle a message."""

    def __init__(self, outcome: Outcome | None = None, raises: Exception | None = None) -> None:
        self.bound: list[str | None] = []
        self.outcome = outcome or Outcome("completed")
        self.raises = raises

    async def handle(self, message: BusMessage) -> Outcome:
        scope = current_scope_or_none()
        self.bound.append(None if scope is None else scope.value)
        if self.raises is not None:
            raise self.raises
        return self.outcome


class _BrokenDirectory:
    async def active_tenant_ids(self) -> Sequence[str]:
        raise ConnectionError("SECRET-DIRECTORY-TEXT")


def _consumer(inner: _Inner, tenants: Sequence[str] = (TENANT_A, TENANT_B)) -> TenantBoundConsumer:
    return TenantBoundConsumer(inner, StaticTenants(tenants))


@pytest.mark.parametrize("tenant", [TENANT_A, TENANT_B])
async def test_the_inner_consumer_runs_with_the_messages_tenant_bound(tenant: str) -> None:
    inner = _Inner()

    outcome = await _consumer(inner).handle(_message(tenant))

    assert outcome == Outcome("completed")
    assert inner.bound == [tenant]


async def test_the_binding_is_gone_when_the_message_is_done() -> None:
    inner = _Inner()

    await _consumer(inner).handle(_message(TENANT_A))

    assert current_scope_or_none() is None


async def test_the_binding_is_gone_when_the_inner_consumer_raises() -> None:
    inner = _Inner(raises=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await _consumer(inner).handle(_message(TENANT_A))

    assert current_scope_or_none() is None


async def test_the_inner_outcome_is_returned_unchanged() -> None:
    inner = _Inner(outcome=Outcome("retry", "ConnectionError"))

    assert await _consumer(inner).handle(_message(TENANT_A)) == Outcome("retry", "ConnectionError")


@pytest.mark.parametrize("missing", [None, ""])
async def test_a_message_with_no_tenant_is_dead_lettered_and_never_handled(
    missing: str | None,
) -> None:
    inner = _Inner()

    outcome = await _consumer(inner).handle(_message(missing))

    assert outcome == Outcome("dead-letter", NO_TENANT)
    assert inner.bound == []


@pytest.mark.parametrize(
    "bad", ["Not A Tenant", "net-abcd1234", "q", "has:colon", "x" * 40, "tenant-a ", "../tenant-a"]
)
async def test_a_message_whose_tenant_is_not_a_tenant_id_is_dead_lettered_and_never_handled(
    bad: str,
) -> None:
    inner = _Inner()

    outcome = await _consumer(inner, tenants=[TENANT_A, bad]).handle(_message(bad))

    assert outcome == Outcome("dead-letter", BAD_TENANT)
    assert inner.bound == []


@pytest.mark.parametrize("listed", [(), (TENANT_B,)])
async def test_an_unknown_or_suspended_tenant_is_dead_lettered_and_never_handled(
    listed: Sequence[str],
) -> None:
    """A suspended tenant is not in the active list, so it reads the same as an unknown one."""
    inner = _Inner()

    outcome = await _consumer(inner, tenants=listed).handle(_message(TENANT_A))

    assert outcome == Outcome("dead-letter", UNKNOWN_TENANT)
    assert inner.bound == []


async def test_the_refusal_texts_hold_no_tenant_and_no_payload() -> None:
    for message in (_message(None), _message("net-abcd1234"), _message("tenant-zz")):
        outcome = await _consumer(_Inner()).handle(message)
        assert outcome.kind == "dead-letter"
        assert outcome.reason is not None
        assert "tenant-zz" not in outcome.reason
        assert "net-abcd1234" not in outcome.reason
        assert "SECRET" not in outcome.reason


async def test_a_directory_that_cannot_answer_is_a_retry_with_the_class_name_only() -> None:
    inner = _Inner()
    consumer = TenantBoundConsumer(inner, _BrokenDirectory())

    outcome = await consumer.handle(_message(TENANT_A))

    assert outcome == Outcome("retry", "ConnectionError")
    assert inner.bound == []


async def test_a_message_for_a_tenant_is_not_handled_in_another_tenants_scope() -> None:
    inner = _Inner()
    consumer = _consumer(inner)

    await consumer.handle(_message(TENANT_A, "SM1"))
    await consumer.handle(_message(TENANT_B, "SM1"))

    assert inner.bound == [TENANT_A, TENANT_B]


async def test_the_trace_hook_wraps_the_handling_of_each_message() -> None:
    events: list[str] = []

    @contextlib.contextmanager
    def observe(message: BusMessage) -> Iterator[None]:
        scope = current_scope_or_none()
        events.append(f"open {message.id} bound={None if scope is None else scope.value}")
        try:
            yield
        finally:
            events.append(f"close {message.id}")

    inner = _Inner()
    consumer = TenantBoundConsumer(inner, StaticTenants([TENANT_A]), observe)

    await consumer.handle(_message(TENANT_A, "SM7"))

    assert events == ["open SM7 bound=tenant-a", "close SM7"]
    assert inner.bound == [TENANT_A]


async def test_a_refused_message_does_not_open_the_trace_hook() -> None:
    opened: list[str] = []

    @contextlib.contextmanager
    def observe(message: BusMessage) -> Iterator[None]:
        opened.append(message.id)
        yield

    consumer = TenantBoundConsumer(_Inner(), StaticTenants([TENANT_A]), observe)

    await consumer.handle(_message(None))

    assert opened == []


def test_the_refusal_reasons_are_the_fixed_words_of_the_bus_contract() -> None:
    # TEN-025: the words TEN-020 fixed for the message itself, and `tenant-unknown` for a tenant the
    # directory does not list as active (a suspended tenant reads the same as an unknown one).
    assert (NO_TENANT, BAD_TENANT, UNKNOWN_TENANT) == (
        "tenant-missing",
        "tenant-malformed",
        "tenant-unknown",
    )


def test_the_consumer_declares_that_it_binds_the_tenant() -> None:
    assert TenantBoundConsumer.binds_tenant is True
