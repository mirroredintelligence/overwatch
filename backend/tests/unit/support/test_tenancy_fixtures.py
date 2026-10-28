"""The test side of the tenancy seam (TEN-003, DEC-130 item 9, DEC-147): the run identity, the
tenant ids derived from it, the binders `as_tenant` and `in_tenant`, the leak guard, the
bound-tenant fixtures and hook, and the unit-of-work factory that binds a chosen tenant.

No Neo4j: the hook tests run a sandbox pytest session on a copy of the real conftest (as
`tests/unit/test_smoke.py` does), and the unit-of-work tests use the recording fake driver.
"""

import asyncio
import contextvars
import inspect
import os
import re
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.application.tenancy import (
    _SCOPE,
    ScopeId,
    ScopeInvalid,
    ScopeKind,
    UnitOfWorkAlreadyOpen,
    bind_scope,
    bind_tenant,
    current_scope_or_none,
    current_tenant,
)
from tests.support.fake_neo4j import FakeDriver
from tests.support.tenancy import (
    LEAK_MESSAGE,
    RunIdentity,
    TenantLeak,
    as_tenant,
    assert_bound_to,
    guard_async_test,
    guard_sync_test,
    in_tenant,
    new_run_identity,
    parse_run_id,
)
from tests.support.uow import tenant_uow_factory

pytest_plugins = ["pytester"]

_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36(number: int) -> str:
    """An independent base-36 writer: lower case, no padding, `0` for zero."""
    if number == 0:
        return "0"
    out = ""
    while number:
        number, remainder = divmod(number, 36)
        out = _DIGITS[remainder] + out
    return out


A1 = ScopeId.tenant("a1")
B1 = ScopeId.tenant("b1")


def _leak(scope: ScopeId) -> None:
    """Bind a scope and never reset it: the leak the guard exists to find. It sets the kernel's
    private variable directly, as a binder that forgot its reset would: a generator-based context
    manager that was entered and dropped would be closed by the garbage collector, which runs its
    `finally` and undoes the binding."""
    _SCOPE.set(scope)


# 1. The run identity


def test_a_run_identity_derives_the_three_scope_ids_from_one_token() -> None:
    identity = new_run_identity(pid=4242, now=1_800_000_000, nonce="ab12")
    token = f"{_base36(4242)}-{_base36(1_800_000_000)}-ab12"
    assert token == "39u-tro8w0-ab12"
    assert identity.token == token
    assert identity.tenant_id == "tt-" + token
    assert identity.other_tenant_id == "tt-" + token + "-b"
    assert identity.network_id == "net-" + token
    assert ScopeId.parse(identity.tenant_id).kind is ScopeKind.TENANT
    assert ScopeId.parse(identity.other_tenant_id).kind is ScopeKind.TENANT
    assert ScopeId.parse(identity.network_id).kind is ScopeKind.NETWORK


def test_zero_is_written_as_a_single_zero() -> None:
    assert new_run_identity(pid=1, now=0, nonce="0000").token == "1-0-0000"


def test_a_run_identity_is_a_frozen_value() -> None:
    identity = new_run_identity(pid=1, now=1, nonce="0000")
    assert identity == RunIdentity(pid=1, started=1, nonce="0000")
    with pytest.raises(AttributeError):
        identity.nonce = "ffff"  # type: ignore[misc]


@pytest.mark.parametrize("nonce", ["", "abc", "abcde", "ABCD", "zzzz", "12 3", "-b12"])
def test_a_nonce_that_is_not_four_hexadecimal_characters_is_refused(nonce: str) -> None:
    with pytest.raises(ValueError, match="nonce"):
        new_run_identity(pid=1, now=1, nonce=nonce)


@pytest.mark.parametrize(
    ("pid", "now"),
    [(-1, 1), (1, -1), (True, 1), (1, False), (2**22 + 1, 1), (1, 2**36)],
)
def test_a_negative_or_boolean_pid_or_start_is_refused(pid: int, now: int) -> None:
    with pytest.raises(ValueError, match="pid|start"):
        new_run_identity(pid=pid, now=now, nonce="ab12")


