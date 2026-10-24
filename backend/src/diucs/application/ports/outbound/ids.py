"""Outbound port: new identifiers for records."""

from typing import Protocol


class IdGenerator(Protocol):
    def new_id(self) -> str:
        """Return a new identifier string."""
        ...
