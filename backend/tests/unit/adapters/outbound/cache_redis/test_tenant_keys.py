"""Pure tests of the tenant key prefix (I13): no Redis, no Docker."""

import base64
from datetime import timedelta

import pytest

from diucs.adapters.outbound.cache_redis.tenant_keys import millis, tenant_prefix
from diucs.application.tenancy import ScopeId, TenantNotBound, bind_scope, bind_tenant


def test_the_prefix_carries_the_bound_tenant() -> None:
    with bind_tenant("tenant-alpha"):
        assert tenant_prefix("diucs:") == "diucs:tenant-alpha:"


def test_a_missing_tenant_is_an_error_never_a_default() -> None:
    with pytest.raises(TenantNotBound):
        tenant_prefix("diucs:")


def test_a_network_scope_is_not_a_tenant_for_these_keys() -> None:
    with bind_scope(ScopeId.network("net-dorset")), pytest.raises(TenantNotBound):
        tenant_prefix("diucs:")


def test_a_run_prefix_is_kept_in_front_of_the_tenant() -> None:
    with bind_tenant("tenant-alpha"):
        assert tenant_prefix("diucs-test-7:") == "diucs-test-7:tenant-alpha:"


@pytest.mark.parametrize(
    ("ttl", "expected"),
    [
        (timedelta(seconds=60), 60_000),
        (timedelta(milliseconds=1), 1),
        (timedelta(milliseconds=0.2), 1),
        (timedelta(hours=12), 43_200_000),
    ],
)
def test_millis_is_whole_milliseconds_and_never_below_one(ttl: timedelta, expected: int) -> None:
    assert millis(ttl) == expected


def test_base64_padding_is_not_needed_for_a_32_byte_value() -> None:
    # Sanity check for the 256-bit session id arithmetic used in sessions.py.
    assert len(base64.urlsafe_b64encode(b"\x00" * 32).rstrip(b"=")) == 43