_PIDS = st.integers(min_value=1, max_value=2**22)
_STARTS = st.integers(min_value=0, max_value=2**36 - 1)
_NONCES = st.text(alphabet="0123456789abcdef", min_size=4, max_size=4)


@given(pid=_PIDS, now=_STARTS, nonce=_NONCES)
def test_every_identity_gives_valid_distinct_short_ids_that_parse_back(
    pid: int, now: int, nonce: str
) -> None:
    identity = new_run_identity(pid=pid, now=now, nonce=nonce)
    ids = [identity.tenant_id, identity.other_tenant_id, identity.network_id]
    assert len(set(ids)) == 3
    assert all(len(value) <= 31 for value in ids)
    assert ScopeId.tenant(identity.tenant_id).value == identity.tenant_id
    assert ScopeId.tenant(identity.other_tenant_id).value == identity.other_tenant_id
    assert ScopeId.network(identity.network_id).value == identity.network_id
    assert not identity.tenant_id.startswith("net-")
    assert not identity.other_tenant_id.startswith("net-")
    for value in ids:
        assert parse_run_id(value) == identity


@given(
    first=st.tuples(_PIDS, _STARTS, _NONCES),
    second=st.tuples(_PIDS, _STARTS, _NONCES),
)
def test_two_identities_share_no_id_unless_they_are_the_same_run(
    first: tuple[int, int, str], second: tuple[int, int, str]
) -> None:
    one = new_run_identity(pid=first[0], now=first[1], nonce=first[2])
    two = new_run_identity(pid=second[0], now=second[1], nonce=second[2])
    shared = {one.tenant_id, one.other_tenant_id, one.network_id} & {
        two.tenant_id,
        two.other_tenant_id,
        two.network_id,
    }
    assert (one == two) == bool(shared)


@pytest.mark.parametrize(
    "value",
    [
        "default",
        "tt-x",
        "tt-1-2-zz",
        "tt-39u-tro8w0-ab12-c",
        "tt-39u-tro8w0-ab12-b-b",
        "tt-039u-tro8w0-ab12",
        "tt-39u-tro8w0-AB12",
        "tt-39u-tro8w0",
        "net-39u-tro8w0-ab12-b",
        "xx-39u-tro8w0-ab12",
        "a1",
        "net-pilot",
        "",
        "tt-",
        "tt---",
    ],
)
def test_a_value_that_is_not_one_of_the_three_shapes_does_not_parse(value: str) -> None:
    assert parse_run_id(value) is None


@given(st.text(max_size=40))
def test_random_text_parses_only_when_it_is_a_run_id(text: str) -> None:
    identity = parse_run_id(text)
    if identity is not None:
        assert text in {identity.tenant_id, identity.other_tenant_id, identity.network_id}


# 3. Distinct runs


def test_two_identities_differ_when_only_the_start_or_only_the_nonce_differs() -> None:
    base = new_run_identity(pid=10, now=100, nonce="aaaa")
    later = new_run_identity(pid=10, now=101, nonce="aaaa")
    other_nonce = new_run_identity(pid=10, now=100, nonce="aaab")
    assert len({base.tenant_id, later.tenant_id, other_nonce.tenant_id}) == 3
    assert len({base.network_id, later.network_id, other_nonce.network_id}) == 3


def test_two_default_identities_differ_and_the_default_nonce_is_four_hex_characters() -> None:
    identities = [new_run_identity() for _ in range(20)]
    assert len({identity.tenant_id for identity in identities}) > 1
    assert all(re.fullmatch(r"[0-9a-f]{4}", identity.nonce) for identity in identities)
    assert all(identity.pid == os.getpid() for identity in identities)


# 4. as_tenant and in_tenant


