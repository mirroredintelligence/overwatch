"""Round 11 (owner decision, DEC-065 item 12): staff text is normalised before any check.

The order is: compatibility normalisation, removal of format characters (category Cf, such as a
zero-width space) and combining marks (category Mn), then the Unicode decimal digit count and the
postcode pattern. Superscripts, circled digits, combining marks and zero-width spaces therefore
cannot hide digits or a postcode. A refusal names the field only and never echoes the value.
"""

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import Practitioner

ZERO_WIDTH_SPACE = "​"
COMBINING_ACUTE = "́"
CIRCLED_ONE = "①"
SUPERSCRIPTS = [
    "⁰",
    "¹",
    "²",
    "³",
    "⁴",
    "⁵",
    "⁶",
    "⁷",
    "⁸",
    "⁹",
    "⁰",
]


def _with_name(display_name: str) -> Practitioner:
    return Practitioner(id="p1", active=True, display_name=display_name, phone_hash=None)


# Neutral ids: a pytest id is built from its value, so a probe number or postcode must not appear
# in an id (DEC-065 item 7).
REFUSED = [
    pytest.param("Bed 943476591" + CIRCLED_ONE, id="nine-ascii-one-circled"),
    pytest.param("Duty " + "".join(SUPERSCRIPTS), id="eleven-superscripts"),
    pytest.param("Duty 07700" + COMBINING_ACUTE + "90012", id="combining-mark-in-ten-digits"),
    pytest.param("Duty 07700" + ZERO_WIDTH_SPACE + "90012", id="zero-width-space-in-ten-digits"),
    pytest.param("Duty SW1A" + COMBINING_ACUTE + " 1AA", id="postcode-with-combining-mark"),
    pytest.param("Duty SW1A" + ZERO_WIDTH_SPACE + "1AA", id="postcode-with-zero-width-space"),
]

ACCEPTED = [
    pytest.param("Ward 4B", id="ward-short-number"),
    pytest.param("Bed 943476591", id="nine-ascii-digits"),
    pytest.param("Dr A Example", id="staff-title-initial"),
]


@pytest.mark.parametrize("display_name", REFUSED)
def test_hidden_digits_and_postcodes_are_refused_after_normalisation(display_name: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _with_name(display_name)

    assert refused.value.field == "display_name"
    assert "07700" not in str(refused.value)
    assert "SW1A" not in str(refused.value)


@pytest.mark.parametrize("display_name", ACCEPTED)
def test_ordinary_staff_names_stay_accepted_after_normalisation(display_name: str) -> None:
    assert _with_name(display_name).display_name == display_name


# Phone hash and email domain are ASCII by design and are not normalised (DEC-065 item 13).
# A fullwidth or Arabic-Indic digit must not be turned into an ASCII one and then accepted.
FULLWIDTH_HASH = "０" * 64
ARABIC_INDIC_HASH = "٠" * 64
FULLWIDTH_DOMAIN = "nhs．example"


@pytest.mark.parametrize(
    "phone_hash",
    [
        pytest.param(FULLWIDTH_HASH, id="fullwidth-hash"),
        pytest.param(ARABIC_INDIC_HASH, id="arabic-indic-hash"),
    ],
)
def test_a_phone_hash_with_non_ascii_digits_is_refused(phone_hash: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        Practitioner(id="p1", active=True, display_name="Duty", phone_hash=phone_hash)

    assert refused.value.field == "phone_hash"


def test_a_phone_hash_of_64_ascii_lowercase_hex_characters_is_accepted() -> None:
    person = Practitioner(id="p1", active=True, display_name="Duty", phone_hash="a1" * 32)

    assert person.phone_hash == "a1" * 32


def test_an_email_domain_with_a_fullwidth_dot_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        Practitioner(
            id="p1",
            active=True,
            display_name="Duty",
            phone_hash=None,
            email_domain=FULLWIDTH_DOMAIN,
        )

    assert refused.value.field == "email_domain"
