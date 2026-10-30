"""A scoped transaction a test can also run raw Cypher on (TEN-030).

`run_query` takes only a `ScopedTx`; a raw driver transaction is refused. A test that seeds or
reads with raw Cypher and also hands the same transaction to a repository needs both, so
`OpenTx` is a `ScopedTx` (it passes the `isinstance` check and carries the scope) that also
forwards `run`, `commit`, `rollback` and the rest to the transaction it wraps. It is for tests
only: production code never builds one, and the architecture test keeps `tests.support` out of
`src`.
"""

from typing import Any

from neo4j import AsyncManagedTransaction, AsyncTransaction

from diucs.adapters.outbound.graph_store.driver import ScopedTx
from diucs.application.tenancy import current_scope_or_none


class OpenTx(ScopedTx):
    """A `ScopedTx` that forwards everything else to the wrapped transaction."""

    def __getattr__(self, name: str) -> Any:
        return getattr(self.tx, name)

    async def run(self, query: Any, parameters: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        """Raw Cypher in a test says `{tenantId: $tenant}` and gets the bound tenant as `tenant`
        unless the caller passed one (a test that reads another tenant's nodes names it). On a
        Neo4j that other runs share, a statement without it would read and change their data
        too (TEN-035)."""
        merged = {**(parameters or {}), **kwargs}
        merged.setdefault("tenant", self.scope.value)
        return await self.tx.run(query, merged)


def scoped(tx: AsyncManagedTransaction | AsyncTransaction) -> Any:
    """The transaction as a test hands it to code under test: an `OpenTx` carrying the scope bound
    now, or the raw transaction itself when nothing is bound (it can then run raw Cypher, and a
    `run_query` on it is refused, which is the point)."""
    scope = current_scope_or_none()
    return tx if scope is None else OpenTx(tx, scope)


def scoped_stub(tx: object, tenant: str) -> Any:
    """A recording double of a transaction, carried on a `ScopedTx` for `tenant`: what a unit of
    work hands a repository. The double records what reaches it."""
    from diucs.application.tenancy import ScopeId

    return ScopedTx(tx, ScopeId.tenant(tenant))  # type: ignore[arg-type]
