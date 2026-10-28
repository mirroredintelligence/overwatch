"""The tenancy kernel (TEN-001): scope ids, the binding context and fixed-message errors.

Reused from the verified earlier branch (DEC-142 item 8) and adapted: the mode (warn and enforce)
and its error are gone, and `QueryNotRegistered` is new. Each reused test was run against this
code. Pure tests: no Neo4j.
"""

import ast
import asyncio
import copy
import dataclasses
import pickle
import random
import re
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import anyio.to_thread
import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from diucs.application import tenancy
from diucs.application.tenancy import (
    DEFAULT_TENANT_ID,
    GLOBAL_STATEMENT_MESSAGE,
    NETWORK_ID_PATTERN,
    NETWORK_PREFIX,
    QUERY_NOT_REGISTERED_MESSAGE,
    SCOPE_INVALID_MESSAGE,
    TENANT_ID_PATTERN,
    TENANT_NOT_BOUND_MESSAGE,
    TENANT_PARAMETER_MESSAGE,
    GlobalStatementMisuse,
    QueryNotRegistered,
    ScopeId,
    ScopeInvalid,
    ScopeKind,
    TenancyError,
    TenantNotBound,
    TenantParameterRefused,
    bind_scope,
    bind_tenant,
    current_scope,
    current_scope_or_none,
    current_tenant,
    is_valid_tenant_id,
)
from diucs.domain.errors import DomainError

# The reference patterns, written out again here so a change to the module's patterns shows up
# as a test failure instead of silently moving both sides.
_REF_TENANT = re.compile(r"[a-z0-9][a-z0-9-]{1,30}")
_REF_NETWORK = re.compile(r"net-[a-z0-9][a-z0-9-]{1,26}")

_TENANT_VALUES = st.from_regex(_REF_TENANT, fullmatch=True).filter(
    lambda v: not v.startswith("net-")
)
_NETWORK_VALUES = st.from_regex(_REF_NETWORK, fullmatch=True)


# 1. Tenant ids


@pytest.mark.parametrize("value", ["default", "ucr-west-1", "ab", "a1", "0z", "a" * 31, "netx"])
def test_a_valid_tenant_id_is_accepted_as_a_tenant_scope(value: str) -> None:
    scope = ScopeId.tenant(value)
    assert scope.value == value
    assert scope.kind is ScopeKind.TENANT


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a",
        "a" * 32,
        "Abc",
        "abC",
        "-ab",
        "a_b",
        "a:b",
        "a/b",
        "a b",
        " ab",
        "ab\n",
        "ab\x00",
        "abé",
        "ａｂ",
        "net-abc",
        "net-",
        "net-a",
    ],
)
def test_an_invalid_tenant_id_is_refused_with_the_fixed_message(value: str) -> None:
    with pytest.raises(ScopeInvalid) as raised:
        ScopeId.tenant(value)
    assert str(raised.value) == SCOPE_INVALID_MESSAGE


@pytest.mark.parametrize("value", [None, 5, b"abc", ["abc"]])
def test_a_value_that_is_not_text_is_refused(value: object) -> None:
    with pytest.raises(ScopeInvalid):
        ScopeId(value, ScopeKind.TENANT)  # type: ignore[arg-type]
    with pytest.raises(ScopeInvalid):
        ScopeId.parse(value)  # type: ignore[arg-type]


def test_a_kind_that_is_not_a_scope_kind_is_refused() -> None:
    with pytest.raises(ScopeInvalid):
        ScopeId("ab", "tenant")  # type: ignore[arg-type]


# 2. Network ids, parse, the default tenant


def test_a_network_scope_has_the_network_kind() -> None:
    scope = ScopeId.network("net-pilot")
    assert scope.value == "net-pilot"
    assert scope.kind is ScopeKind.NETWORK


@pytest.mark.parametrize("value", ["pilot", "net-", "net-a", "net-" + "a" * 28, "NET-pilot", ""])
def test_an_invalid_network_id_is_refused(value: str) -> None:
    with pytest.raises(ScopeInvalid) as raised:
        ScopeId.network(value)
    assert str(raised.value) == SCOPE_INVALID_MESSAGE