def test_as_tenant_binds_for_the_block_and_restores_the_outer_binding() -> None:
    with bind_tenant("a1"):
        with as_tenant("b1"):
            assert current_tenant() == "b1"
        assert current_tenant() == "a1"
    assert current_scope_or_none() is None


def test_as_tenant_restores_on_an_exception() -> None:
    with bind_tenant("a1"):
        with pytest.raises(ValueError, match="stop"), as_tenant("b1"):
            raise ValueError("stop")
        assert current_tenant() == "a1"


@pytest.mark.parametrize("tenant", ["b1", B1])
def test_as_tenant_accepts_a_string_and_a_scope_id(tenant: str | ScopeId) -> None:
    with as_tenant(tenant):
        assert current_tenant() == "b1"


@pytest.mark.parametrize(
    "tenant", ["B1", "a:1", "x", "", "net-pilot", ScopeId.network("net-pilot")]
)
def test_as_tenant_refuses_an_invalid_id_or_a_network(tenant: str | ScopeId) -> None:
    with pytest.raises(ScopeInvalid), as_tenant(tenant):
        pytest.fail("the block must not run")
    assert current_scope_or_none() is None


async def test_in_tenant_runs_an_async_helper_in_that_tenant_and_restores() -> None:
    @in_tenant("b1")
    async def helper(value: int) -> tuple[str, int]:
        await asyncio.sleep(0)
        return current_tenant(), value

    with bind_tenant("a1"):
        assert await helper(7) == ("b1", 7)
        assert current_tenant() == "a1"
    assert inspect.iscoroutinefunction(helper)


async def test_in_tenant_restores_when_the_helper_raises() -> None:
    @in_tenant(B1)
    async def helper() -> None:
        raise ValueError("stop")

    with bind_tenant("a1"):
        with pytest.raises(ValueError, match="stop"):
            await helper()
        assert current_tenant() == "a1"


def test_in_tenant_refuses_a_plain_function_when_it_decorates_it() -> None:
    with pytest.raises(TypeError):

        @in_tenant("a1")  # type: ignore[type-var]
        def plain() -> None: ...

    with pytest.raises(ScopeInvalid):

        @in_tenant("A1")
        async def helper() -> None: ...


# 5. assert_bound_to


def test_assert_bound_to_passes_for_the_bound_tenant_and_for_none_when_unbound() -> None:
    with bind_tenant("a1"):
        assert_bound_to("a1")
        assert_bound_to(A1)
    assert_bound_to(None)


@pytest.mark.parametrize("expected", ["a1", A1, None])
def test_assert_bound_to_raises_the_fixed_message_for_another_tenant_or_none(
    expected: str | ScopeId | None,
) -> None:
    with bind_tenant("zz-secret-9"), pytest.raises(TenantLeak) as raised:
        assert_bound_to(expected)
    assert str(raised.value) == LEAK_MESSAGE
    assert "zz-secret-9" not in str(raised.value)


def test_assert_bound_to_raises_when_nothing_is_bound_and_a_tenant_was_expected() -> None:
    with pytest.raises(TenantLeak, match="the bound tenant changed"):
        assert_bound_to("a1")


def test_a_leak_is_an_assertion_error_with_the_fixed_text() -> None:
    assert issubclass(TenantLeak, AssertionError)
    assert LEAK_MESSAGE == (
        "the bound tenant changed during the test: "
        "something bound another tenant and did not reset it"
    )


def test_a_network_binding_is_not_the_expected_tenant() -> None:
    with bind_scope(ScopeId.network("net-pilot")), pytest.raises(TenantLeak):
        assert_bound_to("a1")


# 6. The guards


async def test_the_async_guard_flags_a_body_that_leaves_another_tenant_bound() -> None:
    async def body() -> None:
        _leak(B1)  # never exited: the leak

    with bind_tenant("a1"), pytest.raises(TenantLeak, match="the bound tenant changed"):
        await guard_async_test(body, "a1")()


