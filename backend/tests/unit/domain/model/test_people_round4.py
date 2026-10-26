"""Round 4 (verifier finding): a phone number cannot be carried in a staff name.

A run of ten or more digits is refused in staff text, whether the digits are contiguous or grouped
with a space or a hyphen between two digits. Refused by field name only, never echoed. A short
number, such as a ward number, is a name and is accepted.
"""

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import Practitioner

# Neutral ids: a pytest id is built from its value, so a probe number must not appear in an id
# (DEC-065 item 7).
REFUSED = [
    pytest.param("Duty 07700900123", id="contiguous-11"),
    pytest.param("Duty 07700 900 123", id="grouped-5-3-3"),
    pytest.param("Duty 077 009 00123", id="grouped-3-3-5"),
    pytest.param("Duty 077 0090 0123", id="grouped-3-4-4"),
    pytest.param("Duty 0770-090-0123", id="hyphen-grouped-4-3-4"),
    pytest.param("Duty 0770-0900123", id="hyphen-grouped-4-7"),
    pytest.param("Duty 9434765919", id="contiguous-10"),
    pytest.param("Duty 943 476 5919", id="grouped-10"),
]

ACCEPTED = [
    pytest.param("Dr A Example", id="staff-title-initial"),
    pytest.param("Ward 4B", id="ward-short-number"),
    pytest.param("Room 12B", id="room-short-number"),
    pytest.param("Bed 4 of 12", id="bed-short-numbers"),
]


def _with_name(display_name: str) -> Practitioner:
    return Practitioner(id="p1", active=True, display_name=display_name, phone_hash=None)


@pytest.mark.parametrize("display_name", REFUSED)
def test_a_run_of_ten_or_more_digits_in_a_staff_name_is_refused(display_name: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _with_name(display_name)

    assert refused.value.field == "display_name"
    assert "07700" not in str(refused.value)
    assert "943" not in str(refused.value)


@pytest.mark.parametrize("display_name", ACCEPTED)
def test_a_short_number_or_plain_title_in_a_staff_name_is_accepted(display_name: str) -> None:
    assert _with_name(display_name).display_name == display_name