@pytest.mark.parametrize("value", ["net-ab", "net-pilot", "net-" + "a" * 27])
def test_network_ids_at_the_length_bounds_are_accepted(value: str) -> None:
    assert ScopeId.network(value).value == value
    assert 6 <= len(value) <= 31


def test_parse_decides_the_kind_by_the_reserved_prefix() -> None:
    assert ScopeId.parse("net-pilot").kind is ScopeKind.NETWORK
    assert ScopeId.parse("pilot").kind is ScopeKind.TENANT
    assert ScopeId.parse("netx").kind is ScopeKind.TENANT


@pytest.mark.parametrize("value", ["net-", "net-a", "NET-pilot", "Pilot", "a"])
def test_parse_refuses_an_invalid_value(value: str) -> None:
    with pytest.raises(ScopeInvalid):
        ScopeId.parse(value)


def test_the_default_tenant_id_is_a_valid_tenant_scope() -> None:
    scope = ScopeId.tenant(DEFAULT_TENANT_ID)
    assert scope.kind is ScopeKind.TENANT
    assert ScopeId.parse(DEFAULT_TENANT_ID) == scope


def test_the_module_constants_are_the_fixed_ones() -> None:
    assert NETWORK_PREFIX == "net-"
    assert DEFAULT_TENANT_ID == "default"
    assert _REF_TENANT.pattern == TENANT_ID_PATTERN
    assert _REF_NETWORK.pattern == NETWORK_ID_PATTERN


def test_a_scope_prints_as_its_value_is_frozen_hashable_and_compares_by_value() -> None:
    scope = ScopeId.tenant("a1")
    assert str(scope) == "a1"
    assert scope == ScopeId.tenant("a1")
    assert scope != ScopeId.tenant("b1")
    assert {scope: 1}[ScopeId.parse("a1")] == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        scope.value = "b1"  # type: ignore[misc]
    assert not hasattr(scope, "__dict__")


# 3. Properties of parse


def _reference_is_valid(text: str) -> bool:
    if text.startswith("net-"):
        return _REF_NETWORK.fullmatch(text) is not None
    return _REF_TENANT.fullmatch(text) is not None


@settings(max_examples=400, deadline=None)
@given(
    st.one_of(
        st.text(max_size=40), _TENANT_VALUES, _NETWORK_VALUES, st.text("ab-n:et ", max_size=12)
    )
)
def test_parse_accepts_exactly_the_reference_patterns_and_round_trips(text: str) -> None:
    try:
        scope = ScopeId.parse(text)
    except ScopeInvalid as error:
        assert str(error) == SCOPE_INVALID_MESSAGE
        assert not _reference_is_valid(text)
        return
    assert _reference_is_valid(text)
    assert scope.value == text
    assert scope.kind is (ScopeKind.NETWORK if text.startswith("net-") else ScopeKind.TENANT)
    assert ScopeId.parse(str(scope)) == scope


@settings(max_examples=300, deadline=None)
@given(_TENANT_VALUES, _NETWORK_VALUES)
def test_a_tenant_scope_never_equals_a_network_scope(tenant_value: str, network_value: str) -> None:
    tenant_scope = ScopeId.tenant(tenant_value)
    network_scope = ScopeId.network(network_value)
    assert tenant_scope != network_scope
    assert tenant_scope.value != network_scope.value


# 4. Binding


def test_unbound_there_is_no_scope_and_current_scope_refuses() -> None:
    assert current_scope_or_none() is None
    with pytest.raises(TenantNotBound) as raised:
        current_scope()
    assert str(raised.value) == TENANT_NOT_BOUND_MESSAGE
    with pytest.raises(TenantNotBound) as raised_tenant:
        current_tenant()
    assert str(raised_tenant.value) == TENANT_NOT_BOUND_MESSAGE


