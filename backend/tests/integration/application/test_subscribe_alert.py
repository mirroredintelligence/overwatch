"""Integration tests for SaveAlertPreferences and GetAlertPreferences (U33), on the real Neo4j.

WRITTEN, NOT RUN in the build wave (no Neo4j per build-wave rules); verification runs them.
Practitioners: an exec who sets preferences, a deputy with a shift-lead role, a reporter. Sample
values only; nothing here is a patient.
"""

from datetime import UTC, datetime, time
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.subscribe_alert import (
    GetAlertPreferences,
    SaveAlertPreferences,
    SaveAlertPreferencesCommand,
)
from diucs.domain.codes import AlertKind, Role
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.people import Practitioner, PractitionerRole, PractitionerRoleCode
from tests.support.actors import ACTOR_TENANT
from tests.support.ladder_rig import reporter, seed_people
from tests.support.neo4j import count_nodes
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

AT = datetime(2026, 10, 25, 13, 12, tzinfo=UTC)
QUIET = (time(22, 0), time(6, 0))


def _exec(id_: str) -> Actor:
    return Actor(
        role=Role.EXEC,
        practitioner_id=id_,
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


EXEC = _exec("exec-1")


def _command(actor: Actor = EXEC, **changes: Any) -> SaveAlertPreferencesCommand:
    base: dict[str, Any] = {
        "idempotency_key": "alerts-1",
        "actor": actor,
        "kinds": frozenset(AlertKind),
        "not_updated_hours": 2,
        "quiet_hours": None,
        "quiet_critical_only": True,
        "ack_minutes": 15,
        "deputy_id": "deputy-1",
        "daily_summary": True,
        "weekly_summary": False,
    }
    base.update(changes)
    return SaveAlertPreferencesCommand(**base)


def _save(uow_factory: UnitOfWorkFactory, driver: AsyncDriver) -> SaveAlertPreferences:

    return SaveAlertPreferences(uow_factory, DriverIdempotencyStore(driver), FixedClock(AT))


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str) -> None:
    """An exec (exec-1), a deputy with a shift-lead role (deputy-1), a reporter (prac-1)."""
    await ensure_audit_heads(neo4j_driver, tenant_id)
    deputy_role = PractitionerRole(
        id="deputy-role-1",
        practitioner_id="deputy-1",
        service_id=None,
        code=PractitionerRoleCode.SHIFT_LEAD,
        active=True,
        channel=None,
        period_start=AT,
    )
    async with uow_factory() as uow:
        for person in (
            Practitioner(id="exec-1", active=True, display_name="Exec", phone_hash=None),
            Practitioner(id="deputy-1", active=True, display_name="Deputy", phone_hash=None),
            Practitioner(id="exec-2", active=True, display_name="Exec two", phone_hash=None),
        ):
            await uow.people.save_practitioner(person)
        await uow.people.save_role(deputy_role)
        await uow.commit()
    await seed_people(uow_factory, reporter(1, None))


async def test_a_new_exec_gets_the_defaults_and_nothing_is_written(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    got = await GetAlertPreferences(uow_factory).execute(EXEC)

    assert set(got.preferences.kinds) == set(AlertKind)
    assert got.preferences.not_updated_hours == 2
    assert got.preferences.ack_minutes == 15
    assert got.preferences.quiet_hours is None
    assert got.daily_summary is True and got.weekly_summary is False
    assert await count_nodes(neo4j_driver, "AlertSubscription") == 0


async def test_an_out_of_range_threshold_writes_no_subscription(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    with pytest.raises(ValidationFailed):
        await _save(uow_factory, neo4j_driver).execute(_command(not_updated_hours=3))
    with pytest.raises(ValidationFailed):
        await _save(uow_factory, neo4j_driver).execute(_command(ack_minutes=20))
    assert await count_nodes(neo4j_driver, "AlertSubscription") == 0


async def test_a_deputy_who_is_the_reporter_or_the_user_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    with pytest.raises(ValidationFailed):
        await _save(uow_factory, neo4j_driver).execute(_command(deputy_id="prac-1"))
    with pytest.raises(ValidationFailed):
        await _save(uow_factory, neo4j_driver).execute(_command(deputy_id="exec-1"))
    assert await count_nodes(neo4j_driver, "AlertSubscription") == 0


async def test_saving_then_turning_a_kind_off_changes_who_is_a_subscriber(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _save(uow_factory, neo4j_driver).execute(_command())
    async with uow_factory() as uow:
        assert [
            s.practitioner_id
            for s in await uow.alert_subscriptions.subscribers_for_kind(AlertKind.OVER_CAPACITY)
        ] == ["exec-1"]

    await _save(uow_factory, neo4j_driver).execute(
        _command(idempotency_key="alerts-2", kinds=frozenset(AlertKind) - {AlertKind.OVER_CAPACITY})
    )
    async with uow_factory() as uow:
        assert await uow.alert_subscriptions.subscribers_for_kind(AlertKind.OVER_CAPACITY) == []


async def test_quiet_hours_and_the_deputy_round_trip(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _save(uow_factory, neo4j_driver).execute(
        _command(quiet_hours=QUIET, quiet_critical_only=False)
    )
    got = await GetAlertPreferences(uow_factory).execute(EXEC)
    assert got.preferences.quiet_hours == QUIET
    assert got.preferences.quiet_critical_only is False
    assert got.deputy_id == "deputy-1"


async def test_an_advisor_is_not_allowed_and_one_exec_never_changes_another(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    advisor = Actor(
        role=Role.ADVISOR,
        practitioner_id="advisor-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )
    with pytest.raises(NotAllowed):
        await _save(uow_factory, neo4j_driver).execute(_command(actor=advisor))
    # The command names no target: the subscription saved is the actor's own.
    await _save(uow_factory, neo4j_driver).execute(
        _command(actor=_exec("exec-2"), deputy_id="deputy-1")
    )
    async with uow_factory() as uow:
        assert await uow.alert_subscriptions.get_for_practitioner("exec-1") is None
        assert (await uow.alert_subscriptions.get_for_practitioner("exec-2")) is not None


async def test_the_audit_records_the_kinds_and_nothing_else_personal(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _save(uow_factory, neo4j_driver).execute(_command())
    async with uow_factory() as uow:
        records = await uow.audit.records()
    entries = [r.entry for r in records if r.entry.use_case == "SaveAlertPreferences"]
    assert len(entries) == 1
    assert entries[0].snapshot == {"kinds": sorted(kind.value for kind in AlertKind)}
