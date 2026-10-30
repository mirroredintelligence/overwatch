"""The support-access ticket flow (TEN-075, TEN-084, DEC-134 item 5, DEC-136 item 6, audit F 4.2).

A support person of the operator's own directory asks one tenant for access, with a reason. The
tenant's administrator approves or refuses. An approval issues the one-time code of the cross-tenant
guard; the support person presents it, the guard opens one access for one tenant and an hour, and
every step is written to the tenant's own chain and to the platform's. There is no standing access:
a request lapses in a day, a code in four hours, an access in one hour, and an administrator can
withdraw any of them at once.

Who does what, and in whose tenant:

- the support person (`PlatformPrincipal`, from an operator token) requests, cancels a request
  nobody has decided, opens with the code, uses and ends the access. They name the tenant, so the
  guard (the one binder of a tenant a platform principal names) writes that tenant's chain; these
  use cases bind nothing;
- the tenant's administrator (an `Actor` of role `tenant-admin`, in the tenant the edge bound from
  their token) lists the tickets that name the tenant, approves, refuses and revokes. The tenant is
  the bound one and nothing else, so another tenant's ticket is not found.

The code. The approval returns it once, to the administrator, who gives it to the support person
(a spoken or typed code, as O06's). It is not stored: the ticket keeps the keyed hash the grant is
held under, which is what lets a refusal, a revocation or a failed approval take the code back
(`withdraw_code`) and lets the opening check that the code the guard redeemed is this ticket's.
If the response carrying the code is lost the administrator revokes and the support person asks
again: a second approval would be a second code.

Order of effects, so that a failure leaves the safe thing. What gives access is done last and
undone first: an approval issues the code, then moves the ticket, then writes both chains, and any
failure on the way withdraws the code and (once the ticket is approved) revokes it; a revocation,
an ending, a refusal and a cancellation take the access away first and are recorded after, so a
chain that cannot be written never leaves access standing. An opening is the guard's own (it writes
both chains and removes the access when it cannot), and the ticket is moved after it.

One refusal for the support person: a ticket that is not theirs, a tenant that is not open and a
code that does not open are the guard's `CrossTenantDenied`, with its fixed message, so an answer
never says which. A ticket in a state that cannot make the move is `InvalidTransition`.
"""

import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor, require_actor_in_bound_tenant
from diucs.application.cross_tenant_guard import (
    AuthoriseCommand,
    CrossTenantDenied,
    CrossTenantGuard,
    DecisionNoteCommand,
    Elevation,
    EndAccessCommand,
    IssueCodeCommand,
    OpenAccessCommand,
    PlatformPrincipal,
    RevokeAccessCommand,
    TicketNoteCommand,
    WithdrawCodeCommand,
    check_issuer,
)
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.cross_tenant_tickets import CrossTenantTicketStore
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.tenancy import is_valid_tenant_id
from diucs.domain.errors import Conflict, InvalidTransition, NotFound
from diucs.domain.model.tenant import Tenant, TenantStatus
from diucs.domain.rules.support_ticket import (
    LIVE_STATES,
    EndedBy,
    ReasonCode,
    SupportTicket,
    TicketState,
    approve,
    cancel,
    check_reason,
    check_reference,
    effective_state,
    end_access,
    new_ticket,
    open_access,
    refuse,
    revoke,
)

log = logging.getLogger(__name__)

LIST_LIMIT: Final = 50
NO_TICKET: Final = "no such ticket"
MOVED: Final = "the ticket changed since it was read"
ALREADY_OPEN: Final = "there is already a live ticket for this tenant"
NOT_PENDING: Final = "the ticket is not waiting for a decision"

ACTION_REQUESTED: Final = "support-ticket-requested"
ACTION_CANCELLED: Final = "support-ticket-cancelled"
ACTION_APPROVED: Final = "support-ticket-approved"
ACTION_REFUSED: Final = "support-ticket-refused"
ACTION_REVOKED: Final = "support-ticket-revoked"
ACTION_OPENED: Final = "support-ticket-opened"
ACTION_ENDED: Final = "support-ticket-ended"
ACTION_ABANDONED: Final = "support-ticket-abandoned"


@dataclass(frozen=True, slots=True)
class TicketView:
    """A ticket and what it reads as now (a live ticket whose time has come is `expired`)."""

    ticket: SupportTicket
    state: TicketState


def view_of(ticket: SupportTicket, now: datetime) -> TicketView:
    return TicketView(ticket=ticket, state=effective_state(ticket, now))


def _principal(value: object) -> PlatformPrincipal:
    if type(value) is not PlatformPrincipal:
        raise CrossTenantDenied
    return value


