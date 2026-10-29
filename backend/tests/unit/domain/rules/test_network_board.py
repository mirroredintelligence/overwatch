"""Assembling the network board from projected inputs (TEN-052; DEC-132, DEC-134 items 6 and 8,
DEC-136 items 3, 4 and 14; hazards H-N01, H-N07).

A row is read-only and capacity-derived: it holds an organisation, a service, a status and figures,
and nothing that belongs to a booking, a case, a reporter or an agreement. The order is fixed and is
not a ranking (design system section 13). All values are invented.
"""

import random
from dataclasses import fields, replace
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.domain.codes import Cadence, Measure, ServiceCategory, Status
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.network import DirectorySource, GrantScope, ListingStatus
from diucs.domain.model.service import AvailableTime
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.network_board import (
    NetworkBoard,
    NetworkBoardEntry,
    NetworkServiceInput,
    assemble_network_board,
    network_pressure,
)
from diucs.domain.rules.pressure import Pressure
from tests.support.projection_samples import (
    NOW,
    REPORTED_AT,
    sample_capacity_projection,
    sample_profile,
    sample_report,
    sample_service_projection,
)

BOTH = frozenset({GrantScope.DIRECTORY, GrantScope.CAPACITY})
ALL_DAY = (AvailableTime.every_day_all_day(),)
NIGHT_ONLY = (AvailableTime.every_day(time(20, 0), time(23, 0)),)  # closed at NOW


def make_input(
    ref: str = "row-1",
    *,
    organisation: str = "Org One",
    service_id: str = "svc-1",
    name: str = "UCR West",
    category: ServiceCategory = ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    value: int | None = 6,
    windows: tuple[AvailableTime, ...] = ALL_DAY,
    listing: ListingStatus = ListingStatus.ADMITTED,
    scopes: frozenset[GrantScope] = BOTH,
    with_capacity: bool = True,
    **profile_changes: Any,
) -> NetworkServiceInput:
    profile = sample_profile(
        id=service_id, name=name, category=category, available_times=windows, **profile_changes
    )
    capacity = None
    if with_capacity:
        report = (
            None
            if value is None
            else sample_report(service_id=service_id, value=value, measure=profile.measure)
        )
        capacity = sample_capacity_projection(profile=profile, latest=report, confirmed_since=0)
    return NetworkServiceInput(
        row_ref=ref,
        organisation_name=organisation,
        service=sample_service_projection(profile=profile),
        capacity=capacity,
        listing=listing,
        visible_scopes=scopes,
    )


def limited(ref: str, **changes: Any) -> NetworkServiceInput:
    # Ten places, 80 percent limit, two free: used 8 of 10 is at the limit.
    return make_input(ref, service_id=f"svc-{ref}", value=2, **changes)


def board(inputs: list[NetworkServiceInput], **changes: Any) -> NetworkBoard:
    arguments: dict[str, Any] = {"watch_from": 3, "high_from": 5}
    arguments.update(changes.pop("thresholds", {}))
    return assemble_network_board(inputs, changes.pop("now", NOW), **arguments)


# ---------------------------------------------------------------- 20. assembly


def test_a_shown_listing_with_both_scopes_becomes_an_entry_with_status_and_figures() -> None:
    result = board([make_input()])

    (entry,) = result.entries
    assert entry.status is Status.ACCEPTING
    assert entry.effective_available == 6
    assert entry.used == 4
    assert entry.established == 10
    assert entry.unit_label == "referrals in the next 2 hrs"
    assert entry.presentation is ListingPresentation.SHOWN
    assert entry.organisation_name == "Org One"
    assert entry.service_name == "UCR West"
    assert entry.category is ServiceCategory.URGENT_COMMUNITY_RESPONSE
    assert entry.source is DirectorySource.MANUAL
    assert entry.reported_at == REPORTED_AT


