"""Report flag rules (D12): which capacity reports a shift lead should check by phone.

Rules: docs/spec/domain-rules.md section 2.3. Both windows are inclusive at their edges and are
measured between instants (aware datetimes), so the London clock changes do not matter here.
Reports are never edited; a flag is a separate record. Sample values only; no patient data.
Ward A on 2026-10-23 (BST, UTC+1) unless a test says otherwise.
"""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportFlagReason,
    ReportSource,
    ReportType,
    ServiceCategory,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.london_time import LONDON
from diucs.domain.rules.report_flags import (
    MANY_CHANGES_COUNT,
    MANY_CHANGES_WINDOW,
    PHONED_WINDOW,
    flags_for_report,
)

SERVICE = "svc-ward-a"
OTHER_SERVICE = "svc-ucr-west"
MANY = ReportFlagReason.MANY_CHANGES
DIFFERS = ReportFlagReason.DIFFERS_FROM_PHONED

_ids = itertools.count(1)


def ward_a(**overrides: Any) -> ServiceProfile:
    fields: dict[str, Any] = {
        "id": SERVICE,
        "name": "Ward A",
        "category": ServiceCategory.INPATIENT_BEDS,
        "measure": Measure.FREE_BEDS,
        "unit_label": "beds",
        "established_capacity": 12,
        "can_exceed_established": False,
        "usual_range": (0, 12),
        "cadence": Cadence.EVERY_2_HRS,
        "available_times": (AvailableTime.every_day_all_day(),),
        "channel": Channel.TEXT,
    }
    fields.update(overrides)
    return ServiceProfile(**fields)


def at(hour: int, minute: int) -> datetime:
    """A London wall-clock time on 2026-10-23."""
    return datetime(2026, 10, 23, hour, minute, tzinfo=LONDON)


def rpt(
    value: int,
    when: datetime,
    *,
    source: ReportSource = ReportSource.TEXT,
    confirm: bool = False,
    service_id: str = SERVICE,
) -> CapacityReport:
    return CapacityReport(
        id=f"r{next(_ids)}",
        service_id=service_id,
        value=value,
        measure=Measure.FREE_BEDS,
        effective_at=when,
        source=source,
        report_type=ReportType.CONFIRMED if confirm else ReportType.NUMBER,
        derived_from="r0" if confirm else None,
    )


def phoned(value: int, when: datetime) -> CapacityReport:
    return rpt(value, when, source=ReportSource.ADVISOR_PHONED)


def flags(new: CapacityReport, recent: Sequence[CapacityReport]) -> list[ReportFlagReason]:
    return flags_for_report(new, recent, ward_a())


# --- Constants --------------------------------------------------------------------------------


def test_window_and_count_constants_match_the_rule_book() -> None:
    assert timedelta(minutes=5) == MANY_CHANGES_WINDOW
    assert MANY_CHANGES_COUNT == 3
    assert timedelta(minutes=60) == PHONED_WINDOW


# --- No flags for an ordinary report ----------------------------------------------------------


def test_single_report_with_nothing_recent_has_no_flags() -> None:
    assert flags(rpt(5, at(13, 14)), []) == []


# --- many-changes -----------------------------------------------------------------------------


def test_three_reports_within_five_minutes_flag_many_changes() -> None:
    recent = [rpt(3, at(13, 10)), rpt(4, at(13, 12))]
    assert flags(rpt(5, at(13, 14)), recent) == [MANY]


def test_first_report_six_minutes_before_is_outside_the_window() -> None:
    recent = [rpt(3, at(13, 8)), rpt(4, at(13, 12))]
    assert flags(rpt(5, at(13, 14)), recent) == []


def test_report_exactly_five_minutes_before_is_inside_the_window() -> None:
    recent = [rpt(3, at(13, 9)), rpt(4, at(13, 12))]
    assert flags(rpt(5, at(13, 14)), recent) == [MANY]


def test_confirmations_count_towards_many_changes() -> None:
    recent = [rpt(3, at(13, 10), confirm=True), rpt(4, at(13, 12))]
    assert flags(rpt(5, at(13, 14)), recent) == [MANY]


