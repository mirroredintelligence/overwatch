"""A suspension or a resume makes the serving process forget the tenant's cached record (TEN-073).

The record is cached for at most `RECORD_TTL`; `forget` is only a shortcut that makes the change
immediate in the process that ran the operator's route. A process that was not told still reads the
record again within the interval, and a token whose epoch is behind the record is refused on the
first read (`tests/unit/application/use_cases/test_tenant_suspend.py`).
"""

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from diucs.adapters.inbound.fhir_rest.auth import forget_tenant
from diucs.adapters.inbound.fhir_rest.tenant_gate import TenantGate
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.domain.codes import Role
from diucs.domain.model.tenant import SuspendMode, SuspendReason
from diucs.domain.rules.bff_token import BffClaims
from diucs.domain.rules.edge_access import EdgeVerdict
from diucs.domain.rules.tenant_lifecycle import suspend_tenant
from tests.support.provisioning_fakes import NOW, OTHER, TENANT, FakePlatform, provisioning_tenant
from tests.support.tenant_samples import make_tenant


def _claims(tenant: str, epoch: int = 1) -> BffClaims:
    return BffClaims(
        sub="prac-1",
        role=Role.LEAD,
        services=frozenset(),
        expires_at=NOW + timedelta(hours=8),
        tenant=tenant,
        epoch=epoch,
    )


def _active(tenant_id: str) -> Any:
    return make_tenant(id=tenant_id)


async def test_forgetting_a_tenant_makes_the_next_token_read_a_fresh_record() -> None:
    platform = FakePlatform(_active(TENANT))
    gate = TenantGate(platform, FixedClock(NOW))  # type: ignore[arg-type]
    assert await gate.verdict(_claims(TENANT), "GET") is EdgeVerdict.ALLOWED

    platform.tenants[TENANT] = suspend_tenant(
        platform.tenants[TENANT], SuspendMode.BLOCKED, SuspendReason.CONTRACT, NOW
    )
    # The token was issued before the suspension, so its epoch is the cached record's: allowed from
    # the cache until the record is read again.
    assert await gate.verdict(_claims(TENANT), "GET") is EdgeVerdict.ALLOWED

    gate.forget(TENANT)

    assert await gate.verdict(_claims(TENANT), "GET") is EdgeVerdict.REFUSED


async def test_forgetting_one_tenant_keeps_the_others_cached() -> None:
    platform = FakePlatform(_active(TENANT), _active(OTHER))
    gate = TenantGate(platform, FixedClock(NOW))  # type: ignore[arg-type]
    await gate.verdict(_claims(TENANT), "GET")
    await gate.verdict(_claims(OTHER), "GET")
    platform.calls.clear()

    gate.forget(TENANT)
    asked: list[str] = []
    original = platform.get

    async def spy(tenant_id: str) -> Any:
        asked.append(tenant_id)
        return await original(tenant_id)

    platform.get = spy  # type: ignore[method-assign]
    await gate.verdict(_claims(OTHER), "GET")  # still cached: no read
    await gate.verdict(_claims(TENANT), "GET")  # read again
    assert asked == [TENANT]


def test_forgetting_a_tenant_nobody_cached_or_in_an_app_with_no_gate_is_harmless() -> None:
    gate = TenantGate(FakePlatform(), FixedClock(NOW))  # type: ignore[arg-type]
    gate.forget("never-seen")
    app = SimpleNamespace(state=SimpleNamespace())
    forget_tenant(app, TENANT)  # no gate built yet: nothing is cached
    app.state.tenant_gate = gate
    forget_tenant(app, TENANT)
    assert provisioning_tenant().id == TENANT


async def test_the_app_level_function_reaches_the_gate_the_edge_uses() -> None:
    platform = FakePlatform(_active(TENANT))
    gate = TenantGate(platform, FixedClock(NOW))  # type: ignore[arg-type]
    app = SimpleNamespace(state=SimpleNamespace(tenant_gate=gate))
    await gate.verdict(_claims(TENANT), "GET")
    platform.tenants[TENANT] = suspend_tenant(
        platform.tenants[TENANT], SuspendMode.BLOCKED, SuspendReason.CONTRACT, NOW
    )

    forget_tenant(app, TENANT)

    assert await gate.verdict(_claims(TENANT), "GET") is EdgeVerdict.REFUSED
