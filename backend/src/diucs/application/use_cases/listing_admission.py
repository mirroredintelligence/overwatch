"""Network administration, part three: listings (TEN-077, DEC-136 item 3, DEC-132 item 4, hazard
H-N12).

A provider registers its service in its own tenant and asks to list it on the network
(`RequestListing`: an active member, an active service of its own tenant, one live listing per
service); the network owner admits, declines, suspends or reinstates the listing, and the provider
withdraws it (`DecideListing`). A listing is the permission to project a service, not data: a
suspended listing stops projecting and reads as unavailable (the producer's gate and the network
board's presentation already follow the registry), and the heartbeat starts a newly admitted
service within its interval. Nothing here reads a service's figures.

The decider is checked by role before anything is read, and by ownership after: a network that is
not the actor's is the one `NotFound`. A decision is a compare-and-set on the status the decider
saw (a lost race is a `Conflict`), then recorded in the decider's scope and the network's (see
`network_admin.py`); the same decision repeated by the same person records nothing twice, and the
record's key holds the instant of the decision, so a second suspension months later is its own
record. A request whose records fail is withdrawn again (a compensation), so no orphan is left
pending. The owner sees the organisation and the service's reference: a listing carries no service
name (a known issue), and the member's tenant id is in no read model.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from diucs.application.actor import Actor, require_actor_in_bound_tenant
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.network_admin import (
    GovernanceRecorder,
    Record,
    account_ref_of,
    require_active,
    require_owner_of,
    require_role,
)
from diucs.domain.codes import Role
from diucs.domain.errors import InvalidTransition, NotFound, ValidationFailed
from diucs.domain.model.network import (
    Listing,
    ListingReason,
    ListingStatus,
    check_network_id,
    check_tenant_field,
)
from diucs.domain.rules.listing import (
    admit_listing,
    decline_listing,
    reinstate_listing,
    request_listing,
    suspend_listing,
    withdraw_listing,
)

logger = logging.getLogger(__name__)

NETWORK_NOT_FOUND: Final = "the network was not found"
LISTING_NOT_FOUND: Final = "the listing was not found"
SERVICE_NOT_FOUND: Final = "the service was not found"
REASON_NEEDED: Final = "needs a listing reason code"


_DIGITS_AS_LETTERS: Final = str.maketrans("0123456789", "ghijklmnop")


def _letters_only(raw: str) -> str:
    """The listing's id is the row reference of the network board, and the board refuses an id
    that the privacy guard reads as personal data (a postcode, a phone number, an NHS number): a
    random id can hold such a shape by chance, and one such listing would make the whole board
    fail. So the id is `lst-` and letters only: digits become letters and separators become one
    letter each, so two different inputs stay different."""
    return "lst-" + "".join(
        character.translate(_DIGITS_AS_LETTERS) if character.isalnum() else "q"
        for character in raw.lower()
    )


class ListingDecision(StrEnum):
    ADMIT = "admit"
    DECLINE = "decline"
    SUSPEND = "suspend"
    REINSTATE = "reinstate"
    WITHDRAW = "withdraw"


_USE_CASE: Final = {
    ListingDecision.ADMIT: "AdmitListing",
    ListingDecision.DECLINE: "DeclineListing",
    ListingDecision.SUSPEND: "SuspendListing",
    ListingDecision.REINSTATE: "ReinstateListing",
    ListingDecision.WITHDRAW: "WithdrawListing",
}
_TARGET: Final = {
    ListingDecision.ADMIT: ListingStatus.ADMITTED,
    ListingDecision.DECLINE: ListingStatus.DECLINED,
    ListingDecision.SUSPEND: ListingStatus.SUSPENDED,
    ListingDecision.REINSTATE: ListingStatus.ADMITTED,
    ListingDecision.WITHDRAW: ListingStatus.WITHDRAWN,
}
_NEEDS_REASON: Final = frozenset({ListingDecision.DECLINE, ListingDecision.SUSPEND})
_SOURCE_ROLES: Final = (Role.TENANT_ADMIN, Role.LEAD)


# ---------------------------------------------------------------- ask


@dataclass(frozen=True, slots=True)
class RequestListingCommand:
    actor: Actor
    network_id: str
    service_id: str


class RequestListing:
    def __init__(
        self,
        registry: NetworkRegistry,
        uow_factory: UnitOfWorkFactory,
        recorder: GovernanceRecorder,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._uow_factory = uow_factory
        self._recorder = recorder
        self._ids = ids
        self._clock = clock

    async def execute(self, command: RequestListingCommand) -> str:
        actor = command.actor
        require_role(actor, *_SOURCE_ROLES)
        require_actor_in_bound_tenant(actor)
        account_ref_of(actor)
        check_network_id(command.network_id)
        membership = await self._registry.active_membership(command.network_id, actor.tenant_id)
        if membership is None:
            raise NotFound(NETWORK_NOT_FOUND)
        await self._service_is_active(command.service_id)
        now = self._clock.now()
        listing = request_listing(
            list(await self._registry.listings_of(command.network_id, actor.tenant_id)),
            membership,
            id=_letters_only(self._ids.new_id()),
            network_id=command.network_id,
            source_service_id=command.service_id,
            now=now,
        )
        await self._registry.create_listing(listing)
        try:
            await self._recorder.write(
                actor,
                command.network_id,
                Record(
                    use_case="RequestListing",
                    key=f"RequestListing:{listing.id}",
                    entity_ids=(command.network_id, listing.id),
                    snapshot={"status": listing.status.value},
                ),
            )
        except Exception:
            await self._take_back(listing, actor)
            raise
        return listing.id

    async def _service_is_active(self, service_id: str) -> None:
        async with self._uow_factory() as uow:
            profile = await uow.services.get(service_id)
        if profile is None or not profile.active:
            raise NotFound(SERVICE_NOT_FOUND)

    async def _take_back(self, listing: Listing, actor: Actor) -> None:
        """Compensation: a request nobody recorded is withdrawn, not left pending."""
        try:
            withdrawn = withdraw_listing(
                listing,
                by_tenant_id=actor.tenant_id,
                account_ref=account_ref_of(actor),
                now=self._clock.now(),
            )
            await self._registry.save_listing(withdrawn, expected_status=ListingStatus.PENDING)
        except Exception as error:
            logger.warning("an unrecorded listing could not be withdrawn: %s", type(error).__name__)


# ---------------------------------------------------------------- decide


@dataclass(frozen=True, slots=True)
class DecideListingCommand:
    actor: Actor
    network_id: str
    listing_id: str
    decision: ListingDecision
    reason: ListingReason | None = None


class DecideListing:
    def __init__(
        self, registry: NetworkRegistry, recorder: GovernanceRecorder, clock: Clock
    ) -> None:
        self._registry = registry
        self._recorder = recorder
        self._clock = clock

    async def execute(self, command: DecideListingCommand) -> None:
        actor = command.actor
        decision = command.decision
        if type(decision) is not ListingDecision:
            raise ValidationFailed("decision", "is not a valid value for this field")
        if decision in _NEEDS_REASON and command.reason is None:
            raise ValidationFailed("reason", REASON_NEEDED)
        by_source = decision is ListingDecision.WITHDRAW
        require_role(actor, *(_SOURCE_ROLES if by_source else (Role.NETWORK_ADMIN,)))
        require_actor_in_bound_tenant(actor)
        account = account_ref_of(actor)
        check_network_id(command.network_id)
        registered = await self._registry.get_network(command.network_id)
        if by_source:
            if registered is None:
                raise NotFound(NETWORK_NOT_FOUND)
            network = registered.network
        else:
            network = require_owner_of(actor, registered)
        listing = await self._registry.get_listing(command.listing_id)
        if listing is None or listing.network_id != network.id:
            raise NotFound(LISTING_NOT_FOUND)
        if by_source and listing.source_tenant_id != actor.tenant_id:
            raise NotFound(LISTING_NOT_FOUND)
        if decision in (ListingDecision.ADMIT, ListingDecision.REINSTATE):
            require_active(network)
        target = _TARGET[decision]
        now = self._clock.now()
        if listing.status is target and listing.decided_by_account_ref == account:
            decided = listing  # a repeat by the same person: finish the records, change nothing
        else:
            decided = self._apply(command, listing, actor, account, network.owner_tenant_id, now)
            await self._registry.save_listing(decided, expected_status=listing.status)
        assert decided.decided_at is not None
        use_case = _USE_CASE[decision]
        await self._recorder.write(
            actor,
            network.id,
            Record(
                use_case=use_case,
                key=f"{use_case}:{decided.id}:{decided.decided_at.isoformat()}",
                entity_ids=(network.id, decided.id),
                snapshot={
                    "status": decided.status.value,
                    "reason": None if decided.reason is None else decided.reason.value,
                },
            ),
        )

    @staticmethod
    def _apply(
        command: DecideListingCommand,
        listing: Listing,
        actor: Actor,
        account: str,
        owner_tenant_id: str,
        now: datetime,
    ) -> Listing:
        check_tenant_field(owner_tenant_id, "owner_tenant_id")
        decision = command.decision
        if decision is ListingDecision.WITHDRAW:
            return withdraw_listing(
                listing, by_tenant_id=actor.tenant_id, account_ref=account, now=now
            )
        party = dict(by_tenant_id=actor.tenant_id, owner_tenant_id=owner_tenant_id)
        if decision is ListingDecision.ADMIT:
            return admit_listing(listing, account_ref=account, now=now, **party)
        if decision is ListingDecision.REINSTATE:
            return reinstate_listing(listing, account_ref=account, now=now, **party)
        reason = command.reason
        if reason is None:
            raise InvalidTransition(REASON_NEEDED)
        if decision is ListingDecision.DECLINE:
            return decline_listing(listing, reason=reason, account_ref=account, now=now, **party)
        return suspend_listing(listing, reason=reason, account_ref=account, now=now, **party)


# ---------------------------------------------------------------- reads


@dataclass(frozen=True, slots=True)
class ListingView:
    """A listing as an administrator reads it: its own id is the handle. The organisation is named
    (from the tenant directory); the member's tenant id is not in it."""

    listing_id: str
    organisation_name: str
    service_id: str
    status: ListingStatus
    reason: ListingReason | None
    requested_at: datetime
    decided_at: datetime | None