def test_canvas_example_all_y_then_nine_then_two_flags_many_changes() -> None:
    # Canvas: "Ward A: 3 reports in 4 minutes. All Y, then 9, then 2."
    recent = [rpt(3, at(13, 10), confirm=True), rpt(9, at(13, 12))]
    assert flags(rpt(2, at(13, 14)), recent) == [MANY]


# --- differs-from-phoned ----------------------------------------------------------------------


def test_text_figure_differing_from_phoned_in_the_last_hour_flags_differs() -> None:
    recent = [phoned(3, at(12, 30))]
    assert flags(rpt(5, at(13, 14)), recent) == [DIFFERS]


def test_text_figure_matching_the_phoned_figure_is_not_flagged() -> None:
    recent = [phoned(3, at(12, 30))]
    assert flags(rpt(3, at(13, 14)), recent) == []


def test_phoned_report_61_minutes_before_is_outside_the_window() -> None:
    recent = [phoned(3, at(12, 13))]
    assert flags(rpt(5, at(13, 14)), recent) == []


def test_phoned_report_exactly_60_minutes_before_is_inside_the_window() -> None:
    recent = [phoned(3, at(12, 14))]
    assert flags(rpt(5, at(13, 14)), recent) == [DIFFERS]


def test_a_phoned_figure_after_another_phoned_figure_is_not_flagged_as_differs() -> None:
    # Two phone calls disagreeing is the advisor's correction, not a contradiction of the service.
    recent = [phoned(3, at(12, 30))]
    assert flags(phoned(5, at(13, 14)), recent) == []


# --- Q10, DEC-1131: a phoned figure that contradicts the last text is flagged too --------------


def test_a_phoned_figure_that_differs_from_the_last_text_flags_differs() -> None:
    recent = [rpt(3, at(12, 30))]
    assert flags(phoned(5, at(13, 14)), recent) == [DIFFERS]


def test_a_phoned_figure_that_matches_the_last_text_is_not_flagged() -> None:
    recent = [rpt(5, at(12, 30))]
    assert flags(phoned(5, at(13, 14)), recent) == []


def test_only_the_last_text_counts_not_an_older_one() -> None:
    recent = [rpt(3, at(12, 20)), rpt(5, at(12, 50))]
    assert flags(phoned(5, at(13, 14)), recent) == []
    recent = [rpt(5, at(12, 20)), rpt(3, at(12, 50))]
    assert flags(phoned(5, at(13, 14)), recent) == [DIFFERS]


def test_a_text_older_than_the_window_is_not_the_last_text() -> None:
    assert flags(phoned(5, at(13, 14)), [rpt(3, at(12, 13))]) == []
    assert flags(phoned(5, at(13, 14)), [rpt(3, at(12, 14))]) == [DIFFERS]


def test_a_text_later_than_the_phoned_figure_is_ignored() -> None:
    assert flags(phoned(5, at(13, 14)), [rpt(3, at(13, 20))]) == []


def test_a_confirmation_counts_as_the_service_having_said_its_figure_again() -> None:
    recent = [rpt(3, at(12, 30), confirm=True)]
    assert flags(phoned(5, at(13, 14)), recent) == [DIFFERS]


def test_the_figure_of_another_service_is_never_the_last_text() -> None:
    recent = [rpt(3, at(12, 30), service_id=OTHER_SERVICE)]
    assert flags(phoned(5, at(13, 14)), recent) == []


def test_an_app_link_or_email_report_counts_as_the_service_speaking() -> None:
    for source in (ReportSource.APP, ReportSource.LINK, ReportSource.EMAIL):
        assert flags(phoned(5, at(13, 14)), [rpt(3, at(12, 30), source=source)]) == [DIFFERS]


def test_a_feed_figure_is_not_the_service_speaking() -> None:
    recent = [rpt(3, at(12, 30), source=ReportSource.FEED)]
    assert flags(phoned(5, at(13, 14)), recent) == []


def test_when_two_texts_share_the_last_instant_a_disagreement_with_either_flags() -> None:
    recent = [rpt(5, at(12, 30)), rpt(3, at(12, 30))]
    assert flags(phoned(5, at(13, 14)), recent) == [DIFFERS]


def test_a_phoned_figure_can_earn_many_changes_and_differs_together() -> None:
    recent = [rpt(3, at(13, 10)), rpt(4, at(13, 12))]
    assert flags(phoned(5, at(13, 14)), recent) == [MANY, DIFFERS]


