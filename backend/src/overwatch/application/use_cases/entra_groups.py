"""The Entra groups of an organisation, and who is in them (DEC-1317; admin consent step 2).

Two people use this, each with their own door:

- The PLATFORM OPERATOR, on a tenant whose admin consent is CONSENTED (DEC-1316):
  `ProvisionEntraGroups`
  creates the tenant's groups in the organisation's own directory, assigns each to our app role on
  the organisation's copy of our service principal, and maps each to its role in our graph;
  `AddInitialGroupMember` puts the first people in a group (found by address in that directory).
- The TENANT ADMINISTRATOR, on the Users and roles page: `ReadManagedGroups` lists the groups and
  who is in them, `ChangeGroupMember` adds or removes a person. Only groups whose names start with
  `<ods>_overwatch_` and which Overwatch mapped can be changed. The check is on the name the
  directory reports for a group id that is in our own role mappings; the client's text is never used
  as a name.

Membership is NOT stored here: the directory holds it. Our graph keeps only the group-to-role
mapping (`TenantRoleMapping`, written by the one existing write path `put_role_mapping`). An address
is never stored, audited or logged: an audit entry holds the group id, the actor and keyed hashes.

Graph calls are made outside any unit of work (no transaction is held open over the network). Then
one unit writes the mappings and the audit entries together. A re-run after a failure half way is
safe: groups are looked up by their fixed name before they are made, an assignment that exists is
left, a member already in is left.

A group deleted in the organisation's directory: the call that names it fails with `GroupMissing`
(the route answers a fixed, non-leaking 409), and the mapping is left as it is. The tenant
administrator's list shows such a group as missing instead of failing.
"""

import logging
from dataclasses import dataclass
from typing import Any, Final

from overwatch.application.actor import Actor, require_actor_in_bound_tenant
from overwatch.application.ports.outbound.admin_consent import (
    AdminConsentRepository,
    AppInstallationCheck,
)
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.entra_groups import (
    DirectoryMember,
    EntraGroupDirectory,
    GroupMissing,
)
from overwatch.application.ports.outbound.tenants import TenantDirectory
from overwatch.application.ports.outbound.tokens import LINK_TOKEN_SECRET, SecretStore
from overwatch.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from overwatch.application.tenancy import ScopeKind, TenantNotBound, current_scope
from overwatch.application.use_cases.tenant_admin import check_operator
from overwatch.application.use_cases.tenant_admin_views import check_administrator
from overwatch.domain.codes import Role
from overwatch.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from overwatch.domain.model.tenant import Tenant, TenantStatus
from overwatch.domain.model.tenant_records import (
    DIRECTORY_ID_PATTERN,
    MappingStatus,
    RoleMapping,
)
from overwatch.domain.rules.admin_consent import check_email, hash_email
from overwatch.domain.rules.entra_groups import (
    OPERATOR_GROUP_ROLES,
    OVERWATCH_MEMBER_APP_ROLE_ID,
    check_search_term,
    group_name,
    group_prefix,
    hash_user_ref,
    role_of_name,
)

log = logging.getLogger(__name__)

USE_CASE_PROVISION: Final = "ProvisionEntraGroups"
USE_CASE_FIRST_MEMBER: Final = "AddInitialGroupMember"
USE_CASE_ADD: Final = "AddEntraGroupMember"
USE_CASE_INVITE: Final = "InviteEntraGroupMember"
USE_CASE_REMOVE: Final = "RemoveEntraGroupMember"
AUDIT_CREATE: Final = "C"
AUDIT_UPDATE: Final = "U"
AUDIT_DELETE: Final = "D"

NO_TENANT: Final = "no tenant with this id"
NOT_OPEN: Final = "the tenant is not open for this change"
NOT_CONSENTED: Final = "the organisation's administrator has not given consent yet"
NO_PRINCIPAL: Final = "our app is not installed in the organisation's directory"
NOT_SET_UP: Final = "the organisation's groups have not been set up yet"
NOT_MANAGED: Final = "that group is not one you manage here"
NO_USER: Final = "no one in your directory has that address"
LAST_ADMIN: Final = "the last administrator cannot be removed"
GROUP_ROLE_CLASH: Final = "that group already gives another role"
MAX_ROLES: Final = 12
MAX_GROUPS: Final = 20


