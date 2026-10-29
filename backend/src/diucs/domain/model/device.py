"""A wall screen as a device record (U10, DEC-160).

A wall display holds no patient data and reads only the board. The record carries the name the shift
lead gave it, an optional place, the status of its pairing, and the keyed hash of its device token
once the screen has collected the token. The token itself is never part of a record.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.privacy_guard import find_patient_data

SCREEN_LABEL_MAX: Final = 60
_TOKEN_HASH: Final = re.compile(r"[0-9a-f]{64}")


class DeviceStatus(StrEnum):
    PAIRED_UNCLAIMED = "paired-unclaimed"
    ACTIVE = "active"
    REVOKED = "revoked"


class DeviceType(StrEnum):
    WALL_DISPLAY = "wall-display"


class BoardScope(StrEnum):
    """Which board the screen shows. A reader that sees anything but NETWORK shows the tenant's
    own board (DEC-132 item 5)."""

    TENANT = "tenant"
    NETWORK = "network"


@dataclass(frozen=True, slots=True)
class Device:
    id: str
    status: DeviceStatus
    name: str
    location: str | None
    device_type: DeviceType
    token_hash: str | None
    board_scope: BoardScope = BoardScope.TENANT

    def __post_init__(self) -> None:
        """The name and place are checked and trimmed. A screen waiting to collect its token has no
        hash, an active one has the keyed hash (64 lower-case hex characters), and a revoked one
        may keep or lose it."""
        object.__setattr__(self, "name", check_screen_label(self.name, "name"))
        if self.location is not None:
            object.__setattr__(self, "location", check_screen_label(self.location, "location"))
        if self.token_hash is not None and not _TOKEN_HASH.fullmatch(self.token_hash):
            raise ValidationFailed("token_hash", "must be a 64-character lower-case hex digest")
        if self.status is DeviceStatus.PAIRED_UNCLAIMED and self.token_hash is not None:
            raise ValidationFailed(
                "token_hash", "a screen that has not collected its token has none"
            )
        if self.status is DeviceStatus.ACTIVE and self.token_hash is None:
            raise ValidationFailed("token_hash", "an active screen has a token hash")


def check_screen_label(value: str, field: str) -> str:
    """The trimmed text of a screen name or place, or ValidationFailed naming the field.

    It must have 1 to SCREEN_LABEL_MAX printable characters once trimmed, and no shape of patient
    data (a full postcode, an NHS number, a titled name: the privacy guard of D17). The message
    never echoes the text. A name is typed by a person and is shown on a wall, so it is checked
    before it is stored (DEC-160)."""
    if not isinstance(value, str):
        raise ValidationFailed(field, "must be text")
    text = value.strip()
    if not text:
        raise ValidationFailed(field, "must not be empty")
    if len(text) > SCREEN_LABEL_MAX:
        raise ValidationFailed(field, f"must be at most {SCREEN_LABEL_MAX} characters")
    if not text.isprintable():
        raise ValidationFailed(field, "must not hold control characters")
    if find_patient_data(text):
        raise ValidationFailed(field, "must not hold anything that looks like patient information")
    return text