def test_a_suspended_listing_is_a_name_only_entry() -> None:
    result = board([make_input(listing=ListingStatus.SUSPENDED, scopes=frozenset())])

    (entry,) = result.entries
    assert entry.presentation is ListingPresentation.UNAVAILABLE
    assert entry.status is None
    assert entry.organisation_name == "Org One"
    assert entry.service_name == "UCR West"
    assert (entry.effective_available, entry.over_by, entry.used, entry.established) == (
        None,
        None,
        None,
        None,
    )
    assert (entry.unit_label, entry.reported_at, entry.was_due_at) == (None, None, None)
    assert entry.stale_warning is False


def test_a_suspended_listing_shows_no_figure_even_when_the_scopes_are_given() -> None:
    result = board([make_input(listing=ListingStatus.SUSPENDED, scopes=BOTH)])

    (entry,) = result.entries
    assert entry.status is None
    assert entry.effective_available is None


@pytest.mark.parametrize(
    "listing",
    [ListingStatus.PENDING, ListingStatus.DECLINED, ListingStatus.WITHDRAWN],
)
def test_a_hidden_listing_is_left_out(listing: ListingStatus) -> None:
    assert board([make_input(listing=listing)]).entries == ()


@pytest.mark.parametrize(
    "scopes",
    [
        frozenset(),
        frozenset({GrantScope.DIRECTORY}),
        frozenset({GrantScope.CAPACITY}),
        frozenset({GrantScope.CRITERIA}),
        frozenset({GrantScope.CRITERIA, GrantScope.DIRECTORY}),
    ],
)
def test_a_shown_listing_missing_the_directory_or_the_capacity_scope_is_left_out(
    scopes: frozenset[GrantScope],
) -> None:
    assert board([make_input(scopes=scopes)]).entries == ()


def test_criteria_scope_is_not_needed_for_a_tile() -> None:
    scopes = BOTH | {GrantScope.CRITERIA}

    assert len(board([make_input(scopes=scopes)]).entries) == 1


def test_a_shown_listing_with_no_capacity_projection_is_not_updated_with_no_figures() -> None:
    (entry,) = board([make_input(with_capacity=False)]).entries

    assert entry.status is Status.NOT_UPDATED
    assert (entry.effective_available, entry.used, entry.over_by, entry.established) == (
        None,
        None,
        None,
        None,
    )
    assert entry.reported_at is None


def test_a_capacity_projection_with_no_report_is_not_updated_with_no_figures() -> None:
    (entry,) = board([make_input(value=None)]).entries

    assert entry.status is Status.NOT_UPDATED
    assert entry.effective_available is None
    assert entry.reported_at is None


def test_an_old_report_reads_not_updated_whatever_was_projected() -> None:
    (entry,) = board([make_input()], now=REPORTED_AT + timedelta(hours=5)).entries

    assert entry.status is Status.NOT_UPDATED
    assert entry.was_due_at is not None
    assert entry.stale_warning is True


def test_a_suspended_service_is_not_updated_on_the_board() -> None:
    (entry,) = board([make_input(suspended=True)]).entries

    assert entry.status is Status.NOT_UPDATED


def test_an_inactive_service_is_left_out() -> None:
    assert board([make_input(active=False)]).entries == ()


def test_the_input_rules_are_applied_per_input() -> None:
    result = board(
        [
            make_input("a", service_id="svc-a"),
            make_input("b", service_id="svc-b", listing=ListingStatus.PENDING),
            make_input("c", service_id="svc-c", scopes=frozenset()),
            make_input(
                "d", service_id="svc-d", listing=ListingStatus.SUSPENDED, scopes=frozenset()
            ),
        ]
    )

    assert sorted(entry.row_ref for entry in result.entries) == ["a", "d"]


def test_the_board_carries_the_moment_it_was_made_in_utc() -> None:
    result = board(
        [make_input()], now=datetime(2026, 10, 29, 10, 30, tzinfo=timezone(timedelta(hours=1)))
    )

    assert result.generated_at == datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
    assert result.generated_at.utcoffset() == timedelta(0)


