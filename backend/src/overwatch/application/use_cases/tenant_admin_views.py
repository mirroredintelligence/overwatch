"""What a tenant's administrator reads of their own tenant (TEN-075, TEN-026, TEN-065, TEN-076).

Reads only; every change is a use case of `tenant_config.py`. Everything is of the tenant the edge
bound from the administrator's token and of no other, and the answer holds no secret and no person:

- `overview`: the tenant's record and host, the configuration in force (its version, its overrides,
  its wording and its policy), the contacts, the channels (a channel is shown without the reference
  of its secret: that there is one, never which), the retention rules, the directory binding and the
  role mappings. The tenant's time zone is on the record (TEN-065);
- `versions`: every configuration version, newest first, each with the keys it changes against the
  version it replaced (the latest version in force below it, or none), which of them are clinical
  and how many people must approve it, so the screen can show a diff and who still has to approve;
- `access_log`: what the platform's own people did in this tenant: the operator's lifecycle steps
  and every step of a support ticket and access, from the tenant's own audit chain, with the
  actor's role and opaque reference and the entity and a small snapshot, newest first. The tenant
  reads it and cannot change it.

The role is checked first: only the tenant's administrator, a named person. A network scope or no
scope is refused.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantNotBound
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.tenant import (
    ConfigStatus,
    Tenant,
    TenantConfig,
    TenantContact,
)
from diucs.domain.model.tenant_records import (
    EntraBinding,
    RoleMapping,
    TenantChannel,
    TenantRetention,
)
from diucs.domain.rules.tenant_settings import (
    approvals_required,
    changed_keys,
    clinical_keys,
    is_named_ref,
)

ROLE_MESSAGE: Final = "only the tenant's administrator reads this"
NO_VERSION: Final = "no such configuration version"
ACCESS_LOG_DAYS: Final = 90
ACCESS_LOG_MAX_DAYS: Final = 400
ACCESS_LOG_LIMIT: Final = 200

# The use cases whose entries are the platform's people acting in a tenant: the operator's
# lifecycle (`tenant_admin.py`, `tenant_suspend.py`, `tenant_offboarding.py`, `tenant_access.py`)
# and the support guard and its tickets (`cross_tenant_guard.py`).
OPERATOR_USE_CASES: Final = frozenset(
    {
        "CreateTenant",
        "RecordTenantNumber",
        "MarkNumberTested",
        "SetTenantHost",
        "RecordTenantReferences",
        "VerifyEntraBinding",
        "ActivateTenant",
        "InviteTenantAdmin",
        "SuspendTenant",
        "ResumeTenant",
        "StartTenantOffboarding",
        "OpenCrossTenantAccess",
        "UseCrossTenantAccess",
        "EndCrossTenantAccess",
        "RevokeCrossTenantAccess",
        "SupportAccessTicket",
    }
)
PLATFORM_ROLES: Final = frozenset({Role.PLATFORM_OPERATOR, Role.SUPPORT})


@dataclass(frozen=True, slots=True)
class TenantOverview:
    tenant: Tenant
    host: str | None
    config: TenantConfig | None
    contacts: tuple[TenantContact, ...]
    channels: tuple[TenantChannel, ...]
    retention: tuple[TenantRetention, ...]
    bindings: tuple[EntraBinding, ...]
    mappings: tuple[RoleMapping, ...]


@dataclass(frozen=True, slots=True)
class ConfigVersionView:
    config: TenantConfig
    changed_keys: tuple[str, ...]
    clinical_keys: tuple[str, ...]
    approvals_required: int
    replaces: int | None
    """The version in force that this one is judged against, or None for the first."""


@dataclass(frozen=True, slots=True)
class AccessLogEntry:
    at: datetime
    use_case: str
    action: str
    role: Role
    actor_ref: str | None
    entity_ids: tuple[str, ...]
    snapshot: dict[str, Any] | None


def _unit_tenant(uow: UnitOfWork) -> str:
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope.value


def check_administrator(actor: Actor) -> None:
    if actor.role is not Role.TENANT_ADMIN or not is_named_ref(actor.practitioner_id):
        raise NotAllowed(ROLE_MESSAGE)


class ReadTenantAdmin:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, tenants: TenantDirectory, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._tenants = tenants
        self._clock = clock

    async def overview(self, actor: Actor) -> TenantOverview:
        check_administrator(actor)
        async with self._uow_factory() as uow:
            tenant_id = _unit_tenant(uow)
            repo = uow.tenant_config
            current = await repo.current_version()
            contacts = await repo.contacts()
            channels = await repo.channels()
            retention = await repo.retention()
            bindings = await repo.bindings()
            mappings = await repo.role_mappings()
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise NotFound("no tenant")
        return TenantOverview(
            tenant=tenant,
            host=await self._tenants.host_of(tenant_id),
            config=current,
            contacts=contacts,
            channels=channels,
            retention=retention,
            bindings=bindings,
            mappings=mappings,
        )

    async def versions(self, actor: Actor) -> list[ConfigVersionView]:
        check_administrator(actor)
        async with self._uow_factory() as uow:
            _unit_tenant(uow)
            repo = uow.tenant_config
            latest = await repo.latest_version_number()
            found: list[TenantConfig] = []
            for number in range(1, latest + 1):
                version = await repo.get_version(number)
                if version is not None:
                    found.append(version)
        return [_view(version, found) for version in reversed(found)]

    async def version(self, actor: Actor, number: int) -> ConfigVersionView:
        for view in await self.versions(actor):
            if view.config.version == number:
                return view
        raise NotFound(NO_VERSION)

    async def access_log(self, actor: Actor, days: int = ACCESS_LOG_DAYS) -> list[AccessLogEntry]:
        check_administrator(actor)
        if type(days) is not int or not 1 <= days <= ACCESS_LOG_MAX_DAYS:
            raise ValidationFailed("days", f"must be from 1 to {ACCESS_LOG_MAX_DAYS}")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            _unit_tenant(uow)
            records = await uow.audit.records_between(
                now - timedelta(days=days), now, OPERATOR_USE_CASES
            )
        entries = [
            AccessLogEntry(
                at=record.entry.at,
                use_case=record.entry.use_case,
                action=record.entry.action,
                role=record.entry.actor.role,
                actor_ref=record.entry.actor.practitioner_id,
                entity_ids=record.entry.entity_ids,
                snapshot=record.entry.snapshot,
            )
            for record in records
            if record.entry.actor.role in PLATFORM_ROLES
        ]
        return list(reversed(entries))[:ACCESS_LOG_LIMIT]


def _view(version: TenantConfig, every: list[TenantConfig]) -> ConfigVersionView:
    """A version judged against the latest version in force that is older than it."""
    base = next(
        (
            other
            for other in reversed(every)
            if other.version < version.version
            and other.status in (ConfigStatus.CURRENT, ConfigStatus.SUPERSEDED)
        ),
        None,
    )
    before = {} if base is None else base.values
    changed = changed_keys(before, version.values)
    return ConfigVersionView(
        config=version,
        changed_keys=tuple(sorted(changed)),
        clinical_keys=tuple(sorted(clinical_keys(changed))),
        approvals_required=approvals_required(before, version.values),
        replaces=None if base is None else base.version,
    )
