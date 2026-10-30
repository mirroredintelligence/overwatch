"""The network projection producer (TEN-054, DEC-543, DEC-132 item 4, DEC-134 items 6 and 7).

The producer is the first of the two units of work that move a member's capacity into a network:
it reads in the member's tenant scope, in a read-only unit that is closed before anything is sent,
builds the allowlisted DTOs with the pure builders (`domain/rules/projection.py`), and publishes
one `ProjectionRequested` message for each grant that may project now and each service the network
owner has admitted. It writes nothing, and it never holds a network scope: the network is reached
only by the apply step (`apply_projection.py`), in its own unit of work.

The gates, in the order they are asked (cheapest first, so a member with no grant costs one
registry read and no unit):

1. the registry's gate, `active_grants_for(tenant, kind, now)`: the grants of the bound tenant that
   are effective now, in an active network where the tenant is an active member;
2. the registry's listings: a service is projected into a network only while the owner has admitted
   it there (`may_project_listing`, DEC-136 item 3), so a pending, declined, suspended or
   withdrawn listing projects nothing new.

Nothing time-dependent is sent as a result: the capacity DTO carries the inputs of the status and
the network read computes it (DEC-134 item 6). `source_version` of a capacity DTO is the instant
the producer read the source, in milliseconds (DEC-270 item 4); of a service the version of the
stored resource; of criteria the version number. The tenant is read from the bound scope
(`current_tenant()`, which refuses a network scope) and never taken as an argument.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.network import ActiveGrant, NetworkRegistry
from diucs.application.ports.outbound.projection import ProjectionPublisher
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.projection import Projection, to_body
from diucs.application.tenancy import current_tenant
from diucs.domain.errors import ValidationFailed
from diucs.domain.events import ProjectionRequested
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.model.network import GrantScope
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules.listing import may_project_listing
from diucs.domain.rules.projection import (
    PROJECTION_ALLOWLIST_VERSION,
    CriteriaProjection,
    build_capacity_projection,
    build_criteria_projection,
    build_service_projection,
)

_ALL_KINDS: Final = tuple(GrantScope)


class ProducerUnitNotReadOnly(RuntimeError):
    """The unit of work the producer was given can write. The producer reads and writes nothing, so
    it refuses one that could (the composition root hands it a read-only factory)."""

    def __init__(self) -> None:
        super().__init__("the projection producer reads in a read-only unit of work")


@dataclass(frozen=True, slots=True)
class ProjectionRun:
    """What a run did: messages published, and (kind, service) pairs it did not project."""

    requested: int
    skipped: int


def _version(dto: Projection) -> int:
    return dto.version if isinstance(dto, CriteriaProjection) else dto.source_version


class ProjectNetwork:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registry: NetworkRegistry,
        publisher: ProjectionPublisher,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._publisher = publisher
        self._clock = clock

    async def project(self, kind: GrantScope, service_id: str) -> ProjectionRun:
        """One kind of one service."""
        return await self._run((kind,), (service_id,))

    async def project_all(self, service_id: str) -> ProjectionRun:
        """The directory, the capacity and the criteria of one service."""
        return await self._run(_ALL_KINDS, (service_id,))

    async def backfill(self, kind: GrantScope | None = None) -> ProjectionRun:
        """Every active service of the bound tenant, for one kind or all (a grant has become
        effective, or a listing was admitted)."""
        return await self._run(_ALL_KINDS if kind is None else (kind,), None)

    # ---- the run

    async def _run(
        self, kinds: tuple[GrantScope, ...], service_ids: tuple[str, ...] | None
    ) -> ProjectionRun:
        for kind in kinds:
            if type(kind) is not GrantScope:
                raise ValidationFailed("kind", "is not a valid value for this field")
        tenant = current_tenant()
        now = self._clock.now()
        plan = await self._plan(tenant, kinds, now)
        if not plan:
            return ProjectionRun(0, len(kinds) * (1 if service_ids is None else len(service_ids)))
        built, skipped = await self._build(plan, kinds, service_ids, now)
        requested = 0
        for kind, service_id, dto in built:
            for entry in plan[kind]:
                if service_id not in entry.admitted:
                    continue
                grant = entry.active.grant
                await self._publisher.publish(
                    ProjectionRequested(
                        network_id=entry.active.network.network.id,
                        source_tenant_id=tenant,
                        grant_id=grant.id,
                        grant_version=grant.version,
                        kind=kind,
                        source_service_id=service_id,
                        source_version=_version(dto),
                        allowlist_version=PROJECTION_ALLOWLIST_VERSION,
                        body=to_body(dto),
                        at=now,
                    )
                )
                requested += 1
        return ProjectionRun(requested, skipped)

    async def _plan(
        self, tenant: str, kinds: tuple[GrantScope, ...], now: datetime
    ) -> dict[GrantScope, list[_Entry]]:
        """For each kind, the effective grants and the services each network has admitted. A kind
        with no grant is left out; so is a grant whose network has admitted nothing."""
        admitted: dict[str, frozenset[str]] = {}
        plan: dict[GrantScope, list[_Entry]] = {}
        for kind in kinds:
            for active in await self._registry.active_grants_for(tenant, kind, now):
                network_id = active.network.network.id
                if network_id not in admitted:
                    listings = await self._registry.listings_of(network_id, tenant)
                    admitted[network_id] = frozenset(
                        listing.source_service_id
                        for listing in listings
                        if may_project_listing(listing, active.membership, active.grant, now)
                    )
                if admitted[network_id]:
                    plan.setdefault(kind, []).append(_Entry(active, admitted[network_id]))
        return plan

    async def _build(
        self,
        plan: dict[GrantScope, list[_Entry]],
        kinds: tuple[GrantScope, ...],
        service_ids: tuple[str, ...] | None,
        now: datetime,
    ) -> tuple[list[tuple[GrantScope, str, Projection]], int]:
        built: list[tuple[GrantScope, str, Projection]] = []
        skipped = 0
        async with self._uow_factory() as uow:
            if not uow.read_only:
                raise ProducerUnitNotReadOnly
            config = await uow.tenant_config.current_version()
            policy = DEFAULT_POLICY if config is None else config.policy
            suspended = await uow.flags.services_with_flag(SERVICE_FLAG_SUSPENDED)
            if service_ids is None:
                service_ids = tuple(profile.id for profile in await uow.services.list_active())
            for service_id in service_ids:
                for kind in kinds:
                    if kind not in plan or not any(service_id in e.admitted for e in plan[kind]):
                        skipped += 1
                        continue
                    dto = await self._dto(uow, kind, service_id, suspended, policy, now)
                    if dto is None:
                        skipped += 1
                    else:
                        built.append((kind, service_id, dto))
        return built, skipped

    @staticmethod
    async def _dto(
        uow: UnitOfWork,
        kind: GrantScope,
        service_id: str,
        suspended: set[str],
        policy: TenantPolicy,
        now: datetime,
    ) -> Projection | None:
        if kind is GrantScope.CRITERIA:
            current = await uow.criteria.current_for_service(service_id)
            return None if current is None else build_criteria_projection(current)
        try:
            stored = await uow.services.get_versioned(service_id)
        except ValidationFailed:  # a scope-list entry that has not registered yet
            return None
        if stored is None or not stored[0].active:
            return None
        profile: ServiceProfile = stored[0]
        if service_id in suspended:
            profile = replace(profile, suspended=True)
        if kind is GrantScope.DIRECTORY:
            return build_service_projection(
                profile, source_version=stored[1], location=None, contact=None
            )
        latest = await uow.capacity.latest(service_id)
        confirmed = 0
        if latest is not None:
            counted = await uow.bookings.confirmed_since_for_services(
                [service_id], latest.effective_at
            )
            confirmed = len(counted.get(service_id, []))
        return build_capacity_projection(
            profile,
            latest,
            confirmed_since=confirmed,
            policy=policy,
            source_version=int(now.timestamp() * 1000),
            valid_until=None,
        )


@dataclass(frozen=True, slots=True)
class _Entry:
    active: ActiveGrant
    admitted: frozenset[str]
