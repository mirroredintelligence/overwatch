"""Network administration, part two: members (TEN-077, DEC-132 items 3 and 6, audit F 4.5).

Inviting, accepting, leaving and removing. The rules (who may be invited, the agreement version a
member accepts, that the owner cannot leave, what ending does to a row) are the domain's
(`domain/model/network.py`); this module orders the steps across the registry and the two scopes
(see `network_admin.py` for the saga's shape).

**Ending a membership** keeps DEC-132 item 6: the registry's membership closes (it is the gate: from
that write a member is refused at once), the member's live grants lapse, its live listings are
withdrawn, its sources in the network scope end with the leave date and its rows are marked
(`EndProjections`), and the records follow with a `MemberRemoved` event published by the acting
tenant (the member, for a leave; the owner, for a removal). Nothing is deleted. A grant the
grantor ended at the same moment is terminal either way, so the lost race is not a failure. A step
that fails after the registry write is finished by running the same command again: the closed row
is found, its leave date is kept (the first one), each step does only what is left, and the records
are written once (the key is the membership). The heartbeat's reconciliation also ends the sources
of a member that left, for the day after, if the network step was lost.

An invitation that was never accepted is removed, not left, and has nothing in the network scope.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor, require_actor_in_bound_tenant
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.use_cases.network_admin import (
    GovernanceRecorder,
    Record,
    account_ref_of,
    require_active,
    require_owner_of,
    require_role,
)
from diucs.application.use_cases.network_leave import EndProjections
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotFound
from diucs.domain.events import MemberAdded, MemberRemoved
from diucs.domain.model.network import (
    MembershipEndReason,
    MembershipStatus,
    Network,
    NetworkMembership,
    accept_membership,
    check_network_id,
    check_tenant_field,
    end_membership,
    invite_member,
)
from diucs.domain.model.tenant import TenantStatus
from diucs.domain.rules.grant import lapse_grants_for_member
from diucs.domain.rules.listing import withdraw_for_leave

logger = logging.getLogger(__name__)

NETWORK_NOT_FOUND: Final = "the network was not found"
MEMBERSHIP_NOT_FOUND: Final = "the membership was not found"
CANNOT_INVITE: Final = "the organisation cannot be invited"


async def _network(registry: NetworkRegistry, network_id: str) -> Network:
    check_network_id(network_id)
    registered = await registry.get_network(network_id)
    if registered is None:
        raise NotFound(NETWORK_NOT_FOUND)
    return registered.network


# ---------------------------------------------------------------- invite


@dataclass(frozen=True, slots=True)
class InviteMemberCommand:
    actor: Actor
    network_id: str
    tenant_id: str
    """The organisation to invite, by the id the platform knows it by."""


@dataclass(frozen=True, slots=True)
class InviteMemberResult:
    membership_id: str


class InviteMember:
    def __init__(
        self,
        registry: NetworkRegistry,
        tenants: TenantDirectory,
        recorder: GovernanceRecorder,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._tenants = tenants
        self._recorder = recorder
        self._ids = ids
        self._clock = clock

    async def execute(self, command: InviteMemberCommand) -> InviteMemberResult:
        actor = command.actor
        require_role(actor, Role.NETWORK_ADMIN)
        require_actor_in_bound_tenant(actor)
        account_ref_of(actor)
        check_network_id(command.network_id)
        check_tenant_field(command.tenant_id, "tenant_id")
        network = require_owner_of(actor, await self._registry.get_network(command.network_id))
        require_active(network)
        invited = await self._tenants.get(command.tenant_id)
        # One answer for an organisation that is unknown and one that is not active, so the owner
        # learns nothing about the platform's other tenants.
        if invited is None or invited.status is not TenantStatus.ACTIVE:
            raise NotFound(CANNOT_INVITE)
        now = self._clock.now()
        row = invite_member(
            network,
            list(await self._registry.memberships(network.id)),
            id=self._ids.new_id(),
            tenant_id=command.tenant_id,
            now=now,
        )
        await self._registry.create_membership(row)
        try:
            await self._recorder.write(
                actor,
                network.id,
                Record(
                    use_case="InviteMember",
                    key=f"InviteMember:{row.id}",
                    entity_ids=(network.id, row.id),
                    snapshot={"role": row.role.value},
                ),
            )
        except Exception:
            await self._take_back(network, row)
            raise
        return InviteMemberResult(row.id)

    async def _take_back(self, network: Network, row: NetworkMembership) -> None:
        """Compensation: an invitation nobody recorded is not left waiting."""
        try:
            removed = end_membership(
                network, row, reason=MembershipEndReason.REMOVED, now=self._clock.now()
            )
            await self._registry.save_membership(removed, expected_status=MembershipStatus.INVITED)
        except Exception as error:
            logger.warning(
                "an unrecorded invitation could not be taken back: %s", type(error).__name__
            )


# ---------------------------------------------------------------- accept


@dataclass(frozen=True, slots=True)
class AcceptMembershipCommand:
    actor: Actor
    membership_id: str
    agreement_version: int
    """The version the administrator read: it must still be the network's current one."""