def test_inside_a_binding_the_tenant_is_visible_and_after_it_the_scope_is_unbound() -> None:
    with bind_tenant("a1") as scope:
        assert scope == ScopeId.tenant("a1")
        assert current_scope_or_none() == ScopeId.tenant("a1")
        assert current_scope() == ScopeId.tenant("a1")
        assert current_scope().kind is ScopeKind.TENANT
        assert current_tenant() == "a1"
    assert current_scope_or_none() is None


def test_an_exception_inside_the_block_still_unbinds() -> None:
    with pytest.raises(RuntimeError, match="boom"), bind_tenant("a1"):
        raise RuntimeError("boom")
    assert current_scope_or_none() is None


def test_nesting_restores_the_outer_binding() -> None:
    with bind_tenant("a1"):
        with bind_tenant("b1"):
            assert current_tenant() == "b1"
        assert current_tenant() == "a1"
        with pytest.raises(RuntimeError, match="inner"), bind_tenant("c1"):
            raise RuntimeError("inner")
        assert current_tenant() == "a1"
    assert current_scope_or_none() is None


def test_bind_scope_binds_the_given_scope_and_bind_tenant_refuses_an_invalid_id() -> None:
    scope = ScopeId.tenant("a1")
    with bind_scope(scope) as bound:
        assert bound is scope
        assert current_scope() is scope
    with pytest.raises(ScopeInvalid), bind_tenant("Not Valid"):
        raise AssertionError("an invalid tenant id must not bind")
    assert current_scope_or_none() is None


@pytest.mark.parametrize("not_a_scope", ["a1", None, ("a1", "tenant")])
def test_bind_scope_refuses_anything_that_is_not_a_scope_id(not_a_scope: object) -> None:
    with pytest.raises(ScopeInvalid), bind_scope(not_a_scope):  # type: ignore[arg-type]
        raise AssertionError("a non-scope must not bind")
    assert current_scope_or_none() is None


# 5. A network scope


def test_a_bound_network_scope_is_a_scope_but_not_a_tenant() -> None:
    network = ScopeId.network("net-pilot")
    with bind_scope(network):
        assert current_scope() == network
        assert current_scope().kind is ScopeKind.NETWORK
        with pytest.raises(TenantNotBound) as raised:
            current_tenant()
        assert str(raised.value) == TENANT_NOT_BOUND_MESSAGE
    assert current_scope_or_none() is None


# 6. Concurrency


async def _bind_sleep_check(tenant_id: str, sleep: float) -> str:
    with bind_tenant(tenant_id):
        await asyncio.sleep(sleep)
        seen = current_tenant()
        await asyncio.sleep(0)
        assert current_tenant() == tenant_id
    assert current_scope_or_none() is None
    return seen


async def test_fifty_tasks_each_keep_their_own_tenant() -> None:
    rng = random.Random(20261028)
    tenants = [f"t{n:02d}" for n in range(50)]
    results = await asyncio.gather(
        *(_bind_sleep_check(tenant, rng.uniform(0, 0.01)) for tenant in tenants)
    )
    assert results == tenants
    assert current_scope_or_none() is None


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(st.lists(st.floats(min_value=0, max_value=0.005), min_size=2, max_size=20))
async def test_tasks_keep_their_own_tenant_for_any_sleep_lengths(sleeps: list[float]) -> None:
    tenants = [f"t{n:02d}" for n in range(len(sleeps))]
    results = await asyncio.gather(
        *(_bind_sleep_check(tenant, sleep) for tenant, sleep in zip(tenants, sleeps, strict=True))
    )
    assert results == tenants
    assert current_scope_or_none() is None


# 8. Errors

_ERRORS: list[tuple[type[TenancyError], str]] = [
    (ScopeInvalid, SCOPE_INVALID_MESSAGE),
    (TenantNotBound, TENANT_NOT_BOUND_MESSAGE),
    (TenantParameterRefused, TENANT_PARAMETER_MESSAGE),
    (QueryNotRegistered, QUERY_NOT_REGISTERED_MESSAGE),
    (GlobalStatementMisuse, GLOBAL_STATEMENT_MESSAGE),
]


