"""Network administration, part three: listings (TEN-077, DEC-136 item 3, DEC-132 item 4, hazard
H-N12).

A provider registers its service in its own tenant and asks to list it on the network; the network
owner admits, declines, suspends or reinstates it; the provider can withdraw it. A listing is not
shared data: it is the permission to project a service, so nothing here reads or writes a service's
figures. Each decision is a compare-and-set on the status the decider saw, recorded in the
decider's scope and the network's, and repeating it records nothing twice.
"""

from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.listing_admission import (
    DecideListing,
    DecideListingCommand,
    ListingDecision,
    QueryListings,
    RequestListing,
    RequestListingCommand,
)
from diucs.application.use_cases.network_admin import GovernanceRecorder
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.network import ListingReason, ListingStatus
from tests.support.network_admin_fakes import (
    Ids,
    MemoryDirectory,
    MemoryRegistry,
    UnitFactories,
    UnitWorld,
    active_tenant,
    person,
)
from tests.support.network_samples import (
    MEMBER_B,
    MEMBER_C,
    NETWORK_ID,
    NOW,
    OTHER_NETWORK_ID,
    OUTSIDER,
    OWNER,
    make_listing,
    make_member,
    make_network,
    make_owner_membership,
    rid,
)
from tests.support.projection_samples import SERVICE_ID, sample_profile

AT = NOW + timedelta(days=1)
LISTING = rid("lst-b-1")


class _Rig:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.world = UnitWorld(self.log)
        self.registry = MemoryRegistry(self.log)
        self.registry.seed(
            make_network(),
            members=[make_owner_membership(), make_member(MEMBER_B), make_member(MEMBER_C)],
        )
        self.world.services[(MEMBER_B, SERVICE_ID)] = sample_profile()
        self.world.services[(MEMBER_B, "svc-gone")] = sample_profile(id="svc-gone", active=False)
        factories = UnitFactories(self.world)
        self.clock = FixedClock(AT)
        recorder = GovernanceRecorder(
            factories.tenant,  # type: ignore[arg-type]
            factories.network,  # type: ignore[arg-type]
            Ids("ob"),
            self.clock,
        )
        self.request = RequestListing(
            self.registry,  # type: ignore[arg-type]
            factories.tenant_read_only,  # type: ignore[arg-type]
            recorder,
            Ids("lst"),
            self.clock,
        )
        self.decide = DecideListing(self.registry, recorder, self.clock)  # type: ignore[arg-type]
        self.query = QueryListings(
            self.registry,  # type: ignore[arg-type]
            MemoryDirectory(active_tenant(OWNER), active_tenant(MEMBER_B), active_tenant(MEMBER_C)),  # type: ignore[arg-type]
        )

    def pending(self) -> str:
        listing = make_listing(id=LISTING, admitted=False)
        self.registry.listing_rows[listing.id] = listing
        return listing.id

    def admitted(self) -> str:
        listing = make_listing(id=LISTING, admitted=True)
        self.registry.listing_rows[listing.id] = listing
        return listing.id


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


def _owner(role: Role = Role.NETWORK_ADMIN) -> Any:
    return person(OWNER, role, "admin")


def _member(tenant: str = MEMBER_B, role: Role = Role.TENANT_ADMIN) -> Any:
    return person(tenant, role, "admin")


# asking


async def test_a_member_asks_to_list_one_of_its_active_services(rig: _Rig) -> None:
    with bind_tenant(MEMBER_B):
        listing_id = await rig.request.execute(
            RequestListingCommand(_member(), NETWORK_ID, SERVICE_ID)
        )
    row = rig.registry.listing_rows[listing_id]
    assert (row.source_tenant_id, row.source_service_id, row.status) == (
        MEMBER_B,
        SERVICE_ID,
        ListingStatus.PENDING,
    )
    assert [s for s, _ in rig.world.audits] == [MEMBER_B, NETWORK_ID]
    assert rig.world.outbox == []


async def test_a_lead_may_ask_too(rig: _Rig) -> None:
    with bind_tenant(MEMBER_B):
        await rig.request.execute(
            RequestListingCommand(_member(role=Role.LEAD), NETWORK_ID, SERVICE_ID)
        )


