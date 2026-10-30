"""The one place the Neo4j driver is created, and the one place named queries are run.

DEC-012: the composition root creates one AsyncDriver per process with create_driver, and closes it
on shutdown. Nothing else constructs a driver.

DEC-130 item 2, DEC-142: run_query is the execution point that binds the tenant, and
run_global_query is the only way an allowlisted global statement runs. Both take a registered
NamedQuery and nothing else. An architecture test checks that nothing else under src (the
migration runner aside) executes Cypher.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncManagedTransaction, AsyncTransaction

from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery, QueryRegistry
from diucs.application.tenancy import (
    GlobalStatementMisuse,
    PlatformStatementMisuse,
    QueryNotRegistered,
    RawTransactionRefused,
    ScopeId,
    TenantNotBound,
    TenantParameterRefused,
)

QueryObserver = Callable[[str, str, int, float], None]

# The Bolt logger writes every RUN message, with its Cypher text, at DEBUG, and the notifications
# logger writes each server notification with the query text. Both stay at INFO or above, so a
# DEBUG root logger does not put Cypher into the logs (DEC-012, L10).
_TEXT_LOGGERS = ("neo4j.io", "neo4j.notifications")

_observer: QueryObserver | None = None


def create_driver(
    uri: str,
    user: str,
    password: str,
    *,
    max_connection_lifetime: float = 1800.0,
    liveness_check_timeout: float = 30.0,
    connection_acquisition_timeout: float = 30.0,
    max_connection_pool_size: int = 50,
) -> AsyncDriver:
    """Build the driver with the DEC-012 staleness and pool bounds. It opens no connection until a
    session first needs one.

    Server notifications are switched off, and the loggers that write query text are held at INFO
    (see _TEXT_LOGGERS). Nothing in this code base relies on the notifications.
    """
    for name in _TEXT_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
    return AsyncGraphDatabase.driver(
        uri,
        auth=(user, password),
        max_connection_lifetime=max_connection_lifetime,
        liveness_check_timeout=liveness_check_timeout,
        connection_acquisition_timeout=connection_acquisition_timeout,
        max_connection_pool_size=max_connection_pool_size,
        notifications_min_severity="OFF",
    )


def _refuse_tenant_parameter(params: dict[str, Any]) -> None:
    """Refuse `tenant`, and refuse `parameters`: neo4j's own `tx.run(query, parameters=None, **kw)`
    merges that dict with the keywords, so it is a second way to hand the server a tenant."""
    if "tenant" in params or "parameters" in params:
        raise TenantParameterRefused


@dataclass(frozen=True, slots=True)
class ScopedTx:
    """A transaction and the scope its unit of work opened under (DEC-132 item 4, TEN-002).

    It has no `run` and no other way to execute Cypher: the only way to run a statement on it is
    `run_query`, so a repository cannot bypass the tenant parameter. The scope is never None: a
    transaction with no scope cannot be made (TEN-030, `TenantNotBound`).
    """

    tx: AsyncManagedTransaction | AsyncTransaction
    scope: ScopeId

    def __post_init__(self) -> None:
        if self.scope is None:
            raise TenantNotBound


# What a tenant statement runs on (TEN-030, DEC-146 item 2): a ScopedTx and nothing else. A raw
# driver transaction is refused at run time, and the annotation of every repository says so, so
# mypy refuses to hand one to `run_query` too.
type Tx = ScopedTx
# What a global statement runs on: it carries no scope, so a raw transaction is fine (the health
# ping and the tenant directory run before any scope exists), and so is a scoped one.
type GlobalTx = AsyncManagedTransaction | AsyncTransaction | ScopedTx


async def _execute(
    tx: GlobalTx, query: NamedQuery, parameters: dict[str, Any]
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    raw = tx.tx if isinstance(tx, ScopedTx) else tx
    result = await raw.run(query.cypher, parameters)
    rows = await result.data()
    duration_ms = (time.perf_counter() - started) * 1000
    observer = _observer
    if observer is not None:
        observer(query.id, query.mode, len(rows), duration_ms)
    return rows


async def run_query(
    tx: Tx,
    query: NamedQuery,
    /,
    *,
    registry: QueryRegistry | None = None,
    **params: Any,
) -> list[dict[str, Any]]:
    """Run a registered tenant statement inside the caller's transaction and return its rows as
    dicts. The registry is the module registry unless one is given.

    The execution point of DEC-130 item 2 and DEC-142, with one path and no exemption (TEN-030).
    In this order, all before any Cypher is sent: a string or a statement that is not the
    registered one is refused; a caller-supplied `tenant` is refused; a global statement is
    refused; a transaction that is not a `ScopedTx` is refused (`RawTransactionRefused`), whatever
    is bound in the context. Otherwise the statement runs with `tenant=<the scope>`, written first
    and with nothing in `params` able to replace it.

    The scope is the one the `ScopedTx` carries: the unit of work took it when it opened, and no
    rebinding of the context afterwards changes it, even to none.

    The observer, if set, is called once per successful run with the query id, its mode, the row
    count and the duration in milliseconds. It never receives the Cypher text, the parameters or
    the scope.
    """
    lookup = REGISTRY if registry is None else registry
    if not lookup.is_registered(query):
        raise QueryNotRegistered
    _refuse_tenant_parameter(params)
    if query.scope == "global":
        raise GlobalStatementMisuse
    if query.scope == "platform":
        raise PlatformStatementMisuse
    if not isinstance(tx, ScopedTx):
        raise RawTransactionRefused
    return await _execute(tx, query, {"tenant": tx.scope.value, **params})


async def run_global_query(
    tx: GlobalTx,
    query: NamedQuery,
    /,
    *,
    registry: QueryRegistry | None = None,
    **params: Any,
) -> list[dict[str, Any]]:
    """Run a global statement (one on GLOBAL_QUERY_IDS) with no tenant parameter, whether or not a
    scope is bound. The only way a global statement runs: the health ping runs before any scope
    exists. Refuses a string, an unregistered statement, a `tenant` parameter and any tenant
    statement.
    """
    lookup = REGISTRY if registry is None else registry
    if not lookup.is_registered(query):
        raise QueryNotRegistered
    _refuse_tenant_parameter(params)
    if query.scope != "global":
        raise GlobalStatementMisuse
    return await _execute(tx, query, params)


async def run_platform_query(
    tx: GlobalTx,
    query: NamedQuery,
    /,
    *,
    registry: QueryRegistry | None = None,
    **params: Any,
) -> list[dict[str, Any]]:
    """Run a platform statement (one on PLATFORM_QUERY_IDS: the tenant registry's writes, TEN-028)
    with no tenant parameter, whether or not a scope is bound. The only way a platform statement
    runs, and called only by `graph_store/tenant_registry.py`. Refuses a string, an unregistered
    statement, a `tenant` parameter and any tenant or global statement."""
    lookup = REGISTRY if registry is None else registry
    if not lookup.is_registered(query):
        raise QueryNotRegistered
    _refuse_tenant_parameter(params)
    if query.scope != "platform":
        raise PlatformStatementMisuse
    return await _execute(tx, query, params)


def set_query_observer(fn: QueryObserver | None) -> None:
    global _observer
    _observer = fn
