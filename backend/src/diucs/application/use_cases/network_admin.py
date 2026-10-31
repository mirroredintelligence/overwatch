"""Network administration, part one: the recorder every governance use case shares, creating a
network, recording its agreement, and the administrator's reads (TEN-077, DEC-132 items 2 and 3,
DEC-136 items 3 and 10, DEC-541, DEC-543 item 7).

**Who.** The platform operator creates a network for an active owner organisation (it is a platform
lifecycle step, like creating a tenant, `tenant_admin.py`); the owner's `network-admin` runs the
sharing of the network (the agreement, members, listings, grants); a member's `tenant-admin` runs
the member's side. A role that may not do a thing is `NotAllowed`, before any read. A network that
is not the actor's own to administer, or does not exist, is the one `NotFound`, so a network id and
who owns it cannot be discovered.

**The registry decides, the records follow (a departure from the plan's wording, DEC-960).** The
registry is the one place two administrators can race, so its compare-and-set comes first: it
decides who won, and nothing is recorded for a write that lost. The records then follow in the two
scopes that did not write it: the acting tenant's own chain with the event on its outbox (the
tenant is the controller of what its administrators did, and the relay publishes it to
`network.events` under the acting tenant), and the network's chain, which has every governance
action of the network. They are two units of work, never nested, each guarded by a marker keyed by
the action (`GovernanceRecorder`), so a step that failed after the registry was written is finished
by the same command run again and nothing is recorded twice. Creating a network is the one saga
that starts elsewhere: the network's audit head comes before the registry record, so a network that
exists has a chain to write to (the gap DEC-543 item 7 recorded).

No audit snapshot holds the agreement's reference, a name, a person or a number: ids, versions and
codes only.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor, require_actor_in_bound_tenant, tenant_scope_of_unit
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.network import NetworkRegistry, RegisteredNetwork
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.projection import ProjectionEndReason, SourceStatus
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.unit_of_work import (
    NetworkUnitOfWorkFactory,
    UnitOfWorkFactory,
)
from diucs.application.provisioning import ScopeProvisioner
from diucs.application.tenancy import bind_network, current_tenant
from diucs.application.use_cases.tenant_admin import check_operator
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import AgreementRecorded, DomainEvent, NetworkCreated
from diucs.domain.model.network import (
    ACCOUNT_REF_PATTERN,
    Agreement,
    GrantScope,
    MembershipRole,
    MembershipStatus,
    Network,
    NetworkMembership,
    NetworkStatus,
    activate_network,
    check_network_id,
    is_agreement_behind,
    owner_membership,
)
from diucs.domain.model.network_settings import NetworkSettings
from diucs.domain.model.tenant import DEFAULT_TIME_ZONE, TenantStatus
from diucs.domain.model.tenant_records import DIRECTORY_ID_PATTERN, MappingStatus, RoleMapping
from diucs.domain.rules.tenant_settings import is_named_ref

AUDIT_CREATE: Final = "C"
AUDIT_UPDATE: Final = "U"
TENANT_MARKER: Final = "governance-tenant"
NETWORK_MARKER: Final = "governance-network"

NETWORK_NOT_FOUND: Final = "the network was not found"
OWNER_NOT_ACTIVE: Final = "the owner organisation was not found"
NOT_ACTIVE: Final = "the network is not active"
ROLE_REFUSED: Final = "this role cannot do this"
UNNAMED: Final = "the person must be named"
TAKEN: Final = "a network with this id already exists"
AGREEMENT_NOT_NEWER: Final = "the agreement version is not newer than the current one"
AGREEMENT_OTHER_REFERENCE: Final = "this version is already recorded with another reference"
GROUP_GIVES_ANOTHER_ROLE: Final = "this group already gives another role"


# ---------------------------------------------------------------- who is acting


def account_ref_of(actor: Actor) -> str:
    """The opaque reference to the person acting, as an approval and an ending record it: the
    token's subject of the tenant, which is a derived id and never a name. A person with no subject,
    or one the records would refuse, cannot act (a service account is not an approver)."""
    ref = actor.practitioner_id
    if not is_named_ref(ref) or ACCOUNT_REF_PATTERN.fullmatch(str(ref)) is None:
        raise NotAllowed(UNNAMED)
    return str(ref)


def require_role(actor: Actor, *roles: Role) -> None:
    """The role is checked before anything is read, so a refusal says nothing about any record."""
    if actor.role not in roles:
        raise NotAllowed(ROLE_REFUSED)


def require_owner_of(actor: Actor, registered: RegisteredNetwork | None) -> Network:
    """The network, when the actor's tenant owns it. Another tenant's network, and one that does not
    exist, are the same `NotFound`."""
    if registered is None or registered.network.owner_tenant_id != actor.tenant_id:
        raise NotFound(NETWORK_NOT_FOUND)
    return registered.network


def require_active(network: Network) -> None:
    if network.status is not NetworkStatus.ACTIVE:
        raise Conflict(NOT_ACTIVE)


# ---------------------------------------------------------------- who is a network administrator


async def owns_active_network(registry: NetworkRegistry, tenant_id: str) -> bool:
    """True when the tenant is the owner of an ACTIVE network (TEN-080, DEC-1260): it has an active
    row of role `owner` in a network whose own `owner_tenant_id` is this tenant and whose status is
    active. Both are checked, so a damaged row alone is not ownership. The registry is asked each
    time; no token and no cache says it."""
    for membership in await registry.memberships_of(tenant_id):
        if membership.role is not MembershipRole.OWNER or membership.status is not (
            MembershipStatus.ACTIVE
        ):
            continue
        found = await registry.get_network(membership.network_id)
        if (
            found is not None
            and found.network.owner_tenant_id == tenant_id
            and found.network.status is NetworkStatus.ACTIVE
        ):
            return True
    return False


class RegistryNetworkOwnership:
    """The token exchange's question (`NetworkOwnership`), answered from the registry."""

    def __init__(self, registry: NetworkRegistry) -> None:
        self._registry = registry

    async def owns_active_network(self, tenant_id: str) -> bool:
        return await owns_active_network(self._registry, tenant_id)


