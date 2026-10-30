"""The test side of the tenancy seam (TEN-003, DEC-130 item 9, DEC-147).

Each pytest session has one run identity (owner pid, start time, a short nonce) from which three
scope ids derive: a run tenant, a second tenant for cross-tenant tests, and a run network scope.
The conftest binds the run tenant around every integration test, and a guard fails a test that
leaves another tenant bound. `as_tenant` and `in_tenant` switch tenant inside a test.

Everything here binds through the production binder (`bind_scope`), so the code under test sees
exactly what production code sees. There is no second context variable.
"""

import contextlib
import functools
import inspect
import os
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any, Final

from diucs.application.tenancy import (
    ScopeId,
    ScopeInvalid,
    ScopeKind,
    bind_scope,
    current_scope_or_none,
)

LEAK_MESSAGE: Final = (
    "the bound tenant changed during the test: something bound another tenant and did not reset it"
)

_DIGITS: Final = "0123456789abcdefghijklmnopqrstuvwxyz"
_NONCE: Final = re.compile(r"[0-9a-f]{4}")
# `tt-<token>`, `tt-<token>-b` or `net-<token>`, where the token is `<pid>-<start>-<nonce>` with
# the pid and the start in base 36, and `-w<n>` (n in base 36) after the nonce for the identity of
# a pytest-xdist worker (TEN-035).
_RUN_ID: Final = re.compile(
    r"(?:tt-(?P<tp>[0-9a-z]+)-(?P<ts>[0-9a-z]+)-(?P<tn>[0-9a-f]{4})(?:-w(?P<tw>[0-9a-z]{1,3}))?"
    r"(?P<other>-b)?"
    r"|net-(?P<np>[0-9a-z]+)-(?P<ns>[0-9a-z]+)-(?P<nn>[0-9a-f]{4})(?:-w(?P<nw>[0-9a-z]{1,3}))?)"
)
# The largest values that keep every id within the 31 characters of a scope id: Linux pids stop at
# 2**22, and 2**36 seconds after the epoch is the year 4147.
MAX_PID: Final = 2**22
MAX_STARTED: Final = 2**36 - 1
# At most this many parallel workers (`-w` and three base-36 digits keep a scope id within 31).
MAX_WORKERS: Final = 4096
WORKERINPUT_KEY: Final = "diucs_run"
_WORKER_ID: Final = re.compile(r"gw(0|[1-9][0-9]*)")


class TenantLeak(AssertionError):
    """A test ended with another tenant (or none) bound. The message is fixed, with no tenant id."""


def _base36(number: int) -> str:
    """Lower case, no padding, `0` for zero."""
    if number == 0:
        return "0"
    out = ""
    while number:
        number, remainder = divmod(number, 36)
        out = _DIGITS[remainder] + out
    return out


