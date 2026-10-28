"""The tenancy kernel: who a unit of work belongs to, and how the data layer finds out.

DEC-130 to DEC-132, DEC-142. A scope is a tenant or a network (DEC-132): both are bound the same
way and reach the data layer as the one `tenant` parameter. The edge of the system (an HTTP
dependency, a worker entry, a webhook) binds a scope once per unit of work from a verified source
and nothing else reads or writes the context variable except the graph store's execution point,
the unit of work and tests. No function takes a tenant argument.

Reused from the verified earlier branch (archived bundle, tip 2bdca21), without the warn and
enforce mode (DEC-142 item 7): this module holds the scope id, the binding and the fixed-message
errors, and nothing about how a statement is checked.

Standard library only (enforced by an import contract): this module is imported by the adapters and
must not pull a framework or a driver in with it.

Every error here has one fixed message and takes no argument, so no tenant id, parameter value or
Cypher text can ever be put in one. They are programming errors (a missing or wrong binding), not
`DomainError`s, and answer 500.
"""

import contextlib
import re
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Final, Self


class ScopeKind(StrEnum):
    TENANT = "tenant"
    NETWORK = "network"


# A network scope id starts with this reserved prefix and a tenant id may not, so the two can never
# be equal (DEC-132 item 4).
NETWORK_PREFIX: Final = "net-"
# The tenant that the backfill of TEN-005 assigns to the development data that exists today.
DEFAULT_TENANT_ID: Final = "default"

# 2 to 31 characters: lower case letters, digits and hyphen, no colon or slash, so the id is safe
# inside a Redis key, a Service Bus property and an idempotency key. Matched with fullmatch.
TENANT_ID_PATTERN: Final = r"[a-z0-9][a-z0-9-]{1,30}"
# `net-` and then 2 to 27 characters of the same alphabet: 6 to 31 characters in all.
NETWORK_ID_PATTERN: Final = r"net-[a-z0-9][a-z0-9-]{1,26}"
_TENANT_ID = re.compile(TENANT_ID_PATTERN)
_NETWORK_ID = re.compile(NETWORK_ID_PATTERN)

SCOPE_INVALID_MESSAGE: Final = "the scope id is not valid"
TENANT_NOT_BOUND_MESSAGE: Final = (
    "no tenant is bound for this work; bind one at the edge before running a query"
)
TENANT_PARAMETER_MESSAGE: Final = (
    "a query cannot be given a tenant parameter; the tenant is bound at the edge"
)
QUERY_NOT_REGISTERED_MESSAGE: Final = (
    "only a registered named query can run; a string or an unregistered query is refused"
)
GLOBAL_STATEMENT_MESSAGE: Final = (
    "a global statement runs only through run_global_query, "
    "and run_global_query runs only global statements"
)
UNIT_OF_WORK_OPEN_MESSAGE: Final = (
    "a unit of work is already open in this context; open the next one after this one has finished"
)
_TENANCY_ERROR_MESSAGE: Final = "a tenancy error"


def is_valid_tenant_id(text: str) -> bool:
    """True when text is a valid tenant id: 2 to 31 characters of `[a-z0-9-]`, starting with a
    letter or digit, and not a network id (`net-...`). The one validator that other layers use
    (the domain cannot import this module and keeps a copy under a parity test)."""
    return (
        isinstance(text, str)
        and _TENANT_ID.fullmatch(text) is not None
        and not text.startswith(NETWORK_PREFIX)
    )


class TenancyError(RuntimeError):
    """Base of the tenancy errors. Takes no argument; `str()` is the class's fixed message."""

    MESSAGE: ClassVar[str] = _TENANCY_ERROR_MESSAGE

    def __init__(self) -> None:
        super().__init__()

    def __str__(self) -> str:
        return self.MESSAGE


class ScopeInvalid(TenancyError):
    MESSAGE = SCOPE_INVALID_MESSAGE


class TenantNotBound(TenancyError):
    MESSAGE = TENANT_NOT_BOUND_MESSAGE


class TenantParameterRefused(TenancyError):
    MESSAGE = TENANT_PARAMETER_MESSAGE


class QueryNotRegistered(TenancyError):
    MESSAGE = QUERY_NOT_REGISTERED_MESSAGE


