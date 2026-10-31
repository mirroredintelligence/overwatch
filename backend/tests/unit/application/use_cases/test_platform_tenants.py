"""The operator's reads of its tenants: the list and one tenant's detail (TEN-075).

The list is the registry's, whatever the status. The detail is the record, its host and directory,
its numbers, and while the tenant is being provisioned what activation still waits for. Nothing of
a tenant's own data is read. No Neo4j: the recording fakes of `tests/support/provisioning_fakes`.
"""

from typing import Any

import pytest

from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.ports.outbound.tenant_registry import TenantNumberRecord
from diucs.application.ports.outbound.tenants import twilio_token_ref
from diucs.application.tenancy import TenantMismatch
from diucs.application.use_cases.platform_tenants import ListPlatformTenants, ReadPlatformTenant
from diucs.application.use_cases.tenant_admin import ActivateTenant
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.tenant import TenantStatus
from tests.support.provisioning_fakes import (
    DIRECTORY_ID,
    NOW,
    OTHER,
    TENANT,
    FakePlatform,
    FakeWorld,
    FixedNow,
    operator,
    provisioning_tenant,
)
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

SID = "AC" + "a" * 32


def _read(platform: FakePlatform, world: FakeWorld) -> ReadPlatformTenant:
    clock = FixedNow()
    activate = ActivateTenant(
        platform,  # type: ignore[arg-type]
        platform,  # type: ignore[arg-type]
        world.factory(),
        SequentialIds(),
        clock,
        lambda scope: frozenset(),
    )
    return ReadPlatformTenant(
        platform,  # type: ignore[arg-type]
        platform,  # type: ignore[arg-type]
        world.factory(),
        clock,
        activate,
    )


def _active(**fields: Any) -> Any:
    return provisioning_tenant(**{"status": TenantStatus.ACTIVE, "activated_at": NOW, **fields})


async def test_the_list_is_every_tenant_in_id_order_whatever_its_status() -> None:
    platform = FakePlatform(_active(id="zeta-org"), provisioning_tenant("alpha-org"), _active())
    platform.hosts["zeta-org"] = "zeta.example.org"

    listed = await ListPlatformTenants(platform).execute()  # type: ignore[arg-type]

    assert [item.tenant.id for item in listed] == ["alpha-org", TENANT, "zeta-org"]
    assert [item.tenant.status for item in listed] == [
        TenantStatus.PROVISIONING,
        TenantStatus.ACTIVE,
        TenantStatus.ACTIVE,
    ]
    assert listed[2].host == "zeta.example.org" and listed[0].host is None


async def test_the_detail_of_a_provisioning_tenant_says_what_activation_waits_for() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    platform.hosts[TENANT] = "new.example.org"
    platform.directories[TENANT] = DIRECTORY_ID

    with as_tenant(TENANT):
        detail = await _read(platform, world).execute(operator())

    assert detail.tenant.tenant.id == TENANT
    assert (detail.tenant.host, detail.tenant.directory_id) == ("new.example.org", DIRECTORY_ID)
    assert detail.activation is not None
    assert detail.activation.blockers
    assert all(isinstance(item, str) for item in detail.activation.blockers)


async def test_the_detail_of_an_active_tenant_has_no_activation_to_wait_for() -> None:
    platform, world = FakePlatform(_active()), FakeWorld()

    with as_tenant(TENANT):
        detail = await _read(platform, world).execute(operator())

    assert detail.activation is None


async def test_the_detail_lists_the_tenants_own_numbers_and_no_other_tenants() -> None:
    platform, world = FakePlatform(_active(), _active(id=OTHER)), FakeWorld()
    await platform.put_number(
        TENANT, TenantNumberRecord("+447700900111", SID, twilio_token_ref(TENANT))
    )
    await platform.put_number(
        OTHER, TenantNumberRecord("+447700900222", SID, twilio_token_ref(OTHER))
    )

    with as_tenant(TENANT):
        detail = await _read(platform, world).execute(operator())

    assert [n.e164 for n in detail.numbers] == ["+447700900111"]


async def test_a_tenant_that_is_not_there_is_not_found() -> None:
    platform, world = FakePlatform(), FakeWorld()

    with as_tenant(TENANT), pytest.raises(NotFound):
        await _read(platform, world).execute(operator())


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.PLATFORM_OPERATOR])
async def test_only_the_platform_operator_reads_the_detail(role: Role) -> None:
    platform, world = FakePlatform(_active()), FakeWorld()

    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _read(platform, world).execute(operator(role=role))


async def test_an_operator_bound_to_another_tenant_is_a_wiring_fault() -> None:
    platform, world = FakePlatform(_active(), _active(id=OTHER)), FakeWorld()

    with as_tenant(OTHER), pytest.raises(TenantMismatch):
        await _read(platform, world).execute(operator())