@dataclass(frozen=True, slots=True)
class MapNetworkAdminGroupCommand:
    actor: Actor
    group_object_id: str
    """A group of the owner's own directory (a GUID). It is never echoed, logged or audited."""


@dataclass(frozen=True, slots=True)
class MapNetworkAdminGroupResult:
    created: bool
    """False when the group already gave the role and nothing changed."""


class MapNetworkAdminGroup:
    """The platform operator names the owner's first network administrators: a group of the owner's
    own directory is mapped to `network-admin` (TEN-080, DEC-1260). It is how the first mapping is
    made, as the tenant administrator who could make it cannot sign in yet; later ones are the
    owner's tenant administrator's, through the ordinary role-mapping route. It runs for the one
    tenant it is bound to, which must own an active network (another tenant, a member and a tenant
    in no network are the one `NotFound`). A group that already gives another role is a `Conflict`:
    the role of a group is never changed under it. A repeat changes nothing."""

    def __init__(
        self, registry: NetworkRegistry, uow_factory: UnitOfWorkFactory, clock: Clock
    ) -> None:
        self._registry = registry
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: MapNetworkAdminGroupCommand) -> MapNetworkAdminGroupResult:
        actor = command.actor
        check_operator(actor)
        require_actor_in_bound_tenant(actor)
        tenant_id = current_tenant()
        group = command.group_object_id
        if type(group) is not str or DIRECTORY_ID_PATTERN.fullmatch(group.lower()) is None:
            raise ValidationFailed("group_object_id", "must be a directory group id")
        wanted = RoleMapping(group.lower(), Role.NETWORK_ADMIN, MappingStatus.ACTIVE)
        if not await owns_active_network(self._registry, tenant_id):
            raise NotFound(NETWORK_NOT_FOUND)
        async with self._uow_factory() as uow:
            tenant_scope_of_unit(uow.unit_scope, actor)
            held = next(
                (
                    mapping
                    for mapping in await uow.tenant_config.role_mappings()
                    if mapping.group_object_id.lower() == wanted.group_object_id
                ),
                None,
            )
            if held is not None and held.role is not Role.NETWORK_ADMIN:
                raise Conflict(GROUP_GIVES_ANOTHER_ROLE)
            if held is not None and held.status is MappingStatus.ACTIVE:
                return MapNetworkAdminGroupResult(created=False)
            await uow.tenant_config.put_role_mapping(wanted)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_UPDATE,
                    use_case="MapNetworkAdminGroup",
                    actor=actor,
                    entity_ids=("role-mapping",),
                    snapshot={"role": wanted.role.value, "status": wanted.status.value},
                    at=self._clock.now(),
                )
            )
            await uow.commit()
        return MapNetworkAdminGroupResult(created=True)


