"""The revoked-grant leak check (TEN-056, hazard H-N05, audit F section 4.7).

The registry is the truth and the network scope is derived from it. Reconciliation reads what the
network scope holds for one member (its sources, and any live row) and ends what the registry no
longer allows: a source with no effective grant, a source of a member who left, a live row under an
ended source (a step that was lost). What the registry still allows is left alone, and a run that
finds nothing changes and audits nothing. It reads in a read-only network unit and ends through
`EndProjections`, so the two units are never nested.
"""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.projection import SourceState, SourceStatus
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.network_leave import EndProjections
from diucs.application.use_cases.projection_reconcile import ReconcileProjection, ReconcileResult
from diucs.domain.model.network import (
    GrantScope,
    GrantStatus,
    MembershipEndReason,
    MembershipStatus,
    NetworkStatus,
)
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


class _Rig:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.world = UnitWorld(self.log)
        self.registry = MemoryRegistry(self.log)
        self.registry.seed(make_network(), members=[make_owner_membership()])
        factories = UnitFactories(self.world)
        clock = FixedClock(AT)
        ends = EndProjections(factories.network, self.registry, clock)  # type: ignore[arg-type]
        self.reconcile = ReconcileProjection(
            factories.network_read_only,  # type: ignore[arg-type]
            ends,
            self.registry,  # type: ignore[arg-type]
            clock,
        )

    def shares(self, member: str, *kinds: GrantScope, rows: int = 1) -> None:
        self.registry.members.setdefault(rid(f"mem-{member}"), make_member(member))
        for kind in kinds:
            grant = make_grant(id=rid(f"grant-{member}-{kind.value}"), tenant=member, scope=kind)
            self.registry.grant_rows[grant.id] = grant
            self.world.sources.append(
                SourceState(member, kind, SourceStatus.ACTIVE, grant.id, None, None)
            )
            self.world.live_rows[(member, kind)] = rows

    def revoke(self, member: str, kind: GrantScope) -> None:
        key = rid(f"grant-{member}-{kind.value}")
        grant = self.registry.grant_rows[key]
        self.registry.grant_rows[key] = replace(
            grant, status=GrantStatus.ENDED, ended_at=NOW, ended_by_account_ref="acct-member-b-01"
        )

    def leave(self, member: str) -> None:
        key = rid(f"mem-{member}")
        row = self.registry.members[key]
        self.registry.members[key] = replace(
            row, status=MembershipStatus.LEFT, left_at=NOW, end_reason=MembershipEndReason.LEFT
        )


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


@pytest.fixture(autouse=True)
def _tenant() -> Any:
    with bind_tenant(MEMBER_B):
        yield


async def test_a_member_whose_grants_all_stand_is_left_alone(rig: _Rig) -> None:
    rig.shares(MEMBER_B, *GrantScope)
    result = await rig.reconcile.member(NETWORK_ID, MEMBER_B)
    assert result == ReconcileResult(checked=3, sources_ended=0, rows_marked=0)
    assert rig.world.audits == [] and rig.world.ended_calls == []


async def test_a_revoked_grant_that_still_has_a_live_source_is_ended(rig: _Rig) -> None:
    rig.shares(MEMBER_B, *GrantScope, rows=2)
    rig.revoke(MEMBER_B, GrantScope.CAPACITY)
    result = await rig.reconcile.member(NETWORK_ID, MEMBER_B)
    assert result == ReconcileResult(checked=3, sources_ended=1, rows_marked=2)
    assert [(c[2]) for c in rig.world.ended_calls] == [GrantScope.CAPACITY]


async def test_a_member_who_left_has_everything_ended(rig: _Rig) -> None:
    rig.shares(MEMBER_B, *GrantScope, rows=1)
    rig.leave(MEMBER_B)
    result = await rig.reconcile.member(NETWORK_ID, MEMBER_B)
    assert (result.sources_ended, result.rows_marked) == (3, 3)


async def test_a_live_row_under_an_ended_source_is_marked_though_no_source_is_active(
    rig: _Rig,
) -> None:
    rig.shares(MEMBER_B, GrantScope.CAPACITY, rows=3)
    rig.revoke(MEMBER_B, GrantScope.CAPACITY)
    rig.world.sources[:] = [
        replace(s, status=SourceStatus.ENDED, ended_at=NOW) for s in rig.world.sources
    ]
    result = await rig.reconcile.member(NETWORK_ID, MEMBER_B)
    assert (result.sources_ended, result.rows_marked) == (0, 3)


async def test_only_the_named_member_is_looked_at(rig: _Rig) -> None:
    rig.shares(MEMBER_B, GrantScope.CAPACITY)
    rig.shares(MEMBER_C, GrantScope.CAPACITY)
    rig.revoke(MEMBER_C, GrantScope.CAPACITY)
    result = await rig.reconcile.member(NETWORK_ID, MEMBER_B)
    assert result.sources_ended == 0
    assert all(c[1] == MEMBER_B for c in rig.world.ended_calls)


async def test_a_network_that_is_not_active_reconciles_nothing(rig: _Rig) -> None:
    rig.shares(MEMBER_B, GrantScope.CAPACITY)
    network = rig.registry.networks[NETWORK_ID][0]
    rig.registry.networks[NETWORK_ID] = (
        replace(network, status=NetworkStatus.SUSPENDED),
        rig.registry.networks[NETWORK_ID][1],
    )
    assert await rig.reconcile.member(NETWORK_ID, MEMBER_B) == ReconcileResult(0, 0, 0)
    assert rig.world.opened == 0


async def test_an_unknown_network_reconciles_nothing(rig: _Rig) -> None:
    assert await rig.reconcile.member(NETWORK_ID + "-z", MEMBER_B) == ReconcileResult(0, 0, 0)


async def test_the_read_and_the_end_are_never_one_unit(rig: _Rig) -> None:
    rig.shares(MEMBER_B, GrantScope.CAPACITY)
    rig.revoke(MEMBER_B, GrantScope.CAPACITY)
    await rig.reconcile.member(NETWORK_ID, MEMBER_B)
    assert rig.world.max_open == 1
    assert rig.world.opened == 2


async def test_a_second_run_finds_nothing(rig: _Rig) -> None:
    rig.shares(MEMBER_B, GrantScope.CAPACITY)
    rig.revoke(MEMBER_B, GrantScope.CAPACITY)
    await rig.reconcile.member(NETWORK_ID, MEMBER_B)
    again = await rig.reconcile.member(NETWORK_ID, MEMBER_B)
    assert again.sources_ended == 0 and again.rows_marked == 0
    assert len(rig.world.audits) == 1