@pytest.mark.parametrize("role", [Role.NETWORK_ADMIN, Role.ADVISOR, Role.REPORTER, Role.OWNER])
async def test_other_roles_do_not_ask(rig: _Rig, role: Role) -> None:
    with bind_tenant(MEMBER_B), pytest.raises(NotAllowed):
        await rig.request.execute(RequestListingCommand(_member(role=role), NETWORK_ID, SERVICE_ID))


async def test_a_service_that_is_not_the_members_or_not_active_is_not_found(rig: _Rig) -> None:
    with bind_tenant(MEMBER_B):
        for service in ("svc-other", "svc-gone"):
            with pytest.raises(NotFound):
                await rig.request.execute(RequestListingCommand(_member(), NETWORK_ID, service))
    assert rig.registry.listing_rows == {}


async def test_an_organisation_that_is_not_a_member_is_the_same_not_found(rig: _Rig) -> None:
    with bind_tenant(OUTSIDER), pytest.raises(NotFound):
        await rig.request.execute(RequestListingCommand(_member(OUTSIDER), NETWORK_ID, SERVICE_ID))
    with bind_tenant(MEMBER_B), pytest.raises(NotFound):
        await rig.request.execute(RequestListingCommand(_member(), OTHER_NETWORK_ID, SERVICE_ID))


async def test_a_service_with_a_live_listing_cannot_be_listed_again(rig: _Rig) -> None:
    rig.pending()
    with bind_tenant(MEMBER_B), pytest.raises(Conflict):
        await rig.request.execute(RequestListingCommand(_member(), NETWORK_ID, SERVICE_ID))


async def test_a_listing_whose_records_failed_is_withdrawn_again(rig: _Rig) -> None:
    rig.world.fail_commit = "tenant"
    with bind_tenant(MEMBER_B), pytest.raises(ConnectionError):
        await rig.request.execute(RequestListingCommand(_member(), NETWORK_ID, SERVICE_ID))
    [row] = rig.registry.listing_rows.values()
    assert row.status is ListingStatus.WITHDRAWN
    rig.world.fail_commit = None
    with bind_tenant(MEMBER_B):
        await rig.request.execute(RequestListingCommand(_member(), NETWORK_ID, SERVICE_ID))


# the owner decides


@pytest.mark.parametrize(
    ("decision", "reason", "status"),
    [
        (ListingDecision.ADMIT, None, ListingStatus.ADMITTED),
        (ListingDecision.DECLINE, ListingReason.OUTSIDE_AREA, ListingStatus.DECLINED),
    ],
)
async def test_the_owner_admits_or_declines_a_pending_listing(
    rig: _Rig, decision: ListingDecision, reason: ListingReason | None, status: ListingStatus
) -> None:
    lid = rig.pending()
    with bind_tenant(OWNER):
        await rig.decide.execute(DecideListingCommand(_owner(), NETWORK_ID, lid, decision, reason))
    row = rig.registry.listing_rows[lid]
    assert row.status is status and row.reason is reason
    assert row.decided_at == AT and row.decided_by_account_ref is not None
    assert [s for s, _ in rig.world.audits] == [OWNER, NETWORK_ID]


async def test_the_owner_suspends_and_reinstates(rig: _Rig) -> None:
    lid = rig.admitted()
    with bind_tenant(OWNER):
        await rig.decide.execute(
            DecideListingCommand(
                _owner(), NETWORK_ID, lid, ListingDecision.SUSPEND, ListingReason.DATA_QUALITY
            )
        )
        assert rig.registry.listing_rows[lid].status is ListingStatus.SUSPENDED
        rig.clock.advance(timedelta(hours=1))
        await rig.decide.execute(
            DecideListingCommand(_owner(), NETWORK_ID, lid, ListingDecision.REINSTATE, None)
        )
    assert rig.registry.listing_rows[lid].status is ListingStatus.ADMITTED
    assert len(rig.world.audits) == 4  # two decisions, two scopes each