def _bound_tenant_id() -> str:
    scope = current_scope()
    if scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope.value


def _unit_tenant(uow: UnitOfWork) -> str:
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope.value


@dataclass(frozen=True, slots=True)
class Consent:
    """What a consented tenant gives the group work: its directory and our principal in it."""

    directory_id: str
    service_principal_id: str | None
    invite_id: str


async def _consent(consents: AdminConsentRepository) -> Consent:
    invite = await consents.consented()
    if invite is None:
        raise NotAllowed(NOT_CONSENTED)
    return Consent(invite.directory_id, invite.service_principal_id, invite.invite_id)


async def _open_tenant(tenants: TenantDirectory, tenant_id: str) -> Tenant:
    tenant = await tenants.get(tenant_id)
    if tenant is None:
        raise NotFound(NO_TENANT)
    if tenant.status not in (TenantStatus.PROVISIONING, TenantStatus.ACTIVE):
        raise NotAllowed(NOT_OPEN)
    return tenant


# ---------------------------------------------------------------- the operator: the groups


@dataclass(frozen=True, slots=True)
class ProvisionEntraGroupsCommand:
    actor: Actor
    roles: tuple[Role, ...] = ()
    """The roles to give a group besides the administrators' (which is always made)."""


@dataclass(frozen=True, slots=True)
class ProvisionedGroup:
    role: Role
    name: str
    group_id: str
    created: bool
    """True when this call made the group, False when it was found by its name."""
    assigned: bool
    """True when this call assigned the group to our app role, False when it already was."""


class ProvisionEntraGroups:
    def __init__(
        self,
        tenants: TenantDirectory,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        directory: EntraGroupDirectory,
        installation: AppInstallationCheck,
    ) -> None:
        self._tenants = tenants
        self._uow_factory = uow_factory
        self._clock = clock
        self._directory = directory
        self._installation = installation

    async def execute(self, command: ProvisionEntraGroupsCommand) -> tuple[ProvisionedGroup, ...]:
        operator = check_operator(command.actor)
        require_actor_in_bound_tenant(command.actor)
        tenant_id = _bound_tenant_id()
        roles = _requested_roles(command.roles)
        tenant = await _open_tenant(self._tenants, tenant_id)
        prefix = group_prefix(tenant.ods_code, tenant.id)
        async with self._uow_factory() as uow:
            consent = await _consent(uow.admin_consents)
        principal = await self._principal(consent)

        made: list[ProvisionedGroup] = []
        for role in (Role.TENANT_ADMIN, *roles):
            name = group_name(prefix, role)
            group_id = await self._directory.find_group(consent.directory_id, name)
            created = group_id is None
            if group_id is None:
                group_id = await self._directory.create_group(
                    consent.directory_id, name, f"Overwatch: {role.value}"
                )
            assigned = await self._directory.assign_app_role(
                consent.directory_id, principal, group_id, OVERWATCH_MEMBER_APP_ROLE_ID
            )
            made.append(ProvisionedGroup(role, name, group_id.lower(), created, assigned))

        now = self._clock.now()
        async with self._uow_factory() as uow:
            _unit_tenant(uow)
            held = {m.group_object_id.lower(): m for m in await uow.tenant_config.role_mappings()}
            for group in made:
                current = held.get(group.group_id)
                if current is not None and current.role is not group.role:
                    raise Conflict(GROUP_ROLE_CLASH)
            for group in made:
                current = held.get(group.group_id)
                if current is None or current.status is not MappingStatus.ACTIVE:
                    await uow.tenant_config.put_role_mapping(
                        RoleMapping(group.group_id, group.role, MappingStatus.ACTIVE)
                    )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_CREATE,
                    use_case=USE_CASE_PROVISION,
                    actor=command.actor,
                    entity_ids=tuple(group.group_id for group in made),
                    snapshot={
                        "operator": operator,
                        "groups": [
                            {
                                "role": g.role.value,
                                "created": g.created,
                                "assigned": g.assigned,
                            }
                            for g in made
                        ],
                    },
                    at=now,
                )
            )
            await uow.commit()
        return tuple(made)

    async def _principal(self, consent: Consent) -> str:
        """Our service principal in the organisation's directory: kept at consent, or read again
        for a consent given before it was kept."""
        if consent.service_principal_id is not None:
            return consent.service_principal_id
        found = await self._installation.check(consent.directory_id)
        if not found.installed or found.service_principal_id is None:
            raise NotAllowed(NO_PRINCIPAL)
        async with self._uow_factory() as uow:
            await uow.admin_consents.set_service_principal(
                consent.invite_id, found.service_principal_id
            )
            await uow.commit()
        return found.service_principal_id


