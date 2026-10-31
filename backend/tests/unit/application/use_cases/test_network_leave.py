"""Leave and grant-end semantics in the network scope (TEN-056, DEC-132 items 3 and 6, DEC-542).

A member leaving or a grant ending ends its source in the network scope and marks the rows it
wrote, with the date and the reason; nothing is deleted, so the history stays. The registry is the
authority and is asked first: a handler that runs late (the message was queued) must not end what a
newer grant or a re-joined membership now shares. The unit is a network unit bound to the
network's own scope, one for the whole end, and a second run changes and audits nothing.
"""

from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.projection import (
    ProjectionEndReason,
    SourceState,
    SourceStatus,
)
from diucs.application.tenancy import ScopeId, bind_tenant
from diucs.application.use_cases.network_leave import EndProjections, EndResult
from diucs.domain.model.network import GrantEndReason, GrantScope, MembershipStatus
from tests.support.network_admin_fakes import MemoryRegistry, UnitFactories, UnitWorld
from tests.support.network_samples import (
    MEMBER_B,
    MEMBER_C,
    NETWORK_ID,
    NOW,
    make_grant,
    make_member,
    make_network,
    make_owner_membership,
    rid,
)

AT = NOW + timedelta(hours=1)
NET = ScopeId.network(NETWORK_ID)


def _active(member: str, kind: GrantScope) -> SourceState:
    return SourceState(member, kind, SourceStatus.ACTIVE, f"grant-{kind.value}", None, None)


class _Rig:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.world = UnitWorld(self.log)
        self.registry = MemoryRegistry(self.log)
        self.registry.seed(make_network(), members=[make_owner_membership()])
        self.ends = EndProjections(
            UnitFactories(self.world).network,  # type: ignore[arg-type]
            self.registry,  # type: ignore[arg-type]
            FixedClock(AT),
        )

    def member_shares(self, member: str = MEMBER_B, *kinds: GrantScope) -> None:
        membership = make_member(member)
        self.registry.members[membership.id] = membership
        for kind in kinds or tuple(GrantScope):
            grant = make_grant(id=rid(f"grant-{member}-{kind.value}"), tenant=member, scope=kind)
            self.registry.grant_rows[grant.id] = grant
            self.world.sources.append(_active(member, kind))
            self.world.live_rows[(member, kind)] = 2


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


@pytest.fixture(autouse=True)
def _tenant() -> Any:
    with bind_tenant(MEMBER_B):
        yield


def _left(rig: _Rig, member: str) -> None:
    from dataclasses import replace

    from diucs.domain.model.network import MembershipEndReason

    row = rig.registry.members[rid(f"mem-{member}")]
    rig.registry.members[row.id] = replace(
        row, status=MembershipStatus.LEFT, left_at=AT, end_reason=MembershipEndReason.LEFT
    )


# a grant that ended


async def test_an_ended_grant_ends_its_own_source_and_marks_its_rows(rig: _Rig) -> None:
    rig.member_shares(MEMBER_B)
    from dataclasses import replace

    from diucs.domain.model.network import GrantStatus

    grant = rig.registry.grant_rows[rid(f"grant-{MEMBER_B}-capacity")]
    rig.registry.grant_rows[grant.id] = replace(
        grant, status=GrantStatus.ENDED, ended_at=AT, ended_by_account_ref="acct-member-b-01"
    )
    result = await rig.ends.end_grant(
        NETWORK_ID, MEMBER_B, GrantScope.CAPACITY, reason=GrantEndReason.ENDED, at=AT
    )
    assert result == EndResult(sources_ended=1, rows_marked=2)
    assert [(c[0], c[1], c[2], c[3], c[4]) for c in rig.world.ended_calls] == [
        (NET.value, MEMBER_B, GrantScope.CAPACITY, ProjectionEndReason.GRANT_ENDED, AT)
    ]
    # the other two kinds are untouched
    live = {s.kind for s in rig.world.sources if s.status is SourceStatus.ACTIVE}
    assert live == {GrantScope.DIRECTORY, GrantScope.CRITERIA}


async def test_the_end_is_dated_by_the_event_and_not_by_the_time_it_is_handled(rig: _Rig) -> None:
    rig.member_shares(MEMBER_B, GrantScope.CAPACITY)
    from dataclasses import replace

    from diucs.domain.model.network import GrantStatus

    grant = next(iter(rig.registry.grant_rows.values()))
    rig.registry.grant_rows[grant.id] = replace(
        grant, status=GrantStatus.ENDED, ended_at=NOW, ended_by_account_ref="acct-member-b-01"
    )
    early = NOW - timedelta(minutes=5)
    await rig.ends.end_grant(
        NETWORK_ID, MEMBER_B, GrantScope.CAPACITY, reason=GrantEndReason.ENDED, at=early
    )
    assert rig.world.ended_calls[0][4] == early


async def test_a_lapsed_grant_is_ended_like_an_ended_one(rig: _Rig) -> None:
    rig.member_shares(MEMBER_B, GrantScope.DIRECTORY)
    _left(rig, MEMBER_B)
    result = await rig.ends.end_grant(
        NETWORK_ID, MEMBER_B, GrantScope.DIRECTORY, reason=GrantEndReason.LAPSED, at=AT
    )
    assert result.sources_ended == 1