def test_any_differing_phoned_figure_in_the_window_flags_differs() -> None:
    # Literal reading of domain-rules 2.3: "differs from an advisor-phoned figure". See DEC-025.
    recent = [phoned(3, at(12, 20)), phoned(5, at(12, 40))]
    assert flags(rpt(5, at(13, 14)), recent) == [DIFFERS]


def test_phoned_report_later_than_the_new_one_is_ignored() -> None:
    recent = [phoned(9, at(13, 20))]
    assert flags(rpt(5, at(13, 14)), recent) == []


# --- Both rules, order, and once each ---------------------------------------------------------


def test_both_rules_at_once_return_many_changes_then_differs() -> None:
    recent = [
        phoned(3, at(12, 30)),
        rpt(4, at(13, 10)),
        rpt(4, at(13, 12)),
    ]
    assert flags(rpt(5, at(13, 14)), recent) == [MANY, DIFFERS]


def test_each_reason_is_returned_at_most_once_however_many_reports_match() -> None:
    recent = [
        phoned(3, at(12, 20)),
        phoned(4, at(12, 30)),
        rpt(6, at(13, 9)),
        rpt(7, at(13, 10)),
        rpt(8, at(13, 11)),
        rpt(9, at(13, 12)),
    ]
    assert flags(rpt(5, at(13, 14)), recent) == [MANY, DIFFERS]


# --- Other services, later reports, and the new report itself ---------------------------------


def test_reports_for_another_service_are_ignored() -> None:
    recent = [
        rpt(3, at(13, 10), service_id=OTHER_SERVICE),
        rpt(4, at(13, 12), service_id=OTHER_SERVICE),
        rpt(3, at(12, 30), source=ReportSource.ADVISOR_PHONED, service_id=OTHER_SERVICE),
    ]
    assert flags(rpt(5, at(13, 14)), recent) == []


def test_reports_later_than_the_new_one_are_ignored() -> None:
    recent = [rpt(3, at(13, 15)), rpt(4, at(13, 16))]
    assert flags(rpt(5, at(13, 14)), recent) == []


def test_new_report_present_in_recent_is_counted_once() -> None:
    # Two real reports only: if the new report were counted twice this would wrongly flag.
    new = rpt(5, at(13, 14))
    recent = [rpt(4, at(13, 12)), new]
    assert flags(new, recent) == []


def test_new_report_present_in_recent_still_counts_towards_three() -> None:
    new = rpt(5, at(13, 14))
    recent = [rpt(3, at(13, 10)), rpt(4, at(13, 12)), new]
    assert flags(new, recent) == [MANY]


def test_profile_does_not_change_the_result() -> None:
    # The rules are about the reports; the profile is passed for the contract, not used.
    recent = [rpt(3, at(13, 10)), rpt(4, at(13, 12))]
    new = rpt(5, at(13, 14))
    assert flags_for_report(new, recent, ward_a(name="Other name")) == [MANY]


# --- Clock changes: windows are measured between instants -------------------------------------


def test_many_changes_window_crosses_the_spring_clock_change() -> None:
    # 2026-03-29: 01:00 GMT is the moment clocks jump to 02:00 BST. Instants, not wall clock.
    recent = [
        rpt(3, datetime(2026, 3, 29, 0, 58, tzinfo=UTC)),
        rpt(4, datetime(2026, 3, 29, 1, 0, tzinfo=UTC)),
    ]
    assert flags(rpt(5, datetime(2026, 3, 29, 1, 2, tzinfo=UTC)), recent) == [MANY]


def test_many_changes_window_crosses_the_autumn_clock_change() -> None:
    # 2026-10-25: 01:00 to 02:00 local happens twice. Instants 00:58Z, 01:00Z, 01:02Z are 4 min.
    recent = [
        rpt(3, datetime(2026, 10, 25, 0, 58, tzinfo=UTC)),
        rpt(4, datetime(2026, 10, 25, 1, 0, tzinfo=UTC)),
    ]
    assert flags(rpt(5, datetime(2026, 10, 25, 1, 2, tzinfo=UTC)), recent) == [MANY]


