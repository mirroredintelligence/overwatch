"""The network side of the tenancy kernel (TEN-037, DEC-132 item 4, DEC-540).

A unit of work binds exactly one scope, and a scope is a tenant or a network. A network use case
asks for the bound network and a tenant use case for the bound tenant, and each is refused inside
the other's binding. The four new errors have one fixed message and take no argument, like the
rest of the kernel.
"""

import copy
import pickle

import pytest

from diucs.application import tenancy
from diucs.application.tenancy import (
    READ_ONLY_MESSAGE,
    SCOPE_KIND_MESSAGE,
    SOURCE_TENANT_MESSAGE,
    NetworkNotBound,
    ReadOnlyUnitWrite,
    ScopeId,
    ScopeKindMismatch,
    SourceTenantRefused,
    TenancyError,
    TenantNotBound,
    bind_network,
    bind_tenant,
    current_network,
    current_scope,
    current_tenant,
)

NETWORK = "net-pilot"


def test_bind_network_binds_a_network_scope_and_current_network_reads_it() -> None:
    with bind_network(NETWORK) as scope:
        assert scope == ScopeId.network(NETWORK)
        assert current_scope() == ScopeId.network(NETWORK)
        assert current_network() == NETWORK


def test_a_network_binding_is_not_a_tenant_binding() -> None:
    with bind_network(NETWORK), pytest.raises(TenantNotBound):
        current_tenant()


def test_a_tenant_binding_is_not_a_network_binding() -> None:
    with bind_tenant("a1"), pytest.raises(NetworkNotBound):
        current_network()


def test_with_nothing_bound_there_is_no_network() -> None:
    with pytest.raises(NetworkNotBound):
        current_network()


@pytest.mark.parametrize("value", ["a1", "net-", "net-A", "NET-pilot", "", "net-pilot/x"])
def test_bind_network_refuses_what_is_not_a_network_id(value: str) -> None:
    with pytest.raises(tenancy.ScopeInvalid):
        bind_network(value)


def test_a_network_binding_nests_and_restores_the_outer_scope() -> None:
    with bind_tenant("a1"):
        with bind_network(NETWORK):
            assert current_network() == NETWORK
        assert current_tenant() == "a1"
        with pytest.raises(NetworkNotBound):
            current_network()


NEW_ERRORS = [
    (NetworkNotBound, "no network is bound for this work; bind one at the edge"),
    (ScopeKindMismatch, "this statement does not run in the kind of scope that is bound"),
    (ReadOnlyUnitWrite, READ_ONLY_MESSAGE),
    (SourceTenantRefused, SOURCE_TENANT_MESSAGE),
]


@pytest.mark.parametrize(("error", "start"), NEW_ERRORS)
def test_each_new_error_is_a_fixed_message_tenancy_error(
    error: type[TenancyError], start: str
) -> None:
    assert issubclass(error, TenancyError)
    assert str(error()).startswith(start)
    with pytest.raises(TypeError):
        error("a tenant id a1")  # type: ignore[call-arg]


@pytest.mark.parametrize(("error", "_start"), NEW_ERRORS)
def test_each_new_error_survives_copying_and_pickling(
    error: type[TenancyError], _start: str
) -> None:
    original = error()
    assert str(copy.copy(original)) == str(original)
    assert str(pickle.loads(pickle.dumps(original))) == str(original)  # noqa: S301


def test_the_new_messages_are_the_fixed_ones_and_name_no_value() -> None:
    assert SCOPE_KIND_MESSAGE == "this statement does not run in the kind of scope that is bound"
    assert "read-only" in READ_ONLY_MESSAGE
    assert "source tenant" in SOURCE_TENANT_MESSAGE
    for message in (SCOPE_KIND_MESSAGE, READ_ONLY_MESSAGE, SOURCE_TENANT_MESSAGE):
        assert "$" not in message
        assert "MATCH" not in message
