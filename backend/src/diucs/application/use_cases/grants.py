"""Network administration, part four: grants and the cross-scope saga (TEN-078, DEC-132 items 3
and 6, DEC-134 item 6, DEC-136 item 4, audit F section 4.6).

A grant is the only way data is shared. The rules (who approves, that two different accounts give
the two approvals, the window, that only the grantor ends one, versions and supersession) are the
domain's (`domain/rules/grant.py`, TEN-036); effectiveness is computed from them at the instant
asked and never stored. This module orders the steps across the registry and the two scopes.

**The saga, command by command** (the shape is in `network_admin.py`: the registry first, because
it decides a race and is the gate; the records after, repeatably, each keyed by the action):

- `ProposeGrant` and `ReviseGrant` create a proposed grant (a revision is the next version, with
  `supersedes_id`). If the records then fail the grant is declined again (a compensation), so no
  proposal is left that nobody recorded.
- `ApproveGrant` is one party's approval, the grantor's administrator (a `tenant-admin` of the
  grantor) or the owner's (`network-admin` of the owner); either order; when the second arrives the
  grant is approved and `GrantEffective` is published by the approver's tenant, which is what
  starts the grantor's projection (the projector's governance consumer, TEN-056). An approved
  revision that has started replaces its predecessor at once (`GrantEnded`, reason `superseded`);
  one that starts later replaces it when the heartbeat finds it due (`SupersedeDueGrants`): there
  is never a gap or an overlap, because the predecessor's window is cut where the successor starts.
- `EndGrant` is the grantor's alone: the registry's end first (from that write the projector's gate
  is closed), then the network scope's end (`EndProjections`: the source and the rows end with the
  date, nothing is deleted), then the records and `GrantEnded`. The owner cannot end a member's
  grant; it removes the member.
- `DeclineGrant` is either party's, before both approvals; after them only ending applies.

A step that fails after the registry write is finished by running the same command again: the
registry write is found done (an approval by the same account, an end of an ended grant, with its
first date) and the rest does only what is left. Nothing here reads or writes a capacity figure.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor, require_actor_in_bound_tenant, system_actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.network_admin import (
    AUDIT_CREATE,
    GovernanceRecorder,
    Record,
    account_ref_of,
    require_active,
    require_owner_of,
    require_role,
)
from diucs.application.use_cases.network_leave import EndProjections
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, InvalidTransition, NotFound, ValidationFailed
from diucs.domain.events import GrantApproved, GrantEffective, GrantEnded, GrantProposed
from diucs.domain.model.network import (
    Agreement,
    Grant,
    GrantApprover,
    GrantEndReason,
    GrantPurpose,
    GrantScope,
    GrantStatus,
    Network,
    check_network_id,
)
from diucs.domain.rules.grant import (
    approve_grant,
    decline_grant,
    end_grant,
    end_reason,
    is_effective,
    propose_grant,
    revise_grant,
    supersede_grant,
)
from diucs.domain.rules.projection import PROJECTION_ALLOWLIST_VERSION

logger = logging.getLogger(__name__)

NETWORK_NOT_FOUND: Final = "the network was not found"
GRANT_NOT_FOUND: Final = "the grant was not found"
OPEN_GRANT: Final = "a grant for this scope is already open; revise it instead"
OPEN_REVISION: Final = "this grant already has a revision waiting"
NO_AGREEMENT: Final = "the network has no agreement in force"

_OPEN: Final = frozenset(
    {
        GrantStatus.PROPOSED,
        GrantStatus.GRANTOR_APPROVED,
        GrantStatus.OWNER_APPROVED,
        GrantStatus.APPROVED,
    }
)


def _identity(grant: Grant) -> tuple[str, str, str, GrantScope, int]:
    return grant.id, grant.network_id, grant.grantor_tenant_id, grant.scope, grant.version


async def _network(registry: NetworkRegistry, network_id: str) -> Network:
    check_network_id(network_id)
    registered = await registry.get_network(network_id)
    if registered is None:
        raise NotFound(NETWORK_NOT_FOUND)
    return registered.network


async def _grant_of(registry: NetworkRegistry, grant_id: str) -> Grant:
    grant = await registry.get_grant(grant_id)
    if grant is None:
        raise NotFound(GRANT_NOT_FOUND)
    return grant


def _agreement(network: Network) -> Agreement:
    if network.agreement is None:
        raise Conflict(NO_AGREEMENT)
    return network.agreement


# ---------------------------------------------------------------- propose and revise


@dataclass(frozen=True, slots=True)
class ProposeGrantCommand:
    actor: Actor
    network_id: str
    scope: GrantScope
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class _Creates:
    """The part a proposal and a revision share: record the creation and take the grant back if the
    records fail."""

    def __init__(
        self, registry: NetworkRegistry, recorder: GovernanceRecorder, clock: Clock
    ) -> None:
        self._registry = registry
        self._recorder = recorder
        self._clock = clock

    async def record(self, actor: Actor, network: Network, grant: Grant, use_case: str) -> None:
        try:
            await self._recorder.write(
                actor,
                network.id,
                Record(
                    use_case=use_case,
                    key=f"{use_case}:{grant.id}",
                    entity_ids=(network.id, grant.id),
                    snapshot={
                        "scope": grant.scope.value,
                        "version": grant.version,
                        "agreement_version": grant.agreement.version,
                    },
                    events=(
                        GrantProposed(
                            grant.id,
                            network.id,
                            grant.grantor_tenant_id,
                            grant.scope,
                            grant.version,
                            self._clock.now(),
                        ),
                    ),
                    action=AUDIT_CREATE,
                ),
            )
        except Exception:
            await self._take_back(actor, network, grant)
            raise

    async def _take_back(self, actor: Actor, network: Network, grant: Grant) -> None:
        """Compensation: a proposal nobody recorded is declined, not left waiting for approvals."""
        try:
            declined = decline_grant(
                grant,
                by_tenant_id=actor.tenant_id,
                network_owner_tenant_id=network.owner_tenant_id,
                account_ref=account_ref_of(actor),
                now=self._clock.now(),
            )
            await self._registry.save_grant(declined, expected_status=GrantStatus.PROPOSED)
        except Exception as error:
            logger.warning("an unrecorded grant could not be declined: %s", type(error).__name__)


class ProposeGrant:
    def __init__(
        self,
        registry: NetworkRegistry,
        recorder: GovernanceRecorder,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._ids = ids
        self._clock = clock
        self._creates = _Creates(registry, recorder, clock)

    async def execute(self, command: ProposeGrantCommand) -> str:
        actor = command.actor
        require_role(actor, Role.TENANT_ADMIN)
        require_actor_in_bound_tenant(actor)
        account = account_ref_of(actor)
        check_network_id(command.network_id)
        if await self._registry.active_membership(command.network_id, actor.tenant_id) is None:
            raise NotFound(NETWORK_NOT_FOUND)
        network = await _network(self._registry, command.network_id)
        require_active(network)
        now = self._clock.now()
        earlier = [
            g
            for g in await self._registry.grants_of(actor.tenant_id)
            if g.network_id == network.id and g.scope is command.scope
        ]
        if any(g.status in _OPEN for g in earlier):
            raise Conflict(OPEN_GRANT)
        grant = propose_grant(
            id=self._ids.new_id(),
            network_id=network.id,
            grantor_tenant_id=actor.tenant_id,
            scope=command.scope,
            purpose=GrantPurpose.NETWORK_CAPACITY_VIEW,
            effective_from=command.effective_from or now,
            effective_to=command.effective_to,
            agreement=_agreement(network),
            allowlist_version=PROJECTION_ALLOWLIST_VERSION,
            proposed_by_account_ref=account,
            proposed_at=now,
        )
        # a version is unique per (network, grantor, scope): a new grant after an ended one is the
        # next version, so the history of one scope reads as one line
        grant = replace(grant, version=max((g.version for g in earlier), default=0) + 1)
        await self._registry.create_grant(grant)
        await self._creates.record(actor, network, grant, "ProposeGrant")
        return grant.id


@dataclass(frozen=True, slots=True)
class ReviseGrantCommand:
    actor: Actor
    grant_id: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class ReviseGrant:
    def __init__(
        self,
        registry: NetworkRegistry,
        recorder: GovernanceRecorder,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._ids = ids
        self._clock = clock
        self._creates = _Creates(registry, recorder, clock)

    async def execute(self, command: ReviseGrantCommand) -> str:
        actor = command.actor
        require_role(actor, Role.TENANT_ADMIN)
        require_actor_in_bound_tenant(actor)
        account = account_ref_of(actor)
        current = await _grant_of(self._registry, command.grant_id)
        if current.grantor_tenant_id != actor.tenant_id:
            raise NotFound(GRANT_NOT_FOUND)
        network = await _network(self._registry, current.network_id)
        require_active(network)
        if any(
            g.supersedes_id == current.id and g.status in _OPEN
            for g in await self._registry.grants_of(actor.tenant_id)
        ):
            raise Conflict(OPEN_REVISION)
        now = self._clock.now()
        revision = revise_grant(
            current,
            new_id=self._ids.new_id(),
            effective_from=command.effective_from or now,
            effective_to=command.effective_to,
            agreement=_agreement(network),
            allowlist_version=PROJECTION_ALLOWLIST_VERSION,
            proposed_by_account_ref=account,
            now=now,
        )
        await self._registry.create_grant(revision)
        await self._creates.record(actor, network, revision, "ReviseGrant")
        return revision.id


# ---------------------------------------------------------------- approve and decline


@dataclass(frozen=True, slots=True)
class ApproveGrantCommand:
    actor: Actor
    grant_id: str


@dataclass(frozen=True, slots=True)
class ApproveGrantResult:
    effective: bool
    """True when both approvals are in (the grant is approved: effective from its start)."""


class ApproveGrant:
    def __init__(
        self, registry: NetworkRegistry, recorder: GovernanceRecorder, clock: Clock
    ) -> None:
        self._registry = registry
        self._recorder = recorder
        self._clock = clock
        self._superseder = SupersedeDueGrants(registry, recorder, clock)

    async def execute(self, command: ApproveGrantCommand) -> ApproveGrantResult:
        actor = command.actor
        require_role(actor, Role.TENANT_ADMIN, Role.NETWORK_ADMIN)
        require_actor_in_bound_tenant(actor)
        account = account_ref_of(actor)
        grant = await _grant_of(self._registry, command.grant_id)
        network = await _network(self._registry, grant.network_id)
        if actor.role is Role.TENANT_ADMIN:
            approver = GrantApprover.GRANTOR
            party_ok = grant.grantor_tenant_id == actor.tenant_id
        else:
            approver = GrantApprover.OWNER
            party_ok = network.owner_tenant_id == actor.tenant_id
        if not party_ok:
            raise NotFound(GRANT_NOT_FOUND)
        require_active(network)
        now = self._clock.now()
        approved = approve_grant(
            grant,
            approver=approver,
            approver_tenant_id=actor.tenant_id,
            network_owner_tenant_id=network.owner_tenant_id,
            account_ref=account,
            now=now,
        )
        if approved != grant:
            await self._registry.save_grant(approved, expected_status=grant.status)
        mine = (
            approved.grantor_approval
            if approver is GrantApprover.GRANTOR
            else approved.owner_approval
        )
        other = (
            approved.owner_approval
            if approver is GrantApprover.GRANTOR
            else approved.grantor_approval
        )
        assert mine is not None
        effective = approved.status is GrantStatus.APPROVED
        events: list[GrantApproved | GrantEffective] = [
            GrantApproved(*_identity(approved), approver, mine.at)
        ]
        if effective and other is not None and mine.at >= other.at:
            events.append(GrantEffective(*_identity(approved), approved.effective_from, mine.at))
        await self._recorder.write(
            actor,
            network.id,
            Record(
                use_case="ApproveGrant",
                key=f"ApproveGrant:{approved.id}:{approver.value}",
                entity_ids=(network.id, approved.id),
                snapshot={
                    "by": approver.value,
                    "status": approved.status.value,
                    "scope": approved.scope.value,
                    "version": approved.version,
                },
                events=tuple(events),
            ),
        )
        if effective and approved.supersedes_id is not None:
            await self._superseder.supersede_one(actor, approved, now)
        return ApproveGrantResult(effective)


@dataclass(frozen=True, slots=True)
class DeclineGrantCommand:
    actor: Actor
    grant_id: str


class DeclineGrant:
    def __init__(
        self, registry: NetworkRegistry, recorder: GovernanceRecorder, clock: Clock
    ) -> None:
        self._registry = registry
        self._recorder = recorder
        self._clock = clock

    async def execute(self, command: DeclineGrantCommand) -> None:
        actor = command.actor
        require_role(actor, Role.TENANT_ADMIN, Role.NETWORK_ADMIN)
        require_actor_in_bound_tenant(actor)
        account = account_ref_of(actor)
        grant = await _grant_of(self._registry, command.grant_id)
        network = await _network(self._registry, grant.network_id)
        party = (
            grant.grantor_tenant_id if actor.role is Role.TENANT_ADMIN else network.owner_tenant_id
        )
        if party != actor.tenant_id:
            raise NotFound(GRANT_NOT_FOUND)
        if grant.status is GrantStatus.DECLINED:
            declined = grant  # a repeat: finish the records
        else:
            declined = decline_grant(
                grant,
                by_tenant_id=actor.tenant_id,
                network_owner_tenant_id=network.owner_tenant_id,
                account_ref=account,
                now=self._clock.now(),
            )
            await self._registry.save_grant(declined, expected_status=grant.status)
        await self._recorder.write(
            actor,
            network.id,
            Record(
                use_case="DeclineGrant",
                key=f"DeclineGrant:{declined.id}",
                entity_ids=(network.id, declined.id),
                snapshot={"scope": declined.scope.value, "version": declined.version},
            ),
        )


# ---------------------------------------------------------------- end


@dataclass(frozen=True, slots=True)
class EndGrantCommand:
    actor: Actor
    grant_id: str


class EndGrant:
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

    async def execute(self, command: EndGrantCommand) -> None:
        actor = command.actor
        require_role(actor, Role.TENANT_ADMIN)  # the owner removes a member; it never ends a grant
        require_actor_in_bound_tenant(actor)
        account = account_ref_of(actor)
        grant = await _grant_of(self._registry, command.grant_id)
        if grant.grantor_tenant_id != actor.tenant_id:
            raise NotFound(GRANT_NOT_FOUND)
        # 1. the registry: from this write the projector's gate is closed
        ended = end_grant(
            grant, by_tenant_id=actor.tenant_id, account_ref=account, now=self._clock.now()
        )
        if ended != grant:
            await self._registry.save_grant(ended, expected_status=grant.status)
        assert ended.ended_at is not None
        # 2. the network scope: the source and its rows end, dated by the end (history stays)
        await self._ends.end_grant(
            ended.network_id,
            ended.grantor_tenant_id,
            ended.scope,
            reason=GrantEndReason.ENDED,
            at=ended.ended_at,
        )
        # 3. the records and the event
        await self._recorder.write(
            actor,
            ended.network_id,
            Record(
                use_case="EndGrant",
                key=f"EndGrant:{ended.id}",
                entity_ids=(ended.network_id, ended.id),
                snapshot={"scope": ended.scope.value, "version": ended.version},
                events=(GrantEnded(*_identity(ended), GrantEndReason.ENDED, ended.ended_at),),
            ),
        )


# ---------------------------------------------------------------- supersession


class SupersedeDueGrants:
    """A revision that is approved and has started replaces its predecessor (the heartbeat runs
    this for the tenant, so a revision that starts later is carried out when it is due)."""

    def __init__(
        self, registry: NetworkRegistry, recorder: GovernanceRecorder, clock: Clock
    ) -> None:
        self._registry = registry
        self._recorder = recorder
        self._clock = clock

    async def execute(self, tenant_id: str) -> int:
        now = self._clock.now()
        done = 0
        with bind_tenant(tenant_id):
            actor = system_actor(tenant_id, "grants")
            grants = list(await self._registry.grants_of(tenant_id))
            for successor in grants:
                if (
                    successor.status is GrantStatus.APPROVED
                    and successor.supersedes_id is not None
                    and await self.supersede_one(actor, successor, now)
                ):
                    done += 1
        return done

    async def supersede_one(self, actor: Actor, successor: Grant, now: datetime) -> bool:
        """Supersede the predecessor of this approved successor if it is approved and the successor
        has started. True when it did."""
        if successor.supersedes_id is None or now < successor.effective_from:
            return False
        old = await self._registry.get_grant(successor.supersedes_id)
        if old is None or old.status is not GrantStatus.APPROVED:
            return False
        try:
            superseded = supersede_grant(old, successor, now=now)
        except Conflict, InvalidTransition, ValidationFailed:
            return False
        await self._registry.save_grant(superseded, expected_status=GrantStatus.APPROVED)
        await self._recorder.write(
            actor,
            old.network_id,
            Record(
                use_case="SupersedeGrant",
                key=f"SupersedeGrant:{old.id}",
                entity_ids=(old.network_id, old.id, successor.id),
                snapshot={"scope": old.scope.value, "version": old.version},
                events=(GrantEnded(*_identity(old), GrantEndReason.SUPERSEDED, now),),
            ),
        )
        return True


# ---------------------------------------------------------------- reads


@dataclass(frozen=True, slots=True)
class GrantView:
    """A grant as an administrator reads it. Approvals are shown as the times they were given:
    never who gave them. `effective` is computed at the time of the read."""

    grant_id: str
    network_id: str
    network_name: str
    organisation_name: str
    scope: GrantScope
    status: GrantStatus
    version: int
    effective_from: datetime
    effective_to: datetime | None
    agreement_version: int
    allowlist_version: int
    grantor_approved_at: datetime | None
    owner_approved_at: datetime | None
    ended_at: datetime | None
    end_reason: GrantEndReason | None
    supersedes_id: str | None
    effective: bool


class QueryGrants:
    def __init__(self, registry: NetworkRegistry, tenants: TenantDirectory, clock: Clock) -> None:
        self._registry = registry
        self._tenants = tenants
        self._clock = clock

    async def for_tenant(self, actor: Actor) -> Sequence[GrantView]:
        """The grants the actor's own organisation has given, in every network."""
        require_role(actor, Role.TENANT_ADMIN)
        own = await self._tenants.get(actor.tenant_id)
        name = "(unknown organisation)" if own is None else own.display_name
        views: list[GrantView] = []
        for grant in await self._registry.grants_of(actor.tenant_id):
            registered = await self._registry.get_network(grant.network_id)
            if registered is None:
                continue
            views.append(self._view(grant, registered.network.name, name))
        return views

    async def for_network(self, actor: Actor, network_id: str) -> Sequence[GrantView]:
        """Every grant of the network: the owner's view."""
        require_role(actor, Role.NETWORK_ADMIN)
        check_network_id(network_id)
        network = require_owner_of(actor, await self._registry.get_network(network_id))
        views: list[GrantView] = []
        for grant in await self._registry.grants(network.id):
            member = await self._tenants.get(grant.grantor_tenant_id)
            views.append(
                self._view(
                    grant,
                    network.name,
                    "(unknown organisation)" if member is None else member.display_name,
                )
            )
        return views

    def _view(self, grant: Grant, network_name: str, organisation_name: str) -> GrantView:
        return GrantView(
            grant_id=grant.id,
            network_id=grant.network_id,
            network_name=network_name,
            organisation_name=organisation_name,
            scope=grant.scope,
            status=grant.status,
            version=grant.version,
            effective_from=grant.effective_from,
            effective_to=grant.effective_to,
            agreement_version=grant.agreement.version,
            allowlist_version=grant.allowlist_version,
            grantor_approved_at=None
            if grant.grantor_approval is None
            else grant.grantor_approval.at,
            owner_approved_at=None if grant.owner_approval is None else grant.owner_approval.at,
            ended_at=grant.ended_at,
            end_reason=end_reason(grant),
            supersedes_id=grant.supersedes_id,
            effective=is_effective(grant, self._clock.now()),
        )
