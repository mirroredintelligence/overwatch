"""The one table of plain words for the needs (DEC-062 item 2, WB4): fall-no-injury prints as
"fall, no injury", never as its code. The clinical notice, the booking messages (B1 to B3), the
booking pages and the case summary all take their words from this table (KI-650, H-489).
"""

import pytest

from diucs.domain.codes import NeedCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.need_words import NEED_WORDS, is_need_words, need_words

# DEC-062 item 2, word for word.
DECIDED = {
    NeedCategory.FALL_NO_INJURY: "fall, no injury",
    NeedCategory.FRAILTY: "frailty",
    NeedCategory.WOUND_CARE: "wound care",
    NeedCategory.IV_THERAPY: "IV therapy",
    NeedCategory.PALLIATIVE: "palliative care",
    NeedCategory.DEMENTIA: "dementia",
    NeedCategory.SUSPECTED_FRACTURE: "suspected fracture",
    NeedCategory.HEAD_INJURY_ANTICOAGULANTS: "head injury on anticoagulants",
    NeedCategory.INFECTION_ISOLATION: "infection or isolation",
}


def test_the_table_is_the_decided_wording_for_every_need() -> None:
    assert dict(NEED_WORDS) == DECIDED
    assert set(NEED_WORDS) == set(NeedCategory)


def test_no_label_is_a_raw_code_with_a_hyphen() -> None:
    assert not [label for label in NEED_WORDS.values() if "-" in label]


def test_one_need_is_its_label() -> None:
    assert need_words((NeedCategory.PALLIATIVE,)) == "palliative care"


def test_two_needs_are_joined_with_and() -> None:
    assert (
        need_words((NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY))
        == "fall, no injury and frailty"
    )


def test_three_needs_are_comma_separated_with_and_before_the_last() -> None:
    needs = (NeedCategory.WOUND_CARE, NeedCategory.IV_THERAPY, NeedCategory.INFECTION_ISOLATION)
    assert need_words(needs) == "wound care, IV therapy and infection or isolation"


def test_every_need_at_once_names_every_need_once() -> None:
    text = need_words(tuple(NeedCategory))
    assert all(label in text for label in NEED_WORDS.values())
    assert text.count(" and ") == 1


def test_no_need_is_refused_as_incomplete() -> None:
    with pytest.raises(ValidationFailed) as error:
        need_words(())
    assert error.value.field == "needs"


@pytest.mark.parametrize("size", [1, 2, 3, 9])
def test_what_need_words_writes_is_accepted_back(size: int) -> None:
    needs = tuple(NeedCategory)[:size]
    assert is_need_words(need_words(needs))


@pytest.mark.parametrize(
    "text",
    [
        "fall-no-injury",
        "fall and frailty",
        "fall",
        "palliative",
        "frailty.",
        "frailty ",
        " frailty",
        "",
        "Jane Smith",
        "frailty and",
        "and frailty",
        "frailty, ",
        "frailty and dementia and wound care",
        "frailty 943 476 5919",
        "DT4 8XX",
        "Frailty",
    ],
)
def test_text_that_is_not_the_table_s_words_is_refused(text: str) -> None:
    assert not is_need_words(text)


def test_a_value_that_is_not_text_is_refused() -> None:
    assert not is_need_words(None)
    assert not is_need_words(("frailty",))