def _administrator(actor: Actor) -> str:
    """The reference of the tenant's administrator acting, in the tenant the edge bound."""
    check_issuer(actor)
    require_actor_in_bound_tenant(actor)
    assert actor.practitioner_id is not None
    return actor.practitioner_id


# ---------------------------------------------------------------- the support person


@dataclass(frozen=True, slots=True)
class RequestTicketCommand:
    principal: PlatformPrincipal
    tenant_id: str
    reason_code: ReasonCode
    reason: str
    reference: str | None = None


class _Tickets:
    def __init__(
        self,
        tickets: CrossTenantTicketStore,
        guard: CrossTenantGuard,
        clock: Clock,
    ) -> None:
        self._tickets = tickets
        self._guard = guard
        self._clock = clock

    async def _own(self, principal: PlatformPrincipal, ticket_id: object) -> SupportTicket:
        """The support person's own ticket. Another person's, another's tenant's and none read the
        same, as the guard's one refusal."""
        if type(ticket_id) is not str:
            raise CrossTenantDenied
        ticket = await self._tickets.for_principal(principal.account_ref, ticket_id)
        if ticket is None:
            raise CrossTenantDenied
        return ticket

    async def _tenants(self, actor: Actor, ticket_id: object) -> SupportTicket:
        """The ticket of the administrator's own tenant (the bound one)."""
        if type(ticket_id) is not str:
            raise NotFound(NO_TICKET)
        ticket = await self._tickets.for_tenant(actor.tenant_id, ticket_id)
        if ticket is None:
            raise NotFound(NO_TICKET)
        return ticket


