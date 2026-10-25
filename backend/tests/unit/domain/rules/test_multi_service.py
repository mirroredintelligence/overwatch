"""Tests for diucs.domain.rules.multi_service: grouped prompts and the phone load limit (D28).

Rules from docs/spec/domain-rules.md 2.4 and the D28 prompt. Groups start at the earliest due time
and take every item less than 10 minutes after the group's first item. Lettering follows name
order and only groups of two or more get letters. Due times are compared as UTC instants
(lessons L52, L53).
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.multi_service import (
    GROUP_WINDOW,
    MAX_SERVICES_PER_PHONE,
    GroupedItem,
    PromptGroup,
    group_due,
    letters_for,
    phone_overloaded,
)
from diucs.domain.rules.schedule import REPLY_WINDOW

LONDON: ZoneInfo = ZoneInfo("Europe/London")
TEN: datetime = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)


def at(minute_offset: int) -> datetime:
    return TEN + timedelta(minutes=minute_offset)


def items_of(group: PromptGroup) -> list[tuple[str, str | None]]:
    return [(item.name, item.letter) for item in group.items]


def test_two_services_due_together_form_one_group_lettered_in_name_order() -> None:
    groups = group_due([("w", "UCR West", TEN), ("e", "UCR East", TEN)])

    assert len(groups) == 1
    group = groups[0]
    assert items_of(group) == [("UCR East", "A"), ("UCR West", "B")]
    assert group.due == TEN
    assert group.reply_by == TEN + timedelta(minutes=30)
    assert group.reply_by == TEN + REPLY_WINDOW


def test_due_times_less_than_ten_minutes_apart_share_a_group() -> None:
    groups = group_due([("a", "Ward A", TEN), ("b", "Ward B", at(9) + timedelta(seconds=59))])

    assert len(groups) == 1
    assert [item.letter for item in groups[0].items] == ["A", "B"]


def test_due_times_ten_minutes_apart_make_two_groups_with_no_letters() -> None:
    groups = group_due([("a", "Ward A", TEN), ("b", "Ward B", at(10))])

    assert len(groups) == 2
    assert [items_of(g) for g in groups] == [[("Ward A", None)], [("Ward B", None)]]
    assert groups[1].due == at(10)


def test_a_group_is_anchored_on_its_first_item_not_on_the_last() -> None:
    groups = group_due(
        [
            ("a", "Ward A", at(0)),
            ("b", "Ward B", at(5)),
            ("c", "Ward C", at(12)),
        ]
    )

    assert len(groups) == 2
    assert [item.name for item in groups[0].items] == ["Ward A", "Ward B"]
    assert [item.name for item in groups[1].items] == ["Ward C"]
    assert groups[1].due == at(12)


def test_empty_input_gives_no_groups() -> None:
    assert group_due([]) == []


def test_letters_follow_name_order_not_input_order() -> None:
    assert letters_for(["UCR West", "Ward A", "Reablement"]) == {
        "Reablement": "A",
        "UCR West": "B",
        "Ward A": "C",
    }


def test_letters_for_no_names_is_empty() -> None:
    assert letters_for([]) == {}


def test_a_group_of_three_is_lettered_a_b_c() -> None:
    groups = group_due(
        [("c", "Ward C", TEN), ("a", "Ward A", TEN), ("b", "Ward B", at(1))],
    )

    assert len(groups) == 1
    # Items run in due order (ties by name); letters follow name order.
    assert items_of(groups[0]) == [("Ward A", "A"), ("Ward C", "C"), ("Ward B", "B")]


@pytest.mark.parametrize(
    ("count", "overloaded"), [(0, False), (1, False), (3, False), (4, True), (9, True)]
)
def test_phone_is_overloaded_only_above_three_services(count: int, overloaded: bool) -> None:
    assert MAX_SERVICES_PER_PHONE == 3
    assert phone_overloaded(count) is overloaded


def test_a_negative_service_count_is_refused() -> None:
    with pytest.raises(ValidationFailed) as raised:
        phone_overloaded(-1)
    assert raised.value.field == "count"


def test_twenty_six_items_due_together_are_lettered_to_z() -> None:
    names = [f"Service {i:02d}" for i in range(26)]
    groups = group_due([(f"id{i}", name, TEN) for i, name in enumerate(names)])

    assert len(groups) == 1
    letters = [item.letter for item in groups[0].items]
    assert letters == [chr(ord("A") + i) for i in range(26)]


def test_twenty_seven_items_due_together_raise_validation_failed() -> None:
    with pytest.raises(ValidationFailed) as raised:
        group_due([(f"id{i}", f"Service {i:02d}", TEN) for i in range(27)])
    assert raised.value.field == "items"


def test_letters_for_more_than_twenty_six_names_raise_validation_failed() -> None:
    with pytest.raises(ValidationFailed):
        letters_for([f"Service {i:02d}" for i in range(27)])


def test_letters_for_refuses_two_names_that_are_the_same() -> None:
    with pytest.raises(ValidationFailed):
        letters_for(["Ward A", "Ward A"])


def test_a_group_refuses_two_items_with_the_same_name() -> None:
    with pytest.raises(ValidationFailed):
        group_due([("a", "Ward A", TEN), ("b", "Ward A", TEN)])


def test_the_same_service_twice_in_one_input_is_refused() -> None:
    with pytest.raises(ValidationFailed) as raised:
        group_due([("a", "Ward A", TEN), ("a", "Ward B", at(20))])
    assert raised.value.field == "service_id"


def test_a_naive_due_time_is_refused() -> None:
    with pytest.raises(ValidationFailed) as raised:
        group_due([("a", "Ward A", datetime(2026, 10, 25, 10, 0))])
    assert raised.value.field == "due"


def test_group_due_times_are_returned_in_utc() -> None:
    london_ten = datetime(2026, 10, 25, 10, 0, tzinfo=LONDON, fold=1)  # GMT, equals 10:00 UTC

    groups = group_due([("a", "Ward A", london_ten)])

    assert groups[0].due == TEN
    assert groups[0].due.utcoffset() == timedelta(0)
    assert groups[0].items[0].due.utcoffset() == timedelta(0)


def test_grouping_compares_real_instants_across_the_clock_change() -> None:
    # 2026-10-25: 01:50 BST (fold 0, 00:50 UTC) and 01:55 GMT (fold 1, 01:55 UTC)
    # are 65 minutes apart.
    # Wall-clock subtraction would read them as 5 minutes and join them into one group (lesson L52).
    bst = datetime(2026, 10, 25, 1, 50, tzinfo=LONDON, fold=0)
    gmt = datetime(2026, 10, 25, 1, 55, tzinfo=LONDON, fold=1)

    groups = group_due([("a", "Ward A", bst), ("b", "Ward B", gmt)])

    assert len(groups) == 2


def test_regression_pin_spring_clock_change_compares_real_instants() -> None:
    # Regression pin, not a new rule. 2026-03-29: 01:58 GMT (01:58 UTC) and 03:03 BST
    # (02:03 UTC) are 5 minutes apart. Wall-clock subtraction would read 65 minutes and split them.
    gmt = datetime(2026, 3, 29, 1, 58, tzinfo=LONDON, fold=0)
    bst = datetime(2026, 3, 29, 3, 3, tzinfo=LONDON, fold=0)

    groups = group_due([("a", "Ward A", gmt), ("b", "Ward B", bst)])

    assert len(groups) == 1
    assert [item.letter for item in groups[0].items] == ["A", "B"]


def test_grouped_item_is_a_frozen_value() -> None:
    item = GroupedItem(service_id="a", name="Ward A", due=TEN, letter=None)
    with pytest.raises(AttributeError):
        item.name = "Ward B"  # type: ignore[misc]


@given(
    offsets=st.lists(st.integers(min_value=0, max_value=600), max_size=26),
)
def test_groups_partition_the_input_with_the_window_and_letter_rules(offsets: list[int]) -> None:
    services = [(f"id{i}", f"Service {i:02d}", at(minute)) for i, minute in enumerate(offsets)]

    groups = group_due(services)

    seen = [item.service_id for group in groups for item in group.items]
    assert sorted(seen) == sorted(service_id for service_id, _, _ in services)
    previous_start: datetime | None = None
    for group in groups:
        first = group.items[0].due
        assert group.due == first
        assert group.reply_by == first + REPLY_WINDOW
        for item in group.items:
            assert first <= item.due < first + GROUP_WINDOW
        if previous_start is not None:
            assert first >= previous_start + GROUP_WINDOW
        previous_start = first
        dues = [item.due for item in group.items]
        assert dues == sorted(dues)
        if len(group.items) == 1:
            assert group.items[0].letter is None
        else:
            by_name = sorted(group.items, key=lambda item: item.name)
            assert [item.letter for item in by_name] == [
                chr(ord("A") + i) for i in range(len(group.items))
            ]
