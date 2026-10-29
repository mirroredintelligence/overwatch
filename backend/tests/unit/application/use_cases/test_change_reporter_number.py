"""The pure rules of ChangeReporterNumber (U16): the cover end, the holder of a role at an instant,
and the new mobile check. Times are London wall clock, so the tests cross the clock change.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from diucs.application.use_cases.change_reporter_number import (
    CoverDuration,
    check_new_mobile,
    cover_until,
    effective_reporter_practitioner_id,
)
from diucs.domain.codes import Channel, PractitionerRoleCode
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import PractitionerRole

LONDON = ZoneInfo("Europe/London")


def london(
    year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=LONDON).astimezone(UTC)


def role(covered_by: str | None = None, covered_until: datetime | None = None) -> PractitionerRole:
    return PractitionerRole(
        id="role-west-duty",
        practitioner_id="prac-original",
        service_id="ucr-west",
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=Channel.TEXT,
        period_start=london(2026, 10, 1, 0),
        covered_by_practitioner_id=covered_by,
        covered_until=covered_until,
    )


# --- The cover end (domain-rules, U16)  ----------------------------------------------------------


def test_today_ends_at_2359_london_on_the_same_day() -> None:
    # Friday 6 November 2026, 14:00 London: GMT, so 23:59 London is 23:59 UTC.
    assert cover_until(CoverDuration.TODAY, london(2026, 11, 6, 14)) == datetime(
        2026, 11, 6, 23, 59, tzinfo=UTC
    )


def test_this_week_from_a_friday_ends_on_the_sunday_at_2359_london() -> None:
    assert cover_until(CoverDuration.THIS_WEEK, london(2026, 11, 6, 14)) == datetime(
        2026, 11, 8, 23, 59, tzinfo=UTC
    )


def test_this_week_from_monday_0000_london_ends_on_that_sunday() -> None:
    # Monday 2 November 2026 at 00:00 London (GMT).
    assert cover_until(CoverDuration.THIS_WEEK, london(2026, 11, 2, 0)) == datetime(
        2026, 11, 8, 23, 59, tzinfo=UTC
    )


def test_this_week_on_a_sunday_ends_that_same_day() -> None:
    assert cover_until(CoverDuration.THIS_WEEK, london(2026, 11, 8, 10)) == datetime(
        2026, 11, 8, 23, 59, tzinfo=UTC
    )


def test_the_end_is_london_wall_clock_across_the_spring_clock_change() -> None:
    # Sunday 29 March 2026 is the change to BST: 23:59 London is 22:59 UTC that day.
    assert cover_until(CoverDuration.THIS_WEEK, london(2026, 3, 27, 14)) == datetime(
        2026, 3, 29, 22, 59, tzinfo=UTC
    )
    assert cover_until(CoverDuration.TODAY, london(2026, 3, 29, 10)) == datetime(
        2026, 3, 29, 22, 59, tzinfo=UTC
    )


def test_until_changed_has_no_end() -> None:
    assert cover_until(CoverDuration.UNTIL_CHANGED, london(2026, 11, 6, 14)) is None


def test_a_cover_one_second_before_the_end_of_the_day_is_still_allowed() -> None:
    assert cover_until(CoverDuration.TODAY, london(2026, 11, 6, 23, 58, 59)) == datetime(
        2026, 11, 6, 23, 59, tzinfo=UTC
    )


def test_a_cover_at_the_end_of_the_day_is_already_over_and_is_refused() -> None:
    with pytest.raises(ValidationFailed) as error:
        cover_until(CoverDuration.TODAY, london(2026, 11, 6, 23, 59))
    assert error.value.field == "duration"


def test_a_duration_that_is_only_the_same_text_is_refused() -> None:
    # A plain string equal to a member is not a member (lessons L3 and L38).
    with pytest.raises(ValidationFailed) as error:
        cover_until("today", london(2026, 11, 6, 14))  # type: ignore[arg-type]
    assert error.value.field == "duration"


def test_a_naive_now_is_refused() -> None:
    with pytest.raises(ValidationFailed) as error:
        cover_until(CoverDuration.TODAY, datetime(2026, 11, 6, 14))
    assert error.value.field == "now"


# --- The holder of a role at an instant (domain-rules 2.4)  --------------------------------------


def test_an_uncovered_role_is_held_by_its_own_practitioner() -> None:
    assert effective_reporter_practitioner_id(role(), london(2026, 11, 6, 16)) == "prac-original"


def test_a_covered_role_goes_to_the_cover_up_to_the_end_and_not_at_it() -> None:
    end = london(2026, 11, 6, 23, 59)
    covering = role(covered_by="prac-cover", covered_until=end)
    assert effective_reporter_practitioner_id(covering, london(2026, 11, 6, 16)) == "prac-cover"
    assert effective_reporter_practitioner_id(covering, london(2026, 11, 6, 23, 58, 59)) == (
        "prac-cover"
    )
    assert effective_reporter_practitioner_id(covering, end) == "prac-original"


def test_the_original_holder_has_the_role_again_at_00_01_on_saturday() -> None:
    end = london(2026, 11, 6, 23, 59)
    covering = role(covered_by="prac-cover", covered_until=end)
    assert effective_reporter_practitioner_id(covering, london(2026, 11, 7, 0, 1)) == (
        "prac-original"
    )


# --- The new mobile (U16 test 6)  ----------------------------------------------------------------


@pytest.mark.parametrize(
    "number", ["07700 900456", "07700900456", "+44 7700 900456", "0044 7700 900456"]
)
def test_a_uk_mobile_is_accepted_in_each_common_form(number: str) -> None:
    assert check_new_mobile(number) == "07700900456"


@pytest.mark.parametrize(
    "number",
    ["0123", "", "01202 000000", "07700 9004567", "not a number", "+1 415 555 0100"],
)
def test_a_number_that_is_not_a_uk_mobile_is_refused_as_new_mobile(number: str) -> None:
    with pytest.raises(ValidationFailed) as error:
        check_new_mobile(number)
    assert error.value.field == "new_mobile"
    assert "900456" not in str(error.value)