async def test_a_decline_or_a_suspension_needs_a_reason_code(rig: _Rig) -> None:
    lid = rig.pending()
    with bind_tenant(OWNER):
        for decision in (ListingDecision.DECLINE, ListingDecision.SUSPEND):
            with pytest.raises(ValidationFailed):
                await rig.decide.execute(
                    DecideListingCommand(_owner(), NETWORK_ID, lid, decision, None)
                )
    assert rig.registry.listing_rows[lid].status is ListingStatus.PENDING


async def test_a_move_the_state_machine_does_not_allow_is_refused(rig: _Rig) -> None:
    lid = rig.admitted()
    with bind_tenant(OWNER), pytest.raises(InvalidTransition):
        await rig.decide.execute(
            DecideListingCommand(_owner(), NETWORK_ID, lid, ListingDecision.REINSTATE, None)
        )


async def test_repeating_a_decision_records_nothing_twice(rig: _Rig) -> None:
    lid = rig.pending()
    command = DecideListingCommand(_owner(), NETWORK_ID, lid, ListingDecision.ADMIT, None)
    with bind_tenant(OWNER):
        await rig.decide.execute(command)
        rig.clock.advance(timedelta(minutes=5))
        await rig.decide.execute(command)
    assert len(rig.world.audits) == 2
    assert rig.registry.listing_rows[lid].decided_at == AT


async def test_a_decision_that_stopped_after_the_registry_is_finished_by_running_it_again(
    rig: _Rig,
) -> None:
    lid = rig.pending()
    command = DecideListingCommand(_owner(), NETWORK_ID, lid, ListingDecision.ADMIT, None)
    rig.world.fail_commit = "network"
    with bind_tenant(OWNER):
        with pytest.raises(ConnectionError):
            await rig.decide.execute(command)
        rig.world.fail_commit = None
        await rig.decide.execute(command)
    assert [s for s, _ in rig.world.audits] == [OWNER, NETWORK_ID]


async def test_only_the_owners_network_administrator_decides(rig: _Rig) -> None:
    lid = rig.pending()
    for actor_tenant, role, error in (
        (OWNER, Role.TENANT_ADMIN, NotAllowed),
        (OWNER, Role.LEAD, NotAllowed),
        (MEMBER_B, Role.NETWORK_ADMIN, NotFound),
    ):
        with bind_tenant(actor_tenant), pytest.raises(error):
            await rig.decide.execute(
                DecideListingCommand(
                    person(actor_tenant, role), NETWORK_ID, lid, ListingDecision.ADMIT, None
                )
            )
    assert rig.registry.listing_rows[lid].status is ListingStatus.PENDING


async def test_a_listing_of_another_network_is_not_found(rig: _Rig) -> None:
    other = make_network(id=OTHER_NETWORK_ID, owner=MEMBER_C)
    rig.registry.networks[other.id] = (other, rig.registry.networks[NETWORK_ID][1])
    from dataclasses import replace

    listing = replace(make_listing(id=rid("lst-x"), admitted=False), network_id=other.id)
    rig.registry.listing_rows[listing.id] = listing
    with bind_tenant(OWNER), pytest.raises(NotFound):
        await rig.decide.execute(
            DecideListingCommand(_owner(), NETWORK_ID, listing.id, ListingDecision.ADMIT, None)
        )


async def test_a_network_that_is_not_active_admits_nothing(rig: _Rig) -> None:
    from dataclasses import replace

    from diucs.domain.model.network import NetworkStatus

    lid = rig.pending()
    network, settings = rig.registry.networks[NETWORK_ID]
    rig.registry.networks[NETWORK_ID] = (replace(network, status=NetworkStatus.SUSPENDED), settings)
    with bind_tenant(OWNER), pytest.raises(Conflict):
        await rig.decide.execute(
            DecideListingCommand(_owner(), NETWORK_ID, lid, ListingDecision.ADMIT, None)
        )


# the member withdraws


async def test_the_source_organisation_withdraws_its_own_listing(rig: _Rig) -> None:
    lid = rig.admitted()
    with bind_tenant(MEMBER_B):
        await rig.decide.execute(
            DecideListingCommand(_member(), NETWORK_ID, lid, ListingDecision.WITHDRAW, None)
        )
    assert rig.registry.listing_rows[lid].status is ListingStatus.WITHDRAWN


