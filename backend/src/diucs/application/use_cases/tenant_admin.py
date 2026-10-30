"""The platform operator's tenant lifecycle: create, record the channels and references, verify the
directory, activate (TEN-028, DEC-503, DEC-136 item 10, audit F section 2).

Only the platform operator runs these (`Role.PLATFORM_OPERATOR`, a named person, DEC-134 item 4).
The operator has no data access: what a use case here writes in a tenant's scope is the tenant's own
structure and its audit chain, so the tenant sees what the operator did (audit F: the lifecycle
action is also an event about the tenant). The tenant is the scope the edge (or the provisioning
script) bound, and the actor must be of that tenant; a tenant id is never read from anywhere but the
bound scope, except by `CreateTenant`, whose id is the one it creates and must equal the bound one.

The registry (the platform's own record of its tenants) is written through `TenantRegistry`, in its
own transaction; the tenant's scope through a unit of work. The two cannot be one transaction, so
each use case is a short saga whose steps are idempotent, in the order that fails closed:

- `CreateTenant`: the registry record first (a tenant in `provisioning` can do nothing), then the
  scope. A creation that stopped between the two is finished by running it again.
- `ActivateTenant`: judged on what the registry and the tenant's scope say now, then one compare and
  set on the registry (epoch and status as read), then the audit entry and the daily jobs. A tenant
  that was activated but not seeded is seeded by `seed_recurring_work` (and at every start-up).
- The registry write that makes a number, a host or a directory the tenant's comes before the
  tenant-scope record that says so, so a value another tenant holds is refused before anything of
  the tenant's changes.

No secret is stored: a number names the reference of its auth token in the secret store (DEC-131
item 4), always the tenant's own. No patient data and no person is named in an audit snapshot.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from diucs.application.actor import Actor, require_actor_in_bound_tenant
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tenant_registry import TenantNumberRecord, TenantRegistry
from diucs.application.ports.outbound.tenants import (
    TenantDirectory,
    normalise_account_sid,
    normalise_directory_id,
    normalise_e164,
    normalise_host,
    twilio_token_ref,
)
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.provisioning import (
    OPERATOR_ROLE_MESSAGE,
    OPERATOR_UNNAMED_MESSAGE,
    TENANT_ADMIN_INVITE,
    ScopeProvisioner,
    activation_facts,
    extra_blockers,
    new_tenant,
    provision_scope,
    same_creation,
    seed_recurring_work,
)
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.application.use_cases.tenant_config import configuration_facts
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.tenant import (
    NumberStatus,
    OrganisationType,
    Tenant,
    TenantStatus,
    check_tenant_id,
)
from diucs.domain.model.tenant_records import (
    CHANNEL_PROVIDER,
    BindingStatus,
    ChannelKind,
    EntraBinding,
    TenantChannel,
)
from diucs.domain.rules.tenant_lifecycle import (
    ActivationFacts,
    activate_tenant,
    activation_blockers,
)
from diucs.domain.rules.tenant_settings import is_named_ref

AUDIT_CREATE: Final = "C"
AUDIT_UPDATE: Final = "U"

NO_TENANT: Final = "no tenant with this id"
NOT_PROVISIONING: Final = "the tenant is not in provisioning"
NOT_OPEN: Final = "the tenant is not open for this change"
MOVED: Final = "the tenant record changed since it was read"
NO_BINDING: Final = "no directory binding is waiting to be verified for this directory"
REFERENCE_MESSAGE: Final = "name at least one reference"

# A number or a reference is the operator's to record while the tenant is being provisioned, and
# while it is active (a second number, a changed reference). Not after it has left.
_OPEN_FOR_CHANGES: Final = frozenset({TenantStatus.PROVISIONING, TenantStatus.ACTIVE})

AreaDistrictsFor = Callable[[ScopeId], frozenset[str]]
"""The districts of a tenant's area (U28, `bootstrap/areas.py`): a tenant that registers services
needs one before it is activated."""


def check_operator(actor: Actor) -> str:
    """The reference of the platform operator acting. Another role, or an operator with no name, is
    refused; the refusals name neither."""
    if actor.role is not Role.PLATFORM_OPERATOR:
        raise NotAllowed(OPERATOR_ROLE_MESSAGE)
    if not is_named_ref(actor.practitioner_id):
        raise NotAllowed(OPERATOR_UNNAMED_MESSAGE)
    assert actor.practitioner_id is not None
    return actor.practitioner_id


def _bound_tenant_scope() -> ScopeId:
    scope = current_scope()
    if scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def _unit_scope(uow: UnitOfWork) -> ScopeId:
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


async def _audit(
    uow: UnitOfWork,
    clock: Clock,
    actor: Actor,
    use_case: str,
    action: str,
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
            at=clock.now(),
        )
    )


class _Operator:
    def __init__(
        self, tenants: TenantDirectory, uow_factory: UnitOfWorkFactory, clock: Clock
    ) -> None:
        self._tenants = tenants
        self._uow_factory = uow_factory
        self._clock = clock

    def _begin(self, actor: Actor) -> tuple[str, ScopeId]:
        """The operator, and the tenant scope bound: the actor is of that tenant (a wiring fault
        otherwise, never an access decision)."""
        operator = check_operator(actor)
        require_actor_in_bound_tenant(actor)
        return operator, _bound_tenant_scope()

    async def _tenant(self, scope: ScopeId, *, allowed: frozenset[TenantStatus]) -> Tenant:
        tenant = await self._tenants.get(scope.value)
        if tenant is None:
            raise NotFound(NO_TENANT)
        if tenant.status not in allowed:
            raise NotAllowed(NOT_OPEN)
        return tenant


# ---------------------------------------------------------------- CreateTenant


@dataclass(frozen=True, slots=True)
class CreateTenantCommand:
    """`tenant_id` is the id of the tenant to create, and must be the scope the call is bound to
    (the edge binds the scope the operator names; the use case reads no other)."""

    actor: Actor
    tenant_id: str
    display_name: str
    legal_name: str
    organisation_type: OrganisationType
    country_code: str = "GB"
    time_zone: str = "Europe/London"
    ods_code: str | None = None


@dataclass(frozen=True, slots=True)
class CreateTenantResult:
    tenant_id: str
    created: bool
    """False when the tenant already existed in provisioning with these fields and only its scope
    was finished."""


class CreateTenant(_Operator):
    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        provisioner: ScopeProvisioner,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._registry = registry
        self._provisioner = provisioner

    async def execute(self, command: CreateTenantCommand) -> CreateTenantResult:
        check_operator(command.actor)
        require_actor_in_bound_tenant(command.actor)
        scope = _bound_tenant_scope()
        if check_tenant_id(command.tenant_id) != scope.value:
            raise ValidationFailed("tenant_id", "must be the tenant this call is bound to")
        wanted = new_tenant(
            tenant_id=command.tenant_id,
            display_name=command.display_name,
            legal_name=command.legal_name,
            organisation_type=command.organisation_type,
            country_code=command.country_code,
            time_zone=command.time_zone,
            ods_code=command.ods_code,
            now=self._clock.now(),
        )
        existing = await self._tenants.get(wanted.id)
        created = existing is None
        if existing is None:
            await self._registry.create(wanted)
        elif not same_creation(existing, wanted):
            # Another tenant holds the id, or this one has moved on: nothing is written.
            raise Conflict("a tenant with this id already exists")
        await provision_scope(self._provisioner, self._uow_factory)
        async with self._uow_factory() as uow:
            await _audit(
                uow,
                self._clock,
                command.actor,
                "CreateTenant",
                AUDIT_CREATE,
                f"tenant-{wanted.id}",
                {
                    "organisationType": wanted.organisation_type.value,
                    "timeZone": wanted.time_zone,
                    "resumed": not created,
                },
            )
            await uow.commit()
        return CreateTenantResult(tenant_id=wanted.id, created=created)


# ---------------------------------------------------------------- numbers, host, references


@dataclass(frozen=True, slots=True)
class RecordNumberCommand:
    actor: Actor
    e164: str
    account_sid: str
    sender_label: str


class RecordTenantNumber(_Operator):
    """Record the tenant's text number: the registry node first (a number another tenant holds is a
    `Conflict` and nothing of the tenant's changes), then the tenant's own channel record, which the
    activation facts and the tenant's administrator read."""

    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._registry = registry

    async def execute(self, command: RecordNumberCommand) -> str:
        """Returns the id of the channel record."""
        _, scope = self._begin(command.actor)
        number = normalise_e164(command.e164)
        account = normalise_account_sid(command.account_sid)
        if number is None:
            raise ValidationFailed("e164", "must be a number in E.164 form")
        if account is None:
            raise ValidationFailed("account_sid", "must be a Twilio account SID")
        await self._tenant(scope, allowed=_OPEN_FOR_CHANGES)
        reference = twilio_token_ref(scope.value)
        record = TenantNumberRecord(number, account, reference)
        channel = TenantChannel(
            id=f"sms-{number[1:]}",
            kind=ChannelKind.SMS,
            provider=CHANNEL_PROVIDER[ChannelKind.SMS],
            status=NumberStatus.ACTIVE,
            sender_label=command.sender_label,
            account_sid=account,
            secret_ref=reference,
        )
        await self._registry.put_number(scope.value, record)
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            await uow.tenant_config.put_channel(channel)
            await _audit(
                uow,
                self._clock,
                command.actor,
                "RecordTenantNumber",
                AUDIT_UPDATE,
                f"channel-{channel.id}",
                {"kind": "sms", "status": channel.status.value},
            )
            await uow.commit()
        return channel.id


