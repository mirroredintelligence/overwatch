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
