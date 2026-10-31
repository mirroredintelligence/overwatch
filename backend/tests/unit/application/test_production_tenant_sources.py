"""The production sources of a tenant's link host and wording (B1 task 3, KI-162, KI-266, KI-482,
KI-490, KI-492, KI-505): the link base comes from the tenant directory, the wording from the
tenant's configuration in force, and a serving process refuses one plain-string link base for every
tenant. Synthetic tenants and hosts only."""

import pytest

from diucs.application.ports.outbound.tenants import TenantRecordInvalid
from diucs.application.tenancy import ScopeId, TenantMismatch, TenantNotBound, bind_scope
from diucs.application.tenant_settings import (
    DirectoryLinkBase,
    FixedLinkBase,
    require_tenant_link_bases,
    resolve_link_base,
)
from diucs.application.tenant_wording import ConfiguredWording
from diucs.domain.model.tenant import TenantWording

TENANT = "tenant-prod-a"
OTHER = "tenant-prod-b"
WORDING = TenantWording(
    system_name="Sample capacity",
    referral_system_name="Sample referral",
    coordination_team_name="The sample coordination team",
)


class _Hosts:
    def __init__(self, hosts: dict[str, str]) -> None:
        self._hosts = hosts
        self.asked: list[str] = []

    async def host_of(self, tenant_id: str) -> str | None:
        self.asked.append(tenant_id)
        return self._hosts.get(tenant_id)


class _Reader:
    def __init__(self, wording: TenantWording | None) -> None:
        self._wording = wording
        self.reads = 0

    async def wording(self) -> TenantWording | None:
        self.reads += 1
        return self._wording


async def test_a_sync_link_base_is_returned_as_it_is() -> None:
    assert await resolve_link_base(
        lambda scope: "https://sync.example", ScopeId.tenant(TENANT)
    ) == ("https://sync.example")


async def test_an_async_link_base_is_awaited() -> None:
    directory = _Hosts({TENANT: "alpha.example.org"})
    source = DirectoryLinkBase(directory).link_base_url  # type: ignore[arg-type]

    assert await resolve_link_base(source, ScopeId.tenant(TENANT)) == "https://alpha.example.org/l"


async def test_two_tenants_get_their_own_hosts_through_the_directory() -> None:
    directory = _Hosts({TENANT: "alpha.example.org", OTHER: "beta.example.org"})
    source = DirectoryLinkBase(directory).link_base_url  # type: ignore[arg-type]

    one = await resolve_link_base(source, ScopeId.tenant(TENANT))
    two = await resolve_link_base(source, ScopeId.tenant(OTHER))

    assert (one, two) == ("https://alpha.example.org/l", "https://beta.example.org/l")
    assert directory.asked == [TENANT, OTHER]


async def test_a_tenant_with_no_host_is_a_fault_and_not_another_tenants_host() -> None:
    source = DirectoryLinkBase(_Hosts({OTHER: "beta.example.org"})).link_base_url  # type: ignore[arg-type]

    with pytest.raises(TenantRecordInvalid):
        await resolve_link_base(source, ScopeId.tenant(TENANT))


async def test_a_source_that_answers_neither_text_nor_an_awaitable_is_refused() -> None:
    with pytest.raises(TypeError):
        await resolve_link_base(lambda scope: 7, ScopeId.tenant(TENANT))  # type: ignore[arg-type, return-value]


def test_a_plain_string_link_base_is_refused_for_a_serving_process() -> None:
    with pytest.raises(TypeError, match="every tenant"):
        require_tenant_link_bases("https://one-base.example")


def test_a_fixed_link_base_object_is_refused_for_a_serving_process() -> None:
    with pytest.raises(TypeError, match="every tenant"):
        require_tenant_link_bases(FixedLinkBase("https://one-base.example"))


def test_a_directory_link_base_is_accepted_for_a_serving_process() -> None:
    source = DirectoryLinkBase(_Hosts({}))  # type: ignore[arg-type]

    assert require_tenant_link_bases(source) is source


async def test_the_configured_wording_is_read_for_the_bound_tenant() -> None:
    reader = _Reader(WORDING)
    wording_for = ConfiguredWording(reader)

    with bind_scope(ScopeId.tenant(TENANT)):
        found = await wording_for(ScopeId.tenant(TENANT))

    assert found == WORDING
    assert reader.reads == 1


async def test_a_tenant_with_no_wording_in_force_has_none() -> None:
    with bind_scope(ScopeId.tenant(TENANT)):
        assert await ConfiguredWording(_Reader(None))(ScopeId.tenant(TENANT)) is None


async def test_the_wording_of_another_tenant_than_the_bound_one_is_never_read() -> None:
    reader = _Reader(WORDING)

    with bind_scope(ScopeId.tenant(TENANT)), pytest.raises(TenantMismatch):
        await ConfiguredWording(reader)(ScopeId.tenant(OTHER))

    assert reader.reads == 0


async def test_a_network_scope_has_no_wording() -> None:
    reader = _Reader(WORDING)

    with bind_scope(ScopeId.network("net-1")), pytest.raises(TenantNotBound):
        await ConfiguredWording(reader)(ScopeId.network("net-1"))

    assert reader.reads == 0
