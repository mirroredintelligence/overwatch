"""Provisioning a tenant: what is pure, and the scope that every new tenant gets (TEN-028, DEC-503).

The pure part builds the new tenant record, the activation facts from what the configuration, the
registry and the invitation say, and the one blocker the domain's list does not hold (a host). The
effectful part is `provision_scope` (the tenant's audit chain head with its own genesis, and its
scope list) and `seed_recurring_work` (its daily jobs), each idempotent and run bound to the one
tenant, so that a half-finished provisioning is finished by running it again.

A new tenant is created in `provisioning` and cannot do anything until the operator activates it:
the activation blockers (`rules/tenant_lifecycle.py`) name what is missing, in fixed words that name
nothing about the tenant, and this module adds the host (without one a tenant's links cannot open).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tenant_registry import TenantNumberRecord
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantNotBound, current_scope
from diucs.application.use_cases.criteria_reviews import ensure_daily_schedule
from diucs.application.use_cases.tenant_config import ConfigurationFacts
from diucs.application.use_cases.tenant_invariants import ensure_invariant_schedule
from diucs.domain.model.tenant import (
    DEFAULT_TIME_ZONE,
    NumberStatus,
    OrganisationType,
    Tenant,
    TenantStatus,
)
from diucs.domain.rules.tenant_lifecycle import ActivationFacts

OPERATOR_ROLE_MESSAGE: Final = "only the platform operator runs a tenant's lifecycle"
OPERATOR_UNNAMED_MESSAGE: Final = "the operator must be named"

# The purpose of the link token that invites a tenant's first administrator. It is not the
# reporters' `invite`: the text-code flow looks the reporters' invitations up by phone, and must
# never find this one.
TENANT_ADMIN_INVITE: Final = "tenant-admin-invite"

# What the registry's references say. The three references the activation needs (DEC-136 item 10).
REFERENCE_NAMES: Final = ("dsa", "dpia", "dcb0160")

# The one blocker added to the domain's list: a tenant with no host cannot be sent a link, and the
# host of a request is what chooses its tenant (DEC-134 item 3).
MISSING_HOST: Final = "Host set"


class ScopeProvisioner(Protocol):
    async def ensure_audit_head(self) -> None:
        """Create the bound scope's audit chain head, with that scope's own genesis, when it is
        missing. Idempotent."""
        ...


def new_tenant(
    *,
    tenant_id: str,
    display_name: str,
    legal_name: str,
    organisation_type: OrganisationType,
    now: datetime,
    country_code: str = "GB",
    time_zone: str = DEFAULT_TIME_ZONE,
    ods_code: str | None = None,
    hash_key_version: int = 1,
) -> Tenant:
    """The record of a tenant that has just been created: `provisioning`, epoch 1, no times but its
    creation. Every field is checked by the record itself; the tenant's keys are its own
    (`hash_key_version` 1: only the default tenant keeps the platform's, DEC-350)."""
    return Tenant(
        id=tenant_id,
        display_name=display_name,
        legal_name=legal_name,
        organisation_type=organisation_type,
        country_code=country_code,
        time_zone=time_zone,
        status=TenantStatus.PROVISIONING,
        created_at=now,
        ods_code=ods_code,
        hash_key_version=hash_key_version,
    )


def same_creation(existing: Tenant, wanted: Tenant) -> bool:
    """True when `existing` is what creating `wanted` would have made, so that a creation that was
    interrupted can be run again: still in provisioning, with the same names, type, country, zone
    and ODS code. Anything else is a different tenant that holds the id."""
    return (
        existing.status is TenantStatus.PROVISIONING
        and existing.display_name == wanted.display_name
        and existing.legal_name == wanted.legal_name
        and existing.organisation_type is wanted.organisation_type
        and existing.country_code == wanted.country_code
        and existing.time_zone == wanted.time_zone
        and existing.ods_code == wanted.ods_code
    )


def count_tested_numbers(numbers: tuple[TenantNumberRecord, ...]) -> int:
    """How many numbers are active and have delivered a test text (an activation fact)."""
    return sum(1 for number in numbers if number.status is NumberStatus.ACTIVE and number.tested_at)


def references_recorded(tenant: Tenant) -> frozenset[str]:
    """The references the operator has recorded (an operator asserts them; the system does not prove
    them)."""
    found = {
        "dsa": tenant.dsa_ref,
        "dpia": tenant.dpia_ref,
        "dcb0160": tenant.dcb0160_ref,
    }
    return frozenset(name for name, value in found.items() if value is not None)


def activation_facts(
    tenant: Tenant,
    configuration: ConfigurationFacts,
    numbers: tuple[TenantNumberRecord, ...],
    *,
    first_admin_invited: bool,
    area_districts_set: bool,
) -> ActivationFacts:
    """What is known of a provisioning tenant, as the domain's activation rule reads it. Email is in
    use when the tenant has an email channel; its sender is verified when one is active (the
    operator makes it active once verified). A tenant is not a member of a network here: network
    membership has its own record and its own blocker when it is built (TEN-077)."""
    return ActivationFacts(
        config_approved=configuration.config_approved,
        time_zone=tenant.time_zone,
        active_numbers_tested=count_tested_numbers(numbers),
        email_in_use=configuration.active_email_channels > 0,
        email_sender_verified=configuration.active_email_channels > 0,
        first_admin_invited=first_admin_invited,
        entra_binding_verified=configuration.entra_binding_verified,
        role_mappings=configuration.role_mappings,
        contact_kinds=configuration.contact_kinds,
        retention_classes_set=configuration.retention_classes_set,
        references_recorded=references_recorded(tenant),
        wording_complete=configuration.wording_complete,
        registers_services=True,
        area_districts_set=area_districts_set,
        network_member=False,
        agreement_accepted=False,
    )


def extra_blockers(host: str | None) -> list[str]:
    """The blockers this module adds to the domain's: no host."""
    return [] if host else [MISSING_HOST]


@dataclass(frozen=True, slots=True)
class ProvisionedScope:
    audit_head: bool
    scope_list: bool


def _tenant_scope() -> str:
    scope = current_scope()
    if scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope.value


async def provision_scope(
    provisioner: ScopeProvisioner, uow_factory: UnitOfWorkFactory
) -> ProvisionedScope:
    """Give the bound tenant its own audit chain head (with its own genesis, so a chain cannot be
    spliced into another tenant's) and its scope list. Run bound to the tenant; idempotent, so a
    provisioning that stopped half way is finished by running it again. Nothing here is a tenant's
    data: it is the structure every scope needs before its first write."""
    _tenant_scope()
    await provisioner.ensure_audit_head()
    async with uow_factory() as uow:
        await uow.scope.ensure_list()
        await uow.commit()
    return ProvisionedScope(audit_head=True, scope_list=True)


async def seed_recurring_work(
    uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock
) -> tuple[bool, bool]:
    """Schedule the bound tenant's daily criteria review run (U31) and daily invariant check
    (TEN-031) when they are not scheduled. Each reports whether it wrote one. Idempotent: the work
    ids are derived from the tenant and the date, so a second run writes nothing. A process starting
    seeds every active tenant the same way (`Container.seed_daily_schedules`)."""
    _tenant_scope()
    return (
        await ensure_daily_schedule(uow_factory, ids, clock),
        await ensure_invariant_schedule(uow_factory, ids, clock),
    )