class GlobalStatementMisuse(TenancyError):
    MESSAGE = GLOBAL_STATEMENT_MESSAGE


class UnitOfWorkAlreadyOpen(TenancyError):
    MESSAGE = UNIT_OF_WORK_OPEN_MESSAGE


@dataclass(frozen=True, slots=True)
class ScopeId:
    """A tenant or a network, validated when it is built. Compares by value and kind."""

    value: str
    kind: ScopeKind

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not isinstance(self.kind, ScopeKind):
            raise ScopeInvalid
        if self.kind is ScopeKind.NETWORK:
            valid = _NETWORK_ID.fullmatch(self.value) is not None
        else:
            valid = is_valid_tenant_id(self.value)
        if not valid:
            raise ScopeInvalid

    @classmethod
    def tenant(cls, value: str) -> Self:
        return cls(value, ScopeKind.TENANT)

    @classmethod
    def network(cls, value: str) -> Self:
        return cls(value, ScopeKind.NETWORK)

    @classmethod
    def parse(cls, value: str) -> Self:
        """The kind is decided by the reserved prefix: `net-...` is a network, anything else a
        tenant."""
        is_network = isinstance(value, str) and value.startswith(NETWORK_PREFIX)
        return cls(value, ScopeKind.NETWORK if is_network else ScopeKind.TENANT)

    def __str__(self) -> str:
        return self.value


# Created and set only here (an architecture test checks it).
_SCOPE: ContextVar[ScopeId | None] = ContextVar("diucs_tenancy_scope", default=None)


@contextlib.contextmanager
def bind_scope(scope: ScopeId) -> Iterator[ScopeId]:
    """Bind a scope for the unit of work inside the block, and restore the previous binding on
    exit, normal or not (nesting restores the outer one)."""
    if not isinstance(scope, ScopeId):
        raise ScopeInvalid
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


def bind_tenant(tenant_id: str) -> contextlib.AbstractContextManager[ScopeId]:
    """`bind_scope` for a tenant id."""
    return bind_scope(ScopeId.tenant(tenant_id))


def current_scope_or_none() -> ScopeId | None:
    return _SCOPE.get()


def current_scope() -> ScopeId:
    scope = _SCOPE.get()
    if scope is None:
        raise TenantNotBound
    return scope


def current_tenant() -> str:
    """The bound tenant id. A bound network scope is not a tenant: a tenant use case must never
    run inside a network binding by accident."""
    scope = _SCOPE.get()
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope.value


# Created and set only here (an architecture test checks it). Holds the unit of work that is open in
# this context, so a second one cannot open inside it (DEC-132 item 4: a unit binds one scope).
_UNIT: ContextVar[object | None] = ContextVar("diucs_open_unit", default=None)


def claim_unit(owner: object) -> None:
    """Take the one place for an open unit of work in this context, or raise
    `UnitOfWorkAlreadyOpen`. Called only by the graph store's unit of work, when it opens.

    The claim is a context variable, so it follows the rules of the scope binding (lesson L151): a
    task started while a unit is open copies the claim and is refused; sibling tasks started from
    a context that holds none each get their own. A unit is entered and left in the same task: left
    in another one, its claim stays in the context that entered it.
    """
    if _UNIT.get() is not None:
        raise UnitOfWorkAlreadyOpen
    _UNIT.set(owner)


def release_unit(owner: object) -> None:
    """Give the place back, but only if `owner` still holds it: a release by another owner, a
    second release, or a release with nothing claimed changes nothing."""
    if _UNIT.get() is owner:
        _UNIT.set(None)


def scope_for_new_unit() -> ScopeId | None:
    """The scope a unit of work, or any other code that opens its own transaction, takes when it
    opens: the one bound now, or None when none is. Read once, at that moment, and carried on the
    transaction (`ScopedTx`), so a later rebinding of the context changes nothing for that unit.

    None is allowed while statements are on the ratchet (DEC-144 item 3): a unit opened unbound can
    run only those, and a converted statement refuses on it. TEN-030 empties the ratchet and makes
    this function refuse with `TenantNotBound`, which is the one place that change is made.
    """
    return current_scope_or_none()