# ---------------------------------------------------------------- the recorder


@dataclass(frozen=True, slots=True)
class Record:
    """What one governance action leaves behind. `key` names the action (for example
    `ApproveGrant:<grant id>:grantor`): the same key is recorded once in each scope."""

    use_case: str
    key: str
    entity_ids: tuple[str, ...]
    snapshot: dict[str, object]
    events: tuple[DomainEvent, ...] = ()
    action: str = AUDIT_UPDATE


class GovernanceRecorder:
    """Writes the records of a governance action after the registry has: in the acting tenant's
    scope (its audit entry and the events on its outbox, one unit of work) and then in the
    network's (its audit entry, one unit of work). Each unit marks the key first, so a repeated
    command, or one that is finishing what stopped, records nothing twice."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        network_uow_factory: NetworkUnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._network_uow_factory = network_uow_factory
        self._ids = ids
        self._clock = clock

    async def write(self, actor: Actor, network_id: str, record: Record) -> None:
        now = self._clock.now()
        entry = AuditEntry(
            action=record.action,
            use_case=record.use_case,
            actor=actor,
            entity_ids=record.entity_ids,
            snapshot=dict(record.snapshot),
            at=now,
        )
        async with self._uow_factory() as uow:
            tenant_scope_of_unit(uow.unit_scope, actor)
            if await uow.processed.mark_if_new(record.key, TENANT_MARKER):
                await uow.audit.append(entry)
                for event in record.events:
                    await uow.outbox.add(
                        outbox_message_for(event, f"gov:{record.key}:{event.event_type}", now)
                    )
            await uow.commit()
        with bind_network(network_id):
            async with self._network_uow_factory() as network_uow:
                if await network_uow.processed.mark_if_new(record.key, NETWORK_MARKER):
                    await network_uow.audit.append(entry)
                await network_uow.commit()


# ---------------------------------------------------------------- create a network


@dataclass(frozen=True, slots=True)
class CreateNetworkCommand:
    actor: Actor
    network_id: str
    name: str
    agreement_reference: str
    agreement_version: int
    system_name: str
    pathway_name: str
    time_zone: str = DEFAULT_TIME_ZONE


@dataclass(frozen=True, slots=True)
class CreateNetworkResult:
    network_id: str
    created: bool
    """False when the network already existed as this command describes it and only what was
    missing was finished."""


def _same_network(existing: RegisteredNetwork, wanted: Network, settings: NetworkSettings) -> bool:
    held = existing.network
    return (
        held.id == wanted.id
        and held.name == wanted.name
        and held.owner_tenant_id == wanted.owner_tenant_id
        and held.agreement == wanted.agreement
        and existing.settings == settings
    )


class CreateNetwork:
    def __init__(
        self,
        registry: NetworkRegistry,
        tenants: TenantDirectory,
        provisioner: ScopeProvisioner,
        recorder: GovernanceRecorder,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._tenants = tenants
        self._provisioner = provisioner
        self._recorder = recorder
        self._ids = ids
        self._clock = clock

    async def execute(self, command: CreateNetworkCommand) -> CreateNetworkResult:
        actor = command.actor
        check_operator(actor)
        require_actor_in_bound_tenant(actor)
        owner_id = current_tenant()
        now = self._clock.now()
        # Every value is checked by its own record before anything is written.
        check_network_id(command.network_id, "network_id")
        settings = NetworkSettings(command.system_name, command.pathway_name, command.time_zone)
        agreement = Agreement(command.agreement_reference, command.agreement_version)
        draft = Network(
            id=command.network_id,
            name=command.name,
            owner_tenant_id=owner_id,
            status=NetworkStatus.DRAFT,
            agreement=None,
            created_at=now,
            closed_at=None,
        )
        network = activate_network(draft, agreement, now)
        owner = await self._tenants.get(owner_id)
        if owner is None or owner.status is not TenantStatus.ACTIVE:
            raise NotFound(OWNER_NOT_ACTIVE)

        # 1. the network's own chain, so that a network that exists has somewhere to write to
        with bind_network(network.id):
            await self._provisioner.ensure_audit_head()
        # 2. the registry record (a retry meets its own record; another network is a conflict)
        created = True
        try:
            await self._registry.create_network(network, settings)
        except Conflict:
            existing = await self._registry.get_network(network.id)
            if existing is None or not _same_network(existing, network, settings):
                raise Conflict(TAKEN) from None
            created = False
        # 3. the owner's own membership
        membership = owner_membership(network, f"mem-{network.id}-owner", now)
        try:
            await self._registry.create_membership(membership)
        except Conflict:
            if await self._registry.active_membership(network.id, owner_id) is None:
                raise
        # 4. the records in the owner's scope and the network's
        await self._recorder.write(
            actor,
            network.id,
            Record(
                use_case="CreateNetwork",
                key=f"CreateNetwork:{network.id}",
                entity_ids=(network.id,),
                snapshot={"agreement_version": agreement.version, "owner": owner_id},
                events=(NetworkCreated(network.id, owner_id, now),),
                action=AUDIT_CREATE,
            ),
        )
        return CreateNetworkResult(network.id, created)


# ---------------------------------------------------------------- the agreement


@dataclass(frozen=True, slots=True)
class RecordAgreementCommand:
    actor: Actor
    network_id: str
    reference: str
    version: int


class RecordAgreement:
    def __init__(
        self, registry: NetworkRegistry, recorder: GovernanceRecorder, clock: Clock
    ) -> None:
        self._registry = registry
        self._recorder = recorder
        self._clock = clock

    async def execute(self, command: RecordAgreementCommand) -> None:
        actor = command.actor
        require_role(actor, Role.NETWORK_ADMIN)
        require_actor_in_bound_tenant(actor)
        account_ref_of(actor)
        check_network_id(command.network_id)
        registered = await self._registry.get_network(command.network_id)
        network = require_owner_of(actor, registered)
        assert registered is not None
        require_active(network)
        agreement = Agreement(command.reference, command.version)  # a reference, never the content
        current = network.agreement
        if current is not None and agreement.version < current.version:
            raise Conflict(AGREEMENT_NOT_NEWER)
        if current is not None and agreement.version == current.version:
            if agreement.reference != current.reference:
                raise Conflict(AGREEMENT_OTHER_REFERENCE)
        else:
            await self._registry.save_network(
                replace(network, agreement=agreement),
                registered.settings,
                expected_status=NetworkStatus.ACTIVE,
            )
        now = self._clock.now()
        await self._recorder.write(
            actor,
            network.id,
            Record(
                use_case="RecordAgreement",
                key=f"RecordAgreement:{network.id}:{agreement.version}",
                entity_ids=(network.id,),
                snapshot={"agreement_version": agreement.version},
                events=(
                    AgreementRecorded(network.id, agreement.reference, agreement.version, now),
                ),
            ),
        )


# ---------------------------------------------------------------- the administrator's reads


@dataclass(frozen=True, slots=True)
class AdminNetworkView:
    """A network as one of its organisations' administrators sees it."""

    network_id: str
    name: str
    status: NetworkStatus
    is_owner: bool
    membership_id: str
    membership_status: MembershipStatus
    agreement_reference: str | None
    agreement_version: int | None
    accepted_agreement_version: int | None
    agreement_behind: bool
    system_name: str
    pathway_name: str
    time_zone: str


