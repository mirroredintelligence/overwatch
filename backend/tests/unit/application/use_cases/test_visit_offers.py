"""The practitioner app's use cases (DEC-1306 to DEC-1309) on a hand-made unit of work: how a
booking becomes an offer, who may see and answer it, the one accept that wins, the status list, the
erasures and the location choice. The stored behaviour (Neo4j, two tenants) is in
tests/integration/application/test_visit_offers.py. Values are synthetic.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.tenancy import ScopeId, ScopeKind
from overwatch.application.use_cases.respond_to_booking import RespondToBookingResult
from overwatch.application.use_cases.visit_offers import (
    AcceptVisit,
    CloseVisitOffer,
    DeclineVisit,
    OfferVisit,
    SettingsCommand,
    SetVisitSettings,
    UpdateVisitStatus,
    VisitReader,
)
from overwatch.application.work import SCHEDULED, ScheduledWork, WorkKind
from overwatch.domain.codes import (
    AgeBand,
    BookingStatus,
    Channel,
    NeedCategory,
    NotReachedReason,
    PractitionerRoleCode,
    ReferrerType,
    Role,
    Urgency,
)
from overwatch.domain.errors import (
    Conflict,
    InvalidTransition,
    NotAllowed,
    NotFound,
    ValidationFailed,
)
from overwatch.domain.model.booking import Booking
from overwatch.domain.model.case import Case
from overwatch.domain.model.people import Practitioner, PractitionerRole
from overwatch.domain.model.visit import (
    LocationChoice,
    ShiftStatus,
    VisitOffer,
    VisitSettings,
    VisitState,
)
from tests.support.actors import ACTOR_TENANT

NOW = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
SCOPE = ScopeId(ACTOR_TENANT, ScopeKind.TENANT)
ADDRESS = "1 Synthetic Street"
CONTACT = "Daughter, 07000 000000"


def person(person_id: str, *, active: bool = True) -> Practitioner:
    return Practitioner(person_id, active, f"Person {person_id}", None)


def role(role_id: str, holder: str, cover: str | None = None) -> PractitionerRole:
    return PractitionerRole(
        id=role_id,
        practitioner_id=holder,
        service_id="svc-1",
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=Channel.TEXT,
        period_start=NOW - timedelta(days=30),
        covered_by_practitioner_id=cover,
        covered_until=None if cover is None else NOW + timedelta(hours=8),
    )


def booking(status: BookingStatus = BookingStatus.REQUESTED, **changes: Any) -> Booking:
    return replace(
        Booking(
            id="bk-1",
            reference="4821",
            service_id="svc-1",
            case_id="case-1",
            requester_id="adv-1",
            status=BookingStatus.REQUESTED,
            requested_at=NOW - timedelta(minutes=2),
            reply_by=NOW + timedelta(minutes=8),
        ),
        status=status,
        **changes,
    )


def case(**changes: Any) -> Case:
    return replace(
        Case(
            id="case-1",
            reference="4821",
            referrer_type=ReferrerType.GP,
            age_band=AgeBand.A80_PLUS,
            postcode="DT4",
            needs=(NeedCategory.FALL_NO_INJURY,),
            urgency=Urgency.WITHIN_2_HRS,
            scores=(),
            opened_at=NOW - timedelta(minutes=5),
        ),
        **changes,
    )


class FakeSealer:
    """Binds the text to the message, tenant and recipient it was sealed for, as the real one."""

    def seal(self, content: str, *, message_id: str, tenant_id: str, recipient_role_id: str) -> str:
        return f"sealed|{message_id}|{tenant_id}|{recipient_role_id}|{content}"

    def unseal(
        self, sealed: str, *, message_id: str, tenant_id: str, recipient_role_id: str
    ) -> str:
        head = f"sealed|{message_id}|{tenant_id}|{recipient_role_id}|"
        if not sealed.startswith(head):
            raise ValidationFailed("sealed", "does not open")
        return sealed[len(head) :]


class MemoryVisits:
    def __init__(self) -> None:
        self.offers: dict[str, VisitOffer] = {}
        self.settings_by_person: dict[str, VisitSettings] = {}

    async def add_many(self, offers: Sequence[VisitOffer]) -> None:
        for offer in offers:
            self.offers[offer.id] = offer

    async def get(self, offer_id: str) -> VisitOffer | None:
        return self.offers.get(offer_id)

    async def for_booking(self, booking_id: str) -> list[VisitOffer]:
        return sorted(
            (o for o in self.offers.values() if o.booking_id == booking_id), key=lambda o: o.id
        )

    async def for_practitioner(
        self, practitioner_id: str, since: datetime, now: datetime
    ) -> list[VisitOffer]:
        live = {VisitState.ACCEPTED, VisitState.ON_MY_WAY, VisitState.ARRIVED}
        return sorted(
            (
                o
                for o in self.offers.values()
                if o.practitioner_id == practitioner_id
                and (
                    (o.state is VisitState.OFFERED and o.expires_at > now)
                    or o.state in live
                    or o.state_at >= since
                )
            ),
            key=lambda o: (o.offered_at, o.id),
        )

    async def change(self, offer: VisitOffer, expected: VisitState) -> bool:
        held = self.offers.get(offer.id)
        if held is None or held.state is not expected:
            return False
        self.offers[offer.id] = offer
        return True

    async def settings(self, practitioner_id: str) -> VisitSettings | None:
        return self.settings_by_person.get(practitioner_id)

    async def save_settings(self, settings: VisitSettings) -> None:
        self.settings_by_person[settings.practitioner_id] = settings


@dataclass
class World:
    people: dict[str, Practitioner] = field(default_factory=dict)
    roles: list[PractitionerRole] = field(default_factory=list)
    bookings: dict[str, Booking] = field(default_factory=dict)
    cases: dict[str, Case] = field(default_factory=dict)
    visits: MemoryVisits = field(default_factory=MemoryVisits)
    visiting: bool = True
    audited: list[AuditEntry] = field(default_factory=list)
    works: dict[str, ScheduledWork] = field(default_factory=dict)
    committed: int = 0

    def factory(self) -> Any:
        world = self

        class People:
            async def get_practitioner(self, practitioner_id: str) -> Practitioner | None:
                return world.people.get(practitioner_id)

            async def reporter_roles_for_service(
                self, service_id: str, now: datetime
            ) -> list[PractitionerRole]:
                return [r for r in world.roles if r.service_id == service_id]

        class Bookings:
            async def get(self, booking_id: str) -> Booking | None:
                return world.bookings.get(booking_id)

            async def save(self, saved: Booking) -> None:
                world.bookings[saved.id] = saved

        class Services:
            async def get(self, service_id: str) -> Any:
                return type("Profile", (), {"id": service_id, "active": True})()

        class Positions:
            async def coverage_districts(self, ids: Sequence[str]) -> dict[str, tuple[str, ...]]:
                return {i: ("DT4",) for i in ids} if world.visiting else {}

        class Cases:
            async def get(self, case_id: str) -> Case | None:
                return world.cases.get(case_id)

        class Audit:
            async def append(self, entry: AuditEntry) -> None:
                world.audited.append(entry)

        class ScheduledWorkStore:
            async def add(self, work: ScheduledWork) -> None:
                world.works[work.id] = work

            async def get(self, work_id: str) -> ScheduledWork:
                return world.works[work_id]

            async def save(self, work: ScheduledWork) -> None:
                world.works[work.id] = work

        class Outbox:
            async def add(self, message: Any) -> None:
                return None

        class Unit:
            people = People()
            bookings = Bookings()
            services = Services()
            positions = Positions()
            cases = Cases()
            visits = world.visits
            audit = Audit()
            scheduled_work = ScheduledWorkStore()
            outbox = Outbox()
            unit_scope = SCOPE

            async def __aenter__(self) -> Unit:
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

            async def commit(self) -> None:
                world.committed += 1

        return Unit


def new_world() -> World:
    world = World()
    for who in ("p-1", "p-2", "p-cover"):
        world.people[who] = person(who)
    world.roles = [role("r-1", "p-1"), role("r-2", "p-2")]
    world.bookings["bk-1"] = booking()
    world.cases["case-1"] = case()
    return world


def advisor() -> Actor:
    return Actor(Role.ADVISOR, "adv-1", None, "web", frozenset(), ACTOR_TENANT)


def practitioner(who: str = "p-1") -> Actor:
    return Actor(Role.REPORTER, who, "device-1", "api", frozenset({"svc-x"}), ACTOR_TENANT)


class Confirmer:
    def __init__(self, world: World, *, final: bool = False) -> None:
        self.world, self.final, self.calls = world, final, 0

    async def confirm(self, actor: Actor, offer: VisitOffer) -> RespondToBookingResult:
        self.calls += 1
        held = self.world.bookings[offer.booking_id]
        if self.final or held.status is not BookingStatus.REQUESTED:
            return RespondToBookingResult(held.id, held.status, None, already_final=True)
        self.world.bookings[held.id] = held.with_status(BookingStatus.CONFIRMED, NOW)
        return RespondToBookingResult(held.id, BookingStatus.CONFIRMED, NOW, already_final=False)


class NotReached:
    def __init__(self, world: World) -> None:
        self.world, self.calls = world, []  # type: ignore[var-annotated]

    async def report(self, actor: Actor, offer: VisitOffer, reason: NotReachedReason) -> None:
        self.calls.append(reason)
        held = self.world.bookings[offer.booking_id]
        self.world.bookings[held.id] = held.with_status(BookingStatus.NOT_REACHED, NOW)


def offer_use_case(world: World) -> OfferVisit:
    return OfferVisit(world.factory(), FixedClock(NOW), SequentialIds(), FakeSealer())


async def offered(world: World | None = None) -> World:
    world = world or new_world()
    await offer_use_case(world).execute(advisor(), "bk-1", "dt4 8ab", ADDRESS, CONTACT)
    return world


def reader(world: World) -> VisitReader:
    return VisitReader(world.factory(), FixedClock(NOW), FakeSealer())


def offer_of(world: World, who: str) -> VisitOffer:
    return next(o for o in world.visits.offers.values() if o.practitioner_id == who)


# ------------------------------------------------------------------------- making the offer


async def test_a_booking_becomes_one_offer_for_each_person_on_the_round() -> None:
    world = await offered()

    assert sorted(o.practitioner_id for o in world.visits.offers.values()) == ["p-1", "p-2"]
    first = offer_of(world, "p-1")
    assert (first.reference, first.need, first.state) == (
        "4821",
        "fall, no injury",  # the needs in plain words, as a case summary says them
        VisitState.OFFERED,
    )
    assert first.expires_at == NOW + timedelta(minutes=8)  # the booking's own reply-by time
    assert world.committed == 1


async def test_the_offer_holds_the_sector_and_never_the_postcode_or_the_address_in_the_clear() -> (
    None
):
    world = await offered()

    for stored in world.visits.offers.values():
        assert stored.sector == "DT4 8"
        assert stored.sealed_details is not None
        assert stored.sealed_details.startswith("sealed|")
        # Everything but the sealed text is free of the postcode, the address and the contact (the
        # fake seals in the clear, so only the plain fields are searched).
        plain = repr(replace(stored, sealed_details=None))
        for secret in ("DT4 8AB", "dt4 8ab", ADDRESS, CONTACT, "07000"):
            assert secret not in plain


async def test_the_audit_names_ids_and_counts_and_no_personal_text() -> None:
    world = await offered()

    entry = world.audited[0]
    blob = json.dumps([entry.entity_ids, entry.snapshot])
    for secret in (ADDRESS, CONTACT, "DT4 8", "07000"):
        assert secret not in blob


async def test_a_cover_is_offered_the_visit_and_the_covered_person_is_not() -> None:
    world = new_world()
    world.roles = [role("r-1", "p-1", cover="p-cover")]

    await offered(world)

    assert [o.practitioner_id for o in world.visits.offers.values()] == ["p-cover"]


async def test_only_an_advisor_or_a_clinician_may_offer() -> None:
    world = new_world()
    for who in (Role.REPORTER, Role.LEAD, Role.WALL, Role.EXEC):
        actor = Actor(who, "x-1", None, "web", frozenset(), ACTOR_TENANT)
        with pytest.raises(NotAllowed):
            await offer_use_case(world).execute(actor, "bk-1", "DT4 8AB", ADDRESS, CONTACT)
    clinician = Actor(Role.CLINICAL, "c-1", None, "web", frozenset(), ACTOR_TENANT)
    await offer_use_case(world).execute(clinician, "bk-1", "DT4 8AB", ADDRESS, CONTACT)


@pytest.mark.parametrize("postcode", ["DT4", "DT4 8", "", "not a postcode", None, 7])
async def test_a_postcode_that_is_not_a_full_postcode_is_refused(postcode: object) -> None:
    with pytest.raises(ValidationFailed):
        await offer_use_case(new_world()).execute(advisor(), "bk-1", postcode, ADDRESS, CONTACT)


async def test_a_booking_that_is_not_waiting_cannot_be_offered() -> None:
    world = new_world()
    world.bookings["bk-1"] = booking(BookingStatus.CONFIRMED)
    with pytest.raises(Conflict):
        await offer_use_case(world).execute(advisor(), "bk-1", "DT4 8AB", ADDRESS, CONTACT)

    late = new_world()
    late.bookings["bk-1"] = booking(reply_by=NOW)
    with pytest.raises(Conflict):
        await offer_use_case(late).execute(advisor(), "bk-1", "DT4 8AB", ADDRESS, CONTACT)


async def test_an_unknown_booking_is_not_found_and_a_service_that_does_not_go_out_is_refused() -> (
    None
):
    with pytest.raises(NotFound):
        await offer_use_case(new_world()).execute(advisor(), "nope", "DT4 8AB", ADDRESS, CONTACT)
    fixed = new_world()
    fixed.visiting = False
    with pytest.raises(ValidationFailed):
        await offer_use_case(fixed).execute(advisor(), "bk-1", "DT4 8AB", ADDRESS, CONTACT)


async def test_a_booking_is_offered_once() -> None:
    world = await offered()
    with pytest.raises(Conflict):
        await offer_use_case(world).execute(advisor(), "bk-1", "DT4 8AB", ADDRESS, CONTACT)


async def test_a_service_with_nobody_on_its_round_is_refused() -> None:
    world = new_world()
    world.people["p-1"] = person("p-1", active=False)
    world.people["p-2"] = person("p-2", active=False)

    with pytest.raises(ValidationFailed):
        await offer_use_case(world).execute(advisor(), "bk-1", "DT4 8AB", ADDRESS, CONTACT)
    assert world.visits.offers == {}


# -------------------------------------------------------------------------- reading the offer


async def test_an_offer_shows_the_need_the_sector_and_the_time_and_no_details() -> None:
    world = await offered()
    mine = offer_of(world, "p-1")

    view = await reader(world).view(practitioner("p-1"), mine.id)

    assert (view.state, view.need, view.sector, view.wanted_within) == (
        VisitState.OFFERED,
        "Fall, no injury",
        "DT4 8",
        "within 2 hrs",
    )
    assert (view.address, view.contact, view.fits_minutes) == (None, None, None)


async def test_another_persons_offer_an_unknown_id_and_a_removed_person_are_the_one_not_found() -> (
    None
):
    world = await offered()
    theirs = offer_of(world, "p-2")

    with pytest.raises(NotFound):
        await reader(world).view(practitioner("p-1"), theirs.id)
    with pytest.raises(NotFound):
        await reader(world).view(practitioner("p-1"), "vo-unknown")
    world.people["p-2"] = person("p-2", active=False)
    with pytest.raises(NotFound):
        await reader(world).view(practitioner("p-2"), theirs.id)


async def test_only_a_signed_in_practitioner_has_the_app() -> None:
    world = await offered()
    mine = offer_of(world, "p-1")

    for wrong in (advisor(), Actor(Role.WALL, None, "dev", "api", frozenset(), ACTOR_TENANT)):
        with pytest.raises(NotAllowed):
            await reader(world).view(wrong, mine.id)


async def test_an_offer_past_its_time_reads_expired() -> None:
    world = await offered()
    mine = offer_of(world, "p-1")

    later = VisitReader(world.factory(), FixedClock(NOW + timedelta(minutes=9)), FakeSealer())

    assert (await later.view(practitioner("p-1"), mine.id)).state is VisitState.EXPIRED
    assert (await later.shift(practitioner("p-1"))).offers == ()


# ------------------------------------------------------------------- accepting and declining


def accept_use_case(world: World, confirmer: Confirmer | None = None) -> AcceptVisit:
    return AcceptVisit(
        world.factory(), FixedClock(NOW), SequentialIds(), confirmer or Confirmer(world)
    )


async def test_accepting_confirms_the_booking_and_shows_the_details_to_this_person() -> None:
    world = await offered()
    mine = offer_of(world, "p-1")

    answer = await accept_use_case(world).execute(practitioner("p-1"), mine.id)

    assert answer.state is VisitState.ACCEPTED
    assert world.bookings["bk-1"].status is BookingStatus.CONFIRMED
    view = await reader(world).view(practitioner("p-1"), mine.id)
    assert (view.state, view.address, view.contact) == (VisitState.ACCEPTED, ADDRESS, CONTACT)


async def test_a_colleagues_offer_is_withdrawn_and_shows_no_details() -> None:
    world = await offered()
    await accept_use_case(world).execute(practitioner("p-1"), offer_of(world, "p-1").id)
    theirs = offer_of(world, "p-2")

    view = await reader(world).view(practitioner("p-2"), theirs.id)

    assert (view.state, view.address, view.contact) == (VisitState.WITHDRAWN, None, None)
    assert theirs.state is VisitState.WITHDRAWN
    with pytest.raises(Conflict):
        await accept_use_case(world).execute(practitioner("p-2"), theirs.id)


async def test_the_second_accept_loses_when_the_booking_was_confirmed_first() -> None:
    world = await offered()
    # p-2's press confirmed the booking between p-1's read and p-1's confirmation.
    world.bookings["bk-1"] = booking(BookingStatus.CONFIRMED)

    with pytest.raises(Conflict):
        await accept_use_case(world).execute(practitioner("p-1"), offer_of(world, "p-1").id)
    assert offer_of(world, "p-1").state is VisitState.OFFERED


async def test_pressing_accept_again_does_nothing_more() -> None:
    world = await offered()
    confirmer = Confirmer(world)
    mine = offer_of(world, "p-1")
    await accept_use_case(world, confirmer).execute(practitioner("p-1"), mine.id)

    again = await accept_use_case(world, confirmer).execute(practitioner("p-1"), mine.id)

    assert again.state is VisitState.ACCEPTED
    assert confirmer.calls == 1


async def test_a_person_who_left_the_round_cannot_accept() -> None:
    world = await offered()
    mine = offer_of(world, "p-1")
    world.roles = [role("r-2", "p-2")]

    with pytest.raises(NotFound):
        await accept_use_case(world).execute(practitioner("p-1"), mine.id)
    assert world.bookings["bk-1"].status is BookingStatus.REQUESTED


async def test_an_offer_past_its_time_cannot_be_accepted() -> None:
    world = await offered()
    mine = offer_of(world, "p-1")
    late = AcceptVisit(
        world.factory(), FixedClock(NOW + timedelta(minutes=9)), SequentialIds(), Confirmer(world)
    )

    with pytest.raises(Conflict):
        await late.execute(practitioner("p-1"), mine.id)


async def test_another_persons_offer_cannot_be_accepted() -> None:
    world = await offered()

    with pytest.raises(NotFound):
        await accept_use_case(world).execute(practitioner("p-1"), offer_of(world, "p-2").id)


async def test_declining_affects_only_this_persons_offer() -> None:
    world = await offered()
    mine = offer_of(world, "p-1")

    answer = await DeclineVisit(world.factory(), FixedClock(NOW)).execute(
        practitioner("p-1"), mine.id
    )

    assert answer.state is VisitState.DECLINED
    assert offer_of(world, "p-1").sealed_details is None
    assert offer_of(world, "p-1").sector == "DT4"
    assert offer_of(world, "p-2").state is VisitState.OFFERED
    assert world.bookings["bk-1"].status is BookingStatus.REQUESTED
    still = await DeclineVisit(world.factory(), FixedClock(NOW)).execute(
        practitioner("p-1"), mine.id
    )
    assert still.state is VisitState.DECLINED


async def test_a_declined_offer_cannot_then_be_accepted() -> None:
    world = await offered()
    mine = offer_of(world, "p-1")
    await DeclineVisit(world.factory(), FixedClock(NOW)).execute(practitioner("p-1"), mine.id)

    with pytest.raises(Conflict):
        await accept_use_case(world).execute(practitioner("p-1"), mine.id)


# ----------------------------------------------------------------------------- the status list


async def accepted(world: World | None = None) -> tuple[World, str]:
    world = await offered(world)
    mine = offer_of(world, "p-1")
    await accept_use_case(world).execute(practitioner("p-1"), mine.id)
    return world, mine.id


def status_use_case(world: World, reporting: NotReached | None = None) -> UpdateVisitStatus:
    return UpdateVisitStatus(world.factory(), FixedClock(NOW), reporting or NotReached(world))


async def test_the_status_list_runs_on_my_way_arrived_done() -> None:
    world, offer_id = await accepted()
    use = status_use_case(world)

    assert (await use.execute(practitioner(), offer_id, VisitState.ON_MY_WAY)).state is (
        VisitState.ON_MY_WAY
    )
    assert (await use.execute(practitioner(), offer_id, VisitState.ARRIVED)).state is (
        VisitState.ARRIVED
    )
    assert (await use.execute(practitioner(), offer_id, VisitState.DONE)).state is VisitState.DONE


async def test_done_completes_the_booking_and_erases_the_details_and_the_sector() -> None:
    world, offer_id = await accepted()
    await status_use_case(world).execute(practitioner(), offer_id, VisitState.DONE)

    stored = world.visits.offers[offer_id]
    assert (stored.sealed_details, stored.sector, stored.eta_at) == (None, "DT4", None)
    assert world.bookings["bk-1"].status is BookingStatus.COMPLETED
    view = await reader(world).view(practitioner(), offer_id)
    assert (view.address, view.contact) == (None, None)


async def test_could_not_reach_reports_the_booking_not_reached_and_erases_the_details() -> None:
    world, offer_id = await accepted()
    reporting = NotReached(world)

    await status_use_case(world, reporting).execute(
        practitioner(), offer_id, VisitState.NOT_REACHED
    )

    assert reporting.calls == [NotReachedReason.NO_ANSWER]
    assert world.bookings["bk-1"].status is BookingStatus.NOT_REACHED
    stored = world.visits.offers[offer_id]
    assert (stored.state, stored.sealed_details) == (VisitState.NOT_REACHED, None)


async def test_a_status_that_is_not_in_the_list_is_refused() -> None:
    world, offer_id = await accepted()

    for bad in (VisitState.ACCEPTED, VisitState.DECLINED, VisitState.OFFERED, "done", None):
        with pytest.raises(ValidationFailed):
            await status_use_case(world).execute(practitioner(), offer_id, bad)


async def test_a_visit_cannot_go_backwards() -> None:
    world, offer_id = await accepted()
    use = status_use_case(world)
    await use.execute(practitioner(), offer_id, VisitState.ARRIVED)

    with pytest.raises(InvalidTransition):
        await use.execute(practitioner(), offer_id, VisitState.ON_MY_WAY)


async def test_an_offer_that_was_not_accepted_cannot_be_updated() -> None:
    world = await offered()

    with pytest.raises(Conflict):
        await status_use_case(world).execute(
            practitioner("p-1"), offer_of(world, "p-1").id, VisitState.ON_MY_WAY
        )


async def test_another_person_cannot_update_my_visit() -> None:
    world, offer_id = await accepted()

    with pytest.raises(NotFound):
        await status_use_case(world).execute(practitioner("p-2"), offer_id, VisitState.ARRIVED)


async def test_a_visit_whose_booking_was_cancelled_cannot_be_updated_and_shows_no_details() -> None:
    world, offer_id = await accepted()
    world.bookings["bk-1"] = booking(BookingStatus.CANCELLED_AFTER)

    with pytest.raises(Conflict):
        await status_use_case(world).execute(practitioner(), offer_id, VisitState.ARRIVED)
    view = await reader(world).view(practitioner(), offer_id)
    assert (view.state, view.address) == (VisitState.WITHDRAWN, None)


# ---------------------------------------------------------- location: an estimate, never a trail


async def choose(world: World, location: LocationChoice) -> None:
    await SetVisitSettings(world.factory(), FixedClock(NOW)).execute(
        practitioner(), SettingsCommand(set_status=False, status=None, location=location)
    )


async def test_an_estimate_is_refused_unless_the_person_chose_to_share() -> None:
    world, offer_id = await accepted()

    with pytest.raises(ValidationFailed):
        await status_use_case(world).execute(practitioner(), offer_id, VisitState.ON_MY_WAY, 20)
    assert world.visits.offers[offer_id].eta_at is None

    await choose(world, LocationChoice.NEVER)
    with pytest.raises(ValidationFailed):
        await status_use_case(world).execute(practitioner(), offer_id, VisitState.ON_MY_WAY, 20)


async def test_a_shared_estimate_is_one_instant_that_is_overwritten_and_erased_on_arrival() -> None:
    world, offer_id = await accepted()
    await choose(world, LocationChoice.TRAVEL)
    use = status_use_case(world)

    await use.execute(practitioner(), offer_id, VisitState.ON_MY_WAY, 20)
    assert world.visits.offers[offer_id].eta_at == NOW + timedelta(minutes=20)
    await use.execute(practitioner(), offer_id, VisitState.ON_MY_WAY, 12)
    assert world.visits.offers[offer_id].eta_at == NOW + timedelta(minutes=12)
    view = await reader(world).view(practitioner(), offer_id)
    assert view.eta_at == NOW + timedelta(minutes=12)

    await use.execute(practitioner(), offer_id, VisitState.ARRIVED)
    assert world.visits.offers[offer_id].eta_at is None


async def test_an_estimate_can_only_go_with_on_my_way_and_in_range() -> None:
    world, offer_id = await accepted()
    await choose(world, LocationChoice.TRAVEL)
    use = status_use_case(world)

    for status, minutes in (
        (VisitState.ARRIVED, 5),
        (VisitState.ON_MY_WAY, 0),
        (VisitState.ON_MY_WAY, 999),
    ):
        with pytest.raises(ValidationFailed):
            await use.execute(practitioner(), offer_id, status, minutes)


async def test_choosing_never_erases_an_estimate_given_earlier() -> None:
    world, offer_id = await accepted()
    await choose(world, LocationChoice.TRAVEL)
    await status_use_case(world).execute(practitioner(), offer_id, VisitState.ON_MY_WAY, 20)

    await choose(world, LocationChoice.NEVER)

    assert world.visits.offers[offer_id].eta_at is None


# --------------------------------------------------------------------------- the shift home


async def test_a_new_person_has_no_status_and_the_location_is_not_shared() -> None:
    world = new_world()

    view = await reader(world).shift(practitioner())

    assert (view.status, view.location, view.visits_today, view.next_visit, view.offers) == (
        None,
        LocationChoice.NEVER,
        0,
        None,
        (),
    )


async def test_the_shift_counts_todays_visits_names_the_next_and_lists_the_offers() -> None:
    world, offer_id = await accepted()
    other_booking = replace(booking(), id="bk-2", reference="4822")
    world.bookings["bk-2"] = other_booking
    world.visits.offers["vo-x"] = replace(
        offer_of(world, "p-2"),
        id="vo-x",
        booking_id="bk-2",
        reference="4822",
        practitioner_id="p-1",
        state=VisitState.OFFERED,
    )

    view = await reader(world).shift(practitioner())

    assert view.visits_today == 1
    assert view.next_visit is not None
    assert (view.next_visit.id, view.next_visit.sector) == (offer_id, "DT4 8")
    assert view.next_visit.due_by == NOW + timedelta(hours=2)
    assert [o.id for o in view.offers] == ["vo-x"]
    assert [(r.id, r.state) for r in view.round] == [(offer_id, VisitState.ACCEPTED)]


async def test_a_finished_visit_counts_for_the_day_and_is_no_longer_next() -> None:
    world, offer_id = await accepted()
    await status_use_case(world).execute(practitioner(), offer_id, VisitState.DONE)

    view = await reader(world).shift(practitioner())

    assert (view.visits_today, view.next_visit) == (1, None)


async def test_the_status_is_optional_and_can_be_set_and_cleared() -> None:
    world = new_world()
    use = SetVisitSettings(world.factory(), FixedClock(NOW))

    set_ = await use.execute(
        practitioner(),
        SettingsCommand(set_status=True, status=ShiftStatus.BREAK, location=None),
    )
    assert (set_.status, set_.location) == (ShiftStatus.BREAK, LocationChoice.NEVER)
    assert (await reader(world).shift(practitioner())).status is ShiftStatus.BREAK

    untouched = await use.execute(
        practitioner(),
        SettingsCommand(set_status=False, status=None, location=LocationChoice.TRAVEL),
    )
    assert (untouched.status, untouched.location) == (ShiftStatus.BREAK, LocationChoice.TRAVEL)

    cleared = await use.execute(
        practitioner(), SettingsCommand(set_status=True, status=None, location=None)
    )
    assert (cleared.status, cleared.status_at) == (None, None)


async def test_settings_are_for_a_signed_in_practitioner_only() -> None:
    world = new_world()

    with pytest.raises(NotAllowed):
        await SetVisitSettings(world.factory(), FixedClock(NOW)).execute(
            advisor(), SettingsCommand(set_status=False, status=None, location=None)
        )


async def test_nothing_in_any_audit_entry_holds_the_details_or_the_postcode() -> None:
    world, offer_id = await accepted()
    await choose(world, LocationChoice.TRAVEL)
    await status_use_case(world).execute(practitioner(), offer_id, VisitState.ON_MY_WAY, 15)
    await status_use_case(world).execute(practitioner(), offer_id, VisitState.DONE)

    blob = json.dumps([[e.use_case, e.entity_ids, e.snapshot] for e in world.audited], default=str)
    for secret in (ADDRESS, CONTACT, "DT4 8", "07000"):
        assert secret not in blob


# --------------------------------------------------------------------------------- the close


def close_use_case(world: World, now: datetime) -> CloseVisitOffer:
    return CloseVisitOffer(world.factory(), FixedClock(now), SequentialIds("close"))


def close_work(world: World, offer_id: str) -> ScheduledWork:
    return next(
        w for w in world.works.values() if w.kind is WorkKind.VISIT_CLOSE and w.about_id == offer_id
    )


async def test_each_offer_gets_a_close_a_minute_after_its_time_is_up() -> None:
    world = await offered()

    for stored in world.visits.offers.values():
        work = close_work(world, stored.id)
        assert work.due_at == stored.expires_at + timedelta(minutes=1)
        assert work.status == SCHEDULED


async def test_accepting_schedules_a_close_a_day_on() -> None:
    world, offer_id = await accepted()

    due = sorted(w.due_at for w in world.works.values() if w.about_id == offer_id)

    assert due[-1] == NOW + timedelta(hours=24)


async def test_an_offer_nobody_answered_in_time_is_closed_and_erased() -> None:
    from overwatch.application.tenancy import bind_tenant

    world = await offered()
    mine = offer_of(world, "p-1")
    work = close_work(world, mine.id)

    with bind_tenant(ACTOR_TENANT):
        result = await close_use_case(world, work.due_at).execute(work.id, mine.id)

    stored = world.visits.offers[mine.id]
    assert result.acted is True
    assert (stored.state, stored.sealed_details, stored.sector) == (VisitState.EXPIRED, None, "DT4")
    assert world.works[work.id].status == "done"
    assert world.audited[-1].use_case == "CloseVisitOffer"
    assert world.audited[-1].actor.role is Role.AUDIT


async def test_an_offer_whose_booking_was_taken_by_a_colleague_is_closed_as_withdrawn() -> None:
    from overwatch.application.tenancy import bind_tenant

    world = await offered()
    mine = offer_of(world, "p-2")
    world.bookings["bk-1"] = booking(BookingStatus.CONFIRMED)
    work = close_work(world, mine.id)

    with bind_tenant(ACTOR_TENANT):
        await close_use_case(world, NOW + timedelta(minutes=1)).execute(work.id, mine.id)

    assert world.visits.offers[mine.id].state is VisitState.WITHDRAWN
    assert world.visits.offers[mine.id].sealed_details is None


async def test_an_offer_still_in_time_for_a_waiting_booking_is_left_alone() -> None:
    world = await offered()
    mine = offer_of(world, "p-1")
    work = close_work(world, mine.id)

    result = await close_use_case(world, NOW).execute(work.id, mine.id)

    assert result.acted is False
    assert world.visits.offers[mine.id].state is VisitState.OFFERED
    assert world.works[work.id].status == "done"


async def test_a_visit_nobody_finished_in_a_day_is_closed_and_its_details_erased() -> None:
    from overwatch.application.tenancy import bind_tenant

    world, offer_id = await accepted()
    work = max((w for w in world.works.values() if w.about_id == offer_id), key=lambda w: w.due_at)

    with bind_tenant(ACTOR_TENANT):
        await close_use_case(world, NOW + timedelta(hours=24)).execute(work.id, offer_id)

    stored = world.visits.offers[offer_id]
    assert (stored.state, stored.sealed_details, stored.sector) == (
        VisitState.WITHDRAWN,
        None,
        "DT4",
    )


async def test_a_visit_that_moved_within_the_day_is_left_and_the_close_is_scheduled_again() -> None:
    world, offer_id = await accepted()
    first = max((w for w in world.works.values() if w.about_id == offer_id), key=lambda w: w.due_at)
    arrived_at = NOW + timedelta(hours=23)
    world.visits.offers[offer_id] = world.visits.offers[offer_id].with_state(
        VisitState.ARRIVED, arrived_at
    )

    result = await close_use_case(world, NOW + timedelta(hours=24)).execute(first.id, offer_id)

    assert result.acted is False
    assert world.visits.offers[offer_id].state is VisitState.ARRIVED
    later = [w for w in world.works.values() if w.about_id == offer_id and w.status == SCHEDULED]
    assert arrived_at + timedelta(hours=24) in [w.due_at for w in later]
    assert world.works[first.id].status == "done"


async def test_a_close_runs_once_and_an_offer_that_ended_is_not_touched() -> None:
    world = await offered()
    mine = offer_of(world, "p-1")
    work = close_work(world, mine.id)
    use = close_use_case(world, work.due_at)
    world.visits.offers[mine.id] = mine.with_state(VisitState.DECLINED, NOW)

    first = await use.execute(work.id, mine.id)
    second = await use.execute(work.id, mine.id)

    assert (first.acted, second.acted) == (False, False)
    assert world.visits.offers[mine.id].state is VisitState.DECLINED


async def test_a_close_for_another_offer_is_not_found() -> None:
    world = await offered()
    mine, theirs = offer_of(world, "p-1"), offer_of(world, "p-2")

    with pytest.raises(NotFound):
        await close_use_case(world, NOW).execute(close_work(world, mine.id).id, theirs.id)
