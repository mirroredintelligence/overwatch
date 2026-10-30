"""What a use case reads about its tenant besides the records: the policy, the time zone and the
link base URL (TEN-027, DEC-500).

No Neo4j: the directory and the unit of work are recording fakes. The zone is the tenant record's
(the rules take any `ZoneInfo`; the allow-list lives where a zone is made from a name), the policy
is the configuration version in force or the defaults, and the link base URL is the tenant's own
host. A tenant that cannot be read fails closed, and no refusal holds a tenant id or a host.
"""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from diucs.adapters.inbound.link_pages.capacity_links import LINK_PAGE_PATH, LINK_SCHEME
from diucs.application.ports.outbound.tenants import TenantRecordInvalid
from diucs.application.tenancy import DEFAULT_TENANT_ID, ScopeId, TenantNotBound
from diucs.application.tenant_settings import (
    LINK_PATH,
    LINK_SCHEME_TEXT,
    DirectoryLinkBase,
    DirectoryZones,
    FixedLinkBase,
    LondonZones,
    as_link_base,
    as_zones,
    read_settings,
)
from diucs.domain.model.tenant import OrganisationType, Tenant, TenantStatus
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.london_time import LONDON

A = ScopeId.tenant("tenant-a")
B = ScopeId.tenant("tenant-b")
NETWORK = ScopeId.network("net-west")
NOW = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)


def _tenant(tenant_id: str) -> Tenant:
    return Tenant(
        id=tenant_id,
        display_name="Sample Organisation",
        legal_name="Sample Organisation Ltd",
        organisation_type=OrganisationType.OTHER,
        status=TenantStatus.ACTIVE,
        created_at=NOW,
        activated_at=NOW,
    )


class _Directory:
    def __init__(self, hosts: dict[str, str | None], missing: frozenset[str] = frozenset()) -> None:
        self._hosts = hosts
        self._missing = missing
        self.asked: list[str] = []

    async def get(self, tenant_id: str) -> Tenant | None:
        self.asked.append(tenant_id)
        return None if tenant_id in self._missing else _tenant(tenant_id)

    async def host_of(self, tenant_id: str) -> str | None:
        self.asked.append(tenant_id)
        return self._hosts.get(tenant_id)


def test_the_link_path_and_scheme_are_the_link_pages() -> None:
    assert LINK_PATH == LINK_PAGE_PATH
    assert LINK_SCHEME_TEXT == LINK_SCHEME


# -- zones ---------------------------------------------------------------------------------------


async def test_the_zone_is_the_tenant_records() -> None:
    zone = await DirectoryZones(_Directory({})).zone_of(A)  # type: ignore[arg-type]
    assert type(zone) is ZoneInfo
    assert zone.key == "Europe/London"


async def test_a_tenant_the_directory_does_not_hold_has_no_zone() -> None:
    directory = _Directory({}, missing=frozenset({"tenant-a"}))
    with pytest.raises(TenantRecordInvalid) as refused:
        await DirectoryZones(directory).zone_of(A)  # type: ignore[arg-type]
    assert "tenant-a" not in str(refused.value)


async def test_a_network_scope_has_no_zone_and_the_directory_is_not_asked() -> None:
    directory = _Directory({})
    with pytest.raises(TenantNotBound):
        await DirectoryZones(directory).zone_of(NETWORK)  # type: ignore[arg-type]
    assert directory.asked == []


async def test_the_default_zones_are_londons_for_a_tenant_and_refuse_a_network() -> None:
    assert await LondonZones().zone_of(A) is LONDON
    with pytest.raises(TenantNotBound):
        await LondonZones().zone_of(NETWORK)


def test_no_zone_source_means_london() -> None:
    assert isinstance(as_zones(None), LondonZones)
    given = DirectoryZones(_Directory({}))  # type: ignore[arg-type]
    assert as_zones(given) is given


# -- link base URLs ------------------------------------------------------------------------------


