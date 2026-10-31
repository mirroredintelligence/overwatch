"""Tenant configuration use cases (TEN-026, DEC-134 item 14, DEC-136 item 10, DEC-032 pattern).

A tenant's configuration is a series of immutable versions of the overrides of its defaults
(`TenantConfig`, TEN-006), plus its contacts, channels, retention rules, directory binding and role
mappings. The configuration read port (`ReadTenantConfig`) gives the rest of the application the
tenant's policy and wording: a use case or a template asks it, and a tenant with no version in force
gets the defaults, which equal the behaviour before tenancy.

Changing the configuration:

- `DraftTenantConfig` builds the next version from the one in force: the changes and removals are
  applied, every value is checked against the registry (bounds, allowed codes, the cross-field rules
  of the policy), a draft that changes nothing is refused, and the diff says which keys changed,
  which are clinical, and how many approvers the change needs.
- `ApproveTenantConfig` adds one approver. An operational change needs one approver. A change that
  touches a clinical setting needs two people who are not its author (the DEC-032 pattern). Only the
  latest version can be approved, so a draft written against an older version can never revert a
  newer one; the approval that completes the change makes it current and supersedes the version it
  replaces, in one unit of work.

Who may change it is a set of roles passed to the use case. The tenant administrator role does not
exist yet (TEN-018 adds it, DEC-134 item 4), so the default set is empty and every actor is
refused: the use cases fail closed until the composition root names the role.

Every change is one unit of work with its audit entry. The unit of work is bound to one tenant, and
a network scope is refused. Nothing here takes a tenant from the command. No secret is stored: a
channel names the reference of its secret in the secret store (DEC-131 item 4).
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tenants import check_secret_ref
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantNotBound
from diucs.domain.codes import Role
from diucs.domain.errors import (
    Conflict,
    InvalidTransition,
    NotAllowed,
    NotFound,
    ValidationFailed,
)
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    NumberStatus,
    RetentionClass,
    TenantConfig,
    TenantContact,
    TenantWording,
)
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, SettingValue, TenantPolicy
from diucs.domain.model.tenant_records import (
    CHANNEL_PROVIDER,
    BindingStatus,
    ChannelKind,
    EntraBinding,
    MappingStatus,
    RoleMapping,
    TenantChannel,
    TenantRetention,
    default_retention,
)
from diucs.domain.rules.tenant_lifecycle import transition_config
from diucs.domain.rules.tenant_settings import (
    CLINICAL_APPROVALS_REQUIRED,
    approvals_required,
    changed_keys,
    check_approvals,
    clinical_keys,
    is_named_ref,
    spec_for,
    validate_settings,
)

CREATE_ACTION: Final = "C"
UPDATE_ACTION: Final = "U"

# The roles that may change a tenant's configuration. Empty until the tenant administrator role
# exists (TEN-018): the composition root then passes `frozenset({Role.TENANT_ADMIN})`.
CONFIGURATION_ROLES: Final[frozenset[Role]] = frozenset()

ROLE_MESSAGE: Final = "this role may not change the tenant configuration"
UNNAMED_MESSAGE: Final = "the person making the change must be named"
APPROVER_UNNAMED_MESSAGE: Final = "the approver must be named"
ALREADY_APPROVED_MESSAGE: Final = "this person has already approved the change"
AUTHOR_MESSAGE: Final = "the author cannot approve a clinical change"
STALE_MESSAGE: Final = "the configuration changed since it was read"
NEWER_MESSAGE: Final = "a newer configuration version exists"
MOVED_MESSAGE: Final = "the configuration version was changed by someone else"

# ---------------------------------------------------------------- commands and results


@dataclass(frozen=True, slots=True)
class ConfigDiff:
    """What a draft changes: the keys, the clinical ones among them, and the approvers it needs."""

    changed_keys: tuple[str, ...]
    clinical_keys: tuple[str, ...]
    approvals_required: int


@dataclass(frozen=True, slots=True)
class DraftConfigCommand:
    """`based_on` is the version in force the caller read (0 when there is none): a change made
    against a version that is no longer in force is a `Conflict`, so a retry of a lost reply cannot
    make a second draft."""

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
class RecordContactCommand:
    actor: Actor
    kind: ContactKind
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class RecordChannelCommand:
    """A channel record. `channel_id` is given to change a channel and left out to make one."""

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
    """Either explicit rules or the proposed defaults, never both."""

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


@dataclass(frozen=True, slots=True)
class ConfigurationFacts:
    """What the configuration says about readiness; TEN-028 combines it with what only the registry
    knows (the numbers tested, the invitation, the references) into the activation facts."""

    config_approved: bool
    wording_complete: bool
    contact_kinds: frozenset[ContactKind]
    retention_classes_set: frozenset[RetentionClass]
    role_mappings: int
    entra_binding_verified: bool
    active_sms_channels: int
    active_email_channels: int


# ---------------------------------------------------------------- the rules (pure)


def check_configuration_role(actor: Actor, roles: frozenset[Role]) -> str:
    """The reference of the person acting, when the role may change the configuration and the person
    is named. The refusals name neither."""
    if actor.role not in roles:
        raise NotAllowed(ROLE_MESSAGE)
    if not is_named_ref(actor.practitioner_id):
        raise NotAllowed(UNNAMED_MESSAGE)
    assert actor.practitioner_id is not None
    return actor.practitioner_id


def plan_draft(
    current: TenantConfig | None,
    command: DraftConfigCommand,
    *,
    version: int,
    now: datetime,
    author_ref: str,
) -> tuple[TenantConfig, ConfigDiff]:
    """The draft the command asks for, from the version in force, and its diff. The values are the
    whole truth of the version (a snapshot of the overrides), so a draft is built from the version
    in force and applied to nothing else."""
    in_force = 0 if current is None else current.version
    if type(command.based_on) is not int or command.based_on != in_force:
        raise Conflict(STALE_MESSAGE)
    if not isinstance(command.changes, Mapping) or not isinstance(command.removals, frozenset):
        raise ValidationFailed("changes", "must be a mapping and a set of keys")
    base: dict[str, SettingValue] = {} if current is None else dict(current.values)
    if set(command.changes) & command.removals:
        raise ValidationFailed("removals", "a key cannot be changed and removed")
    for key in command.removals:
        spec_for(key)
        if key not in base:
            raise ValidationFailed("removals", "a key that is not set cannot be removed")
    merged = {key: value for key, value in base.items() if key not in command.removals}
    merged.update(command.changes)
    values = validate_settings(merged)
    if values == base:
        raise ValidationFailed("changes", "the draft changes nothing")
    diff = ConfigDiff(
        changed_keys=tuple(sorted(changed_keys(base, values))),
        clinical_keys=tuple(sorted(clinical_keys(changed_keys(base, values)))),
        approvals_required=approvals_required(base, values),
    )
    draft = TenantConfig(
        version=version,
        status=ConfigStatus.DRAFT,
        values=values,
        created_at=now,
        created_by_ref=author_ref,
        reason_code=command.reason_code,
    )
    return draft, diff


def apply_approval(
    draft: TenantConfig, current: TenantConfig | None, approver_ref: str, now: datetime
) -> TenantConfig:
    """The version after one more approver. It stays pending while it has too few approvers, and
    becomes current (effective `now`) with the approval that completes it. The approvers needed
    are judged against the version in force now, from the values alone; the author of a clinical
    change may not approve it, and nobody approves twice."""
    if draft.status not in (ConfigStatus.DRAFT, ConfigStatus.PENDING_APPROVAL):
        raise InvalidTransition(f"configuration cannot be approved from {draft.status.value}")
    if not is_named_ref(approver_ref):
        raise NotAllowed(APPROVER_UNNAMED_MESSAGE)
    if approver_ref in draft.approved_by_refs:
        raise NotAllowed(ALREADY_APPROVED_MESSAGE)
    in_force: Mapping[str, SettingValue] = {} if current is None else current.values
    required = approvals_required(in_force, draft.values)
    if required == CLINICAL_APPROVALS_REQUIRED and approver_ref == draft.created_by_ref:
        raise NotAllowed(AUTHOR_MESSAGE)
    approvers = (*draft.approved_by_refs, approver_ref)
    if len(approvers) < required:
        return dataclasses.replace(
            draft, status=ConfigStatus.PENDING_APPROVAL, approved_by_refs=approvers
        )
    check_approvals(in_force, draft.values, draft.created_by_ref, approvers)
    return dataclasses.replace(
        draft, status=ConfigStatus.CURRENT, approved_by_refs=approvers, effective_from=now
    )


def plan_moves(
    draft: TenantConfig, approved: TenantConfig
) -> list[tuple[TenantConfig, ConfigStatus]]:
    """The writes that take a version from `draft` to `approved`, as (version to write, status it
    must still be in). A change completed by its first approver passes through pending, because the
    table of moves has no direct step from draft to current."""
    if approved.status is ConfigStatus.CURRENT and draft.status is ConfigStatus.DRAFT:
        pending = dataclasses.replace(
            approved, status=ConfigStatus.PENDING_APPROVAL, effective_from=None
        )
        return [(pending, ConfigStatus.DRAFT), (approved, ConfigStatus.PENDING_APPROVAL)]
    return [(approved, draft.status)]


def supersede(config: TenantConfig) -> TenantConfig:
    """The version in force, replaced: the same version with the status `superseded`."""
    transition_config(config.status, ConfigStatus.SUPERSEDED)
    return dataclasses.replace(config, status=ConfigStatus.SUPERSEDED)


def configuration_facts(
    current: TenantConfig | None,
    contacts: tuple[TenantContact, ...],
    channels: tuple[TenantChannel, ...],
    retention: tuple[TenantRetention, ...],
    bindings: tuple[EntraBinding, ...],
    mappings: tuple[RoleMapping, ...],
) -> ConfigurationFacts:
    return ConfigurationFacts(
        config_approved=current is not None,
        wording_complete=current is not None and current.wording is not None,
        contact_kinds=frozenset(contact.kind for contact in contacts),
        retention_classes_set=frozenset(rule.data_class for rule in retention),
        role_mappings=sum(1 for mapping in mappings if mapping.status is MappingStatus.ACTIVE),
        entra_binding_verified=any(b.status is BindingStatus.VERIFIED for b in bindings),
        active_sms_channels=_active(channels, ChannelKind.SMS),
        active_email_channels=_active(channels, ChannelKind.EMAIL),
    )


def _active(channels: tuple[TenantChannel, ...], kind: ChannelKind) -> int:
    return sum(1 for c in channels if c.kind is kind and c.status is NumberStatus.ACTIVE)


def plan_channel(command: RecordChannelCommand, channel_id: str, tenant_id: str) -> TenantChannel:
    """The channel the command describes. A secret reference must be this tenant's own, so a
    channel can never point at another tenant's token (DEC-131 item 4)."""
    if type(command.kind) is not ChannelKind:
        raise ValidationFailed("kind", "has the wrong type")
    secret_ref = command.secret_ref
    if secret_ref is not None:
        secret_ref = check_secret_ref(secret_ref, tenant_id)
    return TenantChannel(
        id=channel_id,
        kind=command.kind,
        provider=CHANNEL_PROVIDER[command.kind],
        status=command.status,
        sender_label=command.sender_label,
        account_sid=command.account_sid,
        secret_ref=secret_ref,
        from_address=command.from_address,
        from_display_name=command.from_display_name,
    )