@pytest.mark.parametrize(("error_class", "message"), _ERRORS)
def test_each_error_is_a_fixed_message_tenancy_error(
    error_class: type[TenancyError], message: str
) -> None:
    error = error_class()
    assert isinstance(error, TenancyError)
    assert isinstance(error, RuntimeError)
    assert not isinstance(error, DomainError)
    assert str(error) == message
    with pytest.raises(TypeError):
        error_class("a tenant id such as a1")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        error_class(tenant="a1")  # type: ignore[call-arg]


@pytest.mark.parametrize(("error_class", "message"), _ERRORS)
def test_an_error_survives_copying_and_pickling_with_its_message(
    error_class: type[TenancyError], message: str
) -> None:
    for clone in (copy.copy(error_class()), pickle.loads(pickle.dumps(error_class()))):
        assert type(clone) is error_class
        assert str(clone) == message


def test_the_base_error_takes_no_argument_either() -> None:
    assert isinstance(TenancyError(), RuntimeError)
    assert not issubclass(TenancyError, DomainError)
    with pytest.raises(TypeError):
        TenancyError("free text")  # type: ignore[call-arg]


def test_the_messages_are_the_fixed_ones() -> None:
    assert SCOPE_INVALID_MESSAGE == "the scope id is not valid"
    assert TENANT_NOT_BOUND_MESSAGE == (
        "no tenant is bound for this work; bind one at the edge before running a query"
    )
    assert TENANT_PARAMETER_MESSAGE == (
        "a query cannot be given a tenant parameter; the tenant is bound at the edge"
    )
    assert QUERY_NOT_REGISTERED_MESSAGE == (
        "only a registered named query can run; a string or an unregistered query is refused"
    )
    assert GLOBAL_STATEMENT_MESSAGE == (
        "a global statement runs only through run_global_query, "
        "and run_global_query runs only global statements"
    )


# 9. Propagation proofs (audit E06): what a context variable does across tasks and threads.


async def test_a_value_bound_before_create_task_is_visible_inside_the_task() -> None:
    async def read() -> str:
        return current_tenant()

    with bind_tenant("a1"):
        assert await asyncio.create_task(read()) == "a1"


async def test_a_value_bound_inside_a_task_is_not_visible_to_the_parent() -> None:
    async def bind_inside() -> str:
        with bind_tenant("inner"):
            await asyncio.sleep(0)
            return current_tenant()

    assert await asyncio.create_task(bind_inside()) == "inner"
    assert current_scope_or_none() is None


async def test_asyncio_to_thread_sees_the_callers_binding() -> None:
    with bind_tenant("a1"):
        assert await asyncio.to_thread(current_tenant) == "a1"


async def test_a_binding_entered_in_an_asyncio_thread_is_gone_after_it_returns() -> None:
    def bind_in_thread() -> str:
        with bind_tenant("thread"):
            return current_tenant()

    assert await asyncio.to_thread(bind_in_thread) == "thread"
    assert current_scope_or_none() is None
    with bind_tenant("a1"):
        assert await asyncio.to_thread(bind_in_thread) == "thread"
        assert current_tenant() == "a1"


async def test_anyio_to_thread_sees_the_callers_binding() -> None:
    with bind_tenant("a1"):
        assert await anyio.to_thread.run_sync(current_tenant) == "a1"


async def test_a_binding_entered_in_an_anyio_thread_is_gone_after_it_returns() -> None:
    def bind_in_thread() -> str:
        with bind_tenant("thread"):
            return current_tenant()

    assert await anyio.to_thread.run_sync(bind_in_thread) == "thread"
    assert current_scope_or_none() is None
    with bind_tenant("a1"):
        assert await anyio.to_thread.run_sync(bind_in_thread) == "thread"
        assert current_tenant() == "a1"


# 10. pytest propagation: what TEN-003's fixtures can rely on. Observed with pytest-asyncio 1.4.0
# and asyncio_default_test_loop_scope = session (see pyproject.toml): a context variable set by a
# synchronous yield fixture, or by an async fixture, is visible in an async test body, in tasks the
# test creates and in asyncio.gather children, and is reset when the fixture is torn down.