class AcceptMembership:
    def __init__(
        self, registry: NetworkRegistry, recorder: GovernanceRecorder, clock: Clock
    ) -> None:
        self._registry = registry
        self._recorder = recorder
        self._clock = clock

    async def execute(self, command: AcceptMembershipCommand) -> None:
        actor = command.actor
        require_role(actor, Role.TENANT_ADMIN)
        require_actor_in_bound_tenant(actor)
        account = account_ref_of(actor)
        row = next(
            (
                r
                for r in await self._registry.memberships_of(actor.tenant_id)
                if r.id == command.membership_id
            ),
            None,
        )
        if row is None:
            raise NotFound(MEMBERSHIP_NOT_FOUND)
        network = await _network(self._registry, row.network_id)
        agreement = network.agreement
        if agreement is None or agreement.version != command.agreement_version:
            raise Conflict("the agreement version is not the current one")
        now = self._clock.now()
        if row.status is not MembershipStatus.ACTIVE:
            accepted = accept_membership(
                network, row, agreement=agreement, account_ref=account, now=now
            )
            await self._registry.save_membership(accepted, expected_status=MembershipStatus.INVITED)
        elif row.accepted_agreement != agreement:
            raise Conflict("the agreement version is not the current one")
        await self._recorder.write(
            actor,
            network.id,
            Record(
                use_case="AcceptMembership",
                key=f"AcceptMembership:{row.id}",
                entity_ids=(network.id, row.id),
                snapshot={"agreement_version": agreement.version},
                events=(MemberAdded(network.id, row.member_tenant_id, now),),
            ),
        )


# ---------------------------------------------------------------- end: leave and remove


@dataclass(frozen=True, slots=True)
class EndMembershipResult:
    grants_lapsed: int
    listings_withdrawn: int
    sources_ended: int
    resumed: bool
    """True when the registry already held the closed row and this run finished what was left."""


