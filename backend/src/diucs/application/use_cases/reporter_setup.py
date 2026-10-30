"""Reporter set-up behind a link or a device, before anyone is signed in (W7C, DEC-810 to DEC-813).

The set-up page holds an invitation token and nothing else: never the mobile number, which the
lead typed and which sits in the protected contact store. Three things are built here, and none of
them says anything about who is known:

- `InvitationReader.view` shows one invitation (the service, the post, the masked number, the
  expiry) or refuses it with `InvitationUnusable`, one refusal for an unknown, malformed, expired,
  used, another tenant's or another purpose's token (H-450).
- `InvitationReader.phone_hash` and `DeviceReader.phone_hash` give the keyed hash of the number a
  text code goes to, so the code routes use the same code use cases as the number-based routes
  (U25, U32) without the browser ever holding a number. A token or a device that is not usable
  gets a stand-in hash that no practitioner holds, so a request for it does the same work and gets
  the same answer as a request for a real one (H-96, H-451).
- `SetDeviceChannel` records how a reporter wants to be contacted, for a device that was verified
  by a text code in the last ten minutes (the channel step of set-up, and the locked PIN's "text
  me"), as `SetDevicePin` does for the PIN.

Nothing here logs, returns or puts in an error a token, a number or a device id.
"""

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.tokens import LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.application.use_cases.link_access import MAX_TOKEN_LENGTH
from diucs.application.use_cases.pin import PIN_SET_WINDOW
from diucs.application.use_cases.reporter_identity import unknown_person
from diucs.application.use_cases.send_prompts import LinkTokenServiceFactory
from diucs.application.use_cases.text_code import INVITATION_PURPOSE
from diucs.domain.codes import Channel, Role
from diucs.domain.errors import DomainError, ValidationFailed
from diucs.domain.model.people import REPORTER_ROLE_CODES
from diucs.domain.model.registration import Invitation
from diucs.domain.model.tenant import ContactKind
from diucs.domain.rules.reporter_app import MASKED_NOTHING, mask_mobile
from diucs.domain.rules.tokens import LinkCheck, LinkTokenRecord, check_link

STAND_IN_TOKEN: Final = "unknown-invitation"
STAND_IN_DEVICE: Final = "unknown-device"
USE_CASE: Final = "SetDeviceChannel"
ACTOR_CHANNEL: Final = "device"


class InvitationUnusable(DomainError):
    """The invitation cannot be used, for any reason. It carries nothing."""


class KnownPhoneHash:
    """A `PhoneHasher` for a caller that holds the keyed hash and not the number: the use cases of
    the text code ask it to hash a number, and it answers the hash it was made with."""

    def __init__(self, phone_hash: str) -> None:
        self._hash = phone_hash

    def hash(self, number: str) -> str:
        return self._hash


def stand_in_hash(kind: str, subject: str) -> str:
    """A 64-hex hash that no practitioner holds, stable for one subject (a token or a device): the
    code of an unusable invitation or an unknown device is kept and discarded like the code of an
    unknown number."""
    return hashlib.sha256(f"{kind}|{subject}".encode()).hexdigest()


def _tenant_bound(uow: UnitOfWork) -> ScopeId:
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


@dataclass(frozen=True, slots=True)
class InvitationView:
    service: str
    role: str
    masked_phone: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class _OpenInvitation:
    record: LinkTokenRecord
    invitation: Invitation


