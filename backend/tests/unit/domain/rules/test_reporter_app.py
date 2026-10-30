"""The pure rules behind the reporter app's routes (W7C): how a number is masked, how a cover ends,
which state a service row is in and what a report may say. Sample numbers only."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from diucs.domain.codes import Cadence, Channel, Measure, ServiceCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.london_time import LONDON
from diucs.domain.rules.reporter_app import (
    MAX_COVER_DAYS,
    RowState,
    assess_row,
    channel_for,
    channel_word,
    check_report,
    cover_end,
    local_day_bounds,
    mask_mobile,
)

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)  # Thursday, 14:00 London (GMT)


def profile(cadence: Cadence = Cadence.EVERY_2_HRS) -> ServiceProfile:
    return ServiceProfile(
        id="ucr-west",
        name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals in the next 2 hrs",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=cadence,
        available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
    )


# ---------------------------------------------------------------------------------- the mask


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        ("+447700900456", "07xxx xxx456"),
        ("07700900456", "07xxx xxx456"),
        ("07700 900 456", "07xxx xxx456"),
    ],
)
def test_a_mobile_is_shown_with_its_first_two_and_last_three_digits(
    stored: str, shown: str
) -> None:
    assert mask_mobile(stored) == shown


@pytest.mark.parametrize("stored", ["", "12345", "+4420 7946 0000", "not a number"])
def test_a_number_that_is_not_a_mobile_is_shown_with_no_digit_at_all(stored: str) -> None:
    masked = mask_mobile(stored)

    assert masked == "xxxxx xxxxxx"


# ---------------------------------------------------------------------------------- channels


def test_the_app_channel_is_the_push_channel_and_back() -> None:
    assert channel_for("app") is Channel.PUSH
    assert channel_for("text") is Channel.TEXT
    assert channel_for("email") is Channel.EMAIL
    assert channel_word(Channel.PUSH) == "app"
    assert channel_word(Channel.TEXT) == "text"
    assert channel_word(None) == "text"


@pytest.mark.parametrize("word", ["push", "sms", "", "APP", None, 3])
def test_a_channel_word_the_screens_do_not_use_is_refused(word: object) -> None:
    with pytest.raises(ValidationFailed) as refused:
        channel_for(word)

    assert refused.value.field == "channel"


# ---------------------------------------------------------------------------------- cover


def test_cover_for_tonight_ends_at_23_59_local_today() -> None:
    assert cover_end("tonight", None, NOW, LONDON) == datetime(2026, 10, 29, 23, 59, tzinfo=UTC)


def test_cover_for_this_week_ends_at_23_59_local_on_the_sunday() -> None:
    assert cover_end("this-week", None, NOW, LONDON) == datetime(2026, 11, 1, 23, 59, tzinfo=UTC)


def test_cover_until_a_date_ends_at_23_59_local_that_day() -> None:
    assert cover_end("date", date(2026, 11, 3), NOW, LONDON) == datetime(
        2026, 11, 3, 23, 59, tzinfo=UTC
    )


def test_cover_end_is_read_in_the_tenants_zone() -> None:
    zone = ZoneInfo("Pacific/Auckland")  # a test of the argument: NZDT is UTC+13 in late October

    ended = cover_end("tonight", None, NOW, zone)

    assert ended == datetime(2026, 10, 30, 10, 59, tzinfo=UTC)  # 23:59 on the 30th, local


def test_cover_across_the_autumn_clock_change_keeps_the_local_time() -> None:
    before_change = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)  # Saturday, BST

    ended = cover_end("this-week", None, before_change, LONDON)

    assert ended == datetime(2026, 10, 25, 23, 59, tzinfo=UTC)  # Sunday 23:59 GMT


@pytest.mark.parametrize(
    "day",
    [
        date(2026, 10, 28),  # yesterday
        date(2026, 10, 29) + timedelta(days=MAX_COVER_DAYS + 1),  # beyond the longest cover
        None,  # a date cover needs its date
    ],
)
def test_a_date_cover_needs_a_day_from_today_to_the_longest_cover(day: date | None) -> None:
    with pytest.raises(ValidationFailed) as refused:
        cover_end("date", day, NOW, LONDON)

    assert refused.value.field == "date"


def test_the_last_day_of_the_longest_cover_is_allowed() -> None:
    last = date(2026, 10, 29) + timedelta(days=MAX_COVER_DAYS)

    assert cover_end("date", last, NOW, LONDON) > NOW


def test_a_cover_that_has_already_ended_is_refused() -> None:
    late = datetime(2026, 10, 29, 23, 59, 30, tzinfo=UTC)

    with pytest.raises(ValidationFailed) as refused:
        cover_end("tonight", None, late, LONDON)

    assert refused.value.field == "until"


@pytest.mark.parametrize("until", ["forever", "", "Tonight", None])
def test_a_cover_length_the_screens_do_not_offer_is_refused(until: object) -> None:
    with pytest.raises(ValidationFailed) as refused:
        cover_end(until, None, NOW, LONDON)  # type: ignore[arg-type]

    assert refused.value.field == "until"


def test_a_date_is_only_read_for_a_date_cover() -> None:
    with pytest.raises(ValidationFailed) as refused:
        cover_end("tonight", date(2026, 10, 30), NOW, LONDON)

    assert refused.value.field == "date"


# ---------------------------------------------------------------------------------- the day


def test_the_local_day_runs_from_midnight_to_midnight_in_the_tenants_zone() -> None:
    start, end = local_day_bounds(NOW, LONDON)

    assert (start, end) == (
        datetime(2026, 10, 29, 0, 0, tzinfo=UTC),
        datetime(2026, 10, 30, 0, 0, tzinfo=UTC),
    )


def test_a_local_day_with_a_clock_change_is_25_hours_long() -> None:
    start, end = local_day_bounds(datetime(2026, 10, 25, 12, 0, tzinfo=UTC), LONDON)

    assert end - start == timedelta(hours=25)
    assert start == datetime(2026, 10, 24, 23, 0, tzinfo=UTC)  # midnight BST


# ---------------------------------------------------------------------------------- row state


def test_a_service_with_no_report_since_its_latest_due_time_is_due() -> None:
    assessed = assess_row(
        profile(),
        suspended=False,
        latest_at=NOW - timedelta(hours=3),
        now=NOW,
        policy=DEFAULT_POLICY,
        zone=LONDON,
    )

    assert assessed.state is RowState.DUE
    assert assessed.due_at == datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
    assert assessed.reply_by == assessed.due_at + DEFAULT_POLICY.reply_window


def test_a_service_reported_since_its_latest_due_time_is_confirmed_with_its_next_time() -> None:
    assessed = assess_row(
        profile(),
        suspended=False,
        latest_at=NOW,
        now=NOW,
        policy=DEFAULT_POLICY,
        zone=LONDON,
    )

    assert assessed.state is RowState.CONFIRMED
    assert assessed.next_due == datetime(2026, 10, 29, 16, 0, tzinfo=UTC)


def test_a_service_that_has_never_reported_is_due() -> None:
    assessed = assess_row(
        profile(), suspended=False, latest_at=None, now=NOW, policy=DEFAULT_POLICY, zone=LONDON
    )

    assert assessed.state is RowState.DUE


def test_a_suspended_service_is_paused_whatever_its_reports_say() -> None:
    assessed = assess_row(
        profile(), suspended=True, latest_at=None, now=NOW, policy=DEFAULT_POLICY, zone=LONDON
    )

    assert assessed.state is RowState.PAUSED


def test_a_service_outside_its_hours_with_a_report_from_today_is_confirmed() -> None:
    late = datetime(2026, 10, 29, 21, 0, tzinfo=UTC)

    assessed = assess_row(
        profile(),
        suspended=False,
        latest_at=datetime(2026, 10, 29, 20, 5, tzinfo=UTC),
        now=late,
        policy=DEFAULT_POLICY,
        zone=LONDON,
    )

    assert assessed.state is RowState.CONFIRMED
    assert assessed.next_due == datetime(2026, 10, 30, 8, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------------- reports


def test_a_confirm_has_no_figure_a_number_has_its_own_and_closed_is_zero() -> None:
    assert check_report("confirm", None) is None
    assert check_report("number", 5) == 5
    assert check_report("number", 0) == 0
    assert check_report("closed", None) == 0


@pytest.mark.parametrize(
    ("kind", "value", "field"),
    [
        ("number", None, "value"),
        ("number", -1, "value"),
        ("number", 1000, "value"),
        ("number", True, "value"),
        ("number", 2.5, "value"),
        ("confirm", 3, "value"),
        ("closed", 3, "value"),
        ("reject", None, "kind"),
        (None, None, "kind"),
    ],
)
def test_a_report_the_screens_cannot_send_is_refused_by_field(
    kind: object, value: object, field: str
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_report(kind, value)  # type: ignore[arg-type]

    assert refused.value.field == field
