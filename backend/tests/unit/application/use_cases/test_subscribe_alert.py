"""SaveAlertPreferences and GetAlertPreferences (U33): the checks that run before any unit of work.

Every case here is refused before the store is used, so no Neo4j is needed; the uow factory is a
guard that fails the test if it is opened. The stored round trip, the subscriber query and the
deputy lookups are in tests/integration/application/test_subscribe_alert.py. Sample values only.
"""

from datetime import time
from typing import Any

import pytest

from diucs.application.actor import Actor
from diucs.application.use_cases.subscribe_alert import (
    GetAlertPreferences,
    SaveAlertPreferences,
    SaveAlertPreferencesCommand,
)
from diucs.domain.codes import AlertKind, Role
from diucs.domain.errors import NotAllowed, ValidationFailed


class _Untouched:
    """Stands in for the unit-of-work factory and the idempotency store: a refused command must not
    open a unit of work or read a key."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the store must not be used")

    async def get(self, key: str) -> Any:
        raise AssertionError("the replay store must not be used")


def _actor(role: Role = Role.EXEC, practitioner: str | None = "exec-1") -> Actor:
    return Actor(
        role=role,
        practitioner_id=practitioner,
        device_id=None,
        channel="web",
        service_ids=frozenset(),
    )


def _command(**changes: Any) -> SaveAlertPreferencesCommand:
    base: dict[str, Any] = {
        "idempotency_key": "alerts-1",
        "actor": _actor(),
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


def _use_case() -> SaveAlertPreferences:
    return SaveAlertPreferences(_Untouched(), _Untouched(), _Untouched())


@pytest.mark.parametrize("hours", [1, 3, 6])
async def test_a_not_updated_threshold_other_than_2_or_4_hours_is_refused(hours: int) -> None:
    with pytest.raises(ValidationFailed) as refused:
        await _use_case().execute(_command(not_updated_hours=hours))
    assert refused.value.field == "not_updated_hours"


@pytest.mark.parametrize("minutes", [5, 20, 45])
async def test_an_acknowledge_window_other_than_10_15_or_30_is_refused(minutes: int) -> None:
    with pytest.raises(ValidationFailed) as refused:
        await _use_case().execute(_command(ack_minutes=minutes))
    assert refused.value.field == "ack_minutes"


async def test_quiet_hours_other_than_22_to_06_or_none_are_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        await _use_case().execute(_command(quiet_hours=(time(21, 0), time(6, 0))))
    assert refused.value.field == "quiet_hours"


async def test_the_deputy_is_required_when_any_kind_is_on() -> None:
    with pytest.raises(ValidationFailed) as refused:
        await _use_case().execute(_command(deputy_id=None))
    assert refused.value.field == "deputy_id"


async def test_a_deputy_who_is_the_user_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        await _use_case().execute(_command(deputy_id="exec-1"))
    assert refused.value.field == "deputy_id"


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.REPORTER, Role.CLINICAL, Role.WALL])
async def test_only_exec_and_lead_may_set_alert_preferences(role: Role) -> None:
    with pytest.raises(NotAllowed):
        await _use_case().execute(_command(actor=_actor(role)))


async def test_an_actor_without_a_practitioner_is_not_allowed() -> None:
    with pytest.raises(NotAllowed):
        await _use_case().execute(_command(actor=_actor(Role.LEAD, None)))


async def test_reading_is_limited_to_exec_and_lead() -> None:
    with pytest.raises(NotAllowed):
        await GetAlertPreferences(_Untouched()).execute(_actor(Role.ADVISOR))