def test_an_empty_board_is_normal_pressure_and_not_all_limited() -> None:
    result = board([])

    assert result.entries == ()
    assert result.pressure is Pressure.NORMAL
    assert result.all_limited_or_worse is False


# ---------------------------------------------------------------- arguments


def test_a_naive_now_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        board([make_input()], now=datetime(2026, 10, 29, 9, 30))


@pytest.mark.parametrize(
    "changes",
    [
        {"listing": "admitted"},
        {"scopes": {GrantScope.DIRECTORY, GrantScope.CAPACITY}},
        {"scopes": frozenset({"directory", "capacity"})},
        {"ref": ""},
        {"ref": "has space"},
        {"organisation": "Mrs Smith"},
        {"organisation": "DT4 8XX"},
        {"organisation": ""},
    ],
)
def test_an_input_that_breaks_a_rule_is_refused(changes: dict[str, Any]) -> None:
    good = make_input()
    mapping = {
        "ref": "row_ref",
        "organisation": "organisation_name",
        "listing": "listing",
        "scopes": "visible_scopes",
    }
    replacements = {mapping[key]: value for key, value in changes.items()}

    with pytest.raises(ValidationFailed):
        replace(good, **replacements)


def test_an_input_that_is_not_an_input_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        board([object()])  # type: ignore[list-item]


@pytest.mark.parametrize(
    "thresholds", [{"watch_from": 0}, {"high_from": 1}, {"watch_from": True}, {"high_from": 101}]
)
def test_thresholds_outside_the_tenant_policy_bounds_are_refused(
    thresholds: dict[str, Any],
) -> None:
    with pytest.raises(ValidationFailed):
        board([make_input()], thresholds=thresholds)


# ------------------------------------------------------------ 21. the entry is the field set


def test_the_entry_has_exactly_the_documented_fields() -> None:
    assert [field.name for field in fields(NetworkBoardEntry)] == [
        "row_ref",
        "organisation_name",
        "service_name",
        "category",
        "presentation",
        "status",
        "unit_label",
        "effective_available",
        "over_by",
        "used",
        "established",
        "reported_at",
        "stale_warning",
        "was_due_at",
        "source",
    ]


def test_the_entry_names_nothing_of_a_booking_a_reporter_a_tenant_or_an_agreement() -> None:
    names = " ".join(field.name for field in fields(NetworkBoardEntry))

    for absent in (
        "pending",
        "comment",
        "next_due",
        "performer",
        "tenant",
        "grant",
        "agreement",
        "booking",
        "phone",
        "contact",
        "on_time",
        "score",
        "rank",
    ):
        assert absent not in names


def test_an_entry_and_its_repr_hold_nothing_of_the_source_tenant_or_the_comment() -> None:
    inputs = make_input(comment="Both women only", ref="opaque-1")

    (entry,) = board([inputs]).entries

    text = repr(entry)
    assert "Both women" not in text
    assert "tenant" not in text.lower()
    assert "role-1" not in text
    assert "opaque-1" in text


def test_a_board_has_exactly_four_fields() -> None:
    assert [field.name for field in fields(NetworkBoard)] == [
        "entries",
        "pressure",
        "all_limited_or_worse",
        "generated_at",
    ]


# ---------------------------------------------------------------- 22. order