def plan_retention(command: SetRetentionCommand) -> tuple[TenantRetention, ...]:
    """The rules to store: the defaults, or the explicit rules (a tuple of rules, one per class)."""
    if type(command.use_defaults) is not bool:
        raise ValidationFailed("use_defaults", "has the wrong type")
    if command.use_defaults:
        if command.rules:
            raise ValidationFailed("rules", "name the defaults or the rules, not both")
        return default_retention()
    rules = command.rules
    if type(rules) is not tuple or not rules:
        raise ValidationFailed("rules", "name at least one rule")
    if any(type(rule) is not TenantRetention for rule in rules):
        raise ValidationFailed("rules", "each rule must be a retention rule")
    classes = [rule.data_class for rule in rules]
    if len(set(classes)) != len(classes):
        raise ValidationFailed("rules", "a data class has one rule")
    return rules


def plan_binding(existing: tuple[EntraBinding, ...], directory_id: str) -> tuple[EntraBinding, ...]:
    """The bindings to write to bind `directory_id`: nothing when it is already bound (pending or
    verified), otherwise the binding in force is revoked and the directory is bound as pending
    (the platform operator verifies it, TEN-043)."""
    target = EntraBinding(directory_id, BindingStatus.PENDING)
    if any(
        binding.directory_id == directory_id and binding.status is not BindingStatus.REVOKED
        for binding in existing
    ):
        return ()
    revoked = tuple(
        EntraBinding(binding.directory_id, BindingStatus.REVOKED)
        for binding in existing
        if binding.status is not BindingStatus.REVOKED
    )
    return (*revoked, target)


