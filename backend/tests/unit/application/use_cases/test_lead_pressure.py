"""The shift lead's Under pressure and Underutilised lists (DEC-1343). Pure: no Neo4j, no network.

A stale or unknown figure is never listed as spare capacity, and an old figure under pressure shows
no percentage and says to confirm first."""

from dataclasses import replace
from datetime import UTC, datetime

from overwatch.application.use_cases.lead_views import (
    STALE_PRESSURE_REASON,
    under_pressure,
    underutilised,
)
from overwatch.application.use_cases.query_board import BoardEntry
from overwatch.domain.codes import Cadence, ServiceCategory, Status

NOW = datetime(2026, 11, 6, 14, 0, tzinfo=UTC)


def _entry(**changes: object) -> BoardEntry:
    base = BoardEntry(
        service_id="svc",
        name="Ward",
        category=ServiceCategory.INPATIENT_BEDS,
        status=Status.ACCEPTING,
        effective_available=5,
        over_by=None,
        used=5,
        established=10,
        pending=0,
        unit_label="beds free",
        comment="",
        reported_at=NOW,
        next_due_at=NOW,
        was_due_at=None,
        cadence=Cadence.EVERY_2_HRS,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_a_service_with_room_is_underutilised_and_the_most_spare_is_first() -> None:
    entries = (
        _entry(service_id="a", name="A", used=5, effective_available=5),
        _entry(service_id="b", name="B", used=2, effective_available=8),
    )

    found = underutilised(entries)

    assert [(item.service_id, item.used_percent, item.spare) for item in found] == [
        ("b", 20, 8),
        ("a", 50, 5),
    ]


def test_the_limits_are_at_most_60_percent_used_and_at_least_25_percent_free() -> None:
    assert underutilised((_entry(used=6, effective_available=4),))  # 60% used, 40% free
    assert not underutilised((_entry(used=7, effective_available=3),))  # 70% used
    assert not underutilised((_entry(used=5, effective_available=2),))  # 20% free


def test_a_stale_overdue_or_unknown_figure_is_never_listed_as_spare_capacity() -> None:
    assert not underutilised((_entry(stale_warning=True),))
    assert not underutilised((_entry(overdue=True),))
    assert not underutilised((_entry(status=Status.NOT_UPDATED, effective_available=None),))
    assert not underutilised((_entry(used=None),))
    assert not underutilised((_entry(effective_available=None),))


def test_only_an_accepting_service_can_be_underutilised() -> None:
    assert not underutilised((_entry(status=Status.LIMITED, used=2, effective_available=8),))


def test_pressure_lists_over_capacity_then_not_accepting_then_limited() -> None:
    entries = (
        _entry(service_id="lim", name="Lim", status=Status.LIMITED, effective_available=1, used=9),
        _entry(service_id="not", name="Not", status=Status.NOT_ACCEPTING, effective_available=0),
        _entry(service_id="over", name="Over", status=Status.OVER_CAPACITY, over_by=3, used=13),
    )

    found = under_pressure(entries)

    assert [item.service_id for item in found] == ["over", "not", "lim"]
    assert [item.reason for item in found] == [
        "3 over normal capacity",
        "Not accepting referrals",
        "Limited: 1 left of 10",
    ]
    assert found[2].used_percent == 90


def test_an_old_figure_under_pressure_is_last_with_no_percentage_and_says_to_confirm() -> None:
    entries = (
        _entry(
            service_id="old", name="Old", status=Status.OVER_CAPACITY, over_by=2, stale_warning=True
        ),
        _entry(service_id="fresh", name="Fresh", status=Status.LIMITED, effective_available=1),
    )

    found = under_pressure(entries)

    assert [item.service_id for item in found] == ["fresh", "old"]
    assert found[1].used_percent is None
    assert found[1].reason == STALE_PRESSURE_REASON


def test_accepting_and_late_reports_are_not_under_pressure() -> None:
    entries = (
        _entry(service_id="ok"),
        _entry(
            service_id="late", status=Status.NOT_UPDATED, overdue=True, effective_available=None
        ),
    )

    assert under_pressure(entries) == ()
