"""Network settings (TEN-051). Stub for the red commit."""

from dataclasses import dataclass
from typing import Final

NAME_MAX_LENGTH: Final = 60


@dataclass(frozen=True, slots=True)
class NetworkSettings:
    system_name: str
    pathway_name: str
    time_zone: str
