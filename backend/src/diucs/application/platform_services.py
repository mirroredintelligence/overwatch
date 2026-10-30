"""The services of the platform's and the tenant administrator's routes (TEN-075).

The routes are inbound adapters and may not build outbound adapters, so the process that serves the
app builds the use cases (`bootstrap/platform_services.py`) and sets two values on the app, as it
sets the network services: `app.state.platform_services` (the operator and support routes,
`/platform`) and `app.state.tenant_admin_services` (the tenant administrator's routes, `/tenant`).
With none set a route fails closed with a 500 (a missing wiring is a configuration error, never an
empty answer).

`PlatformRecorder` writes the operator's lifecycle steps to the platform chain (the tenant's own
chain already holds them: `tenant_admin.py`, `tenant_suspend.py`, `tenant_offboarding.py`). A step
is recorded after it has been done, because the lifecycle use cases write in two places that cannot
share a transaction (the registry and the tenant's scope) and what they did cannot be undone by a
chain that is down. A platform chain that cannot be written does not hide the step (the tenant's
chain has it) and is never silent: the failure is logged by class and the caller is told, so the
route can say the step was done and not recorded (`recorded` is False).
"""

import logging
from dataclasses import dataclass
from typing import Any

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.platform_audit import (
    PlatformAudit,
    PlatformAuditEntry,
    PlatformAuditReader,
)
from diucs.application.use_cases.cross_tenant_tickets import (
    ApproveSupportTicket,
    CancelSupportTicket,
    EndTicketAccess,
    ListSupportTickets,
    OpenTicketAccess,
    ReadSupportTicket,
    RefuseSupportTicket,
    RequestSupportTicket,
    RevokeSupportTicket,
    UseTicketAccess,
)
from diucs.application.use_cases.platform_tenants import ListPlatformTenants, ReadPlatformTenant
from diucs.application.use_cases.tenant_access import InviteTenantAdmin
from diucs.application.use_cases.tenant_admin import (
    ActivateTenant,
    CreateTenant,
    MarkNumberTested,
    RecordTenantNumber,
    RecordTenantReferences,
    SetTenantHost,
    VerifyEntraBinding,
)
from diucs.application.use_cases.tenant_admin_views import ReadTenantAdmin
from diucs.application.use_cases.tenant_config import (
    ApproveTenantConfig,
    BindEntraDirectory,
    DraftTenantConfig,
    MapEntraGroup,
    RecordTenantChannel,
    RecordTenantContact,
    SetTenantRetention,
)
from diucs.application.use_cases.tenant_offboarding import StartTenantOffboarding
from diucs.application.use_cases.tenant_suspend import ResumeTenant, SuspendTenant

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SupportTicketServices:
    """The ticket flow's use cases, built once on one guard and one store."""

    request: RequestSupportTicket
    listing: ListSupportTickets
    reading: ReadSupportTicket
    cancelling: CancelSupportTicket
    opening: OpenTicketAccess
    using: UseTicketAccess
    ending: EndTicketAccess
    approving: ApproveSupportTicket
    refusing: RefuseSupportTicket
    revoking: RevokeSupportTicket


class PlatformRecorder:
    def __init__(self, audit: PlatformAudit, clock: Clock) -> None:
        self._audit = audit
        self._clock = clock

    async def record(
        self,
        action: str,
        principal_ref: str,
        tenant_id: str | None,
        snapshot: dict[str, Any] | None = None,
    ) -> bool:
        """Write one step to the platform chain. True when written; False when the chain could not
        be written (logged by class, never the entry)."""
        try:
            await self._audit.append(
                PlatformAuditEntry(
                    action=action,
                    principal_ref=principal_ref,
                    tenant_id=tenant_id,
                    access_id=None,
                    snapshot=snapshot,
                    at=self._clock.now(),
                )
            )
        except Exception as error:
            log.error("the platform audit chain could not be written: %s", type(error).__name__)
            return False
        return True


@dataclass(frozen=True, slots=True)
class PlatformServices:
    """What `/platform` runs: the operator's tenant lifecycle, the platform chain and the support
    person's side of the ticket flow."""

    tenants: ListPlatformTenants
    detail: ReadPlatformTenant
    create: CreateTenant
    number: RecordTenantNumber
    tested: MarkNumberTested
    host: SetTenantHost
    references: RecordTenantReferences
    directory: VerifyEntraBinding
    invite: InviteTenantAdmin
    activate: ActivateTenant
    suspend: SuspendTenant
    resume: ResumeTenant
    offboard: StartTenantOffboarding
    recorder: PlatformRecorder
    audit_reader: PlatformAuditReader
    tickets: SupportTicketServices


@dataclass(frozen=True, slots=True)
class TenantAdminServices:
    """What `/tenant` runs: the administrator's reads and changes of their own tenant, and their
    side of the ticket flow. The configuration use cases are built with the administrator's role."""

    reads: ReadTenantAdmin
    draft: DraftTenantConfig
    approve: ApproveTenantConfig
    contact: RecordTenantContact
    channel: RecordTenantChannel
    retention: SetTenantRetention
    bind: BindEntraDirectory
    map_group: MapEntraGroup
    tickets: SupportTicketServices
