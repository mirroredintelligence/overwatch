"""The world of the network tests (TEN-060). Stub for the red commit."""

from dataclasses import dataclass
from typing import Final

NETWORK_INVARIANTS: Final[dict[str, str]] = {}


@dataclass(frozen=True, slots=True)
class WorldIds:
    owner: str
    members: tuple[str, str, str]
    outsider: str
    network: str
    other_network: str


def world_ids(identity: object) -> WorldIds:
    raise NotImplementedError