def plan_mapping(command: MapGroupCommand) -> RoleMapping:
    return RoleMapping(command.group_object_id, command.role, command.status)


# ---------------------------------------------------------------- the use cases


def _tenant_of(uow: UnitOfWork) -> str:
    """The tenant the unit of work is bound to. A network scope, or none, is refused."""
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope.value


class _Configurer:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, roles: frozenset[Role]
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._roles = roles

    async def _audit(
        self,
        uow: UnitOfWork,
        action: str,
        use_case: str,
        actor: Actor,
        entity: str,
        snapshot: dict[str, object],
    ) -> None:
        await uow.audit.append(
            AuditEntry(
                action=action,
                use_case=use_case,
                actor=actor,
                entity_ids=(entity,),
                snapshot=snapshot,
                at=self._clock.now(),
            )
        )


class DraftTenantConfig(_Configurer):
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        roles: frozenset[Role] = CONFIGURATION_ROLES,
    ) -> None:
        super().__init__(uow_factory, clock, roles)

    async def execute(self, command: DraftConfigCommand) -> DraftConfigResult:
        author = check_configuration_role(command.actor, self._roles)
        async with self._uow_factory() as uow:
            _tenant_of(uow)
            repo = uow.tenant_config
            current = await repo.current_version()
            latest = await repo.latest_version_number()
            draft, diff = plan_draft(
                current,
                command,
                version=latest + 1,
                now=self._clock.now(),
                author_ref=author,
            )
            await repo.add_version(draft)
            await self._audit(
                uow,
                CREATE_ACTION,
                "DraftTenantConfig",
                command.actor,
                f"config-{draft.version}",
                {
                    "version": draft.version,
                    "changedKeys": list(diff.changed_keys),
                    "clinicalKeys": list(diff.clinical_keys),
                    "approvalsRequired": diff.approvals_required,
                    "reasonCode": draft.reason_code,
                },
            )
            await uow.commit()
        return DraftConfigResult(draft.version, diff)