@dataclass(frozen=True, slots=True)
class MarkNumberTestedCommand:
    actor: Actor
    e164: str


class MarkNumberTested(_Operator):
    """Record that a test text was delivered from the tenant's number (an activation fact). The
    operator sends the text and reads the delivery; this records that it happened."""

    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._registry = registry

    async def execute(self, command: MarkNumberTestedCommand) -> None:
        _, scope = self._begin(command.actor)
        await self._tenant(scope, allowed=_OPEN_FOR_CHANGES)
        await self._registry.mark_number_tested(scope.value, command.e164, self._clock.now())
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            await _audit(
                uow,
                self._clock,
                command.actor,
                "MarkNumberTested",
                AUDIT_UPDATE,
                "number-test",
                {},
            )
            await uow.commit()


@dataclass(frozen=True, slots=True)
class SetHostCommand:
    actor: Actor
    host: str


class SetTenantHost(_Operator):
    """The tenant's one host: its capacity links and its sign-in are on it (DEC-134 item 3)."""

    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._registry = registry

    async def execute(self, command: SetHostCommand) -> None:
        _, scope = self._begin(command.actor)
        host = normalise_host(command.host)
        if host is None:
            raise ValidationFailed("host", "must be a host name")
        await self._tenant(scope, allowed=_OPEN_FOR_CHANGES)
        await self._registry.set_host(scope.value, host)
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            await _audit(uow, self._clock, command.actor, "SetTenantHost", AUDIT_UPDATE, "host", {})
            await uow.commit()


