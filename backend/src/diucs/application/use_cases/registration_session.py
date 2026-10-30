"""Signing in to the registration flow, and exchanging a PIN session for a token (W7B A2).

After a text code the applicant has no token: the back end issues every token (TEN-043, DEC-134
item 2) and the BFF holds no signing secret. Three things close that gap, all through the machinery
that already exists (U24 invitations, U25 text codes, U32 devices, U37 sessions):

- `ReadInvitation`: what an invitation link says (its state, the service, the end of the number), so
  the page can show the right words before a code is asked for. The link is found inside the host's
  tenant only (`PreSessionResolver`); an unknown, malformed or other tenant's link is the one
  `EntryRefused`.
- `RequestRegistrationCode`: a code sent to the number the invitation holds, so the browser never
  needs the number.
- `RegistrationSignIn`: the code is checked and recorded on the device by the same call the code
  route uses (`ConfirmDeviceByTextCode`), and a right code ends in a reporter token. The person is
  the one the invitation names (or the one who holds the number), never one the caller sends; the
  services are the ones that person holds a reporter post for; the tenant is the host's.
- `ExchangeReporterSession`: a live PIN session is exchanged for a short token, so the reporter app
  is no longer a session id in a place that needs a token. A session that has ended, or been signed
  out everywhere, is gone.

A token is made only for a tenant the edge would accept (`may_issue`, the one edge rule). The order
is: the tenant, the invitation, then the code, so a refused request never uses up a try. Every
refusal that could say which tokens or sessions exist is the one `EntryRefused`; every wrong code
is the code route's own answer. No number, code, device id, session id or token reaches a log line,
an error or the audit. Decisions: DEC-790 to DEC-793.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PhoneHasher, SessionStore
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantNotBound
from diucs.application.tenant_resolution import EntryRefused, ResolvedLink
from diucs.application.use_cases.exchange_token import SIGNING_SECRET, IssuedToken
from diucs.application.use_cases.reporter_identity import ConfirmDeviceCommand, ConfirmDeviceResult
from diucs.application.use_cases.text_code import (
    INVITATION_PURPOSE,
    RequestTextCodeCommand,
    RequestTextCodeResult,
)
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.people import PractitionerRole
from diucs.domain.model.registration import Invitation, Registration
from diucs.domain.model.tenant import Tenant
from diucs.domain.rules.bff_token import BffClaims, encode_bff_token
from diucs.domain.rules.token_exchange import expiry, may_issue
from diucs.domain.rules.tokens import LinkCheck

REGISTRATION_TOKEN_LIFETIME: Final = timedelta(hours=2)
"""[ASSUMED] How long a token from a text code lasts: a registration is filled in over a sitting,
and the applicant signs in again by number and code after it (DEC-790 item 3)."""
SESSION_TOKEN_LIFETIME: Final = timedelta(minutes=30)
"""[ASSUMED] How long a token made from a PIN session lasts. The session itself ends or is
signed out; the token cannot be recalled, so it is short and the app asks again (DEC-792 item 2)."""
REPORTER_POSTS: Final = frozenset(
    {PractitionerRoleCode.DUTY_MANAGER, PractitionerRoleCode.COORDINATOR}
)
"""The posts that report for a service: the services a token names are the ones its person holds
one of these for."""
SESSION_PURPOSE: Final = "setup"
"""The text-code purpose of a first sign-in on a device (DEC-413)."""
SESSION_ROLES: Final = frozenset({Role.REPORTER, Role.EXEC})
NUMBER_ENDING_DIGITS: Final = 3


class SignInKind(StrEnum):
    SIGNED_IN = "signed-in"
    WRONG_CODE = "wrong-code"
    NEEDS_NEW_CODE = "needs-new-code"
    DEVICE_REFUSED = "device-refused"


class _Resolver(Protocol):
    async def invitation(self, token: str) -> ResolvedLink: ...


class _RequestCode(Protocol):
    async def execute(self, command: RequestTextCodeCommand) -> RequestTextCodeResult: ...


class _Confirm(Protocol):
    async def execute(self, command: ConfirmDeviceCommand) -> ConfirmDeviceResult: ...


def number_ending(number: str) -> str:
    """The last three digits of a number: all the page ever shows of it."""
    digits = "".join(char for char in number if char.isdigit())
    return digits[-NUMBER_ENDING_DIGITS:]


def reporter_services(roles: Sequence[PractitionerRole]) -> frozenset[str]:
    """The services a person reports for: the active reporter posts that name a service."""
    return frozenset(
        role.service_id
        for role in roles
        if role.active and role.code in REPORTER_POSTS and role.service_id is not None
    )


def issue_reporter_token(
    *,
    tenant: Tenant,
    person: str,
    services: Collection[str],
    device: str,
    role: Role,
    now: datetime,
    lifetime: timedelta,
    secrets: SecretStore,
) -> IssuedToken:
    """A tenant-bound token for a reporter or an exec, signed with the platform secret. A tenant the
    edge would not accept, or a role that is not a reporter's, gets none: the one `EntryRefused`. A
    missing secret is a configuration fault, never a refusal."""
    if role not in SESSION_ROLES or not may_issue(tenant, role):
        raise EntryRefused
    try:
        signing = secrets.get(SIGNING_SECRET)
    except NotFound:
        raise RuntimeError("a secret the token exchange needs is not configured") from None
    expires_at = expiry(now, lifetime)
    token = encode_bff_token(
        BffClaims(
            sub=person,
            role=role,
            services=frozenset(services),
            expires_at=expires_at,
            tenant=tenant.id,
            epoch=tenant.epoch,
            device=device,
        ),
        signing,
    )
    return IssuedToken(token=token, expires_at=expires_at, role=role)


@dataclass(frozen=True, slots=True)
class InvitationFacts:
    """An invitation, its registration and the service it is for, read in the host's tenant. The
    number is the applicant's, from the protected contact store, and never leaves this module but as
    its last digits or as the number the code goes to."""

    invitation: Invitation
    registration: Registration
    service_name: str
    state: LinkCheck
    phone: str = field(repr=False)

    @property
    def number_ending(self) -> str:
        return number_ending(self.phone)


def _tenant_bound(uow: UnitOfWork) -> None:
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound


class ReadInvitation:
    def __init__(self, uow_factory: UnitOfWorkFactory, resolver: _Resolver) -> None:
        self._uow_factory = uow_factory
        self._resolver = resolver

    async def execute(self, token: str) -> InvitationFacts:
        link = await self._resolver.invitation(token)
        if link.record.purpose != INVITATION_PURPOSE:
            raise EntryRefused
        async with self._uow_factory() as uow:
            _tenant_bound(uow)
            invitation = await uow.registrations.get_invitation(link.record.about_id)
            if invitation is None:
                raise EntryRefused
            registration = await uow.registrations.get(invitation.registration_id)
            entry = await uow.scope.get_entry(invitation.service_id)
            role_id = None if registration is None else registration.requester_role_id
            phone = None if role_id is None else await uow.contacts.get_phone(role_id)
        if registration is None or entry is None or phone is None:
            raise EntryRefused
        return InvitationFacts(
            invitation=invitation,
            registration=registration,
            service_name=entry.name,
            state=link.state,
            phone=phone,
        )


class RequestRegistrationCode:
    """A code to the number an open invitation holds. The caller never gives the number."""

    def __init__(self, read: ReadInvitation, request_code: _RequestCode) -> None:
        self._read = read
        self._request_code = request_code

    async def execute(self, token: str, idempotency_key: str) -> RequestTextCodeResult:
        facts = await self._read.execute(token)
        if facts.state is not LinkCheck.OK:
            raise EntryRefused
        return await self._request_code.execute(
            RequestTextCodeCommand(
                idempotency_key=idempotency_key, phone=facts.phone, purpose=SESSION_PURPOSE
            )
        )


@dataclass(frozen=True, slots=True)
class RegistrationSignInCommand:
    tenant: Tenant
    code: str = field(repr=False)
    device_id: str = field(repr=False)
    invitation: str | None = field(default=None, repr=False)
    mobile: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class RegistrationSignInResult:
    kind: SignInKind
    token: IssuedToken | None = None
    registration_id: str | None = None
    service_id: str | None = None
    service_name: str | None = None


_WRONG: Final = RegistrationSignInResult(SignInKind.WRONG_CODE)
_NEW_CODE: Final = RegistrationSignInResult(SignInKind.NEEDS_NEW_CODE)
_DEVICE: Final = RegistrationSignInResult(SignInKind.DEVICE_REFUSED)


class RegistrationSignIn:
    """A code, checked and recorded on the device, that ends in a reporter token. The person is the
    invitation's, or (for an applicant who comes back) the holder of the number; a number nobody
    holds, or that holds no reporter post, answers as a code that needs asking for again."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        read: ReadInvitation,
        confirm: _Confirm,
        phone_hasher: PhoneHasher,
        secrets: SecretStore,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._read = read
        self._confirm = confirm
        self._hasher = phone_hasher
        self._secrets = secrets
        self._clock = clock

    async def execute(self, command: RegistrationSignInCommand) -> RegistrationSignInResult:
        if (command.invitation is None) == (command.mobile is None):
            raise ValidationFailed("invitation", "give the invitation or the mobile, not both")
        now = self._clock.now()
        if not may_issue(command.tenant, Role.REPORTER):
            raise EntryRefused
        facts: InvitationFacts | None = None
        if command.invitation is not None:
            facts = await self._read.execute(command.invitation)
            if facts.state is not LinkCheck.OK:
                raise EntryRefused
            phone = facts.phone
        else:
            phone = command.mobile or ""
        checked = await self._confirm.execute(
            ConfirmDeviceCommand(
                phone=phone, code=command.code, purpose=SESSION_PURPOSE, device_id=command.device_id
            )
        )
        if not checked.verified:
            return _NEW_CODE if checked.needs_new_code else _WRONG
        if checked.device_refused:
            return _DEVICE
        person = facts.invitation.invitee_id if facts is not None else await self._holder(phone)
        if person is None:
            return _NEW_CODE
        services = await self._services(person, now)
        if not services:
            return _NEW_CODE
        token = issue_reporter_token(
            tenant=command.tenant,
            person=person,
            services=services,
            device=command.device_id,
            role=Role.REPORTER,
            now=now,
            lifetime=REGISTRATION_TOKEN_LIFETIME,
            secrets=self._secrets,
        )
        return RegistrationSignInResult(
            SignInKind.SIGNED_IN,
            token=token,
            registration_id=None if facts is None else facts.registration.id,
            service_id=None if facts is None else facts.invitation.service_id,
            service_name=None if facts is None else facts.service_name,
        )

    async def _holder(self, phone: str) -> str | None:
        async with self._uow_factory() as uow:
            _tenant_bound(uow)
            practitioner = await uow.people.find_by_phone_hash(self._hasher.hash(phone))
        return None if practitioner is None else practitioner.id

    async def _services(self, person: str, now: datetime) -> frozenset[str]:
        async with self._uow_factory() as uow:
            _tenant_bound(uow)
            return reporter_services(await uow.people.roles_for_practitioner(person))


class ExchangeReporterSession:
    """A live PIN session, exchanged for a short token with the session's own person, services and
    device. Read-only: the session is not extended or ended here."""

    def __init__(self, sessions: SessionStore, secrets: SecretStore, clock: Clock) -> None:
        self._sessions = sessions
        self._secrets = secrets
        self._clock = clock

    async def execute(self, tenant: Tenant, session_id: str) -> IssuedToken:
        session = await self._sessions.get(session_id)
        if session is None or session.role not in SESSION_ROLES:
            raise EntryRefused
        return issue_reporter_token(
            tenant=tenant,
            person=session.practitioner_id,
            services=session.services,
            device=session.device_id,
            role=session.role,
            now=self._clock.now(),
            lifetime=SESSION_TOKEN_LIFETIME,
            secrets=self._secrets,
        )
