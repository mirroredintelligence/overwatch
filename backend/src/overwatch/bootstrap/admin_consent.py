"""The admin-consent invitation, wired (DEC-1316).

Builds the operator's invite and read use cases and the public confirmation on the container, the
Graph check on an injected HTTP client, and the sender resolver that falls back to the platform's
Twilio. Nothing here holds a rule. Unconfigured (no staff app id): nothing is installed, and every
admin-consent route fails closed with a 500.
"""

import dataclasses
import logging
from typing import Any

import httpx

from overwatch.adapters.outbound.entra_graph.app_installation import GraphAppInstallationCheck
from overwatch.application.ports.outbound.admin_consent import AppInstallationCheck
from overwatch.application.ports.outbound.sender_resolver import SenderResolver
from overwatch.application.ports.outbound.tenants import normalise_directory_id
from overwatch.application.use_cases.admin_consent import (
    AdminConsentLinks,
    ConfirmAdminConsent,
    InviteAdminConsent,
    ReadAdminConsent,
)
from overwatch.bootstrap.container import Container
from overwatch.bootstrap.settings import Settings
from overwatch.bootstrap.tenant_senders import (
    PlatformEmailIdentity,
    TenantSenderResolver,
    smtp_relay_from,
    status_callback_url,
)

log = logging.getLogger(__name__)

RETURN_PATH = "/admin-consent/return"


def consent_links(settings: Settings) -> AdminConsentLinks | None:
    client_id = normalise_directory_id(settings.entra_staff_client_id)
    if client_id is None:
        return None
    return AdminConsentLinks(client_id, settings.base_url.rstrip("/") + RETURN_PATH)


def platform_email_identity(settings: Settings) -> PlatformEmailIdentity | None:
    if not settings.platform_twilio_account_sid:
        return None
    return PlatformEmailIdentity(settings.platform_twilio_account_sid, settings.platform_email_from)


def install_admin_consent(
    app: Any,
    container: Container,
    settings: Settings,
    http: httpx.AsyncClient,
    *,
    senders: SenderResolver | None = None,
    installation: AppInstallationCheck | None = None,
) -> None:
    """Set the admin-consent services on the app. `senders` and `installation` are injected by a
    test; production builds the tenant-first, platform-fallback resolver and the Graph check."""
    links = consent_links(settings)
    if links is None:
        log.warning("admin consent is not configured: no staff app registration is set")
        return
    resolver = senders or TenantSenderResolver(
        container.tenants,
        container.secrets,
        http,
        status_callback_url(settings),
        smtp_relay_from(settings),
        platform_email_identity(settings),
    )
    check = installation or GraphAppInstallationCheck(http, container.secrets, links.client_id)
    clock = container.clock
    app.state.platform_services = dataclasses.replace(
        app.state.platform_services,
        consent_invite=InviteAdminConsent(
            container.tenants,
            container.uow_factory,
            clock,
            container.ids,
            container.secrets,
            resolver,
            links,
        ),
        consent_read=ReadAdminConsent(container.uow_factory, clock),
    )
    app.state.admin_consent_confirm = ConfirmAdminConsent(
        container.tenants, container.uow_factory, clock, check
    )
