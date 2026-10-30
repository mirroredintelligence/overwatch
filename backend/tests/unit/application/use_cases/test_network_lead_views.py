"""What the lead reads of a network beyond its board: system now and the phones (TEN-082, the
network variants of W17 and W43; DEC-136 items 1, 9 and 14).

Both read through the board projector and the directory, so they hold only what those hold: counts
and a pressure state (never a task or a push), and the service line each organisation shared.
"""

import pytest

from diucs.application.actor import Actor
from diucs.application.use_cases.network_lead_views import (
    STATUS_KEYS,
    UNAVAILABLE_KEY,
    QueryPhones,
    QuerySystemNow,
    status_counts,
)
from diucs.application.use_cases.query_network_board import NetworkBoardView
from diucs.application.use_cases.query_network_directory import (
    NetworkDirectoryEntry,
    NetworkDirectoryView,
)
from diucs.domain.codes import Role, ServiceCategory, Status
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.network import DirectorySource
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.pressure import Pressure
from tests.support.network_board_samples import BOARD_AT, board_entry, board_of

NET = "net-pilot"
WATCH_FROM = DEFAULT_POLICY.pressure_watch_from
HIGH_FROM = DEFAULT_POLICY.pressure_high_from


def _viewer(role: Role = Role.LEAD) -> Actor:
    return Actor(role, "prac-1", None, "web", frozenset(), "tenant-b")


class _Projector:
    def __init__(self, view: NetworkBoardView) -> None:
        self._view = view
        self.asked: list[tuple[Role, str]] = []
        self.refuse: Exception | None = None

    async def get_board(self, actor: Actor, network_id: str) -> NetworkBoardView:
        self.asked.append((actor.role, network_id))
        if self.refuse is not None:
            raise self.refuse
        return self._view


class _Directory:
    def __init__(self, view: NetworkDirectoryView) -> None:
        self._view = view

    async def execute(
        self, actor: Actor, network_id: str, *, history: bool = False
    ) -> NetworkDirectoryView:
        assert history is False
        return self._view


def _view(*entries, pressure: Pressure | None = None) -> NetworkBoardView:  # type: ignore[no-untyped-def]
    board = board_of(*entries)
    return NetworkBoardView(board, "Capacity board", "Urgent pathway", "Europe/London")


def _limited(n: int) -> list:  # type: ignore[type-arg]
    return [board_entry(f"l{i}", f"Org {i}", Status.LIMITED) for i in range(n)]


async def test_system_now_counts_every_status_and_the_unavailable_rows() -> None:
    view = _view(
        board_entry("a", "North", Status.ACCEPTING),
        board_entry("b", "North", Status.LIMITED),
        board_entry("c", "South", Status.NOT_UPDATED, stale=True),
        board_entry("d", "East", Status.OUT_OF_HOURS),
        board_entry("e", "East", None),
    )
    result = await QuerySystemNow(_Projector(view)).execute(_viewer(), NET)  # type: ignore[arg-type]
    assert set(result.by_status) == set(STATUS_KEYS)
    assert result.by_status["accepting"] == 1
    assert result.by_status["limited"] == 1
    assert result.by_status["not-updated"] == 1
    assert result.by_status["out-of-hours"] == 1
    assert result.by_status[UNAVAILABLE_KEY] == 1
    assert result.by_status["over-capacity"] == 0
    assert (result.services, result.organisations) == (5, 3)
    assert result.generated_at == BOARD_AT
    assert (result.system_name, result.pathway_name) == ("Capacity board", "Urgent pathway")


@pytest.mark.parametrize(
    ("limited", "level", "raised"),
    [
        (0, Pressure.NORMAL, False),
        (WATCH_FROM - 1, Pressure.NORMAL, False),
        (WATCH_FROM, Pressure.WATCH, False),
        (HIGH_FROM - 1, Pressure.WATCH, False),
        (HIGH_FROM, Pressure.HIGH, True),
    ],
)
async def test_the_pressure_alert_is_raised_while_the_pressure_is_high(
    limited: int, level: Pressure, raised: bool
) -> None:
    view = _view(*_limited(limited), board_entry("z", "Last", Status.ACCEPTING))
    result = await QuerySystemNow(_Projector(view)).execute(_viewer(), NET)  # type: ignore[arg-type]
    assert result.pressure is level
    assert result.alert.raised is raised and result.alert.level is level
    assert result.alert.limited_or_worse == limited
    assert (result.alert.watch_from, result.alert.high_from) == (WATCH_FROM, HIGH_FROM)


async def test_not_updated_and_out_of_hours_do_not_count_towards_the_alert() -> None:
    entries = [board_entry(f"n{i}", f"Org {i}", Status.NOT_UPDATED) for i in range(5)]
    entries += [board_entry(f"o{i}", f"Out {i}", Status.OUT_OF_HOURS) for i in range(5)]
    result = await QuerySystemNow(_Projector(_view(*entries))).execute(_viewer(), NET)  # type: ignore[arg-type]
    assert result.alert.raised is False and result.alert.limited_or_worse == 0


