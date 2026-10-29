"""The actor of a command: who asked, in what role, through which channel (contracts.md)."""

from dataclasses import dataclass

from diucs.domain.codes import Role


@dataclass(frozen=True, slots=True)
class Actor:
    role: Role
    practitioner_id: str | None
    device_id: str | None
    channel: str
    service_ids: frozenset[str]


SYSTEM_ACTOR = Actor(
    role=Role.AUDIT,
    practitioner_id=None,
    device_id=None,
    channel="system",
    service_ids=frozenset(),
)
"""The actor of a timer that the system runs on its own (U19): no person, no device, no service."""