class QueryListings:
    def __init__(self, registry: NetworkRegistry, tenants: TenantDirectory) -> None:
        self._registry = registry
        self._tenants = tenants

    async def for_network(self, actor: Actor, network_id: str) -> list[ListingView]:
        """Every listing of the network: the owner's view."""
        require_role(actor, Role.NETWORK_ADMIN)
        check_network_id(network_id)
        network = require_owner_of(actor, await self._registry.get_network(network_id))
        views: list[ListingView] = []
        for listing in await self._registry.listings(network.id):
            member = await self._tenants.get(listing.source_tenant_id)
            views.append(
                _view(listing, "(unknown organisation)" if member is None else member.display_name)
            )
        return views

    async def of_member(self, actor: Actor, network_id: str) -> list[ListingView]:
        """The actor's own organisation's listings in this network."""
        require_role(actor, *_SOURCE_ROLES)
        check_network_id(network_id)
        rows = [
            m
            for m in await self._registry.memberships_of(actor.tenant_id)
            if m.network_id == network_id
        ]
        if not rows:
            raise NotFound(NETWORK_NOT_FOUND)
        own = await self._tenants.get(actor.tenant_id)
        name = "(unknown organisation)" if own is None else own.display_name
        return [
            _view(x, name) for x in await self._registry.listings_of(network_id, actor.tenant_id)
        ]


def _view(listing: Listing, name: str) -> ListingView:
    return ListingView(
        listing_id=listing.id,
        organisation_name=name,
        service_id=listing.source_service_id,
        status=listing.status,
        reason=listing.reason,
        requested_at=listing.requested_at,
        decided_at=listing.decided_at,
    )
