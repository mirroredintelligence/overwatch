"""Round 10 (verifier finding of round 9): every Unicode decimal digit counts (DEC-065 item 11).

A staff name holds at most nine digits in total, counting every Unicode decimal digit (category Nd),
whatever the script. A postcode written in fullwidth letters and digits is still refused: the
postcode check runs on NFKC-normalised text. A refusal names the field only and never echoes the value.
"""

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import Practitioner


def _fullwidth(digits: str) -> str:
    return "".join(chr(0xFF10 + int(d)) for d in digits)


def _arabic_indic(digits: str) -> str:
    return "".join(chr(0x0660 + int(d)) for d in digits)


# Neutral ids: a pytest id is built from its value, so a probe number must not appear in an id
# (DEC-065 item 7).
REFUSED = [
    pytest.param("Duty " + _fullwidth("07700900123"), id="fullwidth-eleven"),
    pytest.param("Duty " + _arabic_indic("07700900123"), id="arabic-indic-eleven"),
    pytest.param("Duty 943476591" + _arabic_indic("2"), id="nine-ascii-one-arabic-indic"),
    pytest.param("Duty ＳＷ１Ａ １ＡＡ", id="fullwidth-postcode"),
]

ACCEPTED = [
    pytest.param("Ward 4B", id="ward-short-number"),
    pytest.param("Bed " + _arabic_indic("943476591"), id="nine-arabic-indic-digits"),
    pytest.param("Bed " + _fullwidth("943476591"), id="nine-fullwidth-digits"),
    pytest.param("Bed 943476591", id="nine-ascii-digits"),
]


def _with_name(display_name: str) -> Practitioner:
    return Practitioner(id="p1", active=True, display_name=display_name, phone_hash=None)


@pytest.mark.parametrize("display_name", REFUSED)
def test_every_unicode_digit_counts_towards_the_nine_digit_limit(display_name: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _with_name(display_name)

    assert refused.value.field == "display_name"
    assert "0770" not in str(refused.value)
    assert "900" not in str(refused.value)


@pytest.mark.parametrize("display_name", ACCEPTED)
def test_nine_or_fewer_digits_in_any_script_are_accepted(display_name: str) -> None:
    assert _with_name(display_name).display_name == display_name