async def test_the_link_base_is_the_tenants_own_host_and_the_link_pages_path() -> None:
    directory = _Directory({"tenant-a": "a.diucs.example", "tenant-b": "b.diucs.example"})
    links = DirectoryLinkBase(directory)  # type: ignore[arg-type]
    assert await links.link_base_url(A) == "https://a.diucs.example/l"
    assert await links.link_base_url(B) == "https://b.diucs.example/l"


async def test_a_tenant_with_no_host_has_no_link_base() -> None:
    links = DirectoryLinkBase(_Directory({"tenant-a": None}))  # type: ignore[arg-type]
    with pytest.raises(TenantRecordInvalid) as refused:
        await links.link_base_url(A)
    assert "tenant-a" not in str(refused.value)


async def test_only_the_default_tenant_may_fall_back_to_the_platform_base() -> None:
    directory = _Directory({})
    links = DirectoryLinkBase(directory, fallback="https://diucs.example/")  # type: ignore[arg-type]
    assert await links.link_base_url(ScopeId.tenant(DEFAULT_TENANT_ID)) == "https://diucs.example/l"
    with pytest.raises(TenantRecordInvalid):
        await links.link_base_url(A)


async def test_a_network_scope_has_no_link_base() -> None:
    with pytest.raises(TenantNotBound):
        await DirectoryLinkBase(_Directory({})).link_base_url(NETWORK)  # type: ignore[arg-type]


async def test_a_fixed_base_is_the_same_for_every_tenant_without_a_trailing_slash() -> None:
    links = FixedLinkBase("diucs.example/")
    assert await links.link_base_url(A) == await links.link_base_url(B) == "diucs.example"


async def test_a_plain_string_is_a_fixed_base() -> None:
    assert await as_link_base("diucs.example").link_base_url(A) == "diucs.example"
    given = FixedLinkBase("x")
    assert as_link_base(given) is given


# -- the settings of a unit of work --------------------------------------------------------------


class _ConfigRepo:
    def __init__(self, current: Any) -> None:
        self._current = current

    async def current_version(self) -> Any:
        return self._current


def _uow(scope: ScopeId | None, current: Any = None) -> Any:
    return SimpleNamespace(unit_scope=scope, tenant_config=_ConfigRepo(current))


async def test_no_version_in_force_gives_the_default_policy_and_no_version() -> None:
    settings = await read_settings(_uow(A), LondonZones())
    assert settings.policy == DEFAULT_POLICY
    assert settings.config_version is None
    assert settings.zone is LONDON


async def test_the_version_in_force_gives_its_policy_and_its_number() -> None:
    from diucs.domain.model.tenant import ConfigStatus, TenantConfig

    config = TenantConfig(
        version=3,
        status=ConfigStatus.CURRENT,
        values={"maxConsecutiveConfirms": 1},
        created_at=NOW,
        created_by_ref="person-a",
        effective_from=NOW,
        approved_by_refs=("person-b",),
    )
    settings = await read_settings(_uow(A, config), LondonZones())
    assert settings.policy == config.policy
    assert settings.policy != DEFAULT_POLICY
    assert settings.config_version == 3


async def test_the_zone_is_asked_for_the_scope_the_unit_is_bound_to() -> None:
    asked: list[ScopeId] = []

    class _Zones:
        async def zone_of(self, scope: ScopeId) -> ZoneInfo:
            asked.append(scope)
            return ZoneInfo("America/New_York")

    settings = await read_settings(_uow(B), _Zones())
    assert asked == [B]
    assert settings.zone.key == "America/New_York"


@pytest.mark.parametrize("scope", [None, NETWORK])
async def test_a_unit_with_no_tenant_or_a_network_is_refused_before_a_read(
    scope: ScopeId | None,
) -> None:
    uow = _uow(scope)

    async def boom() -> Any:
        raise AssertionError("the configuration must not be read")

    uow.tenant_config.current_version = boom
    with pytest.raises(TenantNotBound):
        await read_settings(uow, LondonZones())


def test_the_settings_are_a_value() -> None:
    from diucs.application.tenant_settings import TenantSettings

    one = TenantSettings(DEFAULT_POLICY, LONDON, None)
    assert replace(one, config_version=2).config_version == 2