def _requested_roles(roles: tuple[Role, ...]) -> tuple[Role, ...]:
    if type(roles) is not tuple or len(roles) > MAX_ROLES:
        raise ValidationFailed("roles", "give the roles as a short list")
    wanted: list[Role] = []
    for role in roles:
        if type(role) is not Role or role not in OPERATOR_GROUP_ROLES:
            raise ValidationFailed("roles", "that role does not have a group")
        if role not in wanted:
            wanted.append(role)
    return tuple(wanted)


# ---------------------------------------------------------------- the operator: the first members


@dataclass(frozen=True, slots=True)
class AddInitialMemberCommand:
    actor: Actor
    role: Role
    """Which group, by role: the administrators' or one the operator mapped. Never a group id."""
    email: str
    """The person's address in the organisation's directory. Used to find them; never kept."""


@dataclass(frozen=True, slots=True)
class MemberChange:
    group_id: str
    changed: bool


class AddInitialGroupMember:
    def __init__(
        self,
        tenants: TenantDirectory,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        directory: EntraGroupDirectory,
        secrets: SecretStore,
    ) -> None:
        self._tenants = tenants
        self._uow_factory = uow_factory
        self._clock = clock
        self._directory = directory
        self._secrets = secrets

    async def execute(self, command: AddInitialMemberCommand) -> MemberChange:
        operator = check_operator(command.actor)
        require_actor_in_bound_tenant(command.actor)
        tenant_id = _bound_tenant_id()
        email = check_email(command.email)
        tenant = await _open_tenant(self._tenants, tenant_id)
        prefix = group_prefix(tenant.ods_code, tenant.id)
        name = group_name(prefix, command.role)
        secret = self._secrets.get(LINK_TOKEN_SECRET)
        async with self._uow_factory() as uow:
            consent = await _consent(uow.admin_consents)
            mappings = await uow.tenant_config.role_mappings()
        group_id = await self._directory.find_group(consent.directory_id, name)
        if group_id is None or not _mapped(mappings, group_id, command.role):
            raise NotAllowed(NOT_SET_UP)
        user_id = await self._directory.find_user(consent.directory_id, email)
        if user_id is None:
            raise ValidationFailed("email", NO_USER)
        added = await self._directory.add_member(consent.directory_id, group_id, user_id)
        async with self._uow_factory() as uow:
            _unit_tenant(uow)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_UPDATE,
                    use_case=USE_CASE_FIRST_MEMBER,
                    actor=command.actor,
                    entity_ids=(group_id.lower(),),
                    snapshot={
                        "operator": operator,
                        "role": command.role.value,
                        "emailHash": hash_email(email, secret),
                        "userRefHash": hash_user_ref(user_id, secret),
                        "added": added,
                    },
                    at=self._clock.now(),
                )
            )
            await uow.commit()
        return MemberChange(group_id.lower(), added)


def _mapped(mappings: tuple[RoleMapping, ...], group_id: str, role: Role) -> bool:
    return any(
        m.group_object_id.lower() == group_id.lower()
        and m.role is role
        and m.status is MappingStatus.ACTIVE
        for m in mappings
    )


# ---------------------------------------------------------------- the tenant administrator


@dataclass(frozen=True, slots=True)
class ManagedGroup:
    group_id: str
    name: str | None
    """None when the group is missing from the directory."""
    role: Role
    missing: bool
    members: tuple[DirectoryMember, ...]


@dataclass(frozen=True, slots=True)
class ManagedGroups:
    set_up: bool
    """False when the organisation's consent or groups are not there yet."""
    groups: tuple[ManagedGroup, ...]


