"""The projector's handling of the governance events (TEN-056, DEC-545 item 6, DEC-132 items 3
and 6).

`network.events` carries what the use cases of the network administration decided. The projector
acts on three of them and ignores the rest: a grant that has become effective starts the grantor's
projection (the grantor's heartbeat chain, and a backfill of that kind, run in the grantor's own
scope); a grant that ended, and a member that was removed or left, end the source in the network
scope. The message is never the authority: the grant or the network is read from the registry, the
sender must be a party to it (the grantor or the network owner for a grant, the member or the owner
for a membership), and the registry decides what is still true (a late message that is overtaken by
a newer grant ends nothing).
"""

from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.tenancy import bind_tenant, current_scope_or_none
from diucs.application.use_cases.network_governance import GovernanceOutcome, NetworkGovernance
from diucs.application.use_cases.network_leave import EndResult
from diucs.application.use_cases.project_network import ProjectionRun
from diucs.application.work import WorkKind
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import (
    GrantEffective,
    GrantEnded,
    GrantProposed,
    MemberAdded,
    MemberRemoved,
)
from diucs.domain.model.network import GrantEndReason, GrantScope, MembershipEndReason
from tests.support.network_admin_fakes import Ids, MemoryRegistry, UnitFactories, UnitWorld
from tests.support.network_samples import (
    MEMBER_B,
    MEMBER_C,
    NETWORK_ID,
    NOW,
    OUTSIDER,
    OWNER,
    make_grant,
    make_member,
    make_network,
    make_owner_membership,
    rid,
)

AT = NOW + timedelta(hours=1)
GRANT_ID = rid("grant-gov")


class _Producer:
    def __init__(self) -> None:
        self.calls: list[tuple[GrantScope | None, str | None]] = []

    async def backfill(self, kind: GrantScope | None = None) -> ProjectionRun:
        scope = current_scope_or_none()
        self.calls.append((kind, None if scope is None else scope.value))
        return ProjectionRun(1, 0)


class _Ends:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.result = EndResult(1, 2)

    async def end_grant(
        self, network: str, member: str, scope: Any, *, reason: Any, at: Any
    ) -> Any:
        self.calls.append(("grant", network, member, scope, reason, at))
        return self.result

    async def end_member(self, network: str, member: str, *, at: Any) -> Any:
        self.calls.append(("member", network, member, at))
        return self.result


class _Active:
    def __init__(self, *ids: str) -> None:
        self.ids = list(ids)

    async def active_tenant_ids(self) -> list[str]:
        return self.ids


class _Rig:
    def __init__(self, active: tuple[str, ...] = (MEMBER_B, MEMBER_C, OWNER)) -> None:
        self.log: list[str] = []
        self.world = UnitWorld(self.log)
        self.registry = MemoryRegistry(self.log)
        self.registry.seed(
            make_network(),
            members=[make_owner_membership(), make_member(MEMBER_B)],
            grants=[make_grant(id=GRANT_ID)],
        )
        self.producer = _Producer()
        self.ends = _Ends()
        self.governance = NetworkGovernance(
            self.registry,  # type: ignore[arg-type]
            self.ends,  # type: ignore[arg-type]
            self.producer,  # type: ignore[arg-type]
            UnitFactories(self.world).tenant,  # type: ignore[arg-type]
            Ids("gv"),
            FixedClock(AT),
            _Active(*active),
        )

    async def handle(self, event: Any, bus_tenant: str = MEMBER_B) -> GovernanceOutcome:
        with bind_tenant(bus_tenant):
            return await self.governance.handle(
                event.event_type, event.to_payload(), bus_tenant=bus_tenant
            )


def _effective(**over: Any) -> GrantEffective:
    fields: dict[str, Any] = dict(
        grant_id=GRANT_ID,
        network_id=NETWORK_ID,
        grantor_tenant_id=MEMBER_B,
        scope=GrantScope.CAPACITY,
        version=1,
        effective_from=AT,
        at=AT,
    )
    return GrantEffective(**{**fields, **over})


def _ended(reason: GrantEndReason = GrantEndReason.ENDED, **over: Any) -> GrantEnded:
    fields: dict[str, Any] = dict(
        grant_id=GRANT_ID,
        network_id=NETWORK_ID,
        grantor_tenant_id=MEMBER_B,
        scope=GrantScope.CAPACITY,
        version=1,
        reason=reason,
        at=AT,
    )
    return GrantEnded(**{**fields, **over})


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


# GrantEffective


async def test_an_effective_grant_projects_its_kind_in_the_grantors_scope(rig: _Rig) -> None:
    assert await rig.handle(_effective(), MEMBER_B) is GovernanceOutcome.HANDLED
    assert rig.producer.calls == [(GrantScope.CAPACITY, MEMBER_B)]


