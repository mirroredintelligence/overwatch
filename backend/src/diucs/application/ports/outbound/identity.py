"""Phone hashing for identity lookups (P10, H-09). A phone number is stored only as a keyed hash.

The hash is HMAC-SHA256 with the secret `phone-hash`, over the normalised UK mobile number (eleven
digits starting 07), so "+44 7700 900123" and "07700 900123" are the same subscriber. A number is
never echoed in an error. Decisions: DEC-057.
"""

import hashlib
import hmac
import re
from datetime import datetime
from typing import Final, Protocol

from diucs.application.ports.outbound.tokens import SecretStore
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.device import Device
from diucs.domain.rules.identity_policy import CodeState, PinState

PHONE_HASH_SECRET: Final = "phone-hash"
DEVICE_TOKEN_SECRET: Final = "device-token"

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


class ContactStore(Protocol):
    """Protected phone numbers and role emails (P16). Only this port reads them."""

    async def put_phone(self, role_id: str, number: str) -> None: ...

    async def get_phone(self, role_id: str) -> str | None: ...

    async def put_email(self, role_id: str, email: str) -> None: ...

    async def get_email(self, role_id: str) -> str | None: ...


class CodeSender(Protocol):
    """Sends a text code to a phone (U25). The code is sent, never stored by the sender."""

    async def send_code(self, phone: str, code: str) -> None: ...


class CodeStore(Protocol):
    """Short-lived text-code state, keyed by the phone hash. Redis in production (I13)."""

    async def save(self, phone_hash: str, code_hash: str, state: CodeState) -> None: ...

    async def get(self, phone_hash: str) -> tuple[str, CodeState] | None: ...

    async def clear(self, phone_hash: str) -> None: ...


class PinStore(Protocol):
    """PIN hashes and their lock state, one credential per practitioner and device (P16)."""

    async def set_pin(self, practitioner_id: str, device_id: str, pin_hash: str) -> None: ...

    async def get(self, practitioner_id: str, device_id: str) -> tuple[str, PinState] | None: ...

    async def save_state(self, practitioner_id: str, device_id: str, state: PinState) -> None: ...

    async def clear_all(self, practitioner_id: str) -> None: ...


class DeviceRegistry(Protocol):
    """The devices a practitioner has registered (P16), and the wall screens of the tenant (U10).
    A revoked device is never known again."""

    async def register(self, practitioner_id: str, device_id: str, at: datetime) -> None: ...

    async def known(self, practitioner_id: str, device_id: str) -> bool: ...

    async def revoke_all(self, practitioner_id: str) -> None: ...

    async def get(self, device_id: str) -> Device | None:
        """The wall screen of the bound tenant with this id, or None. Takes the screen's write lock
        first, so a read that decides a single-use change cannot interleave with another (L85): use
        it inside the unit of work that saves. A device of another tenant is None."""
        ...

    async def save(self, device: Device) -> None:
        """Create or replace the wall screen of the bound tenant with this id. A device id that
        another tenant or a practitioner's device already holds is Conflict."""
        ...

    async def find_by_token_hash(self, token_hash: str) -> Device | None:
        """The ACTIVE wall screen of the bound tenant whose token hashes to this, or None: a screen
        that is not active, or of another tenant, is never found. More than one is Conflict."""
        ...
