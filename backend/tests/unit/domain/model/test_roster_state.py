"""Where a roster duty manager stands (DEC-1341): the role is the shift."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from overwatch.domain.codes import Channel, PractitionerRoleCode
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.people import PractitionerRole, RosterState, roster_state

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)


def _role(**changes: object) -> PractitionerRole:
    base = PractitionerRole(
        id="r-1",
        practitioner_id="p-1",
        service_id="svc-1",
        code=PractitionerRoleCode.ROSTER_DUTY_MANAGER,
        active=False,
        channel=Channel.TEXT,
        period_start=NOW - timedelta(days=1),
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_a_role_that_was_never_on_shift_is_off_shift() -> None:
    assert roster_state(_role(), NOW) is RosterState.OFF_SHIFT


def test_an_active_role_whose_period_covers_now_is_on_shift() -> None:
    role = _role(
        active=True, period_start=NOW - timedelta(hours=1), period_end=NOW + timedelta(hours=7)
    )
    assert roster_state(role, NOW) is RosterState.ON_SHIFT


def test_an_active_role_whose_planned_end_has_passed_is_off_shift() -> None:
    role = _role(
        active=True, period_start=NOW - timedelta(hours=9), period_end=NOW - timedelta(hours=1)
    )
    assert roster_state(role, NOW) is RosterState.OFF_SHIFT


def test_an_inactive_role_with_an_end_is_removed() -> None:
    assert roster_state(_role(period_end=NOW - timedelta(hours=1)), NOW) is RosterState.REMOVED


def test_only_a_roster_role_has_a_roster_state() -> None:
    with pytest.raises(ValidationFailed):
        roster_state(_role(code=PractitionerRoleCode.DUTY_MANAGER), NOW)