class RequestSupportTicket(_Tickets):
    def __init__(
        self,
        tickets: CrossTenantTicketStore,
        guard: CrossTenantGuard,
        tenants: TenantDirectory,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        super().__init__(tickets, guard, clock)
        self._tenant_directory = tenants
        self._ids = ids

    async def execute(self, command: RequestTicketCommand) -> SupportTicket:
        principal = _principal(command.principal)
        tenant_id = command.tenant_id
        if type(tenant_id) is not str or not is_valid_tenant_id(tenant_id):
            raise CrossTenantDenied
        tenant = await self._tenant_directory.get(tenant_id)
        if type(tenant) is not Tenant or tenant.status is not TenantStatus.ACTIVE:
            raise CrossTenantDenied
        reason = check_reason(command.reason)
        reference = check_reference(command.reference)
        now = self._clock.now()
        for held in await self._tickets.of_principal(principal.account_ref, LIST_LIMIT):
            if held.tenant_id == tenant_id and effective_state(held, now) in LIVE_STATES:
                raise Conflict(ALREADY_OPEN)
        ticket = new_ticket(
            ticket_id=self._ids.new_id(),
            tenant_id=tenant_id,
            requested_by_ref=principal.account_ref,
            reason_code=command.reason_code,
            reason=reason,
            reference=reference,
            now=now,
        )
        await self._tickets.add(ticket)
        try:
            await self._guard.note_ticket(
                TicketNoteCommand(
                    principal=principal,
                    tenant_id=tenant_id,
                    action=ACTION_REQUESTED,
                    ticket_id=ticket.id,
                    snapshot={"reason_code": ticket.reason_code.value},
                )
            )
        except BaseException:
            # A request nobody could be told of does not stand: it is withdrawn.
            await self._abandon(ticket)
            raise
        return ticket

    async def _abandon(self, ticket: SupportTicket) -> None:
        try:
            await self._tickets.move(cancel(ticket, now=self._clock.now()), TicketState.PENDING)
        except Exception as error:
            log.error("a support ticket could not be withdrawn: %s", type(error).__name__)


class ListSupportTickets(_Tickets):
    async def for_principal(self, principal: PlatformPrincipal) -> list[TicketView]:
        person = _principal(principal)
        now = self._clock.now()
        found = await self._tickets.of_principal(person.account_ref, LIST_LIMIT)
        return [view_of(ticket, now) for ticket in found]

    async def for_tenant(self, actor: Actor) -> list[TicketView]:
        _administrator(actor)
        now = self._clock.now()
        found = await self._tickets.of_tenant(actor.tenant_id, LIST_LIMIT)
        return [view_of(ticket, now) for ticket in found]


class ReadSupportTicket(_Tickets):
    async def for_principal(self, principal: PlatformPrincipal, ticket_id: str) -> TicketView:
        person = _principal(principal)
        return view_of(await self._own(person, ticket_id), self._clock.now())

    async def for_tenant(self, actor: Actor, ticket_id: str) -> TicketView:
        _administrator(actor)
        return view_of(await self._tenants(actor, ticket_id), self._clock.now())


@dataclass(frozen=True, slots=True)
class CancelTicketCommand:
    principal: PlatformPrincipal
    ticket_id: str


class CancelSupportTicket(_Tickets):
    """The support person withdraws a request nobody has decided."""

    async def execute(self, command: CancelTicketCommand) -> SupportTicket:
        principal = _principal(command.principal)
        ticket = await self._own(principal, command.ticket_id)
        cancelled = cancel(ticket, now=self._clock.now())
        if not await self._tickets.move(cancelled, TicketState.PENDING):
            raise Conflict(MOVED)
        await self._guard.note_ticket(
            TicketNoteCommand(
                principal=principal,
                tenant_id=ticket.tenant_id,
                action=ACTION_CANCELLED,
                ticket_id=ticket.id,
            )
        )
        return cancelled


@dataclass(frozen=True, slots=True)
class OpenTicketCommand:
    principal: PlatformPrincipal
    ticket_id: str
    code: str


@dataclass(frozen=True, slots=True)
class OpenedAccess:
    ticket: SupportTicket
    elevation: Elevation


class OpenTicketAccess(_Tickets):
    """The support person presents the code the approval issued. The guard opens one access for the
    ticket's tenant and an hour; the ticket then names the access. A code the guard redeems that
    is not this ticket's opens nothing: the access is ended at once."""

    async def execute(self, command: OpenTicketCommand) -> OpenedAccess:
        principal = _principal(command.principal)
        ticket = await self._own(principal, command.ticket_id)
        if effective_state(ticket, self._clock.now()) is not TicketState.APPROVED:
            raise CrossTenantDenied
        elevation = await self._guard.open(
            OpenAccessCommand(principal=principal, tenant_id=ticket.tenant_id, code=command.code)
        )
        try:
            if elevation.grant_hash != ticket.grant_hash:
                raise CrossTenantDenied
            opened = open_access(
                ticket,
                access_id=elevation.access_id,
                grant_hash=elevation.grant_hash,
                opened_at=elevation.opened_at,
                expires_at=elevation.expires_at,
            )
            if not await self._tickets.move(opened, TicketState.APPROVED):
                raise Conflict(MOVED)
            await self._guard.note_ticket(
                TicketNoteCommand(
                    principal=principal,
                    tenant_id=ticket.tenant_id,
                    action=ACTION_OPENED,
                    ticket_id=ticket.id,
                    access_id=elevation.access_id,
                )
            )
        except BaseException:
            await self._end_quietly(principal, elevation)
            raise
        return OpenedAccess(ticket=opened, elevation=elevation)

    async def _end_quietly(self, principal: PlatformPrincipal, elevation: Elevation) -> None:
        """An access the ticket could not take is not left open."""
        try:
            await self._guard.end(
                EndAccessCommand(
                    principal=principal,
                    tenant_id=elevation.tenant_id,
                    access_id=elevation.access_id,
                )
            )
        except Exception as error:
            log.error("an access could not be ended: %s", type(error).__name__)


@dataclass(frozen=True, slots=True)
class UseTicketCommand:
    principal: PlatformPrincipal
    ticket_id: str
    action: str


class UseTicketAccess(_Tickets):
    """Check one call under the ticket's access and write it to both chains: allowed only while the
    access stands for this person and this tenant (`CrossTenantGuard.authorise`). The support
    routes that read a tenant's data call this before every read."""

    async def execute(self, command: UseTicketCommand) -> Elevation:
        principal = _principal(command.principal)
        ticket = await self._own(principal, command.ticket_id)
        if effective_state(ticket, self._clock.now()) is not TicketState.OPENED:
            raise CrossTenantDenied
        return await self._guard.authorise(
            AuthoriseCommand(
                principal=principal,
                tenant_id=ticket.tenant_id,
                access_id=str(ticket.access_id),
                action=command.action,
            )
        )


class EndTicketAccess(_Tickets):
    """The support person ends the access at once; the access goes first, the ticket after."""

    async def execute(self, command: CancelTicketCommand) -> SupportTicket:
        principal = _principal(command.principal)
        ticket = await self._own(principal, command.ticket_id)
        now = self._clock.now()
        if effective_state(ticket, now) is not TicketState.OPENED:
            raise InvalidTransition("the ticket has no open access")
        await self._guard.end(
            EndAccessCommand(
                principal=principal,
                tenant_id=ticket.tenant_id,
                access_id=str(ticket.access_id),
            )
        )
        ended = end_access(ticket, by=EndedBy.SUPPORT, now=now)
        if not await self._tickets.move(ended, TicketState.OPENED):
            raise Conflict(MOVED)
        await self._guard.note_ticket(
            TicketNoteCommand(
                principal=principal,
                tenant_id=ticket.tenant_id,
                action=ACTION_ENDED,
                ticket_id=ticket.id,
                access_id=ticket.access_id,
            )
        )
        return ended


# ---------------------------------------------------------------- the tenant's administrator


@dataclass(frozen=True, slots=True)
class DecideTicketCommand:
    actor: Actor
    ticket_id: str


@dataclass(frozen=True, slots=True)
class ApprovedTicket:
    ticket: SupportTicket
    code: str
    code_expires_at: datetime

    def __repr__(self) -> str:
        return f"ApprovedTicket(ticket={self.ticket.id!r})"

    __str__ = __repr__


class ApproveSupportTicket(_Tickets):
    """Approve a pending ticket: issue the one-time code (returned once, held as a hash), move the
    ticket, write both chains. Any failure after the code exists takes the code back."""

    async def execute(self, command: DecideTicketCommand) -> ApprovedTicket:
        actor = command.actor
        administrator = _administrator(actor)
        ticket = await self._tenants(actor, command.ticket_id)
        now = self._clock.now()
        if effective_state(ticket, now) is not TicketState.PENDING:
            raise InvalidTransition(NOT_PENDING)
        issued = await self._guard.issue_code(IssueCodeCommand(actor=actor))
        try:
            approved = approve(
                ticket,
                decided_by_ref=administrator,
                grant_hash=issued.code_hash,
                grant_expires_at=issued.expires_at,
                now=now,
            )
            if not await self._tickets.move(approved, TicketState.PENDING):
                raise Conflict(MOVED)
        except BaseException:
            await self._withdraw(actor, issued.code_hash)
            raise
        try:
            await self._guard.note_decision(
                DecisionNoteCommand(
                    actor=actor,
                    action=ACTION_APPROVED,
                    ticket_id=ticket.id,
                    snapshot={"expires_at": issued.expires_at},
                )
            )
        except BaseException:
            # An approval that cannot be recorded does not stand.
            await self._withdraw(actor, issued.code_hash)
            await self._revoke_quietly(approved)
            raise
        return ApprovedTicket(ticket=approved, code=issued.code, code_expires_at=issued.expires_at)

    async def _withdraw(self, actor: Actor, code_hash: str) -> None:
        try:
            await self._guard.withdraw_code(WithdrawCodeCommand(actor=actor, code_hash=code_hash))
        except Exception as error:
            log.error("a support code could not be withdrawn: %s", type(error).__name__)

    async def _revoke_quietly(self, approved: SupportTicket) -> None:
        try:
            await self._tickets.move(revoke(approved, now=self._clock.now()), TicketState.APPROVED)
        except Exception as error:
            log.error("a support ticket could not be revoked: %s", type(error).__name__)


class RefuseSupportTicket(_Tickets):
    async def execute(self, command: DecideTicketCommand) -> SupportTicket:
        actor = command.actor
        administrator = _administrator(actor)
        ticket = await self._tenants(actor, command.ticket_id)
        refused = refuse(ticket, decided_by_ref=administrator, now=self._clock.now())
        if not await self._tickets.move(refused, TicketState.PENDING):
            raise Conflict(MOVED)
        await self._guard.note_decision(
            DecisionNoteCommand(actor=actor, action=ACTION_REFUSED, ticket_id=ticket.id)
        )
        return refused


class RevokeSupportTicket(_Tickets):
    """Take back an approved code or end an open access at once. The access or the code is removed
    first; the ticket is marked and recorded after."""

    async def execute(self, command: DecideTicketCommand) -> SupportTicket:
        actor = command.actor
        _administrator(actor)
        ticket = await self._tenants(actor, command.ticket_id)
        now = self._clock.now()
        revoked = revoke(ticket, now=now)  # refuses a ticket that cannot be revoked or has lapsed
        if ticket.state is TicketState.OPENED:
            # The access may already be gone from the cache (ended or lost): then nothing stands.
            with contextlib.suppress(CrossTenantDenied):
                await self._guard.revoke(
                    RevokeAccessCommand(actor=actor, access_id=str(ticket.access_id))
                )
        else:
            await self._guard.withdraw_code(
                WithdrawCodeCommand(actor=actor, code_hash=str(ticket.grant_hash))
            )
        if not await self._tickets.move(revoked, ticket.state):
            raise Conflict(MOVED)
        await self._guard.note_decision(
            DecisionNoteCommand(actor=actor, action=ACTION_REVOKED, ticket_id=ticket.id)
        )
        return revoked
