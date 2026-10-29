"""InviteReporter and ResendInvitation: a shift lead invites a person to report for a pilot service
(U24, docs/spec/domain-rules.md section 6, ui-screens.md "ShiftLeadInvite" and "OnboardReporter1").

An invitation locks the service, the mobile number and the 48 hours. One unit of work writes the
reporter's practitioner (reused when the number is already held in this tenant), the reporter's post
(active, on the still inactive service, so a report before go-live is refused for the service not
being active), the registration in state `invited`, the invitation Task, the link token (purpose
`invite`, about the invitation, 48 hours), the text I1, the `ReporterInvited` event, the audit entry
and the replay record. The mobile number goes only to the protected contact store; the rest of the
graph keeps its keyed hash. The stored copy of the text holds no live token (DEC-311).

Decisions: DEC-310 to DEC-312 (fragment U24).
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PhoneHasher, normalise_uk_mobile
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.outbox import OutboxMessage, outbox_message_for
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.application.use_cases.send_prompts import LinkTokenServiceFactory
from diucs.application.use_cases.setup_service_by_lead import check_role_name, international
from diucs.application.use_cases.text_code import INVITATION_PURPOSE
from diucs.domain.codes import Channel, PractitionerRoleCode, RegistrationStatus, Role, ScopeFlag
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import ReporterInvited
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import RenderedMessage, render
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Invitation, Registration
from diucs.domain.rules.registration import INVITATION_VALID_FOR, can_invite

LinkBaseUrlFor = Callable[[ScopeId], str]
"""The link base URL of a tenant (`https://<host>`), given the bound scope (DEC-134 item 3)."""
INVITE_LINK_PATH: Final = "/i/"
"""The set-up page of an invitation is `/i/<token>`."""
REDACTED_LINK: Final = "[link]"
MOBILE_MESSAGE: Final = "Enter a UK mobile number, like 07700 900123"
NOT_IN_PILOT_MESSAGE: Final = "Only services in the pilot can be invited"
MESSAGES_TOPIC: Final = "messages.outbound"
SEND_MESSAGE: Final = "SendMessage"
INVITE_USE_CASE: Final = "InviteReporter"
RESEND_USE_CASE: Final = "ResendInvitation"
AUDIT_CREATE: Final = "C"
AUDIT_UPDATE: Final = "U"
REPORTER_POST_CODE: Final = PractitionerRoleCode.DUTY_MANAGER
"""The post an invited reporter holds. The lead gives a role label, not a code, so the post is one
code for every invitation, as in U15."""
LEAD_POST_CODE: Final = PractitionerRoleCode.SHIFT_LEAD
MAX_OPEN_LINKS_BURNED: Final = 5
"""A resend burns every open link of the invitation, at most this many. One is open by
construction; the bound only stops a loop on a store that does not move."""


@dataclass(frozen=True, slots=True)
class InviteReporterCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    role_label: str
    mobile: str
    suggested_channel: Channel


@dataclass(frozen=True, slots=True)
class InviteReporterResult:
    invitation_id: str
    registration_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ResendInvitationCommand:
    idempotency_key: str
    actor: Actor
    invitation_id: str


@dataclass(frozen=True, slots=True)
class _Stored:
    """A result with the fingerprint of the command that made it (DEC-104)."""

    fingerprint: str
    result: InviteReporterResult


def check_may_invite(actor: Actor) -> str:
    """Only a shift lead acting as a named practitioner may invite or resend. Returns the lead's
    practitioner id."""
    if actor.role is not Role.LEAD:
        raise NotAllowed("only the shift lead may invite a reporter")
    if actor.practitioner_id is None:
        raise NotAllowed("the lead must act as a named practitioner")
    return actor.practitioner_id


def check_invite_mobile(text: str) -> str:
    """The national form of a UK mobile (eleven digits from 07), or ValidationFailed on `mobile`
    with the screen's wording. Spaces, hyphens and +44 are accepted. The number is never echoed."""
    try:
        return normalise_uk_mobile(text)
    except ValidationFailed:
        raise ValidationFailed("mobile", MOBILE_MESSAGE) from None


def check_in_pilot(flag: ScopeFlag) -> None:
    """Invitations only for an entry flagged in-pilot (domain-rules 6)."""
    if not can_invite(flag):
        raise NotAllowed(NOT_IN_PILOT_MESSAGE)


def invitation_expiry(sent_at: datetime) -> datetime:
    """48 hours of real time after the text went out (INVITATION_VALID_FOR, D22)."""
    if sent_at.tzinfo is None or sent_at.utcoffset() is None:
        raise ValidationFailed("sent_at", "must be timezone-aware")
    return sent_at + INVITATION_VALID_FOR


def invitation_link(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}{INVITE_LINK_PATH}{token}"


def redacted_invitation_link(base_url: str) -> str:
    """The link as the stored copy of the text shows it: the host and path, no token."""
    return invitation_link(base_url, REDACTED_LINK)