def _is_whole(value: object, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Who a pytest session is: the process that owns it, when it started, and a nonce. Three
    scope ids derive from it, so two runs never share one and the orphan sweeper of TEN-033 can tell
    whose a leftover is."""

    pid: int
    started: int
    nonce: str
    # The number of the pytest-xdist worker this identity is for, or None for a session that has
    # no workers (and for the controller). A worker shares its controller's pid and start, so the
    # orphan sweeper finds the tenants of every worker when the controller dies (TEN-035).
    worker: int | None = None

    def __post_init__(self) -> None:
        if not _is_whole(self.pid, MAX_PID):
            raise ValueError("the run pid must be a whole number from 0 to 2**22")
        if not _is_whole(self.started, MAX_STARTED):
            raise ValueError("the run start must be a whole number of seconds from 0 to 2**36 - 1")
        if not isinstance(self.nonce, str) or _NONCE.fullmatch(self.nonce) is None:
            raise ValueError("the run nonce must be four lower-case hexadecimal characters")
        if self.worker is not None and not _is_whole(self.worker, MAX_WORKERS - 1):
            raise ValueError("the worker must be a whole number below 4096")

    @property
    def token(self) -> str:
        base = f"{_base36(self.pid)}-{_base36(self.started)}-{self.nonce}"
        return base if self.worker is None else f"{base}-w{_base36(self.worker)}"

    def for_worker(self, index: int) -> RunIdentity:
        """The identity of worker number `index` of this run: its own tenant, second tenant and
        network scope, and the owner (pid, start) of the run."""
        if self.worker is not None or not _is_whole(index, MAX_WORKERS - 1):
            raise ValueError(
                "the worker must be a whole number below 4096, of a run with no worker"
            )
        return RunIdentity(self.pid, self.started, self.nonce, index)

    @property
    def tenant_id(self) -> str:
        return f"tt-{self.token}"

    @property
    def other_tenant_id(self) -> str:
        return f"{self.tenant_id}-b"

    @property
    def network_id(self) -> str:
        return f"net-{self.token}"

    @property
    def scope_ids(self) -> tuple[str, str, str]:
        """Every scope this run may write to: the tenant, the second tenant and the network."""
        return (self.tenant_id, self.other_tenant_id, self.network_id)


def new_run_identity(
    *, pid: int | None = None, now: int | None = None, nonce: str | None = None
) -> RunIdentity:
    return RunIdentity(
        pid=os.getpid() if pid is None else pid,
        started=int(time.time()) if now is None else now,
        nonce=secrets.token_hex(2) if nonce is None else nonce,
    )


def parse_run_id(scope_value: str) -> RunIdentity | None:
    """The identity a tenant, other-tenant or network id was made from, or None for anything else
    (`default`, a value that does not decode, a bad nonce, a suffix on a network id, a token that
    is not written the way `RunIdentity.token` writes it). Whether the owner is still alive is the
    business of TEN-033."""
    if not isinstance(scope_value, str):
        return None
    found = _RUN_ID.fullmatch(scope_value)
    if found is None:
        return None
    pid_text = found["tp"] or found["np"]
    started_text = found["ts"] or found["ns"]
    nonce = found["tn"] or found["nn"]
    worker_text = found["tw"] or found["nw"]
    try:
        identity = RunIdentity(
            int(pid_text, 36),
            int(started_text, 36),
            nonce,
            None if worker_text is None else int(worker_text, 36),
        )
    except ValueError:
        return None
    if scope_value not in (identity.tenant_id, identity.other_tenant_id, identity.network_id):
        return None
    return identity


def workerinput_for(identity: RunIdentity) -> dict[str, object]:
    """What the controller sends each xdist worker (in `workerinput`): its own run identity, as
    plain values. The worker adds its number to it (`identity_from_workerinput`)."""
    return {WORKERINPUT_KEY: [identity.pid, identity.started, identity.nonce]}


def identity_from_workerinput(received: Mapping[str, object]) -> RunIdentity:
    """The identity of this worker, from the controller's `workerinput`: the controller's run and
    the number in `workerid` (`gw0`, `gw1`, ...). Anything else raises ValueError naming
    `workerinput`: a worker that cannot tell whose run it is must not guess a tenant."""
    run = received.get(WORKERINPUT_KEY)
    worker = received.get("workerid")
    if not isinstance(run, list | tuple) or len(run) != 3:
        raise ValueError("workerinput has no run identity from the controller")
    if not isinstance(worker, str) or (named := _WORKER_ID.fullmatch(worker)) is None:
        raise ValueError(f"workerinput has no usable worker id: {worker!r}")
    pid, started, nonce = run
    try:
        return RunIdentity(pid, started, nonce).for_worker(int(named.group(1)))
    except ValueError as error:
        raise ValueError(f"workerinput does not hold a valid run identity: {error}") from error


RUN_ENV: Final = "DIUCS_TEST_RUN"
WORKER_ENV: Final = "PYTEST_XDIST_WORKER"
_PROCESS_IDENTITY: RunIdentity | None = None


def derive_process_identity(environ: Mapping[str, str]) -> RunIdentity:
    """The identity of the process that holds `environ`. A pytest-xdist worker
    (`PYTEST_XDIST_WORKER` is `gw<n>`, set before any conftest is read) takes its controller's run
    from `DIUCS_TEST_RUN` (inherited from the controller, which exported it when it started) and
    its own number; any other process makes a new one. A worker with no run from its controller
    raises: it must not guess a tenant."""
    worker = environ.get(WORKER_ENV)
    if worker is None:
        return new_run_identity()
    controller = parse_run_token(environ.get(RUN_ENV, ""))
    if controller is None:
        raise ValueError(
            f"workerinput: a worker has no run identity from its controller ({RUN_ENV})"
        )
    return identity_from_workerinput({WORKERINPUT_KEY: _as_list(controller), "workerid": worker})


def _as_list(identity: RunIdentity) -> list[object]:
    return [identity.pid, identity.started, identity.nonce]


def parse_run_token(text: str) -> RunIdentity | None:
    """`<pid>.<started>.<nonce>` as `export_process_identity` writes it, or None."""
    parts = text.split(".")
    if len(parts) != 3 or not (parts[0].isdecimal() and parts[1].isdecimal()):
        return None
    try:
        return RunIdentity(int(parts[0]), int(parts[1]), parts[2])
    except ValueError:
        return None


def export_identity(identity: RunIdentity, environ: MutableMapping[str, str]) -> None:
    """Write the three scope ids of `identity` to `environ` (child processes and the front end's
    end-to-end run read them). A process with no worker number also writes its run token, so the
    workers it starts, which inherit the environment, derive their identities from it."""
    environ["DIUCS_TEST_TENANT"] = identity.tenant_id
    environ["DIUCS_TEST_OTHER_TENANT"] = identity.other_tenant_id
    environ["DIUCS_TEST_NETWORK"] = identity.network_id
    if identity.worker is None:
        environ[RUN_ENV] = f"{identity.pid}.{identity.started}.{identity.nonce}"


def process_identity() -> RunIdentity:
    """This process's run identity, made once and exported at once. The root conftest calls it
    when it is imported, so a module that reads the run's tenant while it is imported (a support
    module that a directory's conftest imports) finds it, however the tests were named on the
    command line."""
    global _PROCESS_IDENTITY
    if _PROCESS_IDENTITY is None:
        _PROCESS_IDENTITY = derive_process_identity(os.environ)
        export_identity(_PROCESS_IDENTITY, os.environ)
    return _PROCESS_IDENTITY


def run_host(label: str) -> str:
    """A host name that belongs to this run alone: `<label>-<run token>.example.org`. A tenant's
    host is looked up across the whole directory, so two runs that register `alpha.example.org`
    for their own tenants on one Neo4j would make it ambiguous (TEN-035). Lower case, one DNS
    label of at most 63 characters before the domain."""
    run_tenant = os.environ.get("DIUCS_TEST_TENANT", "")
    if not run_tenant.startswith("tt-") or not re.fullmatch(r"[a-z0-9]{1,20}", label):
        raise ValueError("run_host needs the run's tenant in the environment and a short label")
    return f"{label}-{run_tenant.removeprefix('tt-')}.example.org"


def tenant_scope(tenant: str | ScopeId) -> ScopeId:
    """A tenant scope from an id or a ScopeId. A network scope, or an invalid id, is refused."""
    if isinstance(tenant, ScopeId):
        if tenant.kind is not ScopeKind.TENANT:
            raise ScopeInvalid
        return tenant
    return ScopeId.tenant(tenant)


def assert_bound_to(expected: str | ScopeId | None) -> None:
    """Raise TenantLeak when the scope bound now is not `expected` (None: nothing bound)."""
    current = current_scope_or_none()
    if expected is None:
        matches = current is None
    else:
        wanted = expected if isinstance(expected, ScopeId) else ScopeId.parse(expected)
        matches = current == wanted
    if not matches:
        raise TenantLeak(LEAK_MESSAGE)


@contextlib.contextmanager
def as_tenant(tenant: str | ScopeId) -> Iterator[ScopeId]:
    """Bind another tenant for the block and restore the previous binding on exit, normal or not."""
    with bind_scope(tenant_scope(tenant)) as bound:
        yield bound


def in_tenant[**P, R](
    tenant: str | ScopeId,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorate an `async def` helper so it runs inside `as_tenant(tenant)`. The tenant is checked
    when the decorator is built, and a function that is not a coroutine function is refused."""
    scope = tenant_scope(tenant)

    def decorate(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        if not inspect.iscoroutinefunction(function):
            raise TypeError("in_tenant decorates an async def function")

        @functools.wraps(function)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with as_tenant(scope):
                return await function(*args, **kwargs)

        return wrapper

    return decorate


def guard_async_test[**P, R](
    function: Callable[P, Awaitable[R]], expected: str | ScopeId | None
) -> Callable[P, Awaitable[R]]:
    """Wrap a coroutine test so that, after the body has finished, in the test's own task context
    and only when the body did not raise, the bound scope is checked (TenantLeak). A body that
    raises propagates its own exception: a leak never masks the real failure. A teardown fixture
    cannot do this check: it runs outside the test's task."""

    @functools.wraps(function)
    async def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
        result = await function(*args, **kwargs)
        assert_bound_to(expected)
        return result

    return guarded


def guard_sync_test[**P, R](
    function: Callable[P, R], expected: str | ScopeId | None
) -> Callable[P, R]:
    """The same for a plain test function, checked in the call phase."""

    @functools.wraps(function)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
        result = function(*args, **kwargs)
        assert_bound_to(expected)
        return result

    return guarded


def guard_test(function: Callable[..., Any], expected: str | ScopeId | None) -> Callable[..., Any]:
    """`guard_async_test` for a coroutine function, `guard_sync_test` for any other callable."""
    if inspect.iscoroutinefunction(function):
        return guard_async_test(function, expected)
    return guard_sync_test(function, expected)
