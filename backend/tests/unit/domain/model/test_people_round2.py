"""Round 2 (verifier finding): the shape of a phone hash and an email domain on a Practitioner.

A phone hash is None or exactly 64 lowercase hex characters. An email domain is a bare domain:
lowercase letters, digits, hyphens and dots, at least one dot, and no '@' or spaces. A refusal names
the field only; it never echoes the value, because the value may be a phone number or an address.
"""

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import Practitioner, check_phone_hash

VALID_HASH = "ab" * 32

# The ids are neutral on purpose: pytest builds ids from the values, and a probe value such as a
# phone number or an address must never appear in a test name (DEC-065 item 6).
BAD_PHONE_HASHES = [
    pytest.param("07700900123", id="raw-phone"),
    pytest.param("A" * 64, id="upper-hex"),
    pytest.param("a" * 63, id="short-hex"),
    pytest.param("a" * 65, id="long-hex"),
    pytest.param("g" * 64, id="non-hex"),
    pytest.param(" " + "a" * 63, id="leading-space"),
    pytest.param("", id="empty"),
]

GOOD_DOMAINS = ["nhs.example", "dorset.nhs.uk", "a-b.c1.example"]
BAD_DOMAINS = [
    pytest.param("jane.doe@nhs.example", id="full-email"),
    pytest.param("nodot", id="no-dot"),
    pytest.param("Upper.Example", id="upper-case"),
    pytest.param("nhs .example", id="space"),
    pytest.param("nhs.example.", id="trailing-dot"),
    pytest.param("", id="empty"),
]


@pytest.mark.parametrize("phone_hash", BAD_PHONE_HASHES)
def test_a_phone_hash_must_be_64_lowercase_hex_characters(phone_hash: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        Practitioner(id="p1", active=True, display_name="Duty", phone_hash=phone_hash)

    assert refused.value.field == "phone_hash"


def test_a_raw_phone_number_is_refused_and_not_echoed() -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_phone_hash("07700900123")

    assert refused.value.field == "phone_hash"
    assert "07700900123" not in str(refused.value)


def test_no_phone_hash_is_allowed() -> None:
    person = Practitioner(id="p1", active=True, display_name="Duty", phone_hash=None)

    assert person.phone_hash is None


def test_a_valid_phone_hash_is_accepted() -> None:
    person = Practitioner(id="p1", active=True, display_name="Duty", phone_hash=VALID_HASH)

    assert person.phone_hash == VALID_HASH


@pytest.mark.parametrize("domain", GOOD_DOMAINS)
def test_a_bare_domain_is_accepted(domain: str) -> None:
    person = Practitioner(
        id="p1", active=True, display_name="Duty", phone_hash=None, email_domain=domain
    )

    assert person.email_domain == domain


@pytest.mark.parametrize("domain", BAD_DOMAINS)
def test_an_email_domain_must_be_a_bare_domain(domain: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        Practitioner(
            id="p1", active=True, display_name="Duty", phone_hash=None, email_domain=domain
        )

    assert refused.value.field == "email_domain"


def test_a_full_address_in_the_email_domain_is_refused_and_not_echoed() -> None:
    with pytest.raises(ValidationFailed) as refused:
        Practitioner(
            id="p1",
            active=True,
            display_name="Duty",
            phone_hash=None,
            email_domain="jane.doe@nhs.example",
        )

    assert refused.value.field == "email_domain"
    assert "jane.doe" not in str(refused.value)
