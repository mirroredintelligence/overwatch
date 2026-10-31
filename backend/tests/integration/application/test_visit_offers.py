"""Integration tests for the practitioner app's use cases and the visit repository (DEC-1306 to
DEC-1309), against the real Neo4j the harness starts. Written in this build and NOT RUN where it
was built (no Docker on that machine): the batch run happens later.

A booking on a visiting service (UCR West, with a coverage area) is requested by an advisor, then
offered to its round (prac-1). The offer is stored as a `VisitOffer` node in the caller's tenant
with the address and contact sealed; accepting confirms the booking through RespondToBooking; done
completes it and erases the details. Tenant B holds the same service, person, booking id and offer
id, and cannot read, accept, decline or update A's offer. Values are synthetic.
"""

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from overwatch.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.tenancy import bind_scope
from overwatch.application.use_cases.coverage import SetServiceCoverage
from overwatch.application.use_cases.respond_to_booking import RespondToBooking
from overwatch.application.use_cases.visit_offers import (
    AcceptVisit,
    DeclineVisit,
    OfferVisit,
    ReportsNotReached,
    RespondsToBooking,
    SettingsCommand,
    SetVisitSettings,
    UpdateVisitStatus,
    VisitReader,
)
from overwatch.application.use_cases.withdraw_booking import ReportNotReached
from overwatch.domain.codes import BookingStatus, Role, Urgency
from overwatch.domain.errors import Conflict, NotFound
from overwatch.domain.model.booking import Booking
from overwatch.domain.model.visit import LocationChoice, VisitOffer, VisitState
from tests.support.booking_rig import (
    CASE_ID,
    LEAD,
    REQUESTED_AT,
    SERVICE_ID,
    sealer,
    seed_world,
)
from tests.support.neo4j import read_tx
from tests.support.tenancy import tenant_scope
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADDRESS = "1 Synthetic Street"
CONTACT = "Daughter, 07000 000000"
NOW = REQUESTED_AT + timedelta(minutes=1)


class World:
    def __init__(
        self, driver: AsyncDriver, factory: UnitOfWorkFactory, tenant: str, prefix: str
    ) -> None:
        self.driver, self.factory, self.tenant, self.prefix = driver, factory, tenant, prefix
        self.clock = FixedClock(NOW)

    def actor(self, role: Role, who: str) -> Actor:
        return Actor(role, who, "device-1", "api", frozenset({SERVICE_ID}), self.tenant)

    async def booking(self, key: str) -> str:
        """A requested booking on UCR West, written directly so that both tenants can hold the
        same booking id and reference (RequestBooking's own behaviour is tested in its own file)."""
        booking = Booking(
            id=f"bk-{key}",
            reference=f"{sum(map(ord, key)) % 9000 + 1000}",
            service_id=SERVICE_ID,
            case_id=CASE_ID,
            requester_id="advisor-1",
            status=BookingStatus.REQUESTED,
            requested_at=REQUESTED_AT,
            reply_by=REQUESTED_AT + timedelta(minutes=10),
        )
        with bind_scope(tenant_scope(self.tenant)):
            async with self.factory() as uow:
                await uow.bookings.add(booking)
                await uow.commit()
        return booking.id

    def offer_use_case(self) -> OfferVisit:
        return OfferVisit(self.factory, self.clock, SequentialIds(f"{self.prefix}vo"), sealer())

    def reader(self) -> VisitReader:
        return VisitReader(self.factory, self.clock, sealer())

    def accept_use_case(self) -> AcceptVisit:
        respond = RespondToBooking(
            self.factory,
            DriverIdempotencyStore(self.driver),
            self.clock,
            SequentialIds(f"{self.prefix}re"),
            sealer(),
        )
        return AcceptVisit(self.factory, self.clock, RespondsToBooking(respond))

    def status_use_case(self) -> UpdateVisitStatus:
        report = ReportNotReached(self.factory, DriverIdempotencyStore(self.driver), self.clock)
        return UpdateVisitStatus(self.factory, self.clock, ReportsNotReached(report))

    async def offer(self, booking_id: str) -> str:
        with bind_scope(tenant_scope(self.tenant)):
            await self.offer_use_case().execute(
                self.actor(Role.ADVISOR, "advisor-1"), booking_id, "DT4 8AB", ADDRESS, CONTACT
            )
            async with self.factory() as uow:
                offers = await uow.visits.for_booking(booking_id)
        assert len(offers) == 1
        return offers[0].id

    async def stored(self, offer_id: str) -> dict[str, object]:
        async def read(tx: AsyncManagedTransaction) -> dict[str, object]:
            rows = await tx.run(
                "MATCH (o:VisitOffer {id: $id, tenantId: $tenant}) "
                "RETURN o.state AS state, o.sector AS sector, o.sealedDetails AS sealed, "
                "o.etaAt AS eta",
                id=offer_id,
                tenant=self.tenant,
            )
            return dict(await rows.single())  # type: ignore[arg-type]

        return await read_tx(self.driver, read)


