"""The staff registry's two use cases (DEC-1327).

`SyncStaffRegistry` is the platform's job: for each active tenant it reads the tenant's verified
directory and its active role mappings, lists the members of each mapped group through Graph, and
replaces that tenant's records in the registry. A group that is not in the directory has no members
(its records end); any other failure leaves the tenant's records as they were, so a Graph fault can
never end a person's access in the picker by mistake.

`StaffTenantChoices` is the sign-in's read: the person's verified identity gives an account
reference (the same one in every tenant they work for), and the registry gives the tenants that
reference holds an active role in. The tenant is not trusted from the registry alone: the exchange
that follows checks the person's groups against that tenant's own mapping (`ExchangeStaffToken`).
"""

import logging
from dataclasses import dataclass

from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.entra_groups import EntraGroupDirectory, GroupMissing
from overwatch.application.ports.outbound.identity_verifier import (
    Audience,
    IdentityRejected,
    IdentityVerifier,
)
from overwatch.application.ports.outbound.staff_registry import StaffRegistry
from overwatch.application.ports.outbound.tenants import TenantDirectory
from overwatch.application.ports.outbound.tokens import SecretStore
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.tenancy import bind_tenant
from overwatch.application.use_cases.exchange_token import (
    ACCOUNT_REF_SECRET,
    ExchangeRefused,
)
from overwatch.domain.codes import Role
from overwatch.domain.errors import NotFound
from overwatch.domain.model.staff_registry import StaffRoleRecord
from overwatch.domain.model.tenant import Tenant, TenantStatus
from overwatch.domain.model.tenant_records import BindingStatus, MappingStatus
from overwatch.domain.rules.token_exchange import (
    STAFF_ROLE_PRIORITY,
    account_ref,
)

log = logging.getLogger(__name__)


def _account_key(secrets: SecretStore) -> bytes:
    try:
        return secrets.get(ACCOUNT_REF_SECRET)
    except NotFound:
        raise RuntimeError("a secret the staff registry needs is not configured") from None


@dataclass(frozen=True, slots=True)
class SyncReport:
    tenants: int
    replaced: int
    skipped: int


class SyncStaffRegistry:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        tenants: TenantDirectory,
        groups: EntraGroupDirectory,
        registry: StaffRegistry,
        secrets: SecretStore,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._tenants = tenants
        self._groups = groups
        self._registry = registry
        self._secrets = secrets
        self._clock = clock

    async def execute(self) -> SyncReport:
        key = _account_key(self._secrets)
        now = self._clock.now()
        replaced = 0
        skipped = 0
        tenant_ids = await self._tenants.active_tenant_ids()
        for tenant_id in tenant_ids:
            try:
                records = await self._records(tenant_id, key)
            except Exception:
                # The tenant keeps its records: a fault reads nothing, so it must end nothing.
                log.warning("staff registry: tenant skipped, reason=read")
                skipped += 1
                continue
            if records is None:
                skipped += 1
                continue
            await self._registry.replace_tenant(tenant_id, records, now)
            replaced += 1
        return SyncReport(tenants=len(tenant_ids), replaced=replaced, skipped=skipped)

    async def _records(self, tenant_id: str, key: bytes) -> tuple[StaffRoleRecord, ...] | None:
        """The tenant's staff records as its directory now gives them, or None when the tenant has
        no verified directory (then nothing can be known, and nothing is written)."""
        with bind_tenant(tenant_id):
            async with self._uow_factory() as uow:
                bindings = await uow.tenant_config.bindings()
                mappings = await uow.tenant_config.role_mappings()
        verified = [b for b in bindings if b.status is BindingStatus.VERIFIED]
        if len(verified) != 1:
            return None
        directory_id = verified[0].directory_id
        active = [
            m
            for m in mappings
            if m.status is MappingStatus.ACTIVE and m.role in STAFF_ROLE_PRIORITY
        ]
        found: dict[str, StaffRoleRecord] = {}
        for mapping in active:
            try:
                members = await self._groups.members(directory_id, mapping.group_object_id)
            except GroupMissing:
                members = ()
            for member in members:
                record = StaffRoleRecord(
                    tenant_id=tenant_id,
                    practitioner_key=account_ref(key, directory_id, member.object_id),
                    role=mapping.role,
                    status="active",
                )
                found[record.id] = record
        return tuple(found.values())


@dataclass(frozen=True, slots=True)
class StaffTenantChoice:
    tenant_id: str
    name: str
    roles: tuple[Role, ...]


class StaffTenantChoices:
    def __init__(
        self,
        verifier: IdentityVerifier,
        secrets: SecretStore,
        registry: StaffRegistry,
        tenants: TenantDirectory,
    ) -> None:
        self._verifier = verifier
        self._secrets = secrets
        self._registry = registry
        self._tenants = tenants

    async def execute(self, credential: object) -> tuple[StaffTenantChoice, ...]:
        """The active tenants this person holds a staff role in, by name. A credential that does not
        verify, and a person in no tenant, are the one refusal."""
        if type(credential) is not str or not credential:
            raise ExchangeRefused
        try:
            identity = await self._verifier.verify(credential, Audience.STAFF)
        except IdentityRejected:
            raise ExchangeRefused from None
        key = account_ref(_account_key(self._secrets), identity.directory_id, identity.object_id)
        by_tenant: dict[str, set[Role]] = {}
        for record in await self._registry.active_roles(key):
            by_tenant.setdefault(record.tenant_id, set()).add(record.role)
        choices: list[StaffTenantChoice] = []
        for tenant_id, roles in by_tenant.items():
            tenant = await self._tenants.get(tenant_id)
            if tenant is None or not _is_active(tenant):
                continue
            ordered = tuple(role for role in STAFF_ROLE_PRIORITY if role in roles)
            choices.append(
                StaffTenantChoice(tenant_id=tenant_id, name=tenant.display_name, roles=ordered)
            )
        if not choices:
            raise ExchangeRefused
        return tuple(sorted(choices, key=lambda choice: choice.name))


def _is_active(tenant: Tenant | None) -> bool:
    return tenant is not None and tenant.status is TenantStatus.ACTIVE