class _Managed:
    """The groups the tenant administrator may change: the active mappings of the tenant whose
    group the DIRECTORY names `<ods>_overwatch_<that role's slug>`. Everything about a group comes
    from our mappings and the directory's own name for it; nothing from the request but the id,
    which is only looked up among the mappings."""

    def __init__(
        self,
        tenants: TenantDirectory,
        uow_factory: UnitOfWorkFactory,
        directory: EntraGroupDirectory,
    ) -> None:
        self._tenants = tenants
        self._uow_factory = uow_factory
        self._directory = directory

    async def _context(self) -> tuple[str, str, tuple[RoleMapping, ...], str | None]:
        """(tenant id, prefix, active mappings, directory id or None when there is no consent)."""
        tenant_id = _bound_tenant_id()
        tenant = await _open_tenant(self._tenants, tenant_id)
        prefix = group_prefix(tenant.ods_code, tenant.id)
        async with self._uow_factory() as uow:
            _unit_tenant(uow)
            invite = await uow.admin_consents.consented()
            mappings = tuple(
                m
                for m in await uow.tenant_config.role_mappings()
                if m.status is MappingStatus.ACTIVE
            )
        return tenant_id, prefix, mappings, None if invite is None else invite.directory_id

    async def _require(
        self, group_id: object, prefix: str, mappings: tuple[RoleMapping, ...], directory_id: str
    ) -> tuple[str, Role]:
        """The group id and role when it is one we may change, else NotAllowed. The name is the
        directory's, read now."""
        if type(group_id) is not str or DIRECTORY_ID_PATTERN.fullmatch(group_id.lower()) is None:
            raise NotAllowed(NOT_MANAGED)
        wanted = group_id.lower()
        mapping = next((m for m in mappings if m.group_object_id.lower() == wanted), None)
        if mapping is None:
            raise NotAllowed(NOT_MANAGED)
        name = await self._directory.group_name(directory_id, wanted)
        if role_of_name(name, prefix) is not mapping.role:
            raise NotAllowed(NOT_MANAGED)
        return wanted, mapping.role


class ReadManagedGroups(_Managed):
    async def execute(self, actor: Actor) -> ManagedGroups:
        check_administrator(actor)
        require_actor_in_bound_tenant(actor)
        _tenant, prefix, mappings, directory_id = await self._context()
        if directory_id is None:
            return ManagedGroups(False, ())
        groups: list[ManagedGroup] = []
        for mapping in mappings:
            if len(groups) >= MAX_GROUPS:
                break
            group_id = mapping.group_object_id.lower()
            try:
                name = await self._directory.group_name(directory_id, group_id)
            except GroupMissing:
                if mapping.role in OPERATOR_GROUP_ROLES or mapping.role is Role.TENANT_ADMIN:
                    groups.append(ManagedGroup(group_id, None, mapping.role, True, ()))
                continue
            if role_of_name(name, prefix) is not mapping.role:
                continue
            members = await self._directory.members(directory_id, group_id)
            groups.append(ManagedGroup(group_id, name, mapping.role, False, members))
        return ManagedGroups(True, tuple(groups))


class SearchDirectoryPeople(_Managed):
    """Look people up in the organisation's own directory by the start of a name or address, for
    the add-a-person box (DEC-1325). The administrator only, in the bound tenant's directory (the
    one its consent names) and nothing else; the term and the people found are not kept or
    logged."""

    async def execute(self, actor: Actor, term: object) -> tuple[DirectoryMember, ...]:
        check_administrator(actor)
        require_actor_in_bound_tenant(actor)
        wanted = check_search_term(term)
        _tenant, _prefix, _mappings, directory_id = await self._context()
        if directory_id is None:
            raise NotAllowed(NOT_SET_UP)
        return await self._directory.search_users(directory_id, wanted)


@dataclass(frozen=True, slots=True)
class ChangeMemberCommand:
    actor: Actor
    group_id: str
    email: str | None = None
    """For an add: the address, to find the person. Never kept."""
    user_id: str | None = None
    """For a remove: the member's directory object id, as the list showed it."""


@dataclass(frozen=True, slots=True)
class InviteResult:
    group_id: str
    changed: bool
    invited: bool
    """True when this call sent an invitation to someone from outside the directory."""