class ApproveTenantConfig(_Configurer):
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        roles: frozenset[Role] = CONFIGURATION_ROLES,
    ) -> None:
        super().__init__(uow_factory, clock, roles)

    async def execute(self, command: ApproveConfigCommand) -> ApproveConfigResult:
        approver = check_configuration_role(command.actor, self._roles)
        async with self._uow_factory() as uow:
            _tenant_of(uow)
            repo = uow.tenant_config
            draft = await repo.get_version(command.version)
            if draft is None:
                raise NotFound("no such configuration version")
            if command.version != await repo.latest_version_number():
                raise Conflict(NEWER_MESSAGE)
            current = await repo.current_version()
            approved = apply_approval(draft, current, approver, self._clock.now())
            for version, expected in plan_moves(draft, approved):
                if not await repo.move_version(version, expected):
                    raise Conflict(MOVED_MESSAGE)
            if (
                approved.status is ConfigStatus.CURRENT
                and current is not None
                and not await repo.move_version(supersede(current), ConfigStatus.CURRENT)
            ):
                raise Conflict(MOVED_MESSAGE)
            required = approvals_required({} if current is None else current.values, draft.values)
            await self._audit(
                uow,
                UPDATE_ACTION,
                "ApproveTenantConfig",
                command.actor,
                f"config-{approved.version}",
                {
                    "version": approved.version,
                    "status": approved.status.value,
                    "approvals": len(approved.approved_by_refs),
                    "approvalsRequired": required,
                    "supersedes": None if current is None else current.version,
                },
            )
            await uow.commit()
        return ApproveConfigResult(
            version=approved.version,
            status=approved.status,
            approvals=len(approved.approved_by_refs),
            approvals_required=required,
        )


class RecordTenantContact(_Configurer):
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        roles: frozenset[Role] = CONFIGURATION_ROLES,
    ) -> None:
        super().__init__(uow_factory, clock, roles)

    async def execute(self, command: RecordContactCommand) -> None:
        check_configuration_role(command.actor, self._roles)
        contact = TenantContact(command.kind, command.label, command.value)
        async with self._uow_factory() as uow:
            _tenant_of(uow)
            await uow.tenant_config.put_contact(contact)
            await self._audit(
                uow,
                UPDATE_ACTION,
                "RecordTenantContact",
                command.actor,
                f"contact-{contact.kind.value}",
                {"kind": contact.kind.value},
            )
            await uow.commit()