@dataclass(frozen=True, slots=True)
class AdminMemberView:
    """A member as the owner sees it: the membership's own id is the handle, and the name comes
    from the tenant directory. The member's tenant id is not in it."""

    membership_id: str
    organisation_name: str
    role: MembershipRole
    status: MembershipStatus
    invited_at: datetime
    joined_at: datetime | None
    left_at: datetime | None
    accepted_agreement_version: int | None
    agreement_behind: bool


@dataclass(frozen=True, slots=True)
class KindStatus:
    kind: GrantScope
    status: SourceStatus
    ended_at: datetime | None
    end_reason: ProjectionEndReason | None


@dataclass(frozen=True, slots=True)
class MemberProjectionStatus:
    membership_id: str
    organisation_name: str
    kinds: tuple[KindStatus, ...] = field(default_factory=tuple)


class QueryNetworkAdmin:
    def __init__(
        self,
        registry: NetworkRegistry,
        tenants: TenantDirectory,
        network_reader_factory: NetworkUnitOfWorkFactory,
    ) -> None:
        self._registry = registry
        self._tenants = tenants
        self._reader_factory = network_reader_factory

    async def networks(self, actor: Actor) -> Sequence[AdminNetworkView]:
        """The networks the actor's organisation belongs to or has been invited to, with its own
        membership: one row each, in the order the registry gives them."""
        require_role(actor, Role.NETWORK_ADMIN, Role.TENANT_ADMIN)
        views: list[AdminNetworkView] = []
        for row in await self._registry.memberships_of(actor.tenant_id):
            if row.status not in (MembershipStatus.ACTIVE, MembershipStatus.INVITED):
                continue
            registered = await self._registry.get_network(row.network_id)
            if registered is None:
                continue
            network, settings = registered.network, registered.settings
            agreement = network.agreement
            accepted = row.accepted_agreement
            views.append(
                AdminNetworkView(
                    network_id=network.id,
                    name=network.name,
                    status=network.status,
                    is_owner=row.role is MembershipRole.OWNER,
                    membership_id=row.id,
                    membership_status=row.status,
                    agreement_reference=None if agreement is None else agreement.reference,
                    agreement_version=None if agreement is None else agreement.version,
                    accepted_agreement_version=None if accepted is None else accepted.version,
                    agreement_behind=row.status is MembershipStatus.ACTIVE
                    and is_agreement_behind(network, row),
                    system_name=settings.system_name,
                    pathway_name=settings.pathway_name,
                    time_zone=settings.time_zone,
                )
            )
        return views

    async def members(self, actor: Actor, network_id: str) -> Sequence[AdminMemberView]:
        """Every row of the network, the owner's view (a closed row is history and stays)."""
        require_role(actor, Role.NETWORK_ADMIN)
        check_network_id(network_id)
        network = require_owner_of(actor, await self._registry.get_network(network_id))
        views: list[AdminMemberView] = []
        for row in await self._registry.memberships(network.id):
            member = await self._tenants.get(row.member_tenant_id)
            accepted = row.accepted_agreement
            views.append(
                AdminMemberView(
                    membership_id=row.id,
                    organisation_name="(unknown organisation)"
                    if member is None
                    else member.display_name,
                    role=row.role,
                    status=row.status,
                    invited_at=row.invited_at,
                    joined_at=row.joined_at,
                    left_at=row.left_at,
                    accepted_agreement_version=None if accepted is None else accepted.version,
                    agreement_behind=row.status is MembershipStatus.ACTIVE
                    and is_agreement_behind(network, row),
                )
            )
        return views

    async def projection_status(
        self, actor: Actor, network_id: str
    ) -> Sequence[MemberProjectionStatus]:
        """For each member, whether each kind of its projection is open or ended, and why: states
        and dates only, never a row. Read in a read-only unit of the network's scope."""
        require_role(actor, Role.NETWORK_ADMIN)
        check_network_id(network_id)
        network = require_owner_of(actor, await self._registry.get_network(network_id))
        memberships = {m.member_tenant_id: m for m in await self._registry.memberships(network.id)}
        with bind_network(network.id):
            async with self._reader_factory() as uow:
                if not uow.read_only:
                    raise ValidationFailed("unit", "must be read-only")
                sources = list(await uow.network_view.sources())
        grouped: dict[str, list[KindStatus]] = {}
        for source in sources:
            grouped.setdefault(source.source_tenant_id, []).append(
                KindStatus(source.kind, source.status, source.ended_at, source.end_reason)
            )
        result: list[MemberProjectionStatus] = []
        for tenant_id, kinds in sorted(grouped.items()):
            row = memberships.get(tenant_id)
            if row is None:
                continue  # a source of nobody the registry knows is not shown (reconciliation's)
            member = await self._tenants.get(tenant_id)
            result.append(
                MemberProjectionStatus(
                    membership_id=row.id,
                    organisation_name="(unknown organisation)"
                    if member is None
                    else member.display_name,
                    kinds=tuple(sorted(kinds, key=lambda k: k.kind.value)),
                )
            )
        return result


def membership_of(
    rows: Sequence[NetworkMembership], membership_id: str
) -> NetworkMembership | None:
    return next((row for row in rows if row.id == membership_id), None)