async def test_the_async_guard_passes_a_body_that_rebinds_and_restores() -> None:
    async def body(x: int) -> int:
        with as_tenant("b1"):
            await asyncio.sleep(0)
        return x + 1

    with bind_tenant("a1"):
        assert await guard_async_test(body, A1)(1) == 2


async def test_the_async_guard_lets_the_bodys_own_failure_through_even_when_it_leaks() -> None:
    async def body() -> None:
        _leak(B1)
        raise ValueError("the real failure")

    with bind_tenant("a1"), pytest.raises(ValueError, match="the real failure"):
        await guard_async_test(body, "a1")()


def test_the_sync_guard_flags_a_leak_passes_a_clean_body_and_lets_a_failure_through() -> None:
    def leaks() -> None:
        _leak(B1)

    def clean() -> str:
        with as_tenant("b1"):
            pass
        return "done"

    def fails() -> None:
        _leak(B1)
        raise ValueError("the real failure")

    with bind_tenant("a1"), pytest.raises(TenantLeak):
        guard_sync_test(leaks, "a1")()
    with bind_tenant("a1"):
        assert guard_sync_test(clean, "a1")() == "done"
    with bind_tenant("a1"), pytest.raises(ValueError, match="the real failure"):
        guard_sync_test(fails, "a1")()


def test_a_guard_keeps_the_signature_and_the_name_of_the_test() -> None:
    async def test_something(tenant_id: str, uow_factory: object) -> None: ...

    def test_other(tenant_id: str) -> None: ...

    for original, guarded in (
        (test_something, guard_async_test(test_something, "a1")),
        (test_other, guard_sync_test(test_other, "a1")),
    ):
        assert inspect.signature(guarded) == inspect.signature(original)
        assert guarded.__name__ == original.__name__
    assert inspect.iscoroutinefunction(guard_async_test(test_something, "a1"))
    assert not inspect.iscoroutinefunction(guard_sync_test(test_other, "a1"))


# 7. The fixtures, in the real conftest

_SEEN: list[tuple[Any, ...]] = []


def test_the_run_fixtures_are_the_identity_of_this_session(
    run_identity: RunIdentity,
    tenant_id: str,
    other_tenant_id: str,
    network_id: str,
    bound_tenant: ScopeId,
) -> None:
    assert current_tenant() == tenant_id
    assert bound_tenant == ScopeId.tenant(tenant_id)
    assert tenant_id == run_identity.tenant_id
    assert other_tenant_id == tenant_id + "-b"
    assert network_id.startswith("net-")
    assert network_id == run_identity.network_id
    assert os.environ["DIUCS_TEST_TENANT"] == tenant_id
    assert os.environ["DIUCS_TEST_OTHER_TENANT"] == other_tenant_id
    assert os.environ["DIUCS_TEST_NETWORK"] == network_id
    _SEEN.append((run_identity, tenant_id, other_tenant_id, network_id))


def test_the_run_fixtures_are_the_same_in_the_next_test(
    run_identity: RunIdentity, tenant_id: str, other_tenant_id: str, network_id: str
) -> None:
    assert _SEEN, "test_the_run_fixtures_are_the_identity_of_this_session runs first"
    first = _SEEN[0]
    assert first[0] is run_identity
    assert first[1:] == (tenant_id, other_tenant_id, network_id)


def test_a_unit_test_that_does_not_ask_for_the_fixture_is_not_bound() -> None:
    assert current_scope_or_none() is None


# 8. The hook, in a sandbox session on a copy of the real conftest

_INI = (
    "[pytest]\nasyncio_mode = auto\nasyncio_default_fixture_loop_scope = session\n"
    "asyncio_default_test_loop_scope = session\n"
    "markers =\n    integration: needs docker\n    no_tenant: runs with no tenant bound\n"
)