# --- London-zoned reports across the clock changes -------------------------------------------
# Same tzinfo object on both sides: Python subtracts and compares wall-clock fields, not instants.
# So these must be converted to UTC. Spring 2026-03-29: 00:58 GMT to 02:02 BST is 4 minutes,
# wall clock says 1h04. Autumn 2026-10-25: 01:02 GMT is fold=1, 01:58 BST is fold=0.


def london(day: int, month: int, hour: int, minute: int, fold: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=LONDON, fold=fold)


def test_many_changes_across_the_spring_change_uses_elapsed_time_london_zoned() -> None:
    # 00:58 GMT and 00:59 GMT are 4 and 3 minutes before 02:02 BST (01:02 UTC).
    recent = [rpt(3, london(29, 3, 0, 58)), rpt(4, london(29, 3, 0, 59))]
    assert flags(rpt(5, london(29, 3, 2, 2)), recent) == [MANY]


def test_many_changes_across_the_autumn_change_uses_elapsed_time_london_zoned() -> None:
    # 01:58 BST (fold 0) and 01:59 BST are 4 and 3 minutes before 01:02 GMT (fold 1).
    recent = [rpt(3, london(25, 10, 1, 58)), rpt(4, london(25, 10, 1, 59))]
    assert flags(rpt(5, london(25, 10, 1, 2, fold=1)), recent) == [MANY]


def test_london_zoned_pair_11_minutes_apart_across_spring_change_is_not_flagged() -> None:
    # True elapsed time 11 minutes (00:50 GMT to 01:01 UTC). Window is not widened.
    recent = [rpt(3, london(29, 3, 0, 50)), rpt(4, london(29, 3, 0, 51))]
    assert flags(rpt(5, london(29, 3, 2, 2)), recent) == []


def test_differs_from_phoned_across_the_spring_change_uses_elapsed_time() -> None:
    # Phoned 00:30 GMT, text 02:10 BST: 40 minutes of real time, 1h40 on the wall clock.
    recent = [rpt(3, london(29, 3, 0, 30), source=ReportSource.ADVISOR_PHONED)]
    assert flags(rpt(5, london(29, 3, 2, 10)), recent) == [DIFFERS]


def test_differs_from_phoned_across_the_autumn_change_uses_elapsed_time() -> None:
    # Phoned 01:30 BST (fold 0), text 01:10 GMT (fold 1): the phoned one is 40 minutes earlier
    # in real time, but later on the wall clock.
    recent = [rpt(3, london(25, 10, 1, 30), source=ReportSource.ADVISOR_PHONED)]
    assert flags(rpt(5, london(25, 10, 1, 10, fold=1)), recent) == [DIFFERS]


# --- Property tests: an independent oracle written from the rule text -------------------------


@dataclass(frozen=True, slots=True)
class Draw:
    minute: int
    value: int
    source: ReportSource
    confirm: bool
    other_service: bool


draws = st.builds(
    Draw,
    minute=st.integers(min_value=-120, max_value=120),
    value=st.integers(min_value=0, max_value=12),
    source=st.sampled_from(list(ReportSource)),
    confirm=st.booleans(),
    other_service=st.booleans(),
)


def build(draw: Draw) -> CapacityReport:
    when = at(13, 14) + timedelta(minutes=draw.minute)
    return rpt(
        draw.value,
        when,
        source=draw.source,
        confirm=draw.confirm,
        service_id=OTHER_SERVICE if draw.other_service else SERVICE,
    )


def oracle(new: CapacityReport, recent: Sequence[CapacityReport]) -> list[ReportFlagReason]:
    """Written from domain-rules 2.3, not from the implementation."""
    new_at = new.effective_at.astimezone(UTC)
    earlier = [
        r
        for r in recent
        if r.id != new.id
        and r.service_id == new.service_id
        and r.effective_at.astimezone(UTC) <= new_at
    ]
    result: list[ReportFlagReason] = []
    in_five = [
        r for r in earlier if r.effective_at.astimezone(UTC) >= new_at - timedelta(minutes=5)
    ]
    if len(in_five) + 1 >= 3:
        result.append(MANY)
    in_hour = [
        r for r in earlier if r.effective_at.astimezone(UTC) >= new_at - timedelta(minutes=60)
    ]
    if new.source is not ReportSource.ADVISOR_PHONED:
        if any(r.value != new.value for r in in_hour if r.source is ReportSource.ADVISOR_PHONED):
            result.append(DIFFERS)
    else:
        spoken = [
            r
            for r in in_hour
            if r.source
            in (ReportSource.TEXT, ReportSource.APP, ReportSource.LINK, ReportSource.EMAIL)
        ]
        if spoken:
            last = max(r.effective_at.astimezone(UTC) for r in spoken)
            if any(r.value != new.value for r in spoken if r.effective_at.astimezone(UTC) == last):
                result.append(DIFFERS)
    return result


