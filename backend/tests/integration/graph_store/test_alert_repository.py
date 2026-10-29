"""Integration tests for the alert repositories (P17), run against the F10 harness Neo4j.

Each write is one committed transaction and each read is a fresh session, so the tests assert on
what was really stored. Values are synthetic; there is no patient data.
"""

from datetime import UTC, datetime, time
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.alert_repository import (
    Neo4jAlertRepository,
    Neo4jAlertSubscriptionRepository,
)
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.codes import AlertKind
from diucs.domain.errors import NotFound
from diucs.domain.model.alerts import AlertRecord, AlertSubscription
from diucs.domain.rules.alerts import AlertPreferences
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

RAISED = datetime(2026, 10, 25, 13, 12, tzinfo=UTC)
DUE = datetime(2026, 10, 25, 13, 27, tzinfo=UTC)
PREFS = AlertPreferences(
    kinds=frozenset({AlertKind.OVER_CAPACITY, AlertKind.SERVICE_CLOSED}),
    not_updated_hours=2,
    quiet_hours=(time(22, 0), time(6, 0)),
    quiet_critical_only=True,
    ack_minutes=15,
)
SUBSCRIPTION = AlertSubscription(
    practitioner_id="p1",
    preferences=PREFS,
    deputy_id="p-deputy",
    daily_summary=False,
    weekly_summary=False,
    updated_at=RAISED,
)
FIRST = AlertRecord(
    id="alert-1",
    kind=AlertKind.OVER_CAPACITY,
    service_id="svc-hospital-at-home",
    owner_practitioner_id="p1",
    status="new",
    raised_at=RAISED,
    escalation_due_at=DUE,
    part_of_id=None,
)
ESCALATION = AlertRecord(
    id="alert-2",
    kind=AlertKind.OVER_CAPACITY,
    service_id="svc-hospital-at-home",
    owner_practitioner_id="p-deputy",
    status="escalated",
    raised_at=datetime(2026, 10, 25, 13, 27, tzinfo=UTC),
    escalation_due_at=None,
    part_of_id="alert-1",
)
ACKNOWLEDGED = AlertRecord(
    id="alert-3",
    kind=AlertKind.OVER_CAPACITY,
    service_id="svc-hospital-at-home",
    owner_practitioner_id="p1",
    status="acknowledged",
    raised_at=RAISED,
    escalation_due_at=None,
    part_of_id=None,
    acknowledged_at=datetime(2026, 10, 25, 13, 20, tzinfo=UTC),
)


async def _seed_practitioner(driver: AsyncDriver, practitioner_id: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await ResourceStore(tx).put(
            {"resourceType": "Practitioner", "id": practitioner_id, "active": True}, None
        )

    await write_tx(driver, work)


async def _save_subscription(driver: AsyncDriver, subscription: AlertSubscription) -> None:
    await write_tx(driver, lambda tx: Neo4jAlertSubscriptionRepository(tx).save(subscription))


async def _add_alerts(driver: AsyncDriver, *alerts: AlertRecord) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = Neo4jAlertRepository(tx, ResourceStore(tx))
        for alert in alerts:
            await repo.add(alert)

    await write_tx(driver, work)


@pytest.fixture
async def practitioners(neo4j_driver: AsyncDriver, clean_graph: None) -> None:
    await _seed_practitioner(neo4j_driver, "p1")
    await _seed_practitioner(neo4j_driver, "p-deputy")


async def test_a_subscription_round_trips(neo4j_driver: AsyncDriver, practitioners: None) -> None:
    await _save_subscription(neo4j_driver, SUBSCRIPTION)

    await assert_round_trip(
        neo4j_driver,
        lambda tx: _noop(tx),
        lambda tx: Neo4jAlertSubscriptionRepository(tx).get_for_practitioner("p1"),
        SUBSCRIPTION,
    )


async def _noop(tx: Any) -> None:
    return None


async def test_saving_again_replaces_the_subscription(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _save_subscription(neo4j_driver, SUBSCRIPTION)
    changed = AlertSubscription(
        practitioner_id="p1",
        preferences=PREFS,
        deputy_id=None,
        daily_summary=True,
        weekly_summary=False,
        updated_at=datetime(2026, 10, 25, 14, 0, tzinfo=UTC),
    )
    await _save_subscription(neo4j_driver, changed)

    assert await count_nodes(neo4j_driver, "AlertSubscription") == 1
    props = await node_props(neo4j_driver, "AlertSubscription", practitionerId="p1")
    assert props["dailySummary"] is True


async def test_subscribers_for_a_kind_follow_the_switch(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _save_subscription(neo4j_driver, SUBSCRIPTION)

    subscribers = await read_tx(
        neo4j_driver,
        lambda tx: Neo4jAlertSubscriptionRepository(tx).subscribers_for_kind(
            AlertKind.OVER_CAPACITY
        ),
    )
    assert [s.practitioner_id for s in subscribers] == ["p1"]

    off = AlertSubscription(
        practitioner_id="p1",
        preferences=AlertPreferences(
            kinds=frozenset({AlertKind.SERVICE_CLOSED}),
            not_updated_hours=2,
            quiet_hours=None,
            quiet_critical_only=True,
            ack_minutes=15,
        ),
        deputy_id=None,
        daily_summary=False,
        weekly_summary=False,
        updated_at=RAISED,
    )
    await _save_subscription(neo4j_driver, off)
    subscribers = await read_tx(
        neo4j_driver,
        lambda tx: Neo4jAlertSubscriptionRepository(tx).subscribers_for_kind(
            AlertKind.OVER_CAPACITY
        ),
    )
    assert subscribers == []


async def test_a_subscription_for_an_unknown_practitioner_is_refused(
    neo4j_driver: AsyncDriver,
) -> None:
    with pytest.raises(NotFound):
        await _save_subscription(neo4j_driver, SUBSCRIPTION)
    assert await count_nodes(neo4j_driver, "AlertSubscription") == 0


async def test_an_alert_round_trips_as_an_acknowledge_alert_task(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _add_alerts(neo4j_driver, FIRST)

    await assert_round_trip(
        neo4j_driver,
        lambda tx: _noop(tx),
        lambda tx: Neo4jAlertRepository(tx, ResourceStore(tx)).get("alert-1"),
        FIRST,
    )
    task = await read_tx(neo4j_driver, lambda tx: ResourceStore(tx).get("Task", "alert-1"))
    assert task is not None
    assert task["code"]["coding"][0]["code"] == "acknowledge-alert"


async def test_an_escalation_chain_runs_from_the_root(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _add_alerts(neo4j_driver, FIRST, ESCALATION)

    chain = await read_tx(
        neo4j_driver,
        lambda tx: Neo4jAlertRepository(tx, ResourceStore(tx)).chain("alert-2"),
    )
    assert chain == [FIRST, ESCALATION]


async def test_open_for_owner_lists_new_alerts_only(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _add_alerts(neo4j_driver, FIRST, ACKNOWLEDGED)

    open_alerts = await read_tx(
        neo4j_driver,
        lambda tx: Neo4jAlertRepository(tx, ResourceStore(tx)).open_for_owner("p1"),
    )
    assert open_alerts == [FIRST]


async def test_a_raise_inside_the_unit_of_work_leaves_no_alert(
    neo4j_driver: AsyncDriver, uow_factory: Any, practitioners: None
) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with uow_factory() as uow:
            await uow.alerts.add(FIRST)
            raise RuntimeError("boom")

    assert await count_nodes(neo4j_driver, "Task") == 0