def _sandbox(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, **files: str) -> None:
    # An unreachable Docker: nothing here may need a container. The conftest of the sandbox
    # exports the run's tenant ids into os.environ; monkeypatch puts the real ones back afterwards.
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:1")
    for name in ("DIUCS_TEST_TENANT", "DIUCS_TEST_OTHER_TENANT", "DIUCS_TEST_NETWORK"):
        monkeypatch.setenv(name, os.environ.get(name, "restore"))
    source = (Path(__file__).parents[2] / "conftest.py").read_text(encoding="utf-8")
    pytester.makeini(_INI)
    pytester.mkdir("tests")
    pytester.mkdir("tests/integration")
    pytester.mkdir("tests/unit")
    (pytester.path / "tests" / "conftest.py").write_text(source, encoding="utf-8")
    pytester.makepyfile(**files)


def _run(pytester: pytest.Pytester) -> pytest.RunResult:
    """Run the sandbox session in an empty context, so nothing it leaves bound reaches the session
    that is running it."""
    return contextvars.Context().run(pytester.runpytest, "-p", "no:cacheprovider")


_SEES_THE_RUN_TENANT = (
    "import os\n"
    "from diucs.application.tenancy import current_tenant\n"
    "async def test_async(request):\n"
    "    assert current_tenant() == os.environ['DIUCS_TEST_TENANT']\n"
    "    assert 'bound_tenant' in request.fixturenames\n"
    "def test_sync(request):\n"
    "    assert current_tenant() == os.environ['DIUCS_TEST_TENANT']\n"
    "    assert 'bound_tenant' in request.fixturenames\n"
    "class TestGroup:\n"
    "    async def test_in_a_class(self):\n"
    "        assert current_tenant() == os.environ['DIUCS_TEST_TENANT']\n"
)