class InvitationReader:
    """Reads the invitation a token opens, in the tenant the edge bound."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, link_tokens: LinkTokenServiceFactory
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._link_tokens = link_tokens

    async def _open(self, uow: UnitOfWork, token: str) -> _OpenInvitation | None:
        if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
            return None  # nothing that long is a token: it is not hashed
        service: LinkTokenService = self._link_tokens(uow.link_tokens)
        record = await service.resolve(token)
        if (
            record is None
            or record.purpose != INVITATION_PURPOSE
            or record.phone_hash is None
            or check_link(record, self._clock.now()) is not LinkCheck.OK
        ):
            return None
        invitation = await uow.registrations.get_invitation(record.about_id)
        if invitation is None:
            return None
        return _OpenInvitation(record, invitation)

    async def view(self, token: str) -> InvitationView:
        async with self._uow_factory() as uow:
            _tenant_bound(uow)
            found = await self._open(uow, token)
            if found is None:
                raise InvitationUnusable
            invitation = found.invitation
            service = await uow.services.get(invitation.service_id)
            registration = await uow.registrations.get(invitation.registration_id)
            if service is None or registration is None or registration.requester_role_id is None:
                raise InvitationUnusable
            number = await uow.contacts.get_phone(registration.requester_role_id)
        return InvitationView(
            service=service.name,
            role=invitation.role_label,
            masked_phone=MASKED_NOTHING if number is None else mask_mobile(number),
            expires_at=invitation.expires_at,
        )

    async def phone_hash(self, token: str) -> str:
        """The hash of the number the invitation was sent to, or a stand-in for any token that is
        not an open invitation of this tenant."""
        async with self._uow_factory() as uow:
            _tenant_bound(uow)
            found = await self._open(uow, token)
        if found is None or found.record.phone_hash is None:
            return stand_in_hash(STAND_IN_TOKEN, token)
        return found.record.phone_hash


class DeviceReader:
    """The number a device's owner holds, for the codes of the 30-day check and a PIN reset."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def phone_hash(self, device_id: str) -> str:
        async with self._uow_factory() as uow:
            _tenant_bound(uow)
            owner = await uow.devices.owner_of(device_id)
            person = None if owner is None else await uow.people.get_practitioner(owner)
        if person is None or not person.active or person.phone_hash is None:
            return stand_in_hash(STAND_IN_DEVICE, unknown_person(device_id))
        return person.phone_hash


@dataclass(frozen=True, slots=True)
class SetDeviceChannelCommand:
    device_id: str = field(repr=False)
    channel: Channel


class SetDeviceChannel:
    """Record the channel for the person who holds a device that a text code verified in the last
    ten minutes (the window of a PIN, `PIN_SET_WINDOW`). True when it was recorded; False for every
    reason it was not (an unknown or revoked device, no recent verification, a person who has left,
    a person with no reporter post), so the answer does not say which devices exist."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: SetDeviceChannelCommand) -> bool:
        if not isinstance(command.channel, Channel):
            raise ValidationFailed("channel", "must be a channel")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            _tenant_bound(uow)
            owner = await uow.devices.owner_of(command.device_id)
            if owner is None or not await uow.devices.known(owner, command.device_id):
                return False
            verified = await uow.devices.verified_at(owner, command.device_id)
            if verified is None or verified > now or now - verified > PIN_SET_WINDOW:
                return False
            person = await uow.people.get_practitioner(owner)
            if person is None or not person.active:
                return False
            roles = [
                role
                for role in await uow.people.roles_for_practitioner(owner)
                if role.code in REPORTER_ROLE_CODES
            ]
            if not roles:
                return False
            for role in roles:
                await uow.people.save_role(replace(role, channel=command.channel))
            await uow.audit.append(
                AuditEntry(
                    action="U",
                    use_case=USE_CASE,
                    actor=Actor(
                        role=Role.REPORTER,
                        practitioner_id=owner,
                        device_id=None,
                        channel=ACTOR_CHANNEL,
                        service_ids=frozenset(),
                        tenant_id=_tenant_bound(uow).value,
                    ),
                    entity_ids=tuple(role.id for role in roles),
                    snapshot={"channel": command.channel.value},
                    at=now,
                )
            )
            await uow.commit()
        return True


class CoordinationPhone:
    """The SPOA's number, for the screen of a reporter who is waiting for the lead's call-back: the
    coordination phone of the bound tenant, or None when the tenant has set none. Never a default
    and never another tenant's number (W7C, H-459)."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def read(self) -> str | None:
        async with self._uow_factory() as uow:
            _tenant_bound(uow)
            contacts = await uow.tenant_config.contacts()
        return next((c.value for c in contacts if c.kind is ContactKind.COORDINATION_PHONE), None)
