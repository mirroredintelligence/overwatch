"""The tenant invariant check (TEN-031, DEC-134 item 11).

Neo4j Community cannot require a node to carry `tenantId`, and a composite constraint ignores a node
that has none, so a node written without one is invisible to every tenant-bound statement: a
service that vanishes from the board reads as "not listed", not "not updated". The check counts
those nodes and the relationships that join two scopes. It is made at start-up (the process refuses
to start on a violation) and once a day by the scheduled-work seam (it raises a flag).

A report carries label names, relationship types and counts, and nothing else: never an id, a
property value or a tenant, so it can be logged and shown.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class UnstampedNodes:
    """Nodes with this set of labels that carry no `tenantId` and are not registry nodes."""

    labels: tuple[str, ...]
    count: int


@dataclass(frozen=True, slots=True)
class CrossScope:
    """Relationships of this type that join two nodes of different scopes."""

    relationship_type: str
    count: int


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


@dataclass(frozen=True, slots=True)
class InvariantReport:
    unstamped: tuple[UnstampedNodes, ...] = ()
    cross_scope: tuple[CrossScope, ...] = ()

    @property
    def unstamped_total(self) -> int:
        return sum(group.count for group in self.unstamped)

    @property
    def cross_scope_total(self) -> int:
        return sum(group.count for group in self.cross_scope)

    @property
    def ok(self) -> bool:
        return self.unstamped_total == 0 and self.cross_scope_total == 0

    def summary(self) -> str:
        """One line of label names, relationship types and counts."""
        if self.ok:
            return (
                "the tenant invariants hold: no node without a tenantId "
                "and no relationship between two scopes"
            )
        parts: list[str] = []
        if self.unstamped_total:
            groups = ", ".join(f"{':'.join(g.labels)} x{g.count}" for g in self.unstamped)
            nodes = _plural(self.unstamped_total, "node has", "nodes have")
            parts.append(f"{nodes} no tenantId ({groups})")
        if self.cross_scope_total:
            groups = ", ".join(f"{g.relationship_type} x{g.count}" for g in self.cross_scope)
            joins = _plural(self.cross_scope_total, "relationship joins", "relationships join")
            parts.append(f"{joins} two scopes ({groups})")
        return "; ".join(parts)


class TenantInvariants(Protocol):
    async def check(self) -> InvariantReport: ...


class TenantInvariantViolated(RuntimeError):
    """The graph holds a node with no tenant or a relationship between two scopes. The process does
    not start, or (the daily check) a flag is raised. The message is the report's summary."""

    def __init__(self, report: InvariantReport) -> None:
        super().__init__(f"tenant invariants violated: {report.summary()}")
        self.report = report
