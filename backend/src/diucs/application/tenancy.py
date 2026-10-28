"""DEC-010 stub for the red commit of TEN-001: the names of the tenancy kernel, no behaviour."""

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self


class ScopeKind(StrEnum):
    TENANT = "tenant"
    NETWORK = "network"


NETWORK_PREFIX: Final = "net-"
DEFAULT_TENANT_ID: Final = "default"
TENANT_ID_PATTERN: Final = r"[a-z0-9][a-z0-9-]{1,30}"
NETWORK_ID_PATTERN: Final = r"net-[a-z0-9][a-z0-9-]{1,26}"

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


def is_valid_tenant_id(text: str) -> bool:
    raise NotImplementedError


class TenancyError(RuntimeError):
    pass


class ScopeInvalid(TenancyError):
    pass


class TenantNotBound(TenancyError):
    pass


class TenantParameterRefused(TenancyError):
    pass


class QueryNotRegistered(TenancyError):
    pass


class GlobalStatementMisuse(TenancyError):
    pass


@dataclass(frozen=True, slots=True)
class ScopeId:
    value: str
    kind: ScopeKind

    @classmethod
    def tenant(cls, value: str) -> Self:
        raise NotImplementedError

    @classmethod
    def network(cls, value: str) -> Self:
        raise NotImplementedError

    @classmethod
    def parse(cls, value: str) -> Self:
        raise NotImplementedError

    def __str__(self) -> str:
        raise NotImplementedError


_SCOPE: ContextVar[ScopeId | None] = ContextVar("diucs_tenancy_scope", default=None)


@contextlib.contextmanager
def bind_scope(scope: ScopeId) -> Iterator[ScopeId]:
    raise NotImplementedError
    yield scope


def bind_tenant(tenant_id: str) -> contextlib.AbstractContextManager[ScopeId]:
    raise NotImplementedError


def current_scope_or_none() -> ScopeId | None:
    raise NotImplementedError


def current_scope() -> ScopeId:
    raise NotImplementedError


def current_tenant() -> str:
    raise NotImplementedError
