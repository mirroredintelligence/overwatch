"""The shape of a migration and the failure of one (TEN-005)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

MAX_LOOP_ITERATIONS: Final = 10_000


class MigrationFailed(RuntimeError):
    """A migration step failed. The message names the migration, the step and the class of the
    cause, never a statement or a value."""


@dataclass(frozen=True, slots=True)
class Migration:
    id: str
    statements: tuple[str, ...] = ()
    loops: tuple[str, ...] = ()
    params: Mapping[str, Any] = field(default_factory=dict, hash=False)
    batch: int = 10_000

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
