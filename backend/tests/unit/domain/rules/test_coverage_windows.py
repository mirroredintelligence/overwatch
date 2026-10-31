"""Coverage by time of day and the coverage setting's checks (DEC-1305)."""

from datetime import time

import pytest

from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.service import AvailableTime
from overwatch.domain.rules.coverage_windows import (
    DAY_CODES,
    WINDOWS,
    DistrictCover,
    check_setting,
    check_window,
    cover_by_district,
    serves_window,
)

OFFICE = (AvailableTime.weekdays(time(8, 0), time(18, 0)),)
OVERNIGHT = (AvailableTime.every_day(time(20, 0), time(8, 0)),)
ALL_DAY = (AvailableTime.every_day_all_day(),)


def test_there_are_five_parts_of_the_day() -> None:
    assert set(WINDOWS) == {"all", "night", "morning", "afternoon", "evening"}
    assert check_window("night") == "night"
    with pytest.raises(ValidationFailed, match="window"):
        check_window("noon")


def test_an_all_day_service_counts_in_every_part_of_the_day() -> None:
    assert all(serves_window(ALL_DAY, None, window) for window in WINDOWS)


def test_office_hours_count_in_the_parts_they_overlap_and_not_the_night() -> None:
    results = {window: serves_window(OFFICE, None, window) for window in WINDOWS}
    assert results == {
        "all": True,
        "night": False,
        "morning": True,
        "afternoon": True,
        "evening": False,  # ends at 18:00, the window starts at 18:00 (end is exclusive)
    }


def test_an_overnight_window_counts_either_side_of_midnight() -> None:
    results = {window: serves_window(OVERNIGHT, None, window) for window in WINDOWS}
    assert results == {
        "all": True,
        "night": True,
        "morning": True,  # until 08:00
        "afternoon": False,
        "evening": True,  # from 20:00
    }


def test_the_days_the_lead_set_narrow_the_days_of_the_profile() -> None:
    assert serves_window(OFFICE, ["mon"], "morning")
    assert not serves_window(OFFICE, ["sat", "sun"], "morning")


def test_no_day_in_common_means_no_cover_even_when_the_hours_overlap() -> None:
    weekend_only = (AvailableTime(frozenset({5, 6}), True, None, None),)
    assert not serves_window(weekend_only, ["mon", "tue"], "all")
    assert serves_window(weekend_only, None, "all")


def test_districts_are_listed_with_their_services_and_an_uncovered_one_is_kept() -> None:
    cover = cover_by_district(
        ["DT2", "DT1", "DT3", "DT1"],
        [("UCR West", ["DT1", "DT2"]), ("UCR East", ["DT2"]), ("Out", [])],
    )
    assert cover == [
        DistrictCover("DT1", ("UCR West",)),
        DistrictCover("DT2", ("UCR East", "UCR West")),
        DistrictCover("DT3", ()),
    ]


def test_a_good_setting_is_put_in_canonical_form() -> None:
    setting = check_setting(["dt4", "DT3", "DT4"], 2, ["fri", "mon", "mon"])
    assert setting.districts == ("DT3", "DT4")
    assert setting.response_hours == 2
    assert setting.days == ("mon", "fri")
    assert DAY_CODES[0] == "mon"


@pytest.mark.parametrize(
    ("districts", "hours", "days", "field"),
    [
        ([], 2, ["mon"], "districts"),
        ("DT4", 2, ["mon"], "districts"),
        (["DT4 8"], 2, ["mon"], "districts"),
        ([4], 2, ["mon"], "districts"),
        ([f"DT{n}" for n in range(1, 10)] * 7, 2, ["mon"], "districts"),
        (["DT4"], 0, ["mon"], "responseHours"),
        (["DT4"], 73, ["mon"], "responseHours"),
        (["DT4"], True, ["mon"], "responseHours"),
        (["DT4"], 2.5, ["mon"], "responseHours"),
        (["DT4"], "2", ["mon"], "responseHours"),
        (["DT4"], 2, [], "days"),
        (["DT4"], 2, ["monday"], "days"),
        (["DT4"], 2, "mon", "days"),
    ],
)
def test_a_bad_setting_is_refused_naming_the_element(
    districts: object, hours: object, days: object, field: str
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_setting(districts, hours, days)
    assert refused.value.field == field


def test_the_limits_themselves_are_allowed() -> None:
    assert check_setting(["DT4"], 1, ["sun"]).response_hours == 1
    assert check_setting(["DT4"], 72, ["sun"]).response_hours == 72
