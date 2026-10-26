"""Round 8 (verifier finding): the digit-run rule covers every separator a phone number uses.

A run of ten or more digits is refused in staff text when its digit groups are separated by a
space, a hyphen, a full stop, round brackets or a plus sign (DEC-065 item 9, superseded by item 11;
these cases still hold under item 11). A short number, and
a run of nine digits, is a name and is accepted. A refusal names the field only and never echoes
the value.
"""

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import Practitioner

# Neutral ids: a pytest id is built from its value, so a probe number must not appear in an id
# (DEC-065 item 7).
REFUSED = [
    pytest.param("Duty (07700) 900 123", id="bracket-then-space-grouped"),
    pytest.param("Duty 07700.900.123", id="full-stop-grouped"),
    pytest.param("Duty +44 7700 900123", id="plus-then-grouped"),
    pytest.param("Duty (0770) 090 0123", id="bracket-grouped-4-3-4"),
]

ACCEPTED = [
    pytest.param("Dr A Example", id="staff-title-initial"),
    pytest.param("Ward 4B", id="ward-short-number"),
    pytest.param("Bed 4 of 12", id="bed-short-numbers"),
    pytest.param("Room 123456789", id="nine-digit-run"),
]


def _with_name(display_name: str) -> Practitioner:
    return Practitioner(id="p1", active=True, display_name=display_name, phone_hash=None)


@pytest.mark.parametrize("display_name", REFUSED)
def test_a_run_of_ten_digits_with_any_phone_separator_is_refused(display_name: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _with_name(display_name)

    assert refused.value.field == "display_name"
    assert "07700" not in str(refused.value)
    assert "0770" not in str(refused.value)


@pytest.mark.parametrize("display_name", ACCEPTED)
def test_a_name_with_a_short_number_or_a_nine_digit_run_is_accepted(display_name: str) -> None:
    assert _with_name(display_name).display_name == display_name