class ChangeGroupMember(_Managed):
    def __init__(
        self,
        tenants: TenantDirectory,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        directory: EntraGroupDirectory,
        secrets: SecretStore,
    ) -> None:
        super().__init__(tenants, uow_factory, directory)
        self._clock = clock
        self._secrets = secrets

    async def add(self, command: ChangeMemberCommand) -> MemberChange:
        check_administrator(command.actor)
        require_actor_in_bound_tenant(command.actor)
        email = check_email(command.email)
        _tenant, prefix, mappings, directory_id = await self._context()
        if directory_id is None:
            raise NotAllowed(NOT_SET_UP)
        group_id, role = await self._require(command.group_id, prefix, mappings, directory_id)
        user_id = await self._directory.find_user(directory_id, email)
        if user_id is None:
            raise ValidationFailed("email", NO_USER)
        added = await self._directory.add_member(directory_id, group_id, user_id)
        secret = self._secrets.get(LINK_TOKEN_SECRET)
        await self._audit(
            command.actor,
            USE_CASE_ADD,
            AUDIT_UPDATE,
            group_id,
            {
                "role": role.value,
                "emailHash": hash_email(email, secret),
                "userRefHash": hash_user_ref(user_id, secret),
                "added": added,
            },
        )
        return MemberChange(group_id, added)

    async def invite(self, command: ChangeMemberCommand) -> InviteResult:
        """Add a person by address as `add` does, and when no one in the directory has the address
        invite them from outside as a guest (the invitation email is sent by the directory) and add
        the guest. A guest already in the directory is found by address and added without a new
        invitation. `InviteNotPermitted` when the directory refuses the invitation."""
        check_administrator(command.actor)
        require_actor_in_bound_tenant(command.actor)
        email = check_email(command.email)
        _tenant, prefix, mappings, directory_id = await self._context()
        if directory_id is None:
            raise NotAllowed(NOT_SET_UP)
        group_id, role = await self._require(command.group_id, prefix, mappings, directory_id)
        user_id = await self._directory.find_user(directory_id, email)
        invited = user_id is None
        if user_id is None:
            user_id = await self._directory.invite_user(directory_id, email)
        added = await self._directory.add_member(directory_id, group_id, user_id)
        secret = self._secrets.get(LINK_TOKEN_SECRET)
        await self._audit(
            command.actor,
            USE_CASE_INVITE,
            AUDIT_UPDATE,
            group_id,
            {
                "role": role.value,
                "emailHash": hash_email(email, secret),
                "userRefHash": hash_user_ref(user_id, secret),
                "invited": invited,
                "added": added,
            },
        )
        return InviteResult(group_id, added, invited)

    async def remove(self, command: ChangeMemberCommand) -> MemberChange:
        check_administrator(command.actor)
        require_actor_in_bound_tenant(command.actor)
        user_id = command.user_id
        if type(user_id) is not str or DIRECTORY_ID_PATTERN.fullmatch(user_id.lower()) is None:
            raise ValidationFailed("user", "not a member id")
        user_id = user_id.lower()
        _tenant, prefix, mappings, directory_id = await self._context()
        if directory_id is None:
            raise NotAllowed(NOT_SET_UP)
        group_id, role = await self._require(command.group_id, prefix, mappings, directory_id)
        if role is Role.TENANT_ADMIN:
            current = await self._directory.members(directory_id, group_id)
            if {m.object_id.lower() for m in current} <= {user_id}:
                raise Conflict(LAST_ADMIN)
        removed = await self._directory.remove_member(directory_id, group_id, user_id)
        secret = self._secrets.get(LINK_TOKEN_SECRET)
        await self._audit(
            command.actor,
            USE_CASE_REMOVE,
            AUDIT_DELETE,
            group_id,
            {
                "role": role.value,
                "userRefHash": hash_user_ref(user_id, secret),
                "removed": removed,
            },
        )
        return MemberChange(group_id, removed)

    async def _audit(
        self, actor: Actor, use_case: str, action: str, group_id: str, snapshot: dict[str, Any]
    ) -> None:
        async with self._uow_factory() as uow:
            _unit_tenant(uow)
            await uow.audit.append(
                AuditEntry(
                    action=action,
                    use_case=use_case,
                    actor=actor,
                    entity_ids=(group_id,),
                    snapshot=snapshot,
                    at=self._clock.now(),
                )
            )
            await uow.commit()