@dataclass(frozen=True, slots=True)
class RecordReferencesCommand:
    """The references the operator asserts: a data sharing agreement, a data protection impact
    assessment and a clinical safety case. An id for each document, never the document. The system
    records that they were asserted, not that they are true (DEC-133 item 2)."""

    actor: Actor
    dsa_ref: str | None = None
    dpia_ref: str | None = None
    dcb0160_ref: str | None = None


class RecordTenantReferences(_Operator):
    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._registry = registry

    async def execute(self, command: RecordReferencesCommand) -> tuple[str, ...]:
        """Returns the names of the references now recorded by this call."""
        _, scope = self._begin(command.actor)
        given = {
            name: value
            for name, value in (
                ("dsa_ref", command.dsa_ref),
                ("dpia_ref", command.dpia_ref),
                ("dcb0160_ref", command.dcb0160_ref),
            )
            if value is not None
        }
        if not given:
            raise ValidationFailed("references", REFERENCE_MESSAGE)
        tenant = await self._tenant(scope, allowed=_OPEN_FOR_CHANGES)
        # The record checks every reference (a short id, never free text).
        changed = dataclasses.replace(
            tenant,
            dsa_ref=tenant.dsa_ref if command.dsa_ref is None else command.dsa_ref,
            dpia_ref=tenant.dpia_ref if command.dpia_ref is None else command.dpia_ref,
            dcb0160_ref=(
                tenant.dcb0160_ref if command.dcb0160_ref is None else command.dcb0160_ref
            ),
        )
        if not await self._registry.save(
            changed, expected_epoch=tenant.epoch, expected_status=tenant.status
        ):
            raise Conflict(MOVED)
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            await _audit(
                uow,
                self._clock,
                command.actor,
                "RecordTenantReferences",
                AUDIT_UPDATE,
                "references",
                {"recorded": sorted(given)},
            )
            await uow.commit()
        return tuple(sorted(given))


# ---------------------------------------------------------------- the directory


@dataclass(frozen=True, slots=True)
class VerifyDirectoryCommand:
    actor: Actor
    directory_id: str


