"""The services of the platform's and the tenant administrator's routes, wired (TEN-075, TEN-084).

The composition root of `/platform` and `/tenant`: the operator's lifecycle use cases of
`bootstrap/provisioning.py` (the same ones the script runs), the ticket flow on the container's
cross-tenant guard and ticket store, and the tenant administrator's configuration use cases, built
on one container. It is in bootstrap, the one layer that may build them from adapters. Nothing here
holds a rule and nothing here binds a tenant.

A process that serves the REST app calls `install_platform_routes(app, container)` once, after
`create_app`: it sets `app.state.platform_services` and `app.state.tenant_admin_services`, and
passes the edge's `forget_tenant` to the lifecycle use cases that change a tenant's status, so a
suspension, a resume or an offboarding takes effect at the edge in this process at once (and
within the cache interval in every other).

The configuration use cases are built with the one role that may change a tenant's configuration,
the tenant's administrator (`CONFIGURATION_ROLES` is empty until the composition root names it,
TEN-026).
"""

import dataclasses
from functools import partial
from typing import Any

import httpx

from overwatch.adapters.inbound.fhir_rest.auth import forget_tenant
from overwatch.application.platform_services import (
    PlatformRecorder,
    PlatformServices,
    SupportTicketServices,
    TenantAdminServices,
)
from overwatch.application.ports.outbound.sender_resolver import SenderResolver
from overwatch.application.use_cases.cross_tenant_tickets import (
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
from overwatch.application.use_cases.platform_tenants import ListPlatformTenants, ReadPlatformTenant
from overwatch.application.use_cases.tenant_admin import SendTestText, UseSharedLine
from overwatch.application.use_cases.tenant_admin_views import ReadTenantAdmin
from overwatch.application.use_cases.tenant_config import (
    ApproveTenantConfig,
    BindEntraDirectory,
    DraftTenantConfig,
    MapEntraGroup,
    RecordTenantChannel,
    RecordTenantContact,
    SetTenantRetention,
)
from overwatch.application.use_cases.tenant_suspend import TenantChanged
from overwatch.bootstrap.admin_consent import platform_email_identity
from overwatch.bootstrap.container import Container
from overwatch.bootstrap.lifecycle_operations import build_offboard
from overwatch.bootstrap.provisioning import build_provisioning
from overwatch.bootstrap.settings import Settings
from overwatch.bootstrap.tenant_senders import (
    TenantSenderResolver,
    platform_sms_identity,
    shared_line_check,
    smtp_relay_from,
    status_callback_url,
)
from overwatch.domain.codes import Role

CONFIGURATION_ROLES = frozenset({Role.TENANT_ADMIN})


def build_ticket_services(container: Container) -> SupportTicketServices:
    """The support-access ticket flow on the container's guard and ticket store."""
    tickets = container.support_tickets
    guard = container.cross_tenant_guard
    clock = container.clock
    return SupportTicketServices(
        request=RequestSupportTicket(tickets, guard, container.tenants, clock, container.ids),
        listing=ListSupportTickets(tickets, guard, clock),
        reading=ReadSupportTicket(tickets, guard, clock),
        cancelling=CancelSupportTicket(tickets, guard, clock),
        opening=OpenTicketAccess(tickets, guard, clock),
        using=UseTicketAccess(tickets, guard, clock),
        ending=EndTicketAccess(tickets, guard, clock),
        approving=ApproveSupportTicket(tickets, guard, clock),
        refusing=RefuseSupportTicket(tickets, guard, clock),
        revoking=RevokeSupportTicket(tickets, guard, clock),
    )


def build_platform_services(
    container: Container, on_changed: tuple[TenantChanged, ...] = ()
) -> tuple[PlatformServices, TenantAdminServices]:
    """The two sets of services of the routes, on one container."""
    provisioning = build_provisioning(container, on_changed)
    tickets = build_ticket_services(container)
    factory = container.uow_factory
    clock = container.clock
    platform = PlatformServices(
        tenants=ListPlatformTenants(container.tenant_registry),
        detail=ReadPlatformTenant(
            container.tenants,
            container.tenant_registry,
            factory,
            clock,
            provisioning.activate,
        ),
        create=provisioning.create,
        number=provisioning.number,
        retire=provisioning.retire,
        host=provisioning.host,
        references=provisioning.references,
        directory=provisioning.directory,
        activate=provisioning.activate,
        suspend=provisioning.suspend,
        resume=provisioning.resume,
        offboard=build_offboard(container, on_changed),
        recorder=PlatformRecorder(container.platform_audit, clock),
        audit_reader=container.platform_audit,
        tickets=tickets,
    )
    tenant_admin = TenantAdminServices(
        reads=ReadTenantAdmin(factory, container.tenants, clock),
        draft=DraftTenantConfig(factory, clock, CONFIGURATION_ROLES),
        approve=ApproveTenantConfig(factory, clock, CONFIGURATION_ROLES),
        contact=RecordTenantContact(factory, clock, CONFIGURATION_ROLES),
        channel=RecordTenantChannel(factory, clock, container.ids, CONFIGURATION_ROLES),
        retention=SetTenantRetention(factory, clock, CONFIGURATION_ROLES),
        bind=BindEntraDirectory(factory, clock, CONFIGURATION_ROLES),
        map_group=MapEntraGroup(factory, clock, CONFIGURATION_ROLES),
        tickets=tickets,
    )
    return platform, tenant_admin


def install_platform_routes(app: Any, container: Container) -> None:
    """Set the services of `/platform` and `/tenant` on the app, with the edge told of a change of
    a tenant's status at once in this process."""
    platform, tenant_admin = build_platform_services(container, (partial(forget_tenant, app),))
    app.state.platform_services = platform
    app.state.tenant_admin_services = tenant_admin


def install_number_tools(
    app: Any,
    container: Container,
    settings: Settings,
    http: httpx.AsyncClient,
    *,
    senders: SenderResolver | None = None,
) -> None:
    """Set the two operator tools that need the settings and the text sender (DEC-1319): the
    platform's shared sending line, and sending a test text from a tenant's line. `senders` is
    injected by a test; production builds the tenant-first resolver with the platform's identity
    (account, shared number and the platform auth token) and the check that reads the tenant's own
    channels. Without a shared number configured the shared line is refused, never half set up."""
    identity = platform_sms_identity(settings)
    resolver = senders or TenantSenderResolver(
        container.tenants,
        container.secrets,
        http,
        status_callback_url(settings),
        smtp_relay_from(settings),
        platform_email_identity(settings),
        platform_sms=identity,
        shared_line=shared_line_check(container.uow_factory),
    )
    app.state.platform_services = dataclasses.replace(
        app.state.platform_services,
        shared_line=UseSharedLine(
            container.tenants,
            container.uow_factory,
            container.clock,
            available=identity is not None,
        ),
        test_text=SendTestText(
            container.tenants,
            container.tenant_registry,
            container.uow_factory,
            container.clock,
            container.ids,
            resolver,
        ),
    )
