"""The public profile of a tenant (TEN-040): the few display fields a page may show before anyone
has signed in. Read inside the tenant's own scope, from its record and its configuration.

What is public: the display name, the time zone and locale, the wording a page prints (system
name, referral system name, coordination team name) and the coordination phone, which is an
organisational role number. Nothing else of the record (id, legal name, status, epoch, ODS code,
references) and no other contact (the support email, the shift lead and the safety officer stay
inside). A tenant with no configuration in force has no wording and a page falls back to its own
words; a tenant with no coordination phone has none. Never a default invented here (H-T15).
"""

from dataclasses import dataclass
from typing import Final

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantNotBound
from diucs.domain.model.tenant import ContactKind, Tenant, TenantWording

# [ASSUMED] (audit D 8): NHS tenants share one locale; the time zone is the tenant's own.
DEFAULT_LOCALE: Final = "en-GB"


@dataclass(frozen=True, slots=True)
class PublicTenantProfile:
    display_name: str
    time_zone: str
    locale: str
    wording: TenantWording | None
    coordination_phone: str | None


class ReadPublicProfile:
    """The profile of a tenant the edge has resolved. The tenant is the unit of work's: a profile
    is never read for a tenant other than the one bound."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, tenant: Tenant) -> PublicTenantProfile:
        async with self._uow_factory() as uow:
            scope = uow.unit_scope
            if scope is None or scope.kind is not ScopeKind.TENANT or scope.value != tenant.id:
                raise TenantNotBound
            current = await uow.tenant_config.current_version()
            contacts = await uow.tenant_config.contacts()
        phone = next(
            (
                contact.value
                for contact in contacts
                if contact.kind is ContactKind.COORDINATION_PHONE
            ),
            None,
        )
        return PublicTenantProfile(
            display_name=tenant.display_name,
            time_zone=tenant.time_zone,
            locale=DEFAULT_LOCALE,
            wording=None if current is None else current.wording,
            coordination_phone=phone,
        )
