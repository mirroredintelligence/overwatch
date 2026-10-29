"""Tenant configuration use cases (TEN-026). Stub for the red commit."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Role
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    NumberStatus,
    RetentionClass,
    TenantConfig,
    TenantContact,
    TenantWording,
)
from diucs.domain.model.tenant_policy import SettingValue, TenantPolicy
from diucs.domain.model.tenant_records import (
    ChannelKind,
    EntraBinding,
    MappingStatus,
    RoleMapping,
    TenantChannel,
    TenantRetention,
)

CONFIGURATION_ROLES: Final[frozenset[Role]] = frozenset({Role.OWNER})  # stub


@dataclass(frozen=True, slots=True)
class ConfigDiff:
    changed_keys: tuple[str, ...]
    clinical_keys: tuple[str, ...]
    approvals_required: int


@dataclass(frozen=True, slots=True)
class DraftConfigCommand:
    actor: Actor
    based_on: int
    changes: Mapping[str, SettingValue] = field(default_factory=dict)
    removals: frozenset[str] = frozenset()
    reason_code: str = ""


@dataclass(frozen=True, slots=True)
class DraftConfigResult:
    version: int
    diff: ConfigDiff


@dataclass(frozen=True, slots=True)
class ApproveConfigCommand:
    actor: Actor
    version: int


@dataclass(frozen=True, slots=True)
class ApproveConfigResult:
    version: int
    status: ConfigStatus
    approvals: int
    approvals_required: int


@dataclass(frozen=True, slots=True)
class ConfigurationFacts:
    config_approved: bool
    wording_complete: bool
    contact_kinds: frozenset[ContactKind]
    retention_classes_set: frozenset[RetentionClass]
    role_mappings: int
    entra_binding_verified: bool
    active_sms_channels: int
    active_email_channels: int


def check_configuration_role(actor: Actor, roles: frozenset[Role]) -> str:
    raise NotImplementedError


def plan_draft(
    current: TenantConfig | None,
    command: DraftConfigCommand,
    *,
    version: int,
    now: datetime,
    author_ref: str,
) -> tuple[TenantConfig, ConfigDiff]:
    raise NotImplementedError


def apply_approval(
    draft: TenantConfig, current: TenantConfig | None, approver_ref: str, now: datetime
) -> TenantConfig:
    raise NotImplementedError


def supersede(config: TenantConfig) -> TenantConfig:
    raise NotImplementedError


def configuration_facts(
    current: TenantConfig | None,
    contacts: tuple[TenantContact, ...],
    channels: tuple[TenantChannel, ...],
    retention: tuple[TenantRetention, ...],
    bindings: tuple[EntraBinding, ...],
    mappings: tuple[RoleMapping, ...],
) -> ConfigurationFacts:
    raise NotImplementedError


class DraftTenantConfig:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: object,
        roles: frozenset[Role] = CONFIGURATION_ROLES,
    ) -> None:
        raise NotImplementedError


class ApproveTenantConfig:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: object,
        roles: frozenset[Role] = CONFIGURATION_ROLES,
    ) -> None:
        raise NotImplementedError


class ReadTenantConfig:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        raise NotImplementedError

    async def policy(self) -> TenantPolicy:
        raise NotImplementedError

    async def wording(self) -> TenantWording | None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class RecordContactCommand:
    actor: Actor
    kind: ContactKind
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class RecordChannelCommand:
    actor: Actor
    kind: ChannelKind
    sender_label: str
    account_sid: str | None = None
    secret_ref: str | None = None
    from_address: str | None = None
    from_display_name: str | None = None
    channel_id: str | None = None
    status: NumberStatus = NumberStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class SetRetentionCommand:
    actor: Actor
    rules: tuple[TenantRetention, ...] = ()
    use_defaults: bool = False


@dataclass(frozen=True, slots=True)
class BindDirectoryCommand:
    actor: Actor
    directory_id: str


@dataclass(frozen=True, slots=True)
class MapGroupCommand:
    actor: Actor
    group_object_id: str
    role: Role
    status: MappingStatus = MappingStatus.ACTIVE


def plan_channel(command: RecordChannelCommand, channel_id: str, tenant_id: str) -> TenantChannel:
    raise NotImplementedError


def plan_retention(command: SetRetentionCommand) -> tuple[TenantRetention, ...]:
    raise NotImplementedError


def plan_binding(existing: tuple[EntraBinding, ...], directory_id: str) -> tuple[EntraBinding, ...]:
    raise NotImplementedError


def plan_mapping(command: MapGroupCommand) -> RoleMapping:
    raise NotImplementedError


class _Stub:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError


class RecordTenantContact(_Stub):
    pass


class RecordTenantChannel(_Stub):
    pass


class SetTenantRetention(_Stub):
    pass


class BindEntraDirectory(_Stub):
    pass


class MapEntraGroup(_Stub):
    pass
