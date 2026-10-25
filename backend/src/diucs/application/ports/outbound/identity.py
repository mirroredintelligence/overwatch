"""Phone hashing for identity lookups (P10, H-09). A phone number is stored only as a keyed hash.

The hash is HMAC-SHA256 with the secret `phone-hash`, over the normalised UK mobile number (eleven
digits starting 07), so "+44 7700 900123" and "07700 900123" are the same subscriber. A number is
never echoed in an error. Decisions: DEC-057.
"""

import hashlib
import hmac
import re
from typing import Final, Protocol

from diucs.application.ports.outbound.tokens import SecretStore
from diucs.domain.errors import ValidationFailed

PHONE_HASH_SECRET: Final = "phone-hash"

_SEPARATORS: Final = re.compile(r"[ \-().]")
_UK_MOBILE: Final = re.compile(r"07[0-9]{9}")


class PhoneHasher(Protocol):
    def hash(self, number: str) -> str: ...


class HmacPhoneHasher:
    def __init__(self, secrets: SecretStore) -> None:
        self._secrets = secrets

    def hash(self, number: str) -> str:
        national = normalise_uk_mobile(number)
        key = self._secrets.get(PHONE_HASH_SECRET)
        return hmac.new(key, national.encode("ascii"), hashlib.sha256).hexdigest()


def normalise_uk_mobile(number: str) -> str:
    """Return the national form of a UK mobile number: eleven digits, starting 07.

    Accepted: national ("07700 900123"), +44 ("+44 7700 900123", "+44 (0)7700 900123") and 0044.
    Anything else, including a landline or a number of the wrong length, is refused as
    ValidationFailed on the field "phone", without the number in the message.
    """
    if not isinstance(number, str):
        raise ValidationFailed("phone", "must be text")
    compact = _SEPARATORS.sub("", number)
    if compact.startswith("+44"):
        national = "0" + compact[3:].removeprefix("0")
    elif compact.startswith("0044"):
        national = "0" + compact[4:]
    else:
        national = compact
    if not _UK_MOBILE.fullmatch(national):
        raise ValidationFailed("phone", "must be a UK mobile number")
    return national