def test_the_hook_binds_the_run_tenant_for_every_integration_test_and_only_for_those(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(
        pytester,
        monkeypatch,
        **{
            "tests/integration/test_bound": _SEES_THE_RUN_TENANT,
            "tests/unit/test_not_bound": (
                "from diucs.application.tenancy import current_scope_or_none\n"
                "def test_probe(request):\n"
                "    assert current_scope_or_none() is None\n"
                "    assert 'bound_tenant' not in request.fixturenames\n"
            ),
        },
    )
    result = _run(pytester)
    result.assert_outcomes(passed=4)


def test_the_hook_fails_an_async_integration_test_that_leaves_another_tenant_bound(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(
        pytester,
        monkeypatch,
        **{
            "tests/integration/test_leak": (
                "from diucs.application.tenancy import _SCOPE, ScopeId\n"
                "async def test_leaks():\n"
                "    _SCOPE.set(ScopeId.tenant('zz-leak'))\n"
                "async def test_next_one_is_clean():\n"
                "    import os\n"
                "    from diucs.application.tenancy import current_tenant\n"
                "    assert current_tenant() == os.environ['DIUCS_TEST_TENANT']\n"
            )
        },
    )
    result = _run(pytester)
    result.assert_outcomes(passed=1, failed=1)
    assert LEAK_MESSAGE in result.stdout.str()


def test_the_hook_fails_a_sync_integration_test_that_leaves_another_tenant_bound(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(
        pytester,
        monkeypatch,
        **{
            "tests/integration/test_leak": (
                "from diucs.application.tenancy import _SCOPE, ScopeId\n"
                "def test_leaks():\n"
                "    _SCOPE.set(ScopeId.tenant('zz-leak'))\n"
                "def test_next_one_is_clean():\n"
                "    import os\n"
                "    from diucs.application.tenancy import current_tenant\n"
                "    assert current_tenant() == os.environ['DIUCS_TEST_TENANT']\n"
            )
        },
    )
    result = _run(pytester)
    result.assert_outcomes(passed=1, failed=1)
    assert LEAK_MESSAGE in result.stdout.str()


def test_the_hook_does_not_let_the_guard_hide_the_tests_own_failure(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(
        pytester,
        monkeypatch,
        **{
            "tests/integration/test_fail": (
                "from diucs.application.tenancy import _SCOPE, ScopeId\n"
                "async def test_fails_and_leaks():\n"
                "    _SCOPE.set(ScopeId.tenant('zz-leak'))\n"
                "    raise ValueError('the real failure')\n"
            )
        },
    )
    result = _run(pytester)
    result.assert_outcomes(failed=1)
    assert "the real failure" in result.stdout.str()
    assert LEAK_MESSAGE not in result.stdout.str()


def test_a_test_marked_no_tenant_runs_unbound_and_is_guarded_to_stay_unbound(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(
        pytester,
        monkeypatch,
        **{
            "tests/integration/test_unbound": (
                "import pytest\n"
                "from diucs.application.tenancy import _SCOPE, ScopeId, current_scope_or_none\n"
                "@pytest.mark.no_tenant\n"
                "async def test_unbound(request):\n"
                "    assert current_scope_or_none() is None\n"
                "    assert 'bound_tenant' not in request.fixturenames\n"
                "@pytest.mark.no_tenant\n"
                "def test_unbound_sync():\n"
                "    assert current_scope_or_none() is None\n"
                "@pytest.mark.no_tenant\n"
                "async def test_leaking_one():\n"
                "    _SCOPE.set(ScopeId.tenant('zz-leak'))\n"
            )
        },
    )
    result = _run(pytester)
    result.assert_outcomes(passed=2, failed=1)
    assert LEAK_MESSAGE in result.stdout.str()


# 9. The unit-of-work factory that binds a chosen tenant


async def test_a_unit_from_the_factory_binds_its_tenant_and_the_ambient_scope_is_untouched() -> (
    None
):
    fake = FakeDriver()
    factory = tenant_uow_factory(cast(Any, fake), "b1")
    with bind_tenant("a1"):
        unit = factory()
        async with unit as uow:
            assert uow.unit_scope == B1
            assert current_tenant() == "a1"
        assert current_tenant() == "a1"
    assert fake.session_calls == 1


async def test_two_factories_used_one_after_the_other_give_units_with_their_own_scopes() -> None:
    fake = FakeDriver()
    first = tenant_uow_factory(cast(Any, fake), A1)
    second = tenant_uow_factory(cast(Any, fake), "b1")
    with bind_tenant("zz1"):
        async with first() as one:
            assert one.unit_scope == A1
        async with second() as two:
            assert two.unit_scope == B1
        assert current_tenant() == "zz1"


async def test_a_unit_from_the_factory_has_a_scope_with_nothing_bound() -> None:
    async with tenant_uow_factory(cast(Any, FakeDriver()), "a1")() as uow:
        assert uow.unit_scope == A1
        assert current_scope_or_none() is None


async def test_units_opened_in_two_tasks_work() -> None:
    fake = FakeDriver()

    async def one(tenant: str) -> ScopeId | None:
        async with tenant_uow_factory(cast(Any, fake), tenant)() as uow:
            await asyncio.sleep(0)
            return uow.unit_scope

    assert await asyncio.gather(one("a1"), one("b1")) == [A1, B1]


async def test_a_unit_from_the_factory_cannot_open_inside_another() -> None:
    fake = FakeDriver()
    async with tenant_uow_factory(cast(Any, fake), "a1")():
        with pytest.raises(UnitOfWorkAlreadyOpen):
            async with tenant_uow_factory(cast(Any, fake), "b1")():
                pytest.fail("the nested unit must not open")
    assert fake.session_calls == 1


def test_an_invalid_tenant_is_refused_when_the_factory_is_built() -> None:
    for tenant in ("A1", "a:1", "", "net-pilot", ScopeId.network("net-pilot")):
        with pytest.raises(ScopeInvalid):
            tenant_uow_factory(cast(Any, FakeDriver()), tenant)
