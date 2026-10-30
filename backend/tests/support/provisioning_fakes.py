"""Recording fakes for the unit tests of the operator's tenant lifecycle (TEN-028, TEN-073).

There is no in-memory store of records (DEC-004): these fakes hold only what the lifecycle use cases
read and write (a tenant directory and registry over one set of tenants, a unit of work with the
few repositories the use cases touch), so a test shows the order of the steps, what is written and
what is refused. What is stored on a real graph is proved by the integration tests.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Self

from diucs.application.actor import Actor
from diucs.application.ports.outbound.tenant_registry import RegistryTenant, TenantNumberRecord
from diucs.application.ports.outbound.tenants import TenantRecordInvalid, normalise_host
from diucs.application.tenancy import ScopeId, current_scope_or_none
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotFound
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    OrganisationType,
    Tenant,
    TenantConfig,
    TenantContact,
    TenantStatus,
)
from diucs.domain.model.tenant_records import (
    BindingStatus,
    EntraBinding,
    MappingStatus,
    RoleMapping,
    TenantChannel,
    default_retention,
)

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
TENANT = "new-org"
OTHER = "other-org"
OPERATOR = "operator-1"
DIRECTORY_ID = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
GROUP_ID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
WORDING = {
    "systemName": "Sample capacity view",
    "referralSystemName": "Sample referral system",
    "coordinationTeamName": "The sample coordination team",
}


def operator(
    tenant: str = TENANT, ref: str | None = OPERATOR, role: Role = Role.PLATFORM_OPERATOR
) -> Actor:
    return Actor(
        role=role,
        practitioner_id=ref,
        device_id=None,
        channel="script",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def provisioning_tenant(tenant_id: str = TENANT, **fields: Any) -> Tenant:
    base: dict[str, Any] = {
        "id": tenant_id,
        "display_name": "New Organisation",
        "legal_name": "New Organisation Ltd",
        "organisation_type": OrganisationType.OTHER,
        "status": TenantStatus.PROVISIONING,
        "created_at": NOW,
    }
    return Tenant(**{**base, **fields})


class FakePlatform:
    """The tenant directory (read) and the registry (write) over one set of tenants, so a flow
    that writes and then reads sees its own writes, as it would on the graph."""

    def __init__(self, *tenants: Tenant) -> None:
        self.tenants: dict[str, Tenant] = {t.id: t for t in tenants}
        self.hosts: dict[str, str] = {}
        self.directories: dict[str, str] = {}
        self.numbers_by_tenant: dict[str, dict[str, TenantNumberRecord]] = {}
        self.calls: list[tuple[str, Any]] = []
        self.reject_save = False

    # the directory
    async def get(self, tenant_id: str) -> Tenant | None:
        return self.tenants.get(tenant_id)

    async def host_of(self, tenant_id: str) -> str | None:
        return self.hosts.get(tenant_id)

    # the registry
    async def create(self, tenant: Tenant) -> None:
        self.calls.append(("create", tenant.id))
        if tenant.id in self.tenants:
            raise Conflict("a tenant with this id already exists")
        self.tenants[tenant.id] = tenant

    async def save(
        self, tenant: Tenant, *, expected_epoch: int, expected_status: TenantStatus
    ) -> bool:
        self.calls.append(("save", (tenant.id, expected_epoch, expected_status, tenant.status)))
        stored = self.tenants.get(tenant.id)
        if self.reject_save or stored is None:
            return False
        if stored.epoch != expected_epoch or stored.status is not expected_status:
            return False
        self.tenants[tenant.id] = tenant
        return True

    async def set_host(self, tenant_id: str, host: str) -> None:
        self.calls.append(("set_host", (tenant_id, host)))
        if tenant_id not in self.tenants:
            raise NotFound("no tenant with this id")
        if normalise_host(host) is None:
            raise TenantRecordInvalid("bad host")
        if any(h == host and t != tenant_id for t, h in self.hosts.items()):
            raise Conflict("this value is held by another tenant")
        self.hosts[tenant_id] = host

    async def set_entra_directory(self, tenant_id: str, directory_id: str) -> None:
        self.calls.append(("set_entra_directory", (tenant_id, directory_id)))
        if any(d == directory_id and t != tenant_id for t, d in self.directories.items()):
            raise Conflict("this value is held by another tenant")
        self.directories[tenant_id] = directory_id

    async def put_number(self, tenant_id: str, number: TenantNumberRecord) -> None:
        self.calls.append(("put_number", (tenant_id, number.e164)))
        for other, held in self.numbers_by_tenant.items():
            if other != tenant_id and number.e164 in held:
                raise Conflict("this value is held by another tenant")
        self.numbers_by_tenant.setdefault(tenant_id, {})[number.e164] = number

    async def mark_number_tested(self, tenant_id: str, e164: str, at: datetime) -> None:
        self.calls.append(("mark_number_tested", (tenant_id, e164)))
        held = self.numbers_by_tenant.get(tenant_id, {})
        if e164 not in held:
            raise NotFound("the tenant holds no such number")
        held[e164] = replace(held[e164], tested_at=at)

    async def numbers(self, tenant_id: str) -> tuple[TenantNumberRecord, ...]:
        return tuple(self.numbers_by_tenant.get(tenant_id, {}).values())

    async def list_all(self) -> tuple[RegistryTenant, ...]:
        return tuple(
            RegistryTenant(t, self.hosts.get(t.id), self.directories.get(t.id))
            for t in sorted(self.tenants.values(), key=lambda t: t.id)
        )

    async def detail(self, tenant_id: str) -> RegistryTenant | None:
        found = self.tenants.get(tenant_id)
        if found is None:
            return None
        return RegistryTenant(found, self.hosts.get(tenant_id), self.directories.get(tenant_id))


class FakeConfig:
    """The tenant configuration repository, with only what the lifecycle reads and writes."""

    def __init__(self) -> None:
        self.current: TenantConfig | None = None
        self.contact_list: list[TenantContact] = []
        self.channel_list: list[TenantChannel] = []
        self.retention_list = ()
        self.binding_list: list[EntraBinding] = []
        self.mapping_list: list[RoleMapping] = []

    async def current_version(self) -> TenantConfig | None:
        return self.current

    async def contacts(self) -> tuple[TenantContact, ...]:
        return tuple(self.contact_list)

    async def channels(self) -> tuple[TenantChannel, ...]:
        return tuple(self.channel_list)

    async def retention(self) -> Any:
        return tuple(self.retention_list)

    async def bindings(self) -> tuple[EntraBinding, ...]:
        return tuple(self.binding_list)

    async def role_mappings(self) -> tuple[RoleMapping, ...]:
        return tuple(self.mapping_list)

    async def put_channel(self, channel: TenantChannel) -> None:
        self.channel_list = [c for c in self.channel_list if c.id != channel.id] + [channel]

    async def put_binding(self, binding: EntraBinding) -> None:
        self.binding_list = [
            b for b in self.binding_list if b.directory_id != binding.directory_id
        ] + [binding]

    def make_ready(self) -> None:
        """Everything the configuration contributes to an activation."""
        self.current = TenantConfig(
            version=1,
            status=ConfigStatus.CURRENT,
            values=WORDING,
            created_at=NOW,
            created_by_ref="person-a",
            effective_from=NOW,
            approved_by_refs=("person-b", "person-c"),
        )
        self.contact_list = [
            TenantContact(ContactKind.COORDINATION_PHONE, "Coordination", "01234 567890"),
            TenantContact(ContactKind.CLINICAL_SAFETY_OFFICER, "Safety", "safety@example.org"),
        ]
        self.retention_list = default_retention()
        self.binding_list = [EntraBinding(DIRECTORY_ID, BindingStatus.PENDING)]
        self.mapping_list = [RoleMapping(GROUP_ID, Role.LEAD, MappingStatus.ACTIVE)]


class FakeTokens:
    """The link tokens of the unit: only `open_for_about`, which the activation reads."""

    def __init__(self) -> None:
        self.open_about: dict[tuple[str, str], object] = {}

    async def open_for_about(self, purpose: str, about_id: str, now: datetime) -> object | None:
        return self.open_about.get((purpose, about_id))


class FakeUnit:
    def __init__(self, world: FakeWorld, scope: ScopeId | None) -> None:
        self.unit_scope = scope
        self.tenant_config = world.config
        self.link_tokens = world.tokens
        self.audit = SimpleNamespace(append=self._append)
        self.scope = SimpleNamespace(ensure_list=self._ensure_list)
        self.committed = False
        self._world = world

    async def _append(self, entry: Any) -> None:
        self._world.audit.append(entry)

    async def _ensure_list(self) -> None:
        self._world.lists_ensured += 1

    async def commit(self) -> None:
        self.committed = True
        self._world.commits += 1

    async def rollback(self) -> None:
        return None

    async def __aenter__(self) -> Self:
        self._world.opened += 1
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the unit of work was touched: {name}")


class FakeWorld:
    """What the lifecycle use cases write into a tenant's scope, recorded."""

    def __init__(self) -> None:
        self.config = FakeConfig()
        self.tokens = FakeTokens()
        self.audit: list[Any] = []
        self.opened = 0
        self.commits = 0
        self.lists_ensured = 0

    def factory(self) -> Callable[[], FakeUnit]:
        return lambda: FakeUnit(self, current_scope_or_none())

    def audited(self) -> list[str]:
        return [entry.use_case for entry in self.audit]


class FakeHeads:
    """The scope provisioner: the audit chain head of the bound scope."""

    def __init__(self) -> None:
        self.calls: list[ScopeId | None] = []

    async def ensure_audit_head(self) -> None:
        self.calls.append(current_scope_or_none())


class FixedNow:
    def __init__(self, value: datetime = NOW) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value
