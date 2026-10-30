"""ConfirmCapacity and the tenant (TEN-027, DEC-500; reworks U02, DEC-112 items 11 and 12).

No Neo4j: a unit of work that fails the test when it is touched. What is proved here is what must
happen before any read or lock: the actor's tenant is the bound one, the unit is bound to a tenant,
and a refusal reads the same wherever it comes from. The limit is the tenant's own, and the replay
fingerprint holds the tenant. The use-case flow on a real graph is in
`tests/integration/application/test_confirm_capacity_tenants.py`.
"""

import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.tenancy import ScopeId, TenantMismatch, TenantNotBound
from diucs.application.use_cases.confirm_capacity import (
    ConfirmCapacity,
    ConfirmCapacityCommand,
    _fingerprint,
    check_confirm_limit,
)
from diucs.domain.codes import ReportSource, Role
from diucs.domain.errors import ConfirmLimitReached
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from tests.support.tenancy import as_tenant

NOW = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)


def _actor(tenant: str) -> Actor:
    return Actor(
        role=Role.REPORTER,
        practitioner_id="prac-1",
        device_id=None,
        channel="text",
        service_ids=frozenset({"ucr-west"}),
        tenant_id=tenant,
    )


def _command(tenant: str = "tenant-a", **fields: Any) -> ConfirmCapacityCommand:
    base: dict[str, Any] = {
        "idempotency_key": "key-1",
        "actor": _actor(tenant),
        "service_id": "ucr-west",
        "source": ReportSource.TEXT,
    }
    return ConfirmCapacityCommand(**{**base, **fields})


class _Untouched:
    def __init__(self, scope: ScopeId | None) -> None:
        self.unit_scope = scope

    async def __aenter__(self) -> _Untouched:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the unit of work was touched: {name}")


class _NoStore:
    async def get(self, key: str) -> Any:
        return None  # the early read is allowed: the store takes the tenant from the binding

    async def put(self, key: str, value: Any) -> None:
        raise AssertionError("the idempotency store was written")


def _use_case(scope: ScopeId | None) -> ConfirmCapacity:
    return ConfirmCapacity(
        lambda: _Untouched(scope),  # type: ignore[arg-type, return-value]
        FixedClock(NOW),
        SequentialIds(),
        _NoStore(),  # type: ignore[arg-type]
    )


async def test_an_actor_of_another_tenant_is_refused_before_anything_is_read() -> None:
    with as_tenant("tenant-a"), pytest.raises(TenantMismatch):
        await _use_case(ScopeId.tenant("tenant-a")).execute(_command("tenant-b"))


async def test_with_no_tenant_bound_nothing_is_read() -> None:
    with pytest.raises(TenantNotBound):
        await _use_case(None).execute(_command())


@pytest.mark.parametrize("scope", [None, ScopeId.network("net-west")], ids=["none", "network"])
async def test_a_unit_that_is_not_a_tenants_is_refused_before_the_lock(
    scope: ScopeId | None,
) -> None:
    with as_tenant("tenant-a"), pytest.raises(TenantNotBound):
        await _use_case(scope).execute(_command("tenant-a", idempotency_key="fresh"))


# -- the limit is the tenant's -------------------------------------------------------------------


def _policy(limit: int) -> TenantPolicy:
    return dataclasses.replace(DEFAULT_POLICY, max_consecutive_confirms=limit)


@pytest.mark.parametrize(("limit", "trailing"), [(1, 1), (2, 2), (3, 3)])
def test_the_limit_is_reached_at_the_tenants_number(limit: int, trailing: int) -> None:
    with pytest.raises(ConfirmLimitReached):
        check_confirm_limit(trailing, _policy(limit))


@pytest.mark.parametrize(("limit", "trailing"), [(1, 0), (2, 1), (3, 2)])
def test_one_below_the_limit_is_allowed(limit: int, trailing: int) -> None:
    check_confirm_limit(trailing, _policy(limit))


def test_the_default_policy_keeps_the_limit_of_two() -> None:
    check_confirm_limit(1, DEFAULT_POLICY)
    with pytest.raises(ConfirmLimitReached):
        check_confirm_limit(2, DEFAULT_POLICY)


# -- the replay fingerprint ----------------------------------------------------------------------


def test_the_fingerprint_holds_the_tenant() -> None:
    assert _fingerprint(_command("tenant-a")) != _fingerprint(_command("tenant-b"))
    assert _fingerprint(_command("tenant-a")) == _fingerprint(_command("tenant-a"))


def test_the_fingerprint_still_tells_commands_apart() -> None:
    base = _command()
    for other in (
        dataclasses.replace(base, service_id="ucr-east"),
        dataclasses.replace(base, source=ReportSource.LINK),
        dataclasses.replace(base, performer_role_id="role-1"),
        dataclasses.replace(base, send_echo=False),
    ):
        assert _fingerprint(other) != _fingerprint(base)