class _Ending:
    """The steps both a leave and a removal take, after the role and the row are settled."""

    def __init__(
        self,
        registry: NetworkRegistry,
        ends: EndProjections,
        recorder: GovernanceRecorder,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._ends = ends
        self._recorder = recorder
        self._clock = clock

    async def run(
        self,
        actor: Actor,
        network: Network,
        row: NetworkMembership,
        reason: MembershipEndReason,
        use_case: str,
    ) -> EndMembershipResult:
        resumed = row.status in (MembershipStatus.LEFT, MembershipStatus.REMOVED)
        was_invited = row.status is MembershipStatus.INVITED
        # 1. the registry's membership: the gate closes, and the leave date is decided
        ended = end_membership(network, row, reason=reason, now=self._clock.now())
        if not resumed:
            await self._registry.save_membership(ended, expected_status=row.status)
        assert ended.left_at is not None
        at = ended.left_at
        lapsed = withdrawn = sources = 0
        if not was_invited:
            lapsed = await self._lapse_grants(ended, at)
            withdrawn = await self._withdraw_listings(network, ended, at)
            # 4. the network scope: the sources end and the rows are marked (history stays)
            sources = (
                await self._ends.end_member(network.id, ended.member_tenant_id, at=at)
            ).sources_ended
        await self._recorder.write(
            actor,
            network.id,
            Record(
                use_case=use_case,
                key=f"EndMembership:{ended.id}",
                entity_ids=(network.id, ended.id),
                snapshot={
                    "reason": reason.value,
                    "grants_lapsed": lapsed,
                    "listings_withdrawn": withdrawn,
                },
                events=(MemberRemoved(network.id, ended.member_tenant_id, reason, at),),
            ),
        )
        return EndMembershipResult(lapsed, withdrawn, sources, resumed)

    async def _lapse_grants(self, ended: NetworkMembership, at: datetime) -> int:
        grants = list(await self._registry.grants_of(ended.member_tenant_id))
        held = {g.id: g.status for g in grants}
        count = 0
        for lapsed in lapse_grants_for_member(grants, ended, now=at):
            try:
                await self._registry.save_grant(lapsed, expected_status=held[lapsed.id])
                count += 1
            except Conflict:
                # The grantor ended it at the same moment: terminal either way.
                logger.info("a grant changed while its member was leaving")
        return count

    async def _withdraw_listings(
        self, network: Network, ended: NetworkMembership, at: datetime
    ) -> int:
        listings = list(await self._registry.listings_of(network.id, ended.member_tenant_id))
        held = {x.id: x.status for x in listings}
        count = 0
        for withdrawn in withdraw_for_leave(listings, ended, now=at):
            try:
                await self._registry.save_listing(withdrawn, expected_status=held[withdrawn.id])
                count += 1
            except Conflict:
                logger.info("a listing changed while its member was leaving")
        return count


@dataclass(frozen=True, slots=True)
class LeaveNetworkCommand:
    actor: Actor
    network_id: str


class LeaveNetwork:
    def __init__(
        self,
        registry: NetworkRegistry,
        ends: EndProjections,
        recorder: GovernanceRecorder,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._ending = _Ending(registry, ends, recorder, clock)

    async def execute(self, command: LeaveNetworkCommand) -> EndMembershipResult:
        actor = command.actor
        require_role(actor, Role.TENANT_ADMIN)
        require_actor_in_bound_tenant(actor)
        account_ref_of(actor)
        network = await _network(self._registry, command.network_id)
        rows = [
            r
            for r in await self._registry.memberships_of(actor.tenant_id)
            if r.network_id == network.id
        ]
        row = next((r for r in rows if r.status is MembershipStatus.ACTIVE), None)
        if row is None:  # a leave that stopped: finish the latest closed row
            closed = [
                r
                for r in rows
                if r.status is MembershipStatus.LEFT and r.end_reason is MembershipEndReason.LEFT
            ]
            row = max(closed, key=lambda r: str(r.left_at), default=None)
        if row is None:
            raise NotFound(MEMBERSHIP_NOT_FOUND)
        return await self._ending.run(actor, network, row, MembershipEndReason.LEFT, "LeaveNetwork")


@dataclass(frozen=True, slots=True)
class RemoveMemberCommand:
    actor: Actor
    network_id: str
    membership_id: str


class RemoveMember:
    def __init__(
        self,
        registry: NetworkRegistry,
        ends: EndProjections,
        recorder: GovernanceRecorder,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._ending = _Ending(registry, ends, recorder, clock)

    async def execute(self, command: RemoveMemberCommand) -> EndMembershipResult:
        actor = command.actor
        require_role(actor, Role.NETWORK_ADMIN)
        require_actor_in_bound_tenant(actor)
        account_ref_of(actor)
        check_network_id(command.network_id)
        registered = await self._registry.get_network(command.network_id)
        network = require_owner_of(actor, registered)
        row = next(
            (
                r
                for r in await self._registry.memberships(network.id)
                if r.id == command.membership_id
            ),
            None,
        )
        if row is None:
            raise NotFound(MEMBERSHIP_NOT_FOUND)
        return await self._ending.run(
            actor, network, row, MembershipEndReason.REMOVED, "RemoveMember"
        )