@pytest.fixture
def bound_sync() -> Iterator[ScopeId]:
    with bind_tenant("fx-sync") as scope:
        yield scope


@pytest_asyncio.fixture
async def bound_async() -> AsyncIterator[ScopeId]:
    with bind_tenant("fx-async") as scope:
        yield scope


async def test_a_sync_fixture_binding_is_visible_in_the_async_test_body(
    bound_sync: ScopeId,
) -> None:
    assert current_scope_or_none() == bound_sync
    assert current_tenant() == "fx-sync"


async def test_a_sync_fixture_binding_reaches_tasks_and_gather_children(
    bound_sync: ScopeId,
) -> None:
    async def read() -> str:
        await asyncio.sleep(0)
        return current_tenant()

    assert await asyncio.create_task(read()) == "fx-sync"
    assert await asyncio.gather(read(), read(), read()) == ["fx-sync"] * 3
    async with asyncio.TaskGroup() as group:
        first = group.create_task(read())
        second = group.create_task(read())
    assert (first.result(), second.result()) == ("fx-sync", "fx-sync")


async def test_an_async_fixture_binding_is_visible_in_the_test_and_its_tasks(
    bound_async: ScopeId,
) -> None:
    async def read() -> str:
        return current_tenant()

    assert current_scope_or_none() == bound_async
    assert current_tenant() == "fx-async"
    assert await asyncio.create_task(read()) == "fx-async"
    assert await asyncio.gather(read(), read()) == ["fx-async"] * 2


async def test_a_binding_made_by_the_previous_tests_fixtures_does_not_leak() -> None:
    """Runs after the fixture tests above (file order): their teardown must have unbound."""
    assert current_scope_or_none() is None


# 11. The module imports only the standard library


def test_the_kernel_imports_only_the_standard_library() -> None:
    source = Path(tenancy.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "the kernel uses absolute imports only"
            imported.add((node.module or "").split(".")[0])
    assert imported, "no imports found: the scan is not looking at the module"
    assert imported <= set(sys.stdlib_module_names), sorted(imported - set(sys.stdlib_module_names))
    assert "diucs" not in imported


# The tenant-id validator that TEN-006, TEN-019 and TEN-020 use instead of copying the pattern.


@pytest.mark.parametrize("value", ["default", "ucr-west-1", "ab", "a1", "0z", "a" * 31, "netx"])
def test_is_valid_tenant_id_accepts_a_valid_tenant_id(value: str) -> None:
    assert is_valid_tenant_id(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a",
        "a" * 32,
        "Abc",
        "-ab",
        "a_b",
        "a:b",
        "a/b",
        "a b",
        "ab\n",
        "abé",
        "net-abc",
        "net-ab",
    ],
)
def test_is_valid_tenant_id_refuses_an_invalid_one_and_a_network_id(value: str) -> None:
    assert is_valid_tenant_id(value) is False


@pytest.mark.parametrize("value", [None, 5, b"abc", ["abc"]])
def test_is_valid_tenant_id_is_false_for_anything_that_is_not_text(value: object) -> None:
    assert is_valid_tenant_id(value) is False  # type: ignore[arg-type]


@settings(
    max_examples=300, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.one_of(st.text(max_size=40), _TENANT_VALUES, _NETWORK_VALUES))
def test_is_valid_tenant_id_agrees_with_scope_id_tenant(text: str) -> None:
    try:
        ScopeId.tenant(text)
    except ScopeInvalid:
        assert is_valid_tenant_id(text) is False
    else:
        assert is_valid_tenant_id(text) is True


# DEC-142 item 7: no warn mode, no enforce mode, no mode switch.


def test_there_is_no_tenancy_mode_in_the_kernel() -> None:
    for name in ("TenancyMode", "tenancy_mode", "set_tenancy_mode", "use_tenancy_mode"):
        assert not hasattr(tenancy, name), name
