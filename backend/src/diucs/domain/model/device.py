"""A wall screen as a device record (U10, DEC-160).

A wall display holds no patient data and reads only the board. The record carries the name the shift
lead gave it, an optional place, the status of its pairing, and the keyed hash of its device token
once the screen has collected the token. The token itself is never part of a record.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

SCREEN_LABEL_MAX: Final = 60


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


def check_screen_label(value: str, field: str) -> str:
    """The trimmed text of a screen name or place, or ValidationFailed."""
    raise NotImplementedError
