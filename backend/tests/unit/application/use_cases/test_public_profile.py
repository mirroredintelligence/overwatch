"""The public profile of a tenant (TEN-040): display fields only, read inside the tenant's own
scope. No Docker: the unit of work is a stub that reports the scope it was opened in."""

from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.application.tenancy import ScopeId, TenantNotBound, bind_scope, bind_tenant
from diucs.application.use_cases.public_profile import DEFAULT_LOCALE, ReadPublicProfile
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    TenantConfig,
    TenantContact,
)
from tests.support.tenant_samples import SAMPLE_WORDING, make_tenant

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


class _Config:
    def __init__(self, config: TenantConfig | None, contacts: tuple[TenantContact, ...]) -> None:
        self._config = config
        self._contacts = contacts

    async def current_version(self) -> TenantConfig | None:
        return self._config

    async def contacts(self) -> tuple[TenantContact, ...]:
        return self._contacts


class _Unit:
    def __init__(self, scope: ScopeId | None, config: _Config) -> None:
        self.unit_scope = scope
        self.tenant_config = config

    async def __aenter__(self) -> _Unit:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _factory(scope: ScopeId | None, config: _Config) -> Any:
    return lambda: _Unit(scope, config)


def _config() -> TenantConfig:
    return TenantConfig(
        version=1,
        status=ConfigStatus.CURRENT,
        values=dict(SAMPLE_WORDING),
        created_at=T0,
        created_by_ref="admin-ref-1",
        effective_from=T0,
    )


PHONE = TenantContact(ContactKind.COORDINATION_PHONE, "Coordination", "01234 567890")
EMAIL = TenantContact(ContactKind.SUPPORT_EMAIL, "Support", "support@example.test")
SHIFT = TenantContact(ContactKind.SHIFT_LEAD_ESCALATION, "Shift lead", "01234 000111")


async def test_the_profile_holds_display_fields_wording_and_only_the_coordination_phone() -> None:
    tenant = make_tenant(id="tenant-a", display_name="Example A ICB")
    read = ReadPublicProfile(
        _factory(ScopeId.tenant("tenant-a"), _Config(_config(), (EMAIL, SHIFT, PHONE)))
    )

    with bind_tenant("tenant-a"):
        profile = await read.execute(tenant)

    assert profile.display_name == "Example A ICB"
    assert profile.time_zone == "Europe/London"
    assert profile.locale == DEFAULT_LOCALE == "en-GB"
    assert profile.wording is not None
    assert profile.wording.system_name == SAMPLE_WORDING["systemName"]
    assert profile.coordination_phone == "01234 567890"


async def test_no_configuration_and_no_phone_are_none_never_a_default() -> None:
    tenant = make_tenant(id="tenant-a")
    read = ReadPublicProfile(_factory(ScopeId.tenant("tenant-a"), _Config(None, (EMAIL, SHIFT))))

    profile = await read.execute(tenant)

    assert profile.wording is None
    assert profile.coordination_phone is None


@pytest.mark.parametrize(
    "scope", [None, ScopeId.network("net-test"), ScopeId.tenant("tenant-b")], ids=str
)
async def test_a_unit_that_is_not_the_tenants_own_scope_is_refused(scope: ScopeId | None) -> None:
    read = ReadPublicProfile(_factory(scope, _Config(_config(), (PHONE,))))

    with pytest.raises(TenantNotBound):
        await read.execute(make_tenant(id="tenant-a"))


async def test_a_network_binding_is_refused_too() -> None:
    read = ReadPublicProfile(_factory(ScopeId.network("net-test"), _Config(_config(), (PHONE,))))

    with bind_scope(ScopeId.network("net-test")), pytest.raises(TenantNotBound):
        await read.execute(make_tenant(id="tenant-a"))