def lead_post(roles: list[PractitionerRole]) -> PractitionerRole | None:
    """The lead's shift-lead post among the roles given (the active ones): the lowest id when more
    than one."""
    posts = [role for role in roles if role.active and role.code is LEAD_POST_CODE]
    return min(posts, key=lambda role: role.id) if posts else None


def command_key(operation: str, scope: ScopeId, key: str) -> str:
    """The replay key, named by operation and tenant (lesson L160)."""
    return f"invite-reporter:{operation}:{scope}:{key}"


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _replayed(stored: object, fingerprint: str) -> InviteReporterResult | None:
    if stored is None:
        return None
    if not isinstance(stored, _Stored) or stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different invitation command")
    return stored.result


def _render(service_name: str, link: str) -> RenderedMessage:
    return render(MessageId.I1, Channel.TEXT, service=service_name, link=link)


async def _send_text(
    uow: UnitOfWork,
    ids: IdGenerator,
    *,
    now: datetime,
    service_name: str,
    link: str,
    redacted: str,
    role_id: str,
    invitation_id: str,
) -> None:
    """The text I1 as an outbox message that carries the real link, and its Communication, which
    keeps the text with the link's token left out so the graph never holds a live token."""
    sent = _render(service_name, link)
    stored = _render(service_name, redacted)
    communication = Communication(
        id=ids.new_id(),
        message_id=sent.message_id.value,
        channel=Channel.TEXT,
        recipient_role_id=role_id,
        about_id=invitation_id,
        payload_text=stored.text,
        sent_at=now,
        delivery_status="queued",
    )
    await uow.communications.add(communication)
    await uow.outbox.add(
        OutboxMessage(
            id=ids.new_id(),
            topic=MESSAGES_TOPIC,
            event_type=SEND_MESSAGE,
            payload={
                "communication_id": communication.id,
                "message_id": sent.message_id.value,
                "channel": Channel.TEXT.value,
                "recipient_role_id": role_id,
                "text": sent.text,
                "subject": sent.subject,
                "html": sent.html,
            },
            created_at=now,
        )
    )


