"""The Analytics User's overview read (DEC-1368). Pure: no Neo4j, no network.

Figures only: one row per service with its status, its covered districts and, only when the figure
is current, its number. A stale, late or unknown figure carries no number and is never listed as
spare capacity. No total of "places available" is made (DEC-1343 rejects it). No patient data."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from overwatch.application.actor import Actor
from overwatch.application.use_cases.analytics_views import (
    ANALYTICS_ROLES,
    build_overview,
    check_analytics,
)
from overwatch.application.use_cases.query_board import BoardEntry
from overwatch.domain.codes import Cadence, Role, ServiceCategory, Status
from overwatch.domain.errors import NotAllowed
from tests.support.actors import ACTOR_TENANT

NOW = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)


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


def test_only_the_analytics_user_may_read_it() -> None:
    assert frozenset({Role.ANALYTICS_USER}) == ANALYTICS_ROLES
    for role in Role:
        actor = Actor(role, "prac-1", None, "web", frozenset(), ACTOR_TENANT)
        if role is Role.ANALYTICS_USER:
            check_analytics(actor)
        else:
            with pytest.raises(NotAllowed):
                check_analytics(actor)


def test_the_five_status_counts_cover_every_service_and_no_places_total_is_made() -> None:
    entries = (
        _entry(service_id="a", name="A"),
        _entry(service_id="b", name="B", status=Status.LIMITED),
        _entry(service_id="c", name="C", status=Status.NOT_ACCEPTING),
        _entry(service_id="d", name="D", status=Status.OVER_CAPACITY, over_by=2),
        _entry(service_id="e", name="E", status=Status.NOT_UPDATED, effective_available=None),
        _entry(service_id="f", name="F", status=Status.OUT_OF_HOURS),
    )

    view = build_overview(entries, {}, NOW)

    assert view.counts == {
        Status.ACCEPTING: 1,
        Status.LIMITED: 1,
        Status.NOT_ACCEPTING: 1,
        Status.OVER_CAPACITY: 1,
        Status.NOT_UPDATED: 1,
    }
    assert view.out_of_hours == 1
    assert not hasattr(view, "places_available")
    assert not hasattr(view, "total_available")


def test_a_service_carries_its_districts_in_name_order_and_one_with_none_has_an_empty_list() -> (
    None
):
    entries = (_entry(service_id="a", name="A"), _entry(service_id="b", name="B"))

    view = build_overview(entries, {"a": ("BH2", "BH1")}, NOW)

    rows = {row.service_id: row for row in view.services}
    assert rows["a"].districts == ("BH1", "BH2")
    assert rows["b"].districts == ()


def test_a_stale_late_or_unknown_figure_carries_no_number() -> None:
    entries = (
        _entry(service_id="fresh", name="Fresh", effective_available=4),
        _entry(service_id="old", name="Old", effective_available=4, stale_warning=True),
        _entry(service_id="late", name="Late", effective_available=4, overdue=True),
        _entry(service_id="none", name="None", status=Status.NOT_UPDATED, effective_available=4),
        _entry(service_id="over", name="Over", status=Status.OVER_CAPACITY, over_by=3),
        _entry(
            service_id="overold",
            name="OverOld",
            status=Status.OVER_CAPACITY,
            over_by=3,
            overdue=True,
        ),
    )

    rows = {row.service_id: row for row in build_overview(entries, {}, NOW).services}

    assert (rows["fresh"].figure_current, rows["fresh"].available) == (True, 4)
    for key in ("old", "late", "none", "overold"):
        assert rows[key].figure_current is False
        assert rows[key].available is None
        assert rows[key].over_by is None
    assert rows["over"].over_by == 3


def test_the_lists_are_by_name_and_a_stale_figure_is_never_spare_capacity() -> None:
    entries = (
        _entry(service_id="z", name="Zed", used=2, effective_available=8),
        _entry(service_id="a", name="Alpha", used=5, effective_available=5),
        _entry(service_id="s", name="Stale", used=2, effective_available=8, stale_warning=True),
        _entry(service_id="p2", name="Pressed B", status=Status.LIMITED, effective_available=1),
        _entry(
            service_id="p1",
            name="Pressed A",
            status=Status.NOT_ACCEPTING,
            effective_available=0,
        ),
        _entry(
            service_id="p3",
            name="Pressed C",
            status=Status.OVER_CAPACITY,
            over_by=2,
            overdue=True,
        ),
    )

    view = build_overview(entries, {}, NOW)

    assert [item.name for item in view.underutilised] == ["Alpha", "Zed"]
    assert [item.name for item in view.under_pressure] == [
        "Pressed A",
        "Pressed B",
        "Pressed C",
    ]
    stale = next(item for item in view.under_pressure if item.service_id == "p3")
    assert stale.used_percent is None
