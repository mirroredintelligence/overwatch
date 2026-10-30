"""Tests for the pure rules of acknowledging, snoozing and checking alerts (U34).

Only the owner of an alert may acknowledge or snooze it. An alert can be acknowledged while it is new
or escalated, anywhere in its chain; a snooze moves a new alert's escalation one hour later. A
not-updated service is checked at two and four hours after it changed. Sample values only.
"""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.domain.errors import InvalidTransition, NotAllowed
from diucs.domain.rules.alert_workflow import (
    SNOOZE_BY,
    may_acknowledge,
    may_snooze,
    not_updated_check_times,
    snoozed_due,
)

AT = datetime(2026, 10, 29, 14, 12, tzinfo=UTC)


def test_a_snooze_moves_the_escalation_one_hour_later() -> None:
    assert SNOOZE_BY == timedelta(hours=1)
    assert snoozed_due(datetime(2026, 10, 29, 14, 27, tzinfo=UTC)) == datetime(
        2026, 10, 29, 15, 27, tzinfo=UTC
    )


def test_the_owner_may_acknowledge_a_new_alert() -> None:
    may_acknowledge("new", owner_id="prac-1", actor_id="prac-1")


def test_the_owner_may_acknowledge_an_escalated_alert_anywhere_in_the_chain() -> None:
    may_acknowledge("escalated", owner_id="prac-1", actor_id="prac-1")


@pytest.mark.parametrize("status", ["acknowledged", "closed"])
def test_a_final_alert_is_not_acknowledged_again(status: str) -> None:
    with pytest.raises(InvalidTransition):
        may_acknowledge(status, owner_id="prac-1", actor_id="prac-1")


def test_someone_else_cannot_acknowledge_the_alert() -> None:
    with pytest.raises(NotAllowed):
        may_acknowledge("new", owner_id="prac-1", actor_id="prac-2")


def test_an_actor_without_a_practitioner_cannot_acknowledge() -> None:
    with pytest.raises(NotAllowed):
        may_acknowledge("new", owner_id="prac-1", actor_id=None)


def test_the_owner_may_snooze_a_new_alert() -> None:
    may_snooze("new", owner_id="prac-1", actor_id="prac-1")


def test_an_escalated_alert_cannot_be_snoozed() -> None:
    with pytest.raises(InvalidTransition):
        may_snooze("escalated", owner_id="prac-1", actor_id="prac-1")


def test_someone_else_cannot_snooze_the_alert() -> None:
    with pytest.raises(NotAllowed):
        may_snooze("new", owner_id="prac-1", actor_id="prac-2")


def test_a_service_not_updated_since_1230_is_checked_at_1430_and_1630() -> None:
    changed = datetime(2026, 10, 29, 12, 30, tzinfo=UTC)
    assert not_updated_check_times(changed) == (
        datetime(2026, 10, 29, 14, 30, tzinfo=UTC),
        datetime(2026, 10, 29, 16, 30, tzinfo=UTC),
    )


def test_a_naive_time_is_refused_for_a_not_updated_check() -> None:
    with pytest.raises(ValueError):
        not_updated_check_times(datetime(2026, 10, 29, 12, 30))