def test_entries_are_ordered_by_category_then_organisation_then_service_then_ref() -> None:
    inputs = [
        make_input(
            "r5", service_id="s5", organisation="beta", name="Zed", category=ServiceCategory.OTHER
        ),
        make_input(
            "r4",
            service_id="s4",
            organisation="Beta",
            name="Alpha",
            category=ServiceCategory.INPATIENT_BEDS,
        ),
        make_input(
            "r3",
            service_id="s3",
            organisation="alpha",
            name="Zed",
            category=ServiceCategory.INPATIENT_BEDS,
        ),
        make_input(
            "r2",
            service_id="s2",
            organisation="alpha",
            name="alpha",
            category=ServiceCategory.INPATIENT_BEDS,
        ),
        make_input(
            "r1",
            service_id="s1",
            organisation="Alpha",
            name="Alpha",
            category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        ),
        make_input(
            "r0",
            service_id="s0",
            organisation="Alpha",
            name="alpha",
            category=ServiceCategory.INPATIENT_BEDS,
        ),
    ]

    result = board(inputs)

    assert [entry.row_ref for entry in result.entries] == ["r1", "r0", "r2", "r3", "r4", "r5"]


def test_a_tie_on_everything_else_is_broken_by_the_row_reference() -> None:
    inputs = [make_input("b", service_id="s-b"), make_input("a", service_id="s-a")]

    assert [entry.row_ref for entry in board(inputs).entries] == ["a", "b"]


def test_status_never_changes_the_order() -> None:
    accepting = make_input("a", service_id="s-a", name="Alpha", value=9)
    full = make_input("b", service_id="s-b", name="Bravo", value=0)
    swapped_a = make_input("a", service_id="s-a", name="Alpha", value=0)
    swapped_b = make_input("b", service_id="s-b", name="Bravo", value=9)

    first = board([accepting, full])
    second = board([swapped_a, swapped_b])

    assert [e.row_ref for e in first.entries] == ["a", "b"] == [e.row_ref for e in second.entries]
    assert [e.status for e in first.entries] != [e.status for e in second.entries]


def test_unavailable_entries_sit_in_the_same_order_as_shown_ones() -> None:
    inputs = [
        make_input("b", service_id="s-b", name="Bravo"),
        make_input(
            "a", service_id="s-a", name="Alpha", listing=ListingStatus.SUSPENDED, scopes=frozenset()
        ),
    ]

    assert [entry.row_ref for entry in board(inputs).entries] == ["a", "b"]


def test_the_category_order_is_the_declaration_order() -> None:
    inputs = [
        make_input(f"r{index}", service_id=f"s{index}", category=category)
        for index, category in enumerate(reversed(list(ServiceCategory)))
    ]

    result = board(inputs)

    assert [entry.category for entry in result.entries] == list(ServiceCategory)


@settings(max_examples=60, deadline=None)
@given(st.randoms(use_true_random=False))
def test_shuffling_the_inputs_gives_the_same_board(rng: random.Random) -> None:
    inputs = [
        make_input("r1", service_id="s1", organisation="Org B", name="Beta", value=0),
        make_input("r2", service_id="s2", organisation="Org A", name="Beta", value=3),
        make_input(
            "r3",
            service_id="s3",
            organisation="Org A",
            name="alpha",
            category=ServiceCategory.REABLEMENT,
        ),
        make_input(
            "r4",
            service_id="s4",
            organisation="Org C",
            name="Gamma",
            listing=ListingStatus.SUSPENDED,
            scopes=frozenset(),
        ),
        make_input(
            "r5", service_id="s5", organisation="Org D", name="Delta", listing=ListingStatus.PENDING
        ),
        make_input("r6", service_id="s6", organisation="Org A", name="Beta", value=5),
    ]
    expected = board(inputs)
    shuffled = list(inputs)
    rng.shuffle(shuffled)

    assert board(shuffled) == expected


# ---------------------------------------------------------------- 23. pressure


def test_three_limited_services_give_watch_and_five_give_high() -> None:
    assert board([limited(str(i)) for i in range(2)]).pressure is Pressure.NORMAL
    assert board([limited(str(i)) for i in range(3)]).pressure is Pressure.WATCH
    assert board([limited(str(i)) for i in range(4)]).pressure is Pressure.WATCH
    assert board([limited(str(i)) for i in range(5)]).pressure is Pressure.HIGH