class VerifyEntraBinding(_Operator):
    """Verify the Entra directory the tenant's administrator bound (`BindEntraDirectory`, TEN-026):
    only a binding that is waiting (`pending`) can be verified, and the directory becomes the
    tenant's one in the registry (a directory another tenant holds is a `Conflict`), which is how
    sign-in finds its tenant (DEC-134 item 14). The operator checks the domain before they call
    this; the system records who verified it and when."""

    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._registry = registry

    async def execute(self, command: VerifyDirectoryCommand) -> None:
        operator, scope = self._begin(command.actor)
        directory = normalise_directory_id(command.directory_id)
        if directory is None:
            raise ValidationFailed("directory_id", "must be a directory id")
        await self._tenant(scope, allowed=_OPEN_FOR_CHANGES)
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            waiting = [
                binding
                for binding in await uow.tenant_config.bindings()
                if binding.directory_id == directory and binding.status is BindingStatus.PENDING
            ]
            if not waiting:
                raise NotFound(NO_BINDING)
        await self._registry.set_entra_directory(scope.value, directory)
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            await uow.tenant_config.put_binding(
                EntraBinding(
                    directory,
                    BindingStatus.VERIFIED,
                    verified_at=self._clock.now(),
                    verified_by_ref=operator,
                )
            )
            await _audit(
                uow,
                self._clock,
                command.actor,
                "VerifyEntraBinding",
                AUDIT_UPDATE,
                "directory-binding",
                {"status": BindingStatus.VERIFIED.value},
            )
            await uow.commit()


# ---------------------------------------------------------------- ActivateTenant


@dataclass(frozen=True, slots=True)
class ActivateTenantCommand:
    actor: Actor


@dataclass(frozen=True, slots=True)
class ActivateTenantResult:
    tenant_id: str
    epoch: int
    seeded: tuple[bool, bool]
    """Whether the daily criteria review run and the daily invariant check were scheduled now."""


@dataclass(frozen=True, slots=True)
class ActivationAssessment:
    tenant: Tenant
    facts: ActivationFacts
    blockers: tuple[str, ...]
    """What activation waits for, in the fixed words of the blockers (they name nothing about the
    tenant)."""


class ActivateTenant(_Operator):
    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        area_districts_for: AreaDistrictsFor,
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._registry = registry
        self._ids = ids
        self._area_districts_for = area_districts_for

    async def assess(self, actor: Actor) -> ActivationAssessment:
        """The tenant, the facts the activation rule reads and what is still missing, from the
        registry and the tenant's scope as they are now. Writes nothing: the operator's status."""
        _, scope = self._begin(actor)
        tenant = await self._tenants.get(scope.value)
        if tenant is None:
            raise NotFound(NO_TENANT)
        if tenant.status is not TenantStatus.PROVISIONING:
            raise NotAllowed(NOT_PROVISIONING)
        now = self._clock.now()
        host = await self._tenants.host_of(scope.value)
        numbers = await self._registry.numbers(scope.value)
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            repo = uow.tenant_config
            configuration = configuration_facts(
                await repo.current_version(),
                await repo.contacts(),
                await repo.channels(),
                await repo.retention(),
                await repo.bindings(),
                await repo.role_mappings(),
            )
            invited = (
                await uow.link_tokens.open_for_about(
                    TENANT_ADMIN_INVITE, f"tenant-admin-{scope.value}", now
                )
                is not None
            )
        facts = activation_facts(
            tenant,
            configuration,
            numbers,
            first_admin_invited=invited,
            area_districts_set=bool(self._area_districts_for(scope)),
        )
        return ActivationAssessment(
            tenant=tenant,
            facts=facts,
            blockers=(*activation_blockers(facts), *extra_blockers(host)),
        )

    async def execute(self, command: ActivateTenantCommand) -> ActivateTenantResult:
        assessment = await self.assess(command.actor)
        scope = _bound_tenant_scope()
        tenant, facts, blockers = assessment.tenant, assessment.facts, assessment.blockers
        now = self._clock.now()
        if blockers:
            raise NotAllowed("Activation is unavailable until: " + "; ".join(blockers))
        activated = activate_tenant(tenant, facts, now)
        if not await self._registry.save(
            activated, expected_epoch=tenant.epoch, expected_status=TenantStatus.PROVISIONING
        ):
            raise Conflict(MOVED)
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            await _audit(
                uow,
                self._clock,
                command.actor,
                "ActivateTenant",
                AUDIT_UPDATE,
                f"tenant-{scope.value}",
                {"from": tenant.status.value, "to": activated.status.value},
            )
            await uow.commit()
        seeded = await seed_recurring_work(self._uow_factory, self._ids, self._clock)
        return ActivateTenantResult(tenant_id=scope.value, epoch=activated.epoch, seeded=seeded)
