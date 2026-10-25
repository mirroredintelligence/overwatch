"""The link-token record holds only a 64-character hex phone hash (P10, H-09, DEC-047).

A phone number, a name or a postcode in the phone field must be refused when the record is built,
so no raw identity value can reach the store through this type.
"""

from datetime import UTC, datetime

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.tokens import LinkTokenRecord

EXPIRES = datetime(2026, 10, 25, 12, 30, tzinfo=UTC)
GOOD_HASH = "ab" * 32


def _record(phone_hash: str | None) -> LinkTokenRecord:
    return LinkTokenRecord(
        token_hash="c" * 64,
        purpose="booking-reply",
        about_id="svc-1",
        phone_hash=phone_hash,
        expires_at=EXPIRES,
        used_at=None,
    )


def test_a_64_character_hex_phone_hash_is_accepted() -> None:
    assert _record(GOOD_HASH).phone_hash == GOOD_HASH


def test_no_phone_hash_is_accepted() -> None:
    assert _record(None).phone_hash is None


@pytest.mark.parametrize(
    "value",
    [
        "07700 900123",  # a phone number, raw
        "+44 7700 900123",
        "Jane Smith",  # a name
        "DT4 8XX",  # a postcode
        "ab" * 31,  # 62 characters
        "ab" * 33,  # 66 characters
        "g" * 64,  # not hex
        "AB" * 32,  # upper-case hex is not the form we store
        "",
    ],
)
def test_a_phone_field_that_is_not_a_64_character_hex_hash_is_refused(value: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _record(value)
    assert refused.value.field == "phone_hash"
    if value:
        assert value not in str(refused.value)
