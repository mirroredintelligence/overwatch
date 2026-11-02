"""The demo tenant is served while it is being set up, and nothing else changes (DEC-1320)."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from overwatch.bootstrap.demo_tenants import DemoAwareTenants
from overwatch.domain.model.tenant import (
    OrganisationType,
    SuspendMode,
    SuspendReason,
    Tenant,
    TenantStatus,
)

NOW = datetime(2026, 11, 2, tzinfo=UTC)


def _tenant(tenant_id: str, status: TenantStatus) -> Tenant:
    return Tenant(
        id=tenant_id,
        display_name="Sample Organisation",
        legal_name="Sample Organisation Ltd",
        organisation_type=OrganisationType.OTHER,
        status=status,
        created_at=NOW,
        activated_at=None if status is TenantStatus.PROVISIONING else NOW,
    )


class _Directory:
    def __init__(self, active: Sequence[str], others: dict[str, Tenant]) -> None:
        self._active = list(active)
        self._others = others

    async def active_tenant_ids(self) -> Sequence[str]:
        return list(self._active)

    async def get(self, tenant_id: str) -> Tenant | None:
        return self._others.get(tenant_id)


async def test_with_the_switch_unset_the_list_is_the_directorys() -> None:
    directory = _Directory(["a", "b"], {"demo": _tenant("demo", TenantStatus.PROVISIONING)})
    assert await DemoAwareTenants(directory, None).active_tenant_ids() == ["a", "b"]


async def test_the_demo_tenant_is_added_while_it_is_provisioning() -> None:
    directory = _Directory(["a"], {"demo": _tenant("demo", TenantStatus.PROVISIONING)})
    assert await DemoAwareTenants(directory, "demo").active_tenant_ids() == ["a", "demo"]


async def test_an_active_demo_tenant_is_listed_once() -> None:
    directory = _Directory(["a", "demo"], {})
    assert await DemoAwareTenants(directory, "demo").active_tenant_ids() == ["a", "demo"]


@pytest.mark.parametrize(
    "status",
    [
        TenantStatus.SUSPENDED,
        TenantStatus.OFFBOARDING,
        TenantStatus.OFFBOARDED,
        TenantStatus.PURGED,
    ],
)
async def test_a_demo_tenant_in_any_other_state_is_never_added(status: TenantStatus) -> None:
    tenant = replace(
        _tenant("demo", TenantStatus.ACTIVE),
        status=status,
        suspended_at=NOW if status is TenantStatus.SUSPENDED else None,
        suspend_mode=SuspendMode.BLOCKED if status is TenantStatus.SUSPENDED else None,
        suspend_reason=SuspendReason.CONTRACT if status is TenantStatus.SUSPENDED else None,
        offboarding_started_at=NOW if status is not TenantStatus.SUSPENDED else None,
        offboarded_at=NOW if status in (TenantStatus.OFFBOARDED, TenantStatus.PURGED) else None,
        purged_at=NOW if status is TenantStatus.PURGED else None,
    )
    directory = _Directory(["a"], {"demo": tenant})
    assert await DemoAwareTenants(directory, "demo").active_tenant_ids() == ["a"]


async def test_a_demo_tenant_that_does_not_exist_is_not_added() -> None:
    assert await DemoAwareTenants(_Directory(["a"], {}), "demo").active_tenant_ids() == ["a"]
