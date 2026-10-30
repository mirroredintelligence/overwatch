"""Integration tests for SavePushSubscription and RemovePushSubscription (I14), on the real Neo4j.

WRITTEN, NOT RUN in the build wave (no Neo4j per build-wave rules); verification runs them.
Each assertion reads back through a fresh unit of work or the harness helpers. Sample values only.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.push_subscription import (
    RemovePushSubscription,
    RemovePushSubscriptionCommand,
    SavePushSubscription,
    SavePushSubscriptionCommand,
    SavePushSubscriptionResult,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound
from tests.support.actors import ACTOR_TENANT
from tests.support.ladder_rig import reporter, seed_people, virtual_ward
from tests.support.neo4j import count_nodes
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

AT = datetime(2026, 10, 25, 13, 12, tzinfo=UTC)
LATER = datetime(2026, 10, 25, 14, 0, tzinfo=UTC)
DEVICE = "dev-1"
WORDING = "wording-v1"
SUBSCRIPTION = {
    "endpoint": "https://push.example/sample-endpoint",
    "keys": {"auth": "sample-auth", "p256dh": "sample-p256dh"},
}
REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-1",
    device_id=DEVICE,
    channel="app",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)


def _actor(practitioner_id: str) -> Actor:
    return Actor(
        role=Role.REPORTER,
        practitioner_id=practitioner_id,
        device_id=DEVICE,
        channel="app",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    """One reporter, prac-1, with no device yet. The audit head exists for the run tenant."""
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.services.save(virtual_ward())
        await uow.commit()
    await seed_people(uow_factory, reporter(1, None))


def _use_cases(uow_factory: UnitOfWorkFactory, driver: AsyncDriver, at: datetime):
    """The save and remove use cases on this clock, with the replay store on the same driver."""
    ids = SequentialIds("push")
    store = DriverIdempotencyStore(driver)
    clock = FixedClock(at)
    return (
        SavePushSubscription(uow_factory, clock, ids, store),
        RemovePushSubscription(uow_factory, clock, ids, store),
    )


async def _save(
    uow_factory: UnitOfWorkFactory,
    driver: AsyncDriver,
    key: str,
    subscription: dict | None = None,
    at: datetime = AT,
) -> SavePushSubscriptionResult:
    save, _ = _use_cases(uow_factory, driver, at)
    return await save.execute(
        SavePushSubscriptionCommand(
            idempotency_key=key,
            actor=REPORTER,
            device_id=DEVICE,
            subscription=subscription or SUBSCRIPTION,
            wording_version=WORDING,
        )
    )


async def test_saving_writes_the_subscription_an_active_consent_and_one_audit_record(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _save(uow_factory, neo4j_driver, "save-1")

    async with uow_factory() as uow:
        subscriptions = await uow.push_subscriptions.for_practitioner("prac-1")
        consent = await uow.notification_consents.get(DEVICE)
    assert [s.device_id for s in subscriptions] == [DEVICE]
    assert consent is not None
    assert (consent.status, consent.wording_version, consent.at) == ("active", WORDING, AT)
    assert await count_nodes(neo4j_driver, "AuditRecord") == 1


async def test_saving_again_for_the_same_device_leaves_one_subscription(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _save(uow_factory, neo4j_driver, "save-1")
    other = {**SUBSCRIPTION, "endpoint": "https://push.example/second"}
    await _save(uow_factory, neo4j_driver, "save-2", subscription=other)

    async with uow_factory() as uow:
        subscriptions = await uow.push_subscriptions.for_practitioner("prac-1")
    assert len(subscriptions) == 1
    assert subscriptions[0].subscription["endpoint"] == "https://push.example/second"


async def test_removing_deletes_the_subscription_and_marks_the_consent_inactive(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _save(uow_factory, neo4j_driver, "save-1")
    _, remove = _use_cases(uow_factory, neo4j_driver, LATER)
    await remove.execute(
        RemovePushSubscriptionCommand(idempotency_key="remove-1", actor=REPORTER, device_id=DEVICE)
    )

    async with uow_factory() as uow:
        subscriptions = await uow.push_subscriptions.for_practitioner("prac-1")
        consent = await uow.notification_consents.get(DEVICE)
    assert subscriptions == []
    assert consent is not None and consent.status == "inactive"


async def test_a_replayed_save_with_the_same_key_writes_nothing_new(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    first = await _save(uow_factory, neo4j_driver, "save-1")
    audits = await count_nodes(neo4j_driver, "AuditRecord")

    replay = await _save(uow_factory, neo4j_driver, "save-1")

    assert replay == first
    assert await count_nodes(neo4j_driver, "AuditRecord") == audits


async def test_a_device_of_another_practitioner_is_not_found_and_nothing_changes(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _save(uow_factory, neo4j_driver, "save-1")
    _, remove = _use_cases(uow_factory, neo4j_driver, LATER)
    with pytest.raises(NotFound):
        await remove.execute(
            RemovePushSubscriptionCommand(
                idempotency_key="remove-x", actor=_actor("prac-2"), device_id=DEVICE
            )
        )
    async with uow_factory() as uow:
        assert len(await uow.push_subscriptions.for_practitioner("prac-1")) == 1


async def test_an_actor_without_a_practitioner_is_not_allowed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    anonymous = Actor(
        role=Role.REPORTER,
        practitioner_id=None,
        device_id=None,
        channel="app",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )
    save, _ = _use_cases(uow_factory, neo4j_driver, AT)
    with pytest.raises(NotAllowed):
        await save.execute(
            SavePushSubscriptionCommand(
                idempotency_key="save-n",
                actor=anonymous,
                device_id=DEVICE,
                subscription=SUBSCRIPTION,
                wording_version=WORDING,
            )
        )


async def test_the_same_key_for_a_different_subscription_is_a_conflict(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _save(uow_factory, neo4j_driver, "save-1")
    other = {**SUBSCRIPTION, "endpoint": "https://x.example/y"}
    with pytest.raises(Conflict):
        await _save(uow_factory, neo4j_driver, "save-1", subscription=other)