@pytest_asyncio.fixture(loop_scope="session")
async def worlds(
    tenant_id: str, other_tenant_id: str, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[tuple[World, World]]:
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    worlds: list[World] = []
    for tenant, prefix in ((tenant_id, "a-"), (other_tenant_id, "b-")):
        factory = tenant_uow_factory(neo4j_driver, tenant)
        with bind_scope(tenant_scope(tenant)):
            await seed_world(factory, neo4j_driver)
            await SetServiceCoverage(
                factory, FixedClock(NOW), SequentialIds(f"{prefix}loc")
            ).execute(
                Actor(Role.LEAD, LEAD.practitioner_id, None, "web", frozenset(), tenant),
                SERVICE_ID,
                ["DT4"],
                2,
                ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            )
        worlds.append(World(neo4j_driver, factory, tenant, prefix))
    yield worlds[0], worlds[1]


async def test_an_offer_is_stored_with_sealed_details_and_the_sector_only(
    worlds: tuple[World, World],
) -> None:
    world, _ = worlds
    offer_id = await world.offer(await world.booking("vo-1"))

    row = await world.stored(offer_id)

    assert (row["state"], row["sector"]) == ("offered", "DT4 8")
    assert isinstance(row["sealed"], str)
    for plain in (ADDRESS, CONTACT, "07000", "DT4 8AB"):
        assert plain not in str(row["sealed"])


async def test_accept_confirms_the_booking_and_shows_the_details_and_done_erases_them(
    worlds: tuple[World, World],
) -> None:
    world, _ = worlds
    booking_id = await world.booking("vo-2")
    offer_id = await world.offer(booking_id)
    me = world.actor(Role.REPORTER, "prac-1")

    with bind_scope(tenant_scope(world.tenant)):
        await world.accept_use_case().execute(me, offer_id)
        view = await world.reader().view(me, offer_id)
        async with world.factory() as uow:
            booking = await uow.bookings.get(booking_id)
        await world.status_use_case().execute(me, offer_id, VisitState.ARRIVED)
        await world.status_use_case().execute(me, offer_id, VisitState.DONE)
        async with world.factory() as uow:
            completed = await uow.bookings.get(booking_id)
        after = await world.reader().view(me, offer_id)

    assert (view.state, view.address, view.contact) == (VisitState.ACCEPTED, ADDRESS, CONTACT)
    assert booking is not None and booking.status is BookingStatus.CONFIRMED
    assert completed is not None and completed.status is BookingStatus.COMPLETED
    assert (after.state, after.address, after.contact, after.sector) == (
        VisitState.DONE,
        None,
        None,
        "DT4",
    )
    row = await world.stored(offer_id)
    assert (row["sealed"], row["sector"]) == (None, "DT4")


async def test_an_accepted_offer_cannot_then_be_declined(
    worlds: tuple[World, World],
) -> None:
    world, _ = worlds
    booking_id = await world.booking("vo-3")
    offer_id = await world.offer(booking_id)
    me = world.actor(Role.REPORTER, "prac-1")

    with bind_scope(tenant_scope(world.tenant)):
        await world.accept_use_case().execute(me, offer_id)
        with pytest.raises(Conflict):
            await DeclineVisit(world.factory, world.clock).execute(me, offer_id)


async def test_the_estimate_is_one_instant_and_choosing_never_erases_it(
    worlds: tuple[World, World],
) -> None:
    world, _ = worlds
    offer_id = await world.offer(await world.booking("vo-4"))
    me = world.actor(Role.REPORTER, "prac-1")

    with bind_scope(tenant_scope(world.tenant)):
        await world.accept_use_case().execute(me, offer_id)
        await SetVisitSettings(world.factory, world.clock).execute(
            me, SettingsCommand(set_status=False, status=None, location=LocationChoice.TRAVEL)
        )
        await world.status_use_case().execute(me, offer_id, VisitState.ON_MY_WAY, 20)
        assert (await world.stored(offer_id))["eta"] is not None
        await SetVisitSettings(world.factory, world.clock).execute(
            me, SettingsCommand(set_status=False, status=None, location=LocationChoice.NEVER)
        )

    assert (await world.stored(offer_id))["eta"] is None


async def test_tenant_b_cannot_read_accept_decline_or_update_tenant_as_offer(
    worlds: tuple[World, World],
) -> None:
    a, b = worlds
    offer_id = await a.offer(await a.booking("vo-5"))
    their = b.actor(Role.REPORTER, "prac-1")  # the same person id exists in B

    with bind_scope(tenant_scope(b.tenant)):
        with pytest.raises(NotFound):
            await b.reader().view(their, offer_id)
        with pytest.raises(NotFound):
            await b.accept_use_case().execute(their, offer_id)
        with pytest.raises(NotFound):
            await DeclineVisit(b.factory, b.clock).execute(their, offer_id)
        with pytest.raises(NotFound):
            await b.status_use_case().execute(their, offer_id, VisitState.ARRIVED)
        async with b.factory() as uow:
            assert await uow.visits.get(offer_id) is None
            assert await uow.visits.for_practitioner("prac-1", NOW - timedelta(days=1), NOW) == []

    assert (await a.stored(offer_id))["state"] == "offered"


async def test_the_same_booking_id_and_person_in_both_tenants_do_not_collide(
    worlds: tuple[World, World],
) -> None:
    a, b = worlds
    booking_a = await a.booking("vo-6")
    booking_b = await b.booking("vo-6")

    offer_a = await a.offer(booking_a)
    offer_b = await b.offer(booking_b)

    assert booking_a == booking_b
    assert offer_a != offer_b
    with bind_scope(tenant_scope(a.tenant)):
        async with a.factory() as uow:
            assert [o.id for o in await uow.visits.for_booking(booking_a)] == [offer_a]
    with bind_scope(tenant_scope(b.tenant)):
        async with b.factory() as uow:
            assert [o.id for o in await uow.visits.for_booking(booking_b)] == [offer_b]


async def test_a_compare_and_set_change_is_refused_when_the_state_has_moved(
    worlds: tuple[World, World],
) -> None:
    world, _ = worlds
    offer_id = await world.offer(await world.booking("vo-7"))

    with bind_scope(tenant_scope(world.tenant)):
        async with world.factory() as uow:
            offer = await uow.visits.get(offer_id)
            assert offer is not None
            declined = offer.with_state(VisitState.DECLINED, NOW)
            assert await uow.visits.change(declined, VisitState.OFFERED) is True
            assert await uow.visits.change(declined, VisitState.OFFERED) is False
            await uow.commit()


async def test_an_offer_to_a_person_or_service_that_is_not_in_the_tenant_is_not_stored(
    worlds: tuple[World, World],
) -> None:
    world, _ = worlds
    stray = VisitOffer(
        id="vo-stray",
        booking_id="bk-stray",
        reference="4999",
        service_id=SERVICE_ID,
        practitioner_id="nobody",
        need="frailty",
        sector="DT4 8",
        urgency=Urgency.TODAY,
        offered_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        state=VisitState.OFFERED,
        state_at=NOW,
        sealed_details="sealed",
    )

    with bind_scope(tenant_scope(world.tenant)):
        async with world.factory() as uow:
            with pytest.raises(NotFound):
                await uow.visits.add_many([stray])
        async with world.factory() as uow:
            assert await uow.visits.get("vo-stray") is None
