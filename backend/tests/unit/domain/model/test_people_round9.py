"""Round 9 (owner decision, DEC-065 item 11): a staff name holds at most nine digits in total.

Every character that is not a digit is removed, and the name is refused if ten or more digits
remain. No separator list is used, so a phone number is refused in any punctuation or spacing.
A refusal names the field only and never echoes the value.
"""

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import Practitioner

# Neutral ids: a pytest id is built from its value, so a probe number must not appear in an id
# (DEC-065 item 7).
REFUSED = [
    pytest.param("Duty 943/476/5919", id="slash-grouped-10"),
    pytest.param("Duty 07700_900_123", id="underscore-grouped-11"),
    pytest.param("Duty 07700\t900\t123", id="tab-grouped-11"),
    pytest.param("Duty (07700) 900 123", id="bracket-grouped-11"),
    pytest.param("Duty 07700.900.123", id="full-stop-grouped-11"),
    pytest.param("Duty +44 7700 900123", id="plus-grouped-12"),
    pytest.param("Duty 943 476 5919", id="space-grouped-10"),
    pytest.param("Duty 9434765919", id="contiguous-10"),
    pytest.param("Duty 0770 090 0123", id="space-grouped-11"),
    pytest.param("Shift 2026 10 26 ref 12", id="ten-digits-across-words"),
]

ACCEPTED = [
    pytest.param("Dr A Example", id="staff-title-initial"),
    pytest.param("Ward 4B", id="ward-short-number"),
    pytest.param("Room 12B", id="room-short-number"),
    pytest.param("Bed 4 of 12", id="bed-short-numbers"),
    pytest.param("943476591", id="nine-digit-run"),
    pytest.param("Sharon Smith", id="staff-plain-name"),
]


def _with_name(display_name: str) -> Practitioner:
    return Practitioner(id="p1", active=True, display_name=display_name, phone_hash=None)


@pytest.mark.parametrize("display_name", REFUSED)
def test_a_name_with_ten_or_more_digits_in_total_is_refused(display_name: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _with_name(display_name)

    assert refused.value.field == "display_name"
    assert "5919" not in str(refused.value)
    assert "900" not in str(refused.value)


@pytest.mark.parametrize("display_name", ACCEPTED)
def test_a_name_with_nine_or_fewer_digits_in_total_is_accepted(display_name: str) -> None:
    assert _with_name(display_name).display_name == display_name