async def test_a_superseded_grant_ends_nothing_because_its_successor_carries_on(
    rig: _Rig,
) -> None:
    rig.member_shares(MEMBER_B, GrantScope.CAPACITY)
    result = await rig.ends.end_grant(
        NETWORK_ID, MEMBER_B, GrantScope.CAPACITY, reason=GrantEndReason.SUPERSEDED, at=AT
    )
    assert result == EndResult(0, 0, skipped=True)
    assert rig.world.opened == 0


async def test_a_grant_that_is_still_effective_in_the_registry_is_not_ended(rig: _Rig) -> None:
    # A late message: the registry says the member shares this scope again (a newer grant).
    rig.member_shares(MEMBER_B, GrantScope.CAPACITY)
    result = await rig.ends.end_grant(
        NETWORK_ID, MEMBER_B, GrantScope.CAPACITY, reason=GrantEndReason.ENDED, at=AT
    )
    assert result == EndResult(0, 0, skipped=True)
    assert rig.world.opened == 0 and rig.world.ended_calls == []


async def test_another_networks_grant_does_not_keep_this_networks_source_open(
    rig: _Rig,
) -> None:
    rig.member_shares(MEMBER_B, GrantScope.CAPACITY)
    # the only effective grant of the member is in another network
    grant = next(iter(rig.registry.grant_rows.values()))
    from dataclasses import replace

    rig.registry.grant_rows[grant.id] = replace(grant, network_id=NETWORK_ID + "-b")
    other = make_network(id=NETWORK_ID + "-b")
    rig.registry.networks[other.id] = (other, rig.registry.networks[NETWORK_ID][1])
    rig.registry.members["mem-other"] = make_member(MEMBER_B, network=other, id="mem-other")
    result = await rig.ends.end_grant(
        NETWORK_ID, MEMBER_B, GrantScope.CAPACITY, reason=GrantEndReason.ENDED, at=AT
    )
    assert result.sources_ended == 1


# a member who left


async def test_a_member_who_left_has_every_source_ended_and_marked(rig: _Rig) -> None:
    rig.member_shares(MEMBER_B)
    rig.member_shares(MEMBER_C)
    _left(rig, MEMBER_B)
    result = await rig.ends.end_member(NETWORK_ID, MEMBER_B, at=AT)
    assert result == EndResult(sources_ended=3, rows_marked=6)
    assert {c[3] for c in rig.world.ended_calls} == {ProjectionEndReason.LEFT}
    assert {c[1] for c in rig.world.ended_calls} == {MEMBER_B}
    # the other member keeps all three
    assert {s.source_tenant_id for s in rig.world.sources if s.status is SourceStatus.ACTIVE} == {
        MEMBER_C
    }


async def test_a_member_who_is_active_again_is_not_ended_by_a_late_message(rig: _Rig) -> None:
    rig.member_shares(MEMBER_B)
    result = await rig.ends.end_member(NETWORK_ID, MEMBER_B, at=AT)
    assert result.skipped and rig.world.opened == 0


# the unit and the audit


async def test_one_network_unit_bound_to_the_network_does_the_whole_end(rig: _Rig) -> None:
    rig.member_shares(MEMBER_B)
    _left(rig, MEMBER_B)
    await rig.ends.end_member(NETWORK_ID, MEMBER_B, at=AT)
    assert rig.world.opened == 1 and rig.world.commits == 1
    assert rig.world.max_open == 1


async def test_one_audit_entry_names_the_member_the_kinds_and_the_counts_and_no_value(
    rig: _Rig,
) -> None:
    rig.member_shares(MEMBER_B)
    _left(rig, MEMBER_B)
    await rig.ends.end_member(NETWORK_ID, MEMBER_B, at=AT)
    [(scope, entry)] = rig.world.audits
    assert scope == NET.value
    assert (entry.use_case, entry.action, entry.at) == ("EndProjection", "U", AT)
    assert entry.entity_ids == (MEMBER_B,)
    assert entry.snapshot == {
        "reason": "left",
        "kinds": ["capacity", "criteria", "directory"],
        "sources_ended": 3,
        "rows_marked": 6,
    }
    assert entry.actor.tenant_id == MEMBER_B


async def test_a_second_run_changes_and_audits_nothing(rig: _Rig) -> None:
    rig.member_shares(MEMBER_B)
    _left(rig, MEMBER_B)
    await rig.ends.end_member(NETWORK_ID, MEMBER_B, at=AT)
    again = await rig.ends.end_member(NETWORK_ID, MEMBER_B, at=AT + timedelta(minutes=1))
    assert again == EndResult(0, 0)
    assert len(rig.world.audits) == 1
    assert rig.world.commits == 2  # the empty unit still closes cleanly


async def test_an_unknown_network_is_refused_before_a_unit_opens(rig: _Rig) -> None:
    from diucs.domain.errors import ValidationFailed

    with pytest.raises(ValidationFailed):
        await rig.ends.end_member("not-a-network", MEMBER_B, at=AT)
    assert rig.world.opened == 0


async def test_a_failed_commit_leaves_the_end_to_be_retried(rig: _Rig) -> None:
    rig.member_shares(MEMBER_B)
    _left(rig, MEMBER_B)
    rig.world.fail_commit = "network"
    with pytest.raises(ConnectionError):
        await rig.ends.end_member(NETWORK_ID, MEMBER_B, at=AT)
    assert rig.world.commits == 0
