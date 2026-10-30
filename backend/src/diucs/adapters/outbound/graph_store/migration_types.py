"""The shape of a migration and the failure of one (TEN-005).

A migration is a list of schema statements, each run in its own write transaction, then a list of
loop statements (data steps repeated in batches until they report no change), both given the
migration's parameters. The areas of the schema each own a module that holds its migrations as
data (`migrations_tenant.py`, `migrations_network.py`); `migrations.py` assembles them and runs
them. This module holds no Cypher and runs none, so every area can import it.
"""

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
    # Names of constraints that must exist before the first statement runs (TEN-032: a key is
    # dropped only when its replacement is there). A missing one stops the migration untouched.
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.batch < 1:
            raise ValueError("a migration batch must be at least 1")
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
