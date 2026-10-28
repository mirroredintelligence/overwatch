"""The test side of the tenancy seam (TEN-003, DEC-130 item 9, DEC-147). DEC-010 stub: the names
and signatures, with no behaviour."""

import contextlib
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any, Final

from diucs.application.tenancy import ScopeId

LEAK_MESSAGE: Final = (
    "the bound tenant changed during the test: something bound another tenant and did not reset it"
)


class TenantLeak(AssertionError):
    pass


@dataclass(frozen=True, slots=True)
class RunIdentity:
    pid: int
    started: int
    nonce: str

    @property
    def token(self) -> str:
        return ""

    @property
    def tenant_id(self) -> str:
        return ""

    @property
    def other_tenant_id(self) -> str:
        return ""

    @property
    def network_id(self) -> str:
        return ""


def new_run_identity(
    *, pid: int | None = None, now: int | None = None, nonce: str | None = None
) -> RunIdentity:
    return RunIdentity(pid or 0, now or 0, nonce or "0000")


def parse_run_id(scope_value: str) -> RunIdentity | None:
    return None


def tenant_scope(tenant: str | ScopeId) -> ScopeId:
    raise NotImplementedError


def assert_bound_to(expected: str | ScopeId | None) -> None:
    return None


@contextlib.contextmanager
def as_tenant(tenant: str | ScopeId) -> Iterator[ScopeId]:
    yield ScopeId.tenant("zz-stub")


def in_tenant(
    tenant: str | ScopeId,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    return lambda function: function


def guard_async_test(
    function: Callable[..., Awaitable[Any]], expected: str | ScopeId | None
) -> Callable[..., Awaitable[Any]]:
    return function


def guard_sync_test(
    function: Callable[..., Any], expected: str | ScopeId | None
) -> Callable[..., Any]:
    return function