async def test_another_member_cannot_withdraw_it_and_the_owner_cannot_either(rig: _Rig) -> None:
    lid = rig.admitted()
    with bind_tenant(MEMBER_C), pytest.raises(NotFound):
        await rig.decide.execute(
            DecideListingCommand(_member(MEMBER_C), NETWORK_ID, lid, ListingDecision.WITHDRAW, None)
        )
    with bind_tenant(OWNER), pytest.raises(NotAllowed):
        await rig.decide.execute(
            DecideListingCommand(_owner(), NETWORK_ID, lid, ListingDecision.WITHDRAW, None)
        )
    assert rig.registry.listing_rows[lid].status is ListingStatus.ADMITTED


async def test_the_owner_may_not_admit_through_a_members_role(rig: _Rig) -> None:
    lid = rig.pending()
    with bind_tenant(MEMBER_B), pytest.raises(NotAllowed):
        await rig.decide.execute(
            DecideListingCommand(_member(), NETWORK_ID, lid, ListingDecision.ADMIT, None)
        )


# the reads


async def test_the_owner_reads_every_listing_with_the_organisations_name_and_no_tenant_id(
    rig: _Rig,
) -> None:
    rig.admitted()
    with bind_tenant(OWNER):
        rows = await rig.query.for_network(_owner(), NETWORK_ID)
    [row] = rows
    assert row.organisation_name == active_tenant(MEMBER_B).display_name
    assert row.status is ListingStatus.ADMITTED and row.service_id == SERVICE_ID
    assert MEMBER_B not in repr(row)


async def test_a_member_reads_only_its_own_listings(rig: _Rig) -> None:
    rig.admitted()
    other = make_listing(id=rid("lst-c-1"), tenant=MEMBER_C)
    rig.registry.listing_rows[other.id] = other
    with bind_tenant(MEMBER_B):
        rows = await rig.query.of_member(_member(), NETWORK_ID)
    assert [r.listing_id for r in rows] == [LISTING]


async def test_a_reader_of_another_network_or_a_non_member_is_not_found(rig: _Rig) -> None:
    rig.admitted()
    with bind_tenant(MEMBER_B), pytest.raises(NotFound):
        await rig.query.for_network(person(MEMBER_B, Role.NETWORK_ADMIN), NETWORK_ID)
    with bind_tenant(OUTSIDER), pytest.raises(NotFound):
        await rig.query.of_member(_member(OUTSIDER), NETWORK_ID)


async def test_a_listing_id_never_looks_like_a_postcode_a_phone_or_an_nhs_number() -> None:
    """The listing's own id is the row reference of the network board (DEC-546), and the board
    refuses an id the privacy guard reads as personal data: a random UUID can hold a postcode shape
    (`b59al`), which would make the whole board fail. The id of a listing is therefore made of
    letters only, whatever the generator gave."""
    from diucs.domain.messages.privacy_guard import find_patient_data
    from diucs.domain.rules.projection import check_projection_id

    awkward = ["b59al-0001", "07700900123", "9434765919", "dt48xx-12", "e12ab-77-d48xx"]

    class _Awkward:
        def __init__(self) -> None:
            self.n = 0

        def new_id(self) -> str:
            self.n += 1
            return awkward[(self.n - 1) % len(awkward)]

    rig = _Rig()
    factories = UnitFactories(rig.world)
    rig.request = RequestListing(
        rig.registry,  # type: ignore[arg-type]
        factories.tenant_read_only,  # type: ignore[arg-type]
        GovernanceRecorder(
            factories.tenant,  # type: ignore[arg-type]
            factories.network,  # type: ignore[arg-type]
            Ids("ob"),
            rig.clock,
        ),
        _Awkward(),
        rig.clock,
    )
    made: list[str] = []
    for _ in awkward:
        rig.registry.listing_rows.clear()
        with bind_tenant(MEMBER_B):
            listing_id = await rig.request.execute(
                RequestListingCommand(_member(), NETWORK_ID, SERVICE_ID)
            )
        assert not find_patient_data(listing_id), listing_id
        assert check_projection_id("row_ref", listing_id) == listing_id
        made.append(listing_id)
    assert len(set(made)) == len(awkward)  # distinct inputs stay distinct