@given(
    new_draw=draws,
    recent_draws=st.lists(draws, max_size=8),
)
def test_result_matches_the_rule_text_for_any_recent_reports(
    new_draw: Draw, recent_draws: list[Draw]
) -> None:
    new = rpt(
        new_draw.value,
        at(13, 14) + timedelta(minutes=new_draw.minute),
        source=new_draw.source,
    )
    recent = [build(d) for d in recent_draws]
    assert flags(new, recent) == oracle(new, recent)


@given(
    new_draw=draws,
    recent_draws=st.lists(draws, max_size=8),
    later_draws=st.lists(draws, min_size=1, max_size=4),
)
def test_reports_later_than_new_never_change_the_result(
    new_draw: Draw, recent_draws: list[Draw], later_draws: list[Draw]
) -> None:
    new = build(new_draw)
    recent = [build(d) for d in recent_draws]
    later = [build(d) for d in later_draws if d.minute > new_draw.minute]
    before = flags(new, recent)
    assert flags(new, recent + later) == before


CHANGE_INSTANTS = [
    datetime(2026, 3, 29, 1, 0, tzinfo=UTC),
    datetime(2026, 10, 25, 1, 0, tzinfo=UTC),
]
near_change = st.builds(
    Draw,
    minute=st.integers(min_value=-15, max_value=15),
    value=st.integers(min_value=0, max_value=12),
    source=st.sampled_from(list(ReportSource)),
    confirm=st.just(False),
    other_service=st.booleans(),
)


@given(
    base=st.sampled_from(CHANGE_INSTANTS),
    new_draw=near_change,
    recent_draws=st.lists(near_change, max_size=8),
)
def test_result_matches_the_rule_text_across_the_clock_changes(
    base: datetime, new_draw: Draw, recent_draws: list[Draw]
) -> None:
    def london_report(d: Draw) -> CapacityReport:
        when = (base + timedelta(minutes=d.minute)).astimezone(LONDON)
        return rpt(
            d.value,
            when,
            source=d.source,
            service_id=OTHER_SERVICE if d.other_service else SERVICE,
        )

    new = london_report(new_draw)
    new = rpt(new.value, new.effective_at, source=new.source)
    recent = [london_report(d) for d in recent_draws]
    assert flags(new, recent) == oracle(new, recent)


@given(new_draw=draws, recent_draws=st.lists(draws, max_size=8))
def test_flags_are_unique_and_in_rule_order(new_draw: Draw, recent_draws: list[Draw]) -> None:
    result = flags(build(new_draw), [build(d) for d in recent_draws])
    assert len(result) == len(set(result))
    assert result == [f for f in (MANY, DIFFERS) if f in result]


# --- One open flag for each service and reason (KI-101) ---------------------------------------


def test_a_reason_with_an_open_flag_earns_no_new_one() -> None:
    from diucs.domain.rules.report_flags import new_flag_reasons

    assert new_flag_reasons([MANY, DIFFERS], {MANY}) == [DIFFERS]
    assert new_flag_reasons([MANY, DIFFERS], {MANY, DIFFERS}) == []
    assert new_flag_reasons([MANY, DIFFERS], set()) == [MANY, DIFFERS]


def test_a_reason_is_given_once_and_the_order_is_kept() -> None:
    from diucs.domain.rules.report_flags import new_flag_reasons

    twice = ReportFlagReason.OUT_OF_RANGE_TWICE
    assert new_flag_reasons([DIFFERS, twice, DIFFERS, MANY], frozenset()) == [DIFFERS, twice, MANY]
    assert new_flag_reasons([], {MANY}) == []
