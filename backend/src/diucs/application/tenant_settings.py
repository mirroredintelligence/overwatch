"""What a use case reads about its tenant besides the records: policy, time zone, link base URL
(TEN-027, DEC-500).

The policy is the configuration version in force (or the defaults, which equal the behaviour before
tenancy). The time zone and the host are on the tenant's registry record, which only the directory
reads: a use case asks a small source for each, so a unit test can give it a fake and the tenant's
zone reaches every rule as an explicit argument (DEC-353). Nothing here takes a tenant from a
command: the scope is the one the unit of work is bound to.

Fail closed. A tenant the directory does not hold, or one with no host, is a configuration fault
(`TenantRecordInvalid`, a fixed message that names no tenant and no host). A network scope has no
zone and no link host: `TenantNotBound`, before the directory is asked. Only the default tenant (the
development data that predates tenancy) may fall back to the platform's base URL, because it has no
host of its own; any other tenant without a host cannot be sent a link, which is better than a link
that opens on another tenant's host (DEC-134 item 3: the host chooses the tenant).
"""

from dataclasses import dataclass
from typing import Final, Protocol
from zoneinfo import ZoneInfo

from diucs.application.ports.outbound.tenants import TenantDirectory, TenantRecordInvalid
from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.application.tenancy import DEFAULT_TENANT_ID, ScopeId, ScopeKind, TenantNotBound
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules.london_time import LONDON, zone_named

# The capacity link pages are served at `/l/<token>` on the tenant's own host (L01, DEC-167). The
# adapter has its own copy of both constants; a test keeps the two equal.
LINK_PATH: Final = "/l"
LINK_SCHEME_TEXT: Final = "https"

ZONE_MESSAGE: Final = "the tenant has no readable time zone"
HOST_MESSAGE: Final = "the tenant has no host to send a link to"


def _tenant_scope(scope: ScopeId | None) -> ScopeId:
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


class TenantZones(Protocol):
    async def zone_of(self, scope: ScopeId) -> ZoneInfo:
        """The time zone of the tenant this scope names."""
        ...


class LinkBases(Protocol):
    async def link_base_url(self, scope: ScopeId) -> str:
        """The base of the tenant's capacity links, without a trailing slash: `<base>/<token>`."""
        ...


class DirectoryZones:
    """The zone of the tenant's registry record, validated against the allow-list."""

    def __init__(self, directory: TenantDirectory) -> None:
        self._directory = directory

    async def zone_of(self, scope: ScopeId) -> ZoneInfo:
        tenant_scope = _tenant_scope(scope)
        tenant = await self._directory.get(tenant_scope.value)
        if tenant is None:
            raise TenantRecordInvalid(ZONE_MESSAGE)
        return zone_named(tenant.time_zone)


class LondonZones:
    """Europe/London for every tenant: the one zone the allow-list holds today. For a caller that
    has not been given a source (the test rigs); the serving process passes `DirectoryZones`."""

    async def zone_of(self, scope: ScopeId) -> ZoneInfo:
        _tenant_scope(scope)
        return LONDON


def as_zones(source: TenantZones | None) -> TenantZones:
    return LondonZones() if source is None else source


class FixedLinkBase:
    """One base for every tenant: for tests and a one-host deployment."""

    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")

    async def link_base_url(self, scope: ScopeId) -> str:
        _tenant_scope(scope)
        return self._url


class DirectoryLinkBase:
    """`https://<the tenant's host>/l`. The host is a property of the tenant's registry node."""

    def __init__(self, directory: TenantDirectory, fallback: str | None = None) -> None:
        self._directory = directory
        self._fallback = None if fallback is None else fallback.rstrip("/")

    async def link_base_url(self, scope: ScopeId) -> str:
        tenant_scope = _tenant_scope(scope)
        host = await self._directory.host_of(tenant_scope.value)
        if host is not None:
            return f"{LINK_SCHEME_TEXT}://{host}{LINK_PATH}"
        if tenant_scope.value == DEFAULT_TENANT_ID and self._fallback is not None:
            return f"{self._fallback}{LINK_PATH}"
        raise TenantRecordInvalid(HOST_MESSAGE)


class HostUrls(Protocol):
    async def host_url(self, scope: ScopeId) -> str:
        """`https://<the tenant's host>`: the root of the pages that are not the capacity link
        pages (the invitation page of the first administrator, `/i/<token>`)."""
        ...


class DirectoryHostUrl:
    """The tenant's own host as a URL root. No fallback: an invitation on another host would not
    open (and a tenant with no host cannot be activated)."""

    def __init__(self, directory: TenantDirectory) -> None:
        self._directory = directory

    async def host_url(self, scope: ScopeId) -> str:
        tenant_scope = _tenant_scope(scope)
        host = await self._directory.host_of(tenant_scope.value)
        if host is None:
            raise TenantRecordInvalid(HOST_MESSAGE)
        return f"{LINK_SCHEME_TEXT}://{host}"


def as_link_base(source: str | LinkBases) -> LinkBases:
    return FixedLinkBase(source) if isinstance(source, str) else source


@dataclass(frozen=True, slots=True)
class TenantSettings:
    policy: TenantPolicy
    zone: ZoneInfo
    config_version: int | None
    """The configuration version the policy came from; None when the defaults apply."""


async def read_settings(uow: UnitOfWork, zones: TenantZones) -> TenantSettings:
    """The policy and zone of the tenant the unit of work is bound to. Read inside the unit, so the
    configuration is the one in force for the whole of the work."""
    scope = _tenant_scope(uow.unit_scope)
    config = await uow.tenant_config.current_version()
    return TenantSettings(
        policy=DEFAULT_POLICY if config is None else config.policy,
        zone=await zones.zone_of(scope),
        config_version=None if config is None else config.version,
    )


async def read_policy(uow: UnitOfWork) -> TenantPolicy:
    """The policy alone, for a use case that judges no time of day (no zone is asked for)."""
    _tenant_scope(uow.unit_scope)
    config = await uow.tenant_config.current_version()
    return DEFAULT_POLICY if config is None else config.policy