def test_the_limited_services_really_are_limited() -> None:
    (entry,) = board([limited("1")]).entries

    assert entry.status is Status.LIMITED


def test_unavailable_entries_are_not_counted() -> None:
    inputs = [limited(str(i)) for i in range(2)] + [
        limited(f"u{i}", listing=ListingStatus.SUSPENDED, scopes=frozenset()) for i in range(5)
    ]

    assert board(inputs).pressure is Pressure.NORMAL


def test_out_of_hours_entries_are_not_counted() -> None:
    inputs = [limited(str(i)) for i in range(2)] + [
        limited(f"n{i}", windows=NIGHT_ONLY) for i in range(5)
    ]

    result = board(inputs)

    assert result.pressure is Pressure.NORMAL
    assert {e.status for e in result.entries if e.row_ref.startswith("n")} == {Status.OUT_OF_HOURS}


def test_custom_thresholds_are_used() -> None:
    inputs = [limited(str(i)) for i in range(2)]

    assert board(inputs, thresholds={"watch_from": 2, "high_from": 6}).pressure is Pressure.WATCH
    assert board(inputs, thresholds={"watch_from": 1, "high_from": 2}).pressure is Pressure.HIGH


def test_a_not_updated_entry_neither_counts_nor_stops_the_count() -> None:
    inputs = [limited(str(i)) for i in range(3)] + [
        make_input("stale", service_id="svc-stale", with_capacity=False)
    ]

    result = board(inputs)

    assert result.pressure is Pressure.WATCH
    assert result.all_limited_or_worse is False


def test_all_limited_or_worse_ignores_out_of_hours_and_is_false_when_one_is_accepting() -> None:
    all_limited = [limited(str(i)) for i in range(3)] + [limited("n", windows=NIGHT_ONLY)]

    assert board(all_limited).all_limited_or_worse is True
    assert (
        board(all_limited + [make_input("ok", service_id="svc-ok", value=9)]).all_limited_or_worse
        is False
    )


def test_network_pressure_counts_only_entries_with_a_shown_status() -> None:
    entries = board([limited(str(i)) for i in range(5)]).entries

    assert network_pressure(entries, watch_from=3, high_from=5) is Pressure.HIGH
    assert network_pressure(entries[:4], watch_from=3, high_from=5) is Pressure.WATCH
    unavailable = tuple(
        replace(entry, presentation=ListingPresentation.UNAVAILABLE, status=None)
        for entry in entries
    )
    assert network_pressure(unavailable, watch_from=3, high_from=5) is Pressure.NORMAL


# ---------------------------------------------------------------- 24. data age


def test_the_data_age_comes_from_the_reported_time_and_not_from_when_the_board_was_made() -> None:
    far = REPORTED_AT + timedelta(days=3, hours=1)
    inputs = make_input(windows=ALL_DAY, cadence=Cadence.EVERY_2_HRS)

    result = board([inputs], now=far)

    (entry,) = result.entries
    assert entry.reported_at == REPORTED_AT
    assert result.generated_at == far
    assert entry.stale_warning is True


def test_a_fresh_report_has_no_stale_warning_however_old_the_projection_is() -> None:
    (entry,) = board([make_input()], now=REPORTED_AT + timedelta(minutes=10)).entries

    assert entry.stale_warning is False
    assert entry.status is Status.ACCEPTING


def test_a_free_slots_measure_and_an_occupied_measure_both_appear() -> None:
    free = make_input("f", service_id="s-f", value=4)
    occupied = make_input("o", service_id="s-o", value=11, measure=Measure.OCCUPIED_PATIENTS)

    result = board([free, occupied])

    by_ref = {entry.row_ref: entry for entry in result.entries}
    assert by_ref["f"].effective_available == 4
    assert by_ref["o"].effective_available is None
    assert by_ref["o"].over_by == 1
    assert by_ref["o"].status is Status.OVER_CAPACITY
