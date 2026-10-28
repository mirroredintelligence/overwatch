"""Unit tests for the unit-label split used by the C2 wording (U03, DEC-115 item 13). Pure."""

import pytest

from diucs.application.use_cases.send_prompts import split_unit_label


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("referrals in the next 2 hrs", ("referrals", "in the next 2 hrs")),
        ("referrals", ("referrals", "")),
        ("referrals in", ("referrals in", "")),
        ("referrals in ", ("referrals in ", "")),
        (" in the next 2 hrs", (" in the next 2 hrs", "")),
    ],
)
def test_the_unit_label_is_split_into_unit_and_window_or_refused(
    label: str, expected: tuple[str, str]
) -> None:
    assert split_unit_label(label) == expected
