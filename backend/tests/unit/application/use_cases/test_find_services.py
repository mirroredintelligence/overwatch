"""Advisor v2: find a service and the capacity overview (DEC-1366). Pure: no Neo4j, no network.

Browse only: nothing here opens a case or stores a postcode, age band or need. A service is
offered by
the same hard criteria as the v1 options (check_hard_criteria); its status is shown and never
ranks it;
a late or old figure is never the current capacity and is never offered as spare capacity."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from overwatch.application.actor import Actor
from overwatch.application.use_cases.find_services import (
    FIND_ROLES,
    FOUND_ORDER_NOTE,
    capacity_overview,
    check_find_role,
    match_services,
    order_key,
)
from overwatch.application.use_cases.query_board import BoardEntry
from overwatch.domain.codes import (
    AgeBand,
    Cadence,
    CriteriaStatus,
    NeedCategory,
    Role,
    ServiceCategory,
    Status,
)
from overwatch.domain.errors import NotAllowed
from overwatch.domain.model.criteria import ServiceCriteria

NOW = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
TODAY = date(2026, 11, 10)
DISTRICT = "DT4"


def _entry(**changes: object) -> BoardEntry:
    base = BoardEntry(
        service_id="svc-a",
        name="Alpha",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        status=Status.ACCEPTING,
        effective_available=5,
        over_by=None,
        used=5,
        established=10,
        pending=0,
        unit_label="referrals",
        comment="",
        reported_at=NOW - timedelta(minutes=20),
        next_due_at=NOW + timedelta(hours=1),
        was_due_at=None,
        cadence=Cadence.EVERY_2_HRS,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _criteria(service_id: str = "svc-a", **changes: object) -> ServiceCriteria:
    base = ServiceCriteria(
        id=f"crit-{service_id}",
        service_id=service_id,
        version=1,
        status=CriteriaStatus.CURRENT,
        age_min=16,
        age_max=None,
        districts=frozenset({"DT1", "DT4"}),
        accepts=frozenset({NeedCategory.FRAILTY, NeedCategory.FALL_NO_INJURY}),
        excludes=frozenset(),
        review_by=date(2026, 12, 31),
        owner_role_id="role-lead",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _match(entries: tuple[BoardEntry, ...], criteria: dict[str, ServiceCriteria], **kw: object):
    args: dict[str, object] = {
        "suspended": set(),
        "age_band": AgeBand.A80_PLUS,
        "district": DISTRICT,
        "needs": (NeedCategory.FRAILTY,),
        "now": NOW,
        "today": TODAY,
    }
    args.update(kw)
    return match_services(entries, criteria, **args)  # type: ignore[arg-type]


def test_a_service_that_meets_the_criteria_is_found_with_what_the_card_needs() -> None:
    found = _match((_entry(),), {"svc-a": _criteria()})

    assert len(found) == 1
    item = found[0]
    assert (item.service_id, item.status, item.criteria_version) == ("svc-a", Status.ACCEPTING, 1)
    assert item.figure_unavailable is False
    assert item.last_figure == 5
    assert "Takes frailty" in " ".join(item.fits)


def test_the_criteria_are_the_v1_rule_so_a_service_outside_them_is_not_found() -> None:
    outside_area = _criteria(districts=frozenset({"DT9"}))
    wrong_need = _criteria(accepts=frozenset({NeedCategory.WOUND_CARE}))
    too_old_for_it = _criteria(age_min=0, age_max=15)

    for criteria in (outside_area, wrong_need, too_old_for_it):
        assert _match((_entry(),), {"svc-a": criteria}) == ()


def test_a_service_with_no_current_criteria_or_that_is_suspended_is_never_found() -> None:
    assert _match((_entry(),), {}) == ()
    assert _match((_entry(),), {"svc-a": _criteria(status=CriteriaStatus.SUPERSEDED)}) == ()
    assert _match((_entry(),), {"svc-a": _criteria()}, suspended={"svc-a"}) == ()


def test_status_does_not_exclude_a_service_it_is_shown_as_it_is() -> None:
    entries = (
        _entry(
            service_id="svc-a", name="Alpha", status=Status.NOT_ACCEPTING, effective_available=0
        ),
        _entry(service_id="svc-b", name="Beta", status=Status.OVER_CAPACITY, over_by=2),
    )
    criteria = {"svc-a": _criteria("svc-a"), "svc-b": _criteria("svc-b")}

    found = _match(entries, criteria)

    assert {(item.service_id, item.status) for item in found} == {
        ("svc-a", Status.NOT_ACCEPTING),
        ("svc-b", Status.OVER_CAPACITY),
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"status": Status.NOT_UPDATED, "effective_available": None},
        {"overdue": True},
        {"stale_warning": True},
        {"reported_at": NOW - timedelta(hours=3)},
    ],
)
def test_a_late_old_or_unknown_figure_is_unavailable_and_keeps_the_last_figure_small(
    changes: dict[str, object],
) -> None:
    found = _match((_entry(**changes),), {"svc-a": _criteria()})

    assert found[0].figure_unavailable is True


def test_a_service_that_never_reported_has_an_unavailable_figure() -> None:
    found = _match(
        (_entry(reported_at=None, effective_available=None, used=None),), {"svc-a": _criteria()}
    )

    assert found[0].figure_unavailable is True
    assert found[0].last_figure is None


def test_order_is_travel_then_name_and_never_status() -> None:
    entries = (
        _entry(service_id="svc-z", name="Zed", status=Status.ACCEPTING),
        _entry(service_id="svc-b", name="Beta", status=Status.NOT_ACCEPTING, effective_available=0),
        _entry(service_id="svc-c", name="Cedar", status=Status.ACCEPTING),
    )
    criteria = {key: _criteria(key) for key in ("svc-z", "svc-b", "svc-c")}
    found = _match(entries, criteria)

    from overwatch.application.ports.outbound.geo import TravelRange

    def _with_travel(item, low):  # type: ignore[no-untyped-def]
        return replace(item, travel=TravelRange(low, low + 5, "test"))

    by_id = {item.service_id: item for item in found}
    ordered = sorted(
        (_with_travel(by_id["svc-z"], 5), _with_travel(by_id["svc-c"], 5), by_id["svc-b"]),
        key=order_key,
    )

    assert [item.service_id for item in ordered] == [
        "svc-c",
        "svc-z",
        "svc-b",
    ]  # travel, name; none last
    assert "status" in FOUND_ORDER_NOTE


def test_only_the_advisor_and_advisor_v2_may_find_a_service() -> None:
    assert set(FIND_ROLES) == {Role.ADVISOR, Role.ADVISOR_V2}
    for role in Role:
        actor = Actor(role, "p", None, "web", frozenset(), "tenant-1")
        if role in FIND_ROLES:
            check_find_role(actor)
        else:
            with pytest.raises(NotAllowed):
                check_find_role(actor)


# ------------------------------------------------------------------------------ the overview


def test_the_overview_counts_the_five_statuses_and_lists_what_needs_attention() -> None:
    entries = (
        _entry(service_id="a", name="A", status=Status.ACCEPTING),
        _entry(service_id="b", name="B", status=Status.LIMITED, effective_available=1),
        _entry(service_id="c", name="C", status=Status.NOT_ACCEPTING, effective_available=0),
        _entry(service_id="d", name="D", status=Status.OVER_CAPACITY, over_by=3),
        _entry(service_id="e", name="E", status=Status.NOT_UPDATED, effective_available=None),
        _entry(service_id="f", name="F", status=Status.OUT_OF_HOURS),
    )

    view = capacity_overview(entries)

    assert view.counts == {
        Status.ACCEPTING: 1,
        Status.LIMITED: 1,
        Status.OVER_CAPACITY: 1,
        Status.NOT_ACCEPTING: 1,
        Status.NOT_UPDATED: 1,
    }
    assert [item.service_id for item in view.under_pressure] == ["d", "c", "b"]


def test_the_overview_never_lists_a_stale_figure_as_spare_and_hides_its_number() -> None:
    entries = (
        _entry(service_id="fresh", name="Fresh", used=2, effective_available=8),
        _entry(service_id="old", name="Old", used=2, effective_available=8, overdue=True),
    )

    view = capacity_overview(entries)

    assert [item.service_id for item in view.underutilised] == ["fresh"]
    rows = {row.service_id: row for row in view.rows}
    assert rows["fresh"].figure_unavailable is False
    assert rows["old"].figure_unavailable is True
    assert rows["old"].last_figure == 8


def test_the_overview_rows_are_by_name_never_by_status() -> None:
    entries = (
        _entry(service_id="b", name="Bravo", status=Status.ACCEPTING),
        _entry(service_id="a", name="Alpha", status=Status.NOT_ACCEPTING, effective_available=0),
    )

    assert [row.name for row in capacity_overview(entries).rows] == ["Alpha", "Bravo"]


def test_the_overview_rows_carry_the_districts_each_service_covers_and_none_is_invented() -> None:
    entries = (_entry(service_id="a", name="A"), _entry(service_id="b", name="B"))

    view = capacity_overview(entries, districts={"a": ("DT4", "DT1")})

    rows = {row.service_id: row for row in view.rows}
    assert rows["a"].districts == ("DT1", "DT4")
    assert rows["b"].districts == ()