async def test_system_now_is_refused_as_the_board_is_and_asks_the_gate_with_the_viewer() -> None:
    projector = _Projector(_view())
    projector.refuse = NotFound("the network was not found")
    with pytest.raises(NotFound):
        await QuerySystemNow(projector).execute(_viewer(Role.EXEC), NET)  # type: ignore[arg-type]
    assert projector.asked == [(Role.EXEC, NET)]
    projector.refuse = NotAllowed("this role cannot see a network")
    with pytest.raises(NotAllowed):
        await QuerySystemNow(projector).execute(_viewer(Role.WALL), NET)  # type: ignore[arg-type]


async def test_system_now_names_no_organisation_service_or_row() -> None:
    view = _view(board_entry("row-ref-7", "North Trust", Status.ACCEPTING))
    result = await QuerySystemNow(_Projector(view)).execute(_viewer(), NET)  # type: ignore[arg-type]
    text = repr(result)
    assert "North" not in text and "row-ref-7" not in text and "Service" not in text


def test_status_counts_always_hold_every_key() -> None:
    assert status_counts(()) == dict.fromkeys(STATUS_KEYS, 0)


# ---- phones


def _listed(
    ref: str, organisation: str, phone: str | None, label: str | None
) -> NetworkDirectoryEntry:
    return NetworkDirectoryEntry(
        row_ref=ref,
        organisation_name=organisation,
        service_name=f"Service {ref}",
        category=ServiceCategory.REABLEMENT,
        active=True,
        source=DirectorySource.MANUAL,
        contact_label=label,
        contact_phone=phone,
        location=None,
        opening_hours=(),
        presentation=ListingPresentation.SHOWN,
        ended_at=None,
        end_reason=None,
    )


def _directory(*entries: NetworkDirectoryEntry) -> _Directory:
    return _Directory(
        NetworkDirectoryView(entries, "Capacity board", "Urgent pathway", "Europe/London")
    )


async def test_a_phone_row_joins_the_directory_line_to_the_status_of_the_same_row() -> None:
    board = _view(
        board_entry("a", "North", Status.LIMITED, stale=True),
        board_entry("b", "South", Status.ACCEPTING),
    )
    directory = _directory(
        _listed("a", "North", "01305 900001", "Intake line"),
        _listed("b", "South", None, None),
    )
    result = await QueryPhones(_Projector(board), directory).execute(_viewer(), NET)  # type: ignore[arg-type]
    first, second = result.phones
    assert (first.organisation_name, first.status, first.stale_warning) == (
        "North",
        Status.LIMITED,
        True,
    )
    assert (first.contact_label, first.contact_phone) == ("Intake line", "01305 900001")
    assert second.contact_phone is None and second.contact_label is None
    assert second.status is Status.ACCEPTING
    assert result.organisations == 2


async def test_a_directory_row_with_no_board_row_has_no_status_and_keeps_its_line() -> None:
    board = _view(board_entry("a", "North", Status.LIMITED))
    directory = _directory(_listed("zz", "West", "01305 900002", "Intake line"))
    result = await QueryPhones(_Projector(board), directory).execute(_viewer(), NET)  # type: ignore[arg-type]
    assert result.phones[0].status is None
    assert result.phones[0].reported_at is None
    assert result.phones[0].stale_warning is False


async def test_the_phones_keep_the_directory_order() -> None:
    directory = _directory(_listed("a", "Alpha", None, None), _listed("b", "Beta", None, None))
    result = await QueryPhones(_Projector(_view()), directory).execute(_viewer(), NET)  # type: ignore[arg-type]
    assert [p.organisation_name for p in result.phones] == ["Alpha", "Beta"]


async def test_phones_are_refused_as_the_board_is() -> None:
    projector = _Projector(_view())
    projector.refuse = NotFound("the network was not found")
    with pytest.raises(NotFound):
        await QueryPhones(projector, _directory()).execute(_viewer(), NET)  # type: ignore[arg-type]


async def test_a_phone_row_has_only_the_organisations_service_line() -> None:
    fields = set(NetworkDirectoryEntry.__dataclass_fields__)
    assert not {"reporter", "phone_hash", "cover", "tenant_id", "source_tenant_id"} & fields
    from diucs.application.use_cases.network_lead_views import NetworkPhone

    assert set(NetworkPhone.__dataclass_fields__) == {
        "row_ref",
        "organisation_name",
        "service_name",
        "category",
        "presentation",
        "status",
        "stale_warning",
        "reported_at",
        "contact_label",
        "contact_phone",
    }