class InviteReporter:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        link_tokens: LinkTokenServiceFactory,
        phone_hasher: PhoneHasher,
        clock: Clock,
        ids: IdGenerator,
        *,
        link_base_url_for: LinkBaseUrlFor,
    ) -> None:
        """`link_tokens` builds the link service over the unit's own repository. The link host of
        a tenant comes from its configuration, through `link_base_url_for`."""
        self._uow_factory = uow_factory
        self._link_tokens = link_tokens
        self._hasher = phone_hasher
        self._clock = clock
        self._ids = ids
        self._link_base_url_for = link_base_url_for

    async def execute(self, command: InviteReporterCommand) -> InviteReporterResult:
        lead_id = check_may_invite(command.actor)
        check_role_name("role_label", command.role_label)
        label = " ".join(command.role_label.split())
        national = check_invite_mobile(command.mobile)
        if not isinstance(command.suggested_channel, Channel):
            raise ValidationFailed("suggested_channel", "must be text, email or push")
        phone_hash = self._hasher.hash(national)
        fingerprint = _fingerprint(
            "invite",
            command.service_id,
            label,
            phone_hash,
            command.suggested_channel.value,
            lead_id,
        )
        now = self._clock.now()

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = command_key("invite", scope, command.idempotency_key)
            replay = _replayed(await uow.idempotency.get(key), fingerprint)
            if replay is not None:
                return replay

            entry = await uow.scope.get_entry(command.service_id)
            if entry is None:
                raise NotFound("no scope entry for this service")
            check_in_pilot(entry.flag)
            if await uow.registrations.for_service(command.service_id):
                raise Conflict("this service already has a registration: resend its invitation")
            lead = lead_post(await uow.people.roles_for_practitioner(lead_id))
            if lead is None:
                raise NotAllowed("the lead holds no shift lead post")

            invitee = await uow.people.find_by_phone_hash(phone_hash)
            invitee_id = invitee.id if invitee is not None else self._ids.new_id()
            if invitee is None:
                await uow.people.save_practitioner(
                    Practitioner(
                        id=invitee_id, active=True, display_name=label, phone_hash=phone_hash
                    )
                )
            role_id = self._ids.new_id()
            await uow.people.save_role(
                PractitionerRole(
                    id=role_id,
                    practitioner_id=invitee_id,
                    service_id=command.service_id,
                    code=REPORTER_POST_CODE,
                    active=True,
                    channel=command.suggested_channel,
                    period_start=now,
                )
            )
            await uow.contacts.put_phone(role_id, international(national))

            registration_id = self._ids.new_id()
            await uow.registrations.add(
                Registration(
                    id=registration_id,
                    service_id=command.service_id,
                    status=RegistrationStatus.INVITED,
                    requester_role_id=role_id,
                    owner_role_id=None,
                    created_at=now,
                    last_modified=now,
                )
            )
            expires_at = invitation_expiry(now)
            invitation_id = self._ids.new_id()
            await uow.registrations.add_invitation(
                Invitation(
                    id=invitation_id,
                    service_id=command.service_id,
                    registration_id=registration_id,
                    requester_role_id=lead.id,
                    invitee_id=invitee_id,
                    role_label=label,
                    created_at=now,
                    sent_at=now,
                    expires_at=expires_at,
                )
            )
            base_url = self._link_base_url_for(scope)
            token = await self._link_tokens(uow.link_tokens).issue(
                INVITATION_PURPOSE, invitation_id, phone_hash, expires_at
            )
            await _send_text(
                uow,
                self._ids,
                now=now,
                service_name=entry.name,
                link=invitation_link(base_url, token),
                redacted=redacted_invitation_link(base_url),
                role_id=role_id,
                invitation_id=invitation_id,
            )
            await uow.outbox.add(
                outbox_message_for(
                    ReporterInvited(
                        invitation_id=invitation_id, service_id=command.service_id, at=now
                    ),
                    id=self._ids.new_id(),
                    now=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_CREATE,
                    use_case=INVITE_USE_CASE,
                    actor=command.actor,
                    entity_ids=(invitation_id, registration_id, command.service_id, role_id),
                    snapshot={
                        "service_id": command.service_id,
                        "invitation_id": invitation_id,
                        "registration_id": registration_id,
                        "role_label": label,
                        "channel": command.suggested_channel.value,
                        "expires_at": expires_at,
                    },
                    at=now,
                )
            )
            result = InviteReporterResult(
                invitation_id=invitation_id, registration_id=registration_id, expires_at=expires_at
            )
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class ResendInvitation:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        link_tokens: LinkTokenServiceFactory,
        clock: Clock,
        ids: IdGenerator,
        *,
        link_base_url_for: LinkBaseUrlFor,
    ) -> None:
        self._uow_factory = uow_factory
        self._link_tokens = link_tokens
        self._clock = clock
        self._ids = ids
        self._link_base_url_for = link_base_url_for

    async def execute(self, command: ResendInvitationCommand) -> InviteReporterResult:
        check_may_invite(command.actor)
        fingerprint = _fingerprint("resend", command.invitation_id)
        now = self._clock.now()

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = command_key("resend", scope, command.idempotency_key)
            replay = _replayed(await uow.idempotency.get(key), fingerprint)
            if replay is not None:
                return replay

            invitation = await uow.registrations.get_invitation(command.invitation_id)
            if invitation is None:
                raise NotFound("no invitation with this id")
            registration = await uow.registrations.get(invitation.registration_id)
            if registration is None:
                raise NotFound("the registration of this invitation")
            if registration.status is not RegistrationStatus.INVITED:
                raise Conflict("an invitation can be resent only while the registration is invited")
            invitee = await uow.people.get_practitioner(invitation.invitee_id)
            entry = await uow.scope.get_entry(invitation.service_id)
            if invitee is None or invitee.phone_hash is None or entry is None:
                raise NotFound("the invitee or the service of this invitation")
            if registration.requester_role_id is None:
                raise NotFound("the reporter's post of this invitation")

            tokens = self._link_tokens(uow.link_tokens)
            for _ in range(MAX_OPEN_LINKS_BURNED):
                old = await uow.link_tokens.open_for_about(INVITATION_PURPOSE, invitation.id, now)
                if old is None:
                    break
                await uow.link_tokens.mark_used(old.token_hash, now, f"resend:{key}")
            expires_at = invitation_expiry(now)
            token = await tokens.issue(
                INVITATION_PURPOSE, invitation.id, invitee.phone_hash, expires_at
            )
            # U26 counts the applicant's 48 hours from the registration's created_at, so a resend
            # restarts it (DEC-312).
            await uow.registrations.save(replace(registration, created_at=now, last_modified=now))
            await uow.registrations.save_invitation(
                replace(invitation, sent_at=now, expires_at=expires_at)
            )
            base_url = self._link_base_url_for(scope)
            await _send_text(
                uow,
                self._ids,
                now=now,
                service_name=entry.name,
                link=invitation_link(base_url, token),
                redacted=redacted_invitation_link(base_url),
                role_id=registration.requester_role_id,
                invitation_id=invitation.id,
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_UPDATE,
                    use_case=RESEND_USE_CASE,
                    actor=command.actor,
                    entity_ids=(invitation.id, registration.id, invitation.service_id),
                    snapshot={
                        "service_id": invitation.service_id,
                        "invitation_id": invitation.id,
                        "expires_at": expires_at,
                    },
                    at=now,
                )
            )
            result = InviteReporterResult(
                invitation_id=invitation.id,
                registration_id=registration.id,
                expires_at=expires_at,
            )
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result
