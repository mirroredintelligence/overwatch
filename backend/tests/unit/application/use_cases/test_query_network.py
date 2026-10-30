"""The network read use cases (TEN-057, DEC-546, DEC-132 item 4, DEC-134 items 6 and 8).

Read-only: each opens a read-only unit of work in the network scope, after the membership, role and
grant check, and uses `network_view` alone. A projection holds inputs, never a status, so the status
of a row is worked out at the time of the read and a service that stops reporting reads Not updated
with no new event (hazard H-N07). A row that no effective grant and admitted listing stands behind
is left out, a member who left shows only in the history, and no row names the member's tenant, the
grant or the member's own service id.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.network_access import NetworkAccess
from diucs.application.ports.outbound.projection import ProjectedRow
from diucs.application.tenancy import ScopeKind, current_scope_or_none
from diucs.application.use_cases.query_network_board import (
    NetworkReadUnitNotReadOnly,
    QueryNetworkBoard,
)
from diucs.application.use_cases.query_network_directory import (
    QueryNetworkCriteria,
    QueryNetworkDirectory,
)
from diucs.domain.codes import Role, Status
from diucs.domain.errors import NotFound
from diucs.domain.model.network import GrantScope, MembershipStatus
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.projection import CapacityProjection, CriteriaProjection, ServiceProjection
from tests.support.network_samples import (
    MEMBER_B,
    MEMBER_C,
    NETWORK_ID,
    OUTSIDER,
    SETTINGS,
    make_grant,
    make_listing,
    make_member,
)
from tests.support.projection_samples import (
    NOW,
    REPORTED_AT,
    sample_capacity_projection,
    sample_criteria_projection,
    sample_report,
    sample_service_projection,
)
from tests.unit.application.test_network_access import Names, Registry, actor


class View:
    def __init__(
        self,
        services: Sequence[ProjectedRow[ServiceProjection]] = (),
        capacities: Sequence[ProjectedRow[CapacityProjection]] = (),
        criteria: Sequence[ProjectedRow[CriteriaProjection]] = (),
    ) -> None:
        self._services = list(services)
        self._capacities = list(capacities)
        self._criteria = list(criteria)
        self.asked: list[tuple[str, bool]] = []

    async def services(
        self, *, live_only: bool = True
    ) -> Sequence[ProjectedRow[ServiceProjection]]:
        self.asked.append(("services", live_only))
        return [r for r in self._services if not live_only or r.ended_at is None]

    async def capacities(
        self, *, live_only: bool = True
    ) -> Sequence[ProjectedRow[CapacityProjection]]:
        self.asked.append(("capacities", live_only))
        return [r for r in self._capacities if not live_only or r.ended_at is None]

    async def criteria(
        self, *, live_only: bool = True
    ) -> Sequence[ProjectedRow[CriteriaProjection]]:
        self.asked.append(("criteria", live_only))
        return [r for r in self._criteria if not live_only or r.ended_at is None]


class Unit:
    def __init__(self, view: View, read_only: bool, scopes: list[Any]) -> None:
        self.network_view = view
        self.read_only = read_only
        self._scopes = scopes

    async def __aenter__(self) -> Unit:
        self._scopes.append(current_scope_or_none())
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class Factory:
    def __init__(self, view: View, read_only: bool = True) -> None:
        self.view = view
        self.read_only = read_only
        self.scopes: list[Any] = []
        self.opened = 0

    def __call__(self) -> Unit:
        self.opened += 1
        return Unit(self.view, self.read_only, self.scopes)


def row[T](projection: T, tenant: str = MEMBER_B, **changes: Any) -> ProjectedRow[T]:
    fields: dict[str, Any] = {
        "source_tenant_id": tenant,
        "projection": projection,
        "projected_at": REPORTED_AT,
        "grant_id": "g-x",
        "ended_at": None,
        "end_reason": None,
    }
    fields.update(changes)
    return ProjectedRow(**fields)


def registry(
    *,
    left: bool = False,
    scopes: Sequence[GrantScope] = (GrantScope.CAPACITY, GrantScope.DIRECTORY, GrantScope.CRITERIA),
) -> Registry:
    members = [
        make_member(MEMBER_B),
        make_member(MEMBER_C, status=MembershipStatus.LEFT if left else MembershipStatus.ACTIVE),
    ]
    grants = [make_grant(id=f"g-b-{s.value}", scope=s) for s in scopes]
    grants += [make_grant(id=f"g-c-{s.value}", tenant=MEMBER_C, scope=s) for s in scopes]
    return Registry(
        members,
        grants=grants,
        listings=[make_listing(), make_listing(id="lst-c-1", tenant=MEMBER_C, service="svc-9")],
    )


def names() -> Names:
    return Names({MEMBER_B: "B Trust", MEMBER_C: "C Trust"})


def board_use_case(
    view: View, reg: Registry | None = None, *, read_only: bool = True, at: datetime = NOW
) -> tuple[QueryNetworkBoard, Factory]:
    factory = Factory(view, read_only)
    gate = NetworkAccess(reg or registry(), names())  # type: ignore[arg-type]
    return QueryNetworkBoard(factory, gate, FixedClock(at)), factory  # type: ignore[arg-type]


def both() -> View:
    return View(
        services=[
            row(sample_service_projection()),
            row(sample_service_projection(profile=_other_profile()), MEMBER_C),
        ],
        capacities=[
            row(sample_capacity_projection()),
            row(
                sample_capacity_projection(
                    profile=_other_profile(), latest=sample_report(service_id="svc-9")
                ),
                MEMBER_C,
            ),
        ],
    )


def _other_profile() -> Any:
    from tests.support.projection_samples import sample_profile

    return sample_profile(id="svc-9", name="Frailty East")


# the board


async def test_the_board_has_a_row_for_each_admitted_service_with_a_capacity_grant() -> None:
    use_case, _ = board_use_case(both())
    result = await use_case.execute(actor(), NETWORK_ID)
    assert {e.organisation_name for e in result.board.entries} == {"B Trust", "C Trust"}
    assert {e.service_name for e in result.board.entries} == {"UCR West", "Frailty East"}
    assert all(e.presentation is ListingPresentation.SHOWN for e in result.board.entries)
    assert all(e.status is not Status.NOT_UPDATED for e in result.board.entries)
    assert result.board.generated_at == NOW


async def test_the_result_carries_the_networks_own_settings_and_zone() -> None:
    use_case, _ = board_use_case(both())
    result = await use_case.execute(actor(), NETWORK_ID)
    assert (result.system_name, result.pathway_name, result.time_zone) == (
        SETTINGS.system_name,
        SETTINGS.pathway_name,
        SETTINGS.time_zone,
    )


async def test_the_unit_is_read_only_and_opened_in_the_network_scope() -> None:
    use_case, factory = board_use_case(both())
    await use_case.execute(actor(), NETWORK_ID)
    [scope] = factory.scopes
    assert scope.kind is ScopeKind.NETWORK and scope.value == NETWORK_ID
    assert current_scope_or_none() is None  # the binding ends with the read
    assert factory.view.asked == [("services", True), ("capacities", True)]


async def test_a_unit_that_could_write_is_refused() -> None:
    use_case, _ = board_use_case(both(), read_only=False)
    with pytest.raises(NetworkReadUnitNotReadOnly):
        await use_case.execute(actor(), NETWORK_ID)


async def test_a_non_member_is_not_found_and_no_unit_is_opened() -> None:
    use_case, factory = board_use_case(both())
    with pytest.raises(NotFound):
        await use_case.execute(actor(OUTSIDER), NETWORK_ID)
    assert factory.opened == 0


async def test_a_role_that_never_sees_a_network_opens_nothing() -> None:
    from diucs.domain.errors import NotAllowed

    use_case, factory = board_use_case(both())
    with pytest.raises(NotAllowed):
        await use_case.execute(actor(role=Role.REPORTER), NETWORK_ID)
    assert factory.opened == 0


async def test_a_service_with_no_capacity_grant_is_left_out() -> None:
    reg = registry(scopes=(GrantScope.DIRECTORY,))
    use_case, _ = board_use_case(both(), reg)
    result = await use_case.execute(actor(), NETWORK_ID)
    assert result.board.entries == ()


async def test_a_service_whose_listing_is_not_admitted_is_left_out() -> None:
    reg = registry()
    reg._listings[0] = make_listing(admitted=False)
    use_case, _ = board_use_case(both(), reg)
    result = await use_case.execute(actor(), NETWORK_ID)
    assert {e.organisation_name for e in result.board.entries} == {"C Trust"}


async def test_a_member_who_left_is_not_on_the_live_board() -> None:
    use_case, _ = board_use_case(both(), registry(left=True))
    result = await use_case.execute(actor(), NETWORK_ID)
    assert {e.organisation_name for e in result.board.entries} == {"B Trust"}


async def test_a_projection_row_with_no_listing_is_left_out() -> None:
    view = View(
        services=[row(sample_service_projection(profile=_other_profile(), source_version=2))],
        capacities=[],
    )
    reg = Registry(
        [make_member(MEMBER_B)],
        grants=[make_grant(), make_grant(id="g-d", scope=GrantScope.DIRECTORY)],
    )
    use_case, _ = board_use_case(view, reg)
    assert (await use_case.execute(actor(), NETWORK_ID)).board.entries == ()


async def test_a_service_that_stops_reporting_reads_not_updated_with_no_new_event() -> None:
    fresh, _ = board_use_case(both(), at=NOW)
    stale, _ = board_use_case(both(), at=NOW + timedelta(days=3))
    before = (await fresh.execute(actor(), NETWORK_ID)).board.entries
    after = (await stale.execute(actor(), NETWORK_ID)).board.entries
    assert all(e.status is not Status.NOT_UPDATED for e in before)
    assert all(e.status is Status.NOT_UPDATED for e in after)
    assert all(e.reported_at == REPORTED_AT for e in after)  # its age is from the source's time


async def test_a_service_with_no_capacity_row_reads_not_updated() -> None:
    view = View(services=[row(sample_service_projection())], capacities=[])
    use_case, _ = board_use_case(view)
    [entry] = (await use_case.execute(actor(), NETWORK_ID)).board.entries
    assert entry.status is Status.NOT_UPDATED


async def test_no_entry_names_a_tenant_a_grant_or_a_source_service() -> None:
    use_case, _ = board_use_case(both())
    result = await use_case.execute(actor(), NETWORK_ID)
    text = repr(result.board)
    for hidden in (MEMBER_B, MEMBER_C, "g-b-capacity", "g-x", "svc-9"):
        assert hidden not in text
    assert {e.row_ref for e in result.board.entries} == {make_listing().id, "lst-c-1"}


async def test_the_pressure_is_over_the_shown_entries_with_the_default_thresholds() -> None:
    use_case, _ = board_use_case(both())
    result = await use_case.execute(actor(), NETWORK_ID)
    assert result.board.pressure is not None


# the directory


def directory_use_case(
    view: View, reg: Registry | None = None
) -> tuple[QueryNetworkDirectory, Factory]:
    factory = Factory(view)
    gate = NetworkAccess(reg or registry(), names())  # type: ignore[arg-type]
    return QueryNetworkDirectory(factory, gate, FixedClock(NOW)), factory  # type: ignore[arg-type]


async def test_the_directory_lists_the_live_services_of_members_who_share_it() -> None:
    use_case, factory = directory_use_case(both())
    result = await use_case.execute(actor(), NETWORK_ID)
    assert {(e.organisation_name, e.service_name) for e in result.entries} == {
        ("B Trust", "UCR West"),
        ("C Trust", "Frailty East"),
    }
    assert factory.view.asked == [("services", True)]
    assert all(e.ended_at is None and e.end_reason is None for e in result.entries)


async def test_the_directory_needs_the_directory_scope() -> None:
    reg = registry(scopes=(GrantScope.CAPACITY,))
    use_case, _ = directory_use_case(both(), reg)
    assert (await use_case.execute(actor(), NETWORK_ID)).entries == ()


async def test_a_departed_member_is_only_in_the_history_with_the_date_and_the_reason() -> None:
    left_at = NOW - timedelta(days=1)
    view = View(
        services=[
            row(sample_service_projection()),
            row(
                sample_service_projection(profile=_other_profile()),
                MEMBER_C,
                ended_at=left_at,
                end_reason=_left(),
            ),
        ]
    )
    reg = registry(left=True)
    live, _ = directory_use_case(view, reg)
    history, factory = directory_use_case(view, reg)
    assert {e.organisation_name for e in (await live.execute(actor(), NETWORK_ID)).entries} == {
        "B Trust"
    }
    entries = (await history.execute(actor(), NETWORK_ID, history=True)).entries
    assert factory.view.asked[-1] == ("services", False)
    by_name = {e.organisation_name: e for e in entries}
    assert by_name["C Trust"].ended_at == left_at
    assert by_name["C Trust"].end_reason is _left()
    assert by_name["B Trust"].ended_at is None


def _left() -> Any:
    from diucs.application.ports.outbound.projection import ProjectionEndReason

    return ProjectionEndReason.LEFT


async def test_a_directory_entry_names_no_tenant_no_grant_and_no_source_service() -> None:
    use_case, _ = directory_use_case(both())
    result = await use_case.execute(actor(), NETWORK_ID)
    text = repr(result)
    for hidden in (MEMBER_B, MEMBER_C, "g-x", "svc-1", "svc-9"):
        assert hidden not in text


async def test_the_directory_refuses_a_non_member() -> None:
    use_case, factory = directory_use_case(both())
    with pytest.raises(NotFound):
        await use_case.execute(actor(OUTSIDER), NETWORK_ID)
    assert factory.opened == 0


# the criteria


def criteria_use_case(
    view: View, reg: Registry | None = None
) -> tuple[QueryNetworkCriteria, Factory]:
    factory = Factory(view)
    gate = NetworkAccess(reg or registry(), names())  # type: ignore[arg-type]
    return QueryNetworkCriteria(factory, gate, FixedClock(NOW)), factory  # type: ignore[arg-type]


def with_criteria() -> View:
    base = both()
    return View(
        services=base._services,
        criteria=[row(sample_criteria_projection())],
    )


async def test_the_criteria_are_the_current_version_of_each_shared_service() -> None:
    use_case, factory = criteria_use_case(with_criteria())
    result = await use_case.execute(actor(), NETWORK_ID)
    [entry] = result.entries
    assert (entry.organisation_name, entry.service_name) == ("B Trust", "UCR West")
    assert (entry.version, entry.age_min, entry.age_max) == (3, 18, None)
    assert factory.view.asked == [("services", True), ("criteria", True)]
    assert "svc-1" not in repr(result) and MEMBER_B not in repr(result)


async def test_the_criteria_need_the_criteria_scope() -> None:
    use_case, _ = criteria_use_case(
        with_criteria(), registry(scopes=(GrantScope.CAPACITY, GrantScope.DIRECTORY))
    )
    assert (await use_case.execute(actor(), NETWORK_ID)).entries == ()


async def test_a_criteria_row_for_a_service_with_no_directory_row_is_left_out() -> None:
    view = View(services=[], criteria=[row(sample_criteria_projection())])
    use_case, _ = criteria_use_case(view)
    assert (await use_case.execute(actor(), NETWORK_ID)).entries == ()