async def test_the_owner_who_gave_the_second_approval_may_be_the_sender(rig: _Rig) -> None:
    assert await rig.handle(_effective(), OWNER) is GovernanceOutcome.HANDLED
    # the projection runs in the grantor's scope, not the owner's
    assert rig.producer.calls == [(GrantScope.CAPACITY, MEMBER_B)]


async def test_the_grantors_heartbeat_chain_is_started(rig: _Rig) -> None:
    await rig.handle(_effective(), MEMBER_B)
    works = [w for w in rig.world.scheduled if w.kind is WorkKind.PROJECTION_HEARTBEAT]
    assert [w.about_id for w in works] == [MEMBER_B]


async def test_a_tenant_that_is_not_active_is_skipped_and_nothing_runs() -> None:
    rig = _Rig(active=(OWNER,))
    assert await rig.handle(_effective(), OWNER) is GovernanceOutcome.SKIPPED
    assert rig.producer.calls == [] and rig.world.opened == 0


async def test_a_sender_who_is_no_party_to_the_grant_is_refused(rig: _Rig) -> None:
    with pytest.raises(NotAllowed):
        await rig.handle(_effective(), MEMBER_C)
    assert rig.producer.calls == []


async def test_a_grant_the_registry_does_not_know_is_refused(rig: _Rig) -> None:
    with pytest.raises(NotFound):
        await rig.handle(_effective(grant_id="grant-none"), MEMBER_B)


@pytest.mark.parametrize(
    "over",
    [
        {"grantor_tenant_id": MEMBER_C},
        {"scope": GrantScope.DIRECTORY},
        {"network_id": NETWORK_ID + "-b"},
    ],
)
async def test_an_event_that_disagrees_with_the_registered_grant_is_refused(
    rig: _Rig, over: dict[str, Any]
) -> None:
    with pytest.raises(NotAllowed):
        await rig.handle(_effective(**over), MEMBER_B)
    assert rig.producer.calls == []


# GrantEnded


async def test_an_ended_grant_ends_the_source_dated_by_the_event(rig: _Rig) -> None:
    assert await rig.handle(_ended(), MEMBER_B) is GovernanceOutcome.HANDLED
    assert rig.ends.calls == [
        ("grant", NETWORK_ID, MEMBER_B, GrantScope.CAPACITY, GrantEndReason.ENDED, AT)
    ]


async def test_a_lapse_may_come_from_the_owner_who_removed_the_member(rig: _Rig) -> None:
    await rig.handle(_ended(GrantEndReason.LAPSED), OWNER)
    assert rig.ends.calls[0][4] is GrantEndReason.LAPSED


async def test_a_skipped_end_is_reported_as_skipped(rig: _Rig) -> None:
    rig.ends.result = EndResult(0, 0, skipped=True)
    assert await rig.handle(_ended(), MEMBER_B) is GovernanceOutcome.SKIPPED


async def test_an_end_sent_by_a_stranger_ends_nothing(rig: _Rig) -> None:
    with pytest.raises(NotAllowed):
        await rig.handle(_ended(), OUTSIDER)
    assert rig.ends.calls == []


# MemberRemoved


async def test_a_member_who_left_has_every_source_ended(rig: _Rig) -> None:
    event = MemberRemoved(NETWORK_ID, MEMBER_B, MembershipEndReason.LEFT, AT)
    assert await rig.handle(event, MEMBER_B) is GovernanceOutcome.HANDLED
    assert rig.ends.calls == [("member", NETWORK_ID, MEMBER_B, AT)]


async def test_the_owner_may_remove_a_member_but_another_member_may_not(rig: _Rig) -> None:
    event = MemberRemoved(NETWORK_ID, MEMBER_B, MembershipEndReason.REMOVED, AT)
    assert await rig.handle(event, OWNER) is GovernanceOutcome.HANDLED
    with pytest.raises(NotAllowed):
        await rig.handle(event, MEMBER_C)


async def test_a_network_the_registry_does_not_know_is_refused(rig: _Rig) -> None:
    event = MemberRemoved(NETWORK_ID + "-z", MEMBER_B, MembershipEndReason.LEFT, AT)
    with pytest.raises(NotFound):
        await rig.handle(event, MEMBER_B)


# the rest


async def test_the_other_events_are_ignored_without_a_read(rig: _Rig) -> None:
    for event in (
        MemberAdded(NETWORK_ID, MEMBER_B, AT),
        GrantProposed(GRANT_ID, NETWORK_ID, MEMBER_B, GrantScope.CAPACITY, 1, AT),
    ):
        assert await rig.handle(event, MEMBER_B) is GovernanceOutcome.IGNORED
    assert rig.producer.calls == [] and rig.ends.calls == []


async def test_a_payload_that_is_not_the_event_is_a_validation_failure(rig: _Rig) -> None:
    with bind_tenant(MEMBER_B), pytest.raises(ValidationFailed):
        await rig.governance.handle("GrantEnded", {"grant_id": "x"}, bus_tenant=MEMBER_B)
