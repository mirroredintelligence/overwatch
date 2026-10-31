"""Invite a tenant's first administrator (TEN-028, DEC-503, audit F section 2.5).

The platform operator invites one person by mobile number: a link token of the purpose
`tenant-admin-invite` (hash only, tied to the tenant-keyed hash of that mobile, valid 48 hours), and
the text I2 queued, sealed, to be sent from the tenant's own number (DEC-131). The link is
`https://<the tenant's host>/i/<token>`. The text and the mobile are held as every invitation's are:
the Communication keeps the text with the link left out, the number is in the protected contact
store under the invitation's recipient key, and nothing but the keyed hash of the mobile is on a
node.

The first sign-in (the person verifies the mobile by text code and signs in through the tenant's
verified Entra directory, which consumes the invitation and gives the account the administrator
role) is the sign-in tasks' (TEN-043, W09); this task builds the invitation the activation rule
asks for (`first_admin_invited`). Nothing is sent here: the outbox relay and the tenant's sender do
that. The tenant must have its wording (the text names its system), and one invitation is open at a
time: a second is a `Conflict` until the first has expired or been used.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor, require_actor_in_bound_tenant
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PhoneHasher
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.provisioning import TENANT_ADMIN_INVITE
from diucs.application.sealed_send import queue_message
from diucs.application.tenancy import ScopeId
from diucs.application.tenant_settings import HostUrls
from diucs.application.use_cases.invite_reporter import (
    check_invite_mobile,
    invitation_link,
)
from diucs.application.use_cases.send_prompts import LinkTokenServiceFactory
from diucs.application.use_cases.setup_service_by_lead import international
from diucs.application.use_cases.tenant_admin import (
    NO_TENANT,
    NOT_OPEN,
    _bound_tenant_scope,
    _unit_scope,
    check_operator,
)
from diucs.domain.codes import Channel
from diucs.domain.errors import Conflict, NotAllowed, NotFound
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.tenant import TenantStatus
from diucs.domain.rules.registration import INVITATION_VALID_FOR

USE_CASE: Final = "InviteTenantAdmin"
AUDIT_ACTION: Final = "C"
NO_WORDING: Final = "the tenant's system name is not set: set the wording before inviting"
ALREADY_OPEN: Final = "an invitation to this tenant's administrator is already open"


def invitation_key(scope: ScopeId) -> str:
    """The key of the tenant's one administrator invitation: the link token's `about` and the
    recipient key of the protected contact. It names the tenant, never a person."""
    return f"tenant-admin-{scope.value}"


@dataclass(frozen=True, slots=True)
class InviteTenantAdminCommand:
    """The mobile is the person's: it is checked, hashed and stored in the protected contact store,
    and never echoed, logged or audited."""

    actor: Actor
    mobile: str


@dataclass(frozen=True, slots=True)
class InviteTenantAdminResult:
    communication_id: str
    expires_at: datetime


class InviteTenantAdmin:
    def __init__(
        self,
        tenants: TenantDirectory,
        uow_factory: UnitOfWorkFactory,
        link_tokens: LinkTokenServiceFactory,
        phone_hasher: PhoneHasher,
        sealer: ContentSealer,
        clock: Clock,
        ids: IdGenerator,
        host_urls: HostUrls,
    ) -> None:
        self._tenants = tenants
        self._uow_factory = uow_factory
        self._link_tokens = link_tokens
        self._hasher = phone_hasher
        self._sealer = sealer
        self._clock = clock
        self._ids = ids
        self._host_urls = host_urls

    async def execute(self, command: InviteTenantAdminCommand) -> InviteTenantAdminResult:
        check_operator(command.actor)
        require_actor_in_bound_tenant(command.actor)
        scope = _bound_tenant_scope()
        national = check_invite_mobile(command.mobile)
        phone_hash = self._hasher.hash(national)
        tenant = await self._tenants.get(scope.value)
        if tenant is None:
            raise NotFound(NO_TENANT)
        if tenant.status not in (TenantStatus.PROVISIONING, TenantStatus.ACTIVE):
            raise NotAllowed(NOT_OPEN)
        base_url = await self._host_urls.host_url(scope)
        now = self._clock.now()

        async with self._uow_factory() as uow:
            _unit_scope(uow)
            about = invitation_key(scope)
            if await uow.link_tokens.open_for_about(TENANT_ADMIN_INVITE, about, now) is not None:
                raise Conflict(ALREADY_OPEN)
            config = await uow.tenant_config.current_version()
            wording = None if config is None else config.wording
            if wording is None:
                raise NotAllowed(NO_WORDING)
            expires_at = now + INVITATION_VALID_FOR
            token = await self._link_tokens(uow.link_tokens).issue(
                TENANT_ADMIN_INVITE, about, phone_hash, expires_at
            )
            await uow.contacts.put_phone(about, international(national))
            link = invitation_link(base_url, token)
            communication_id = await queue_message(
                uow,
                self._ids,
                self._sealer,
                scope=scope,
                rendered=render(
                    MessageId.I2, Channel.TEXT, system_name=wording.system_name, link=link
                ),
                recipient_role_id=about,
                about_id=None,
                now=now,
                link=link,
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=command.actor,
                    entity_ids=(about, communication_id),
                    snapshot={"expiresAt": expires_at.isoformat()},
                    at=now,
                )
            )
            await uow.commit()
        return InviteTenantAdminResult(communication_id=communication_id, expires_at=expires_at)