class RecordTenantChannel(_Configurer):
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        roles: frozenset[Role] = CONFIGURATION_ROLES,
    ) -> None:
        super().__init__(uow_factory, clock, roles)
        self._ids = ids

    async def execute(self, command: RecordChannelCommand) -> str:
        """Store the channel and return its id."""
        check_configuration_role(command.actor, self._roles)
        async with self._uow_factory() as uow:
            tenant_id = _tenant_of(uow)
            channel_id = (
                command.channel_id if command.channel_id is not None else self._ids.new_id()
            )
            channel = plan_channel(command, channel_id, tenant_id)
            await uow.tenant_config.put_channel(channel)
            await self._audit(
                uow,
                UPDATE_ACTION if command.channel_id is not None else CREATE_ACTION,
                "RecordTenantChannel",
                command.actor,
                f"channel-{channel.id}",
                {
                    "kind": channel.kind.value,
                    "provider": channel.provider.value,
                    "status": channel.status.value,
                },
            )
            await uow.commit()
        return channel_id


class SetTenantRetention(_Configurer):
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        roles: frozenset[Role] = CONFIGURATION_ROLES,
    ) -> None:
        super().__init__(uow_factory, clock, roles)

    async def execute(self, command: SetRetentionCommand) -> int:
        """Store the rules and return how many were stored."""
        check_configuration_role(command.actor, self._roles)
        rules = plan_retention(command)
        async with self._uow_factory() as uow:
            _tenant_of(uow)
            for rule in rules:
                await uow.tenant_config.put_retention(rule)
            await self._audit(
                uow,
                UPDATE_ACTION,
                "SetTenantRetention",
                command.actor,
                "retention",
                {
                    "dataClasses": sorted(rule.data_class.value for rule in rules),
                    "defaults": command.use_defaults,
                },
            )
            await uow.commit()
        return len(rules)


class BindEntraDirectory(_Configurer):
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        roles: frozenset[Role] = CONFIGURATION_ROLES,
    ) -> None:
        super().__init__(uow_factory, clock, roles)

    async def execute(self, command: BindDirectoryCommand) -> None:
        check_configuration_role(command.actor, self._roles)
        async with self._uow_factory() as uow:
            _tenant_of(uow)
            planned = plan_binding(await uow.tenant_config.bindings(), command.directory_id)
            for binding in planned:
                await uow.tenant_config.put_binding(binding)
            if planned:
                await self._audit(
                    uow,
                    UPDATE_ACTION,
                    "BindEntraDirectory",
                    command.actor,
                    "directory-binding",
                    {"bound": planned[-1].status.value, "revoked": len(planned) - 1},
                )
            await uow.commit()


class MapEntraGroup(_Configurer):
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        roles: frozenset[Role] = CONFIGURATION_ROLES,
    ) -> None:
        super().__init__(uow_factory, clock, roles)

    async def execute(self, command: MapGroupCommand) -> None:
        check_configuration_role(command.actor, self._roles)
        mapping = plan_mapping(command)
        async with self._uow_factory() as uow:
            _tenant_of(uow)
            await uow.tenant_config.put_role_mapping(mapping)
            await self._audit(
                uow,
                UPDATE_ACTION,
                "MapEntraGroup",
                command.actor,
                "role-mapping",
                {"role": mapping.role.value, "status": mapping.status.value},
            )
            await uow.commit()


class ReadTenantConfig:
    """The configuration read port: the policy and wording of the tenant the unit of work is bound
    to, and its readiness facts. A tenant with no version in force has the default policy."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def policy(self) -> TenantPolicy:
        async with self._uow_factory() as uow:
            _tenant_of(uow)
            current = await uow.tenant_config.current_version()
        return DEFAULT_POLICY if current is None else current.policy

    async def wording(self) -> TenantWording | None:
        async with self._uow_factory() as uow:
            _tenant_of(uow)
            current = await uow.tenant_config.current_version()
        return None if current is None else current.wording

    async def contacts(self) -> tuple[TenantContact, ...]:
        async with self._uow_factory() as uow:
            _tenant_of(uow)
            return await uow.tenant_config.contacts()

    async def facts(self) -> ConfigurationFacts:
        async with self._uow_factory() as uow:
            _tenant_of(uow)
            repo = uow.tenant_config
            return configuration_facts(
                await repo.current_version(),
                await repo.contacts(),
                await repo.channels(),
                await repo.retention(),
                await repo.bindings(),
                await repo.role_mappings(),
            )
