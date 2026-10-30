"""The projection repository without a database (TEN-053): what it sends, what it refuses to send
and what it makes of the rows it gets back.

The transaction is a recording stub on a scoped transaction in a network scope (a unit of work
hands a repository exactly that); no Neo4j. What the statements do on a real database, with two
networks holding the same source and service ids, is the generated test (TEN-060) and
`tests/integration/graph_store/test_projection_repository.py`.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import Any, cast

import pytest
from neo4j.time import Date, DateTime
from neo4j.time import Time as Neo4jTime

from diucs.adapters.outbound.graph_store.driver import ScopedTx
from diucs.adapters.outbound.graph_store.projection_repository import Neo4jProjectionRepository
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.application.ports.outbound.projection import (
    GrantRef,
    ProjectionEndReason,
    ProjectionRecordInvalid,
    SourceStatus,
)
from diucs.application.projection import to_rows
from diucs.application.tenancy import (
    ReadOnlyUnitWrite,
    ScopeId,
    ScopeKindMismatch,
    SourceTenantRefused,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.network import GrantScope
from diucs.domain.rules.projection import OpeningHourProjection
from tests.support.network_connection import NetworkTx
from tests.support.projection_samples import (
    sample_capacity_projection,
    sample_criteria_projection,
    sample_service_projection,
)

NET = ScopeId.network("net-pilot")
SOURCE = "tenant-x"
GRANT = GrantRef("grant-x-1", 3)
AT = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
LEFT = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def _repository(
    answers: dict[str, list[dict[str, Any]]] | None = None,
    *,
    scope: ScopeId = NET,
    read_only: bool = False,
) -> tuple[Neo4jProjectionRepository, NetworkTx]:
    tx = NetworkTx({} if answers is None else answers, {})
    return Neo4jProjectionRepository(ScopedTx(cast(Any, tx), scope, read_only)), tx


def _ids(tx: NetworkTx) -> list[str]:
    by_text = {REGISTRY.get(i).cypher: i for i in REGISTRY.ids() if i.startswith("Q-PROJ-")}
    by_text |= {REGISTRY.get(i).cypher: i for i in REGISTRY.ids() if i.startswith("Q-NETVIEW-")}
    return [by_text[text] for text, _ in tx.calls]


def _written(count: int = 1) -> list[dict[str, Any]]:
    return [{"written": count}]


# The source


async def test_a_source_is_opened_with_the_member_the_kind_and_the_grant_and_no_tenant() -> None:
    repository, tx = _repository({"Q-PROJ-SOURCE-OPEN": [{"status": "active"}]})
    await repository.open_source(SOURCE, GrantScope.CAPACITY, GRANT)
    [(_, params)] = tx.calls
    assert params == {
        "tenant": "net-pilot",
        "sourceTenant": SOURCE,
        "kind": "capacity",
        "grantId": "grant-x-1",
    }


async def test_ending_a_source_says_whether_it_was_active() -> None:
    repository, tx = _repository({"Q-PROJ-SOURCE-END": [{"kind": "capacity"}]})
    assert await repository.end_source(
        SOURCE, GrantScope.CAPACITY, at=LEFT, reason=ProjectionEndReason.LEFT
    )
    assert tx.calls[0][1] == {
        "tenant": "net-pilot",
        "sourceTenant": SOURCE,
        "kind": "capacity",
        "endedAt": LEFT,
        "endReason": "left",
    }
    quiet, _ = _repository({"Q-PROJ-SOURCE-END": []})
    assert not await quiet.end_source(
        SOURCE, GrantScope.CAPACITY, at=LEFT, reason=ProjectionEndReason.GRANT_ENDED
    )


async def test_a_source_is_read_with_its_end_marks() -> None:
    row = {
        "source": {
            "sourceTenantId": SOURCE,
            "kind": "directory",
            "status": "ended",
            "grantId": "grant-x-1",
            "endedAt": DateTime.from_native(LEFT),
            "endReason": "grant-ended",
        }
    }
    repository, _ = _repository({"Q-PROJ-SOURCE-GET": [row], "Q-PROJ-SOURCES": [row]})
    state = await repository.source(SOURCE, GrantScope.DIRECTORY)
    assert state is not None
    assert (state.status, state.ended_at, state.end_reason) == (
        SourceStatus.ENDED,
        LEFT,
        ProjectionEndReason.GRANT_ENDED,
    )
    assert [s.kind for s in await repository.sources()] == [GrantScope.DIRECTORY]
    empty, _ = _repository()
    assert await empty.source(SOURCE, GrantScope.DIRECTORY) is None


async def test_a_member_that_is_not_a_tenant_id_is_refused_before_anything_is_sent() -> None:
    repository, tx = _repository()
    for bad in ("net-pilot", "", "A1", "a"):
        with pytest.raises(SourceTenantRefused):
            await repository.open_source(bad, GrantScope.CAPACITY, GRANT)
    assert tx.calls == []


async def test_a_kind_that_is_not_a_grant_scope_is_refused() -> None:
    repository, tx = _repository()
    with pytest.raises(ValidationFailed):
        await repository.open_source(SOURCE, "capacity", GRANT)  # type: ignore[arg-type]
    assert tx.calls == []


# The upserts


async def test_a_service_is_written_with_its_location_and_its_hours_in_order() -> None:
    service = sample_service_projection()
    repository, tx = _repository(
        {
            "Q-PROJ-SERVICE-UPSERT": _written(),
            "Q-PROJ-LOCATION-UPSERT": _written(),
            "Q-PROJ-HOUR-UPSERT": _written(),
            "Q-PROJ-HOURS-END": _written(0),
        }
    )
    assert await repository.upsert_service(SOURCE, service, grant=GRANT, projected_at=AT)
    hours = len(service.opening_hours)
    assert _ids(tx) == [
        "Q-PROJ-SERVICE-UPSERT",
        "Q-PROJ-LOCATION-UPSERT",
        *["Q-PROJ-HOUR-UPSERT"] * hours,
        "Q-PROJ-HOURS-END",
    ]
    first = tx.calls[0][1]
    assert first["tenant"] == "net-pilot"
    assert first["sourceTenant"] == SOURCE
    assert first["grantId"] == "grant-x-1"
    assert first["grantVersion"] == 3
    assert first["projectedAt"] == AT
    assert first["serviceName"] == service.service_name
    assert first["sourceVersion"] == service.source_version
    # The hours end from the first position this version no longer has.
    assert tx.calls[-1][1]["fromPosition"] == hours
    assert tx.calls[-1][1]["sourceVersion"] == service.source_version


async def test_a_service_row_that_is_not_written_stops_the_children() -> None:
    repository, tx = _repository({"Q-PROJ-SERVICE-UPSERT": _written(0)})
    assert not await repository.upsert_service(
        SOURCE, sample_service_projection(), grant=GRANT, projected_at=AT
    )
    assert _ids(tx) == ["Q-PROJ-SERVICE-UPSERT"]


async def test_a_service_with_no_location_ends_the_old_one_and_writes_no_new_one() -> None:
    one_hour = sample_service_projection().opening_hours[:1]
    service = replace(sample_service_projection(), location=None, opening_hours=one_hour)
    repository, tx = _repository(
        {
            "Q-PROJ-SERVICE-UPSERT": _written(),
            "Q-PROJ-LOCATION-END": _written(0),
            "Q-PROJ-HOUR-UPSERT": _written(),
            "Q-PROJ-HOURS-END": _written(0),
        }
    )
    assert await repository.upsert_service(SOURCE, service, grant=GRANT, projected_at=AT)
    assert _ids(tx) == [
        "Q-PROJ-SERVICE-UPSERT",
        "Q-PROJ-LOCATION-END",
        "Q-PROJ-HOUR-UPSERT",
        "Q-PROJ-HOURS-END",
    ]
    assert tx.calls[1][1]["endReason"] == "replaced"
    assert tx.calls[3][1]["fromPosition"] == 1


async def test_every_parameter_sent_is_an_allowlisted_property_or_a_stamp() -> None:
    service = sample_service_projection()
    repository, tx = _repository(
        {
            "Q-PROJ-SERVICE-UPSERT": _written(),
            "Q-PROJ-LOCATION-UPSERT": _written(),
            "Q-PROJ-HOUR-UPSERT": _written(),
        }
    )
    await repository.upsert_service(SOURCE, service, grant=GRANT, projected_at=AT)
    for row in to_rows(service):
        assert row.params  # the allowlist's own rows are what is sent
    stored = {key for row in to_rows(service) for key in row.params}
    sent = {key for _, params in tx.calls for key in params}
    stamps = {
        "tenant",
        "sourceTenant",
        "projectedAt",
        "grantId",
        "grantVersion",
        "sourceServiceId",
        "sourceVersion",
        "fromPosition",
        "endedAt",
        "endReason",
    }
    assert sent <= stored | stamps


async def test_a_capacity_row_is_exactly_the_allowlisted_row_and_the_stamps() -> None:
    capacity = sample_capacity_projection()
    repository, tx = _repository({"Q-PROJ-CAPACITY-UPSERT": _written()})
    assert await repository.upsert_capacity(SOURCE, capacity, grant=GRANT, projected_at=AT)
    [(_, params)] = tx.calls
    [row] = to_rows(capacity)
    assert params == {
        **row.params,
        "tenant": "net-pilot",
        "sourceTenant": SOURCE,
        "projectedAt": AT,
        "grantId": "grant-x-1",
        "grantVersion": 3,
    }


async def test_a_criteria_row_is_exactly_the_allowlisted_row_and_the_stamps() -> None:
    criteria = sample_criteria_projection()
    repository, tx = _repository({"Q-PROJ-CRITERIA-UPSERT": _written()})
    assert await repository.upsert_criteria(SOURCE, criteria, grant=GRANT, projected_at=AT)
    [(_, params)] = tx.calls
    [row] = to_rows(criteria)
    assert params == {
        **row.params,
        "tenant": "net-pilot",
        "sourceTenant": SOURCE,
        "projectedAt": AT,
        "grantId": "grant-x-1",
        "grantVersion": 3,
    }
    assert not await _repository({"Q-PROJ-CRITERIA-UPSERT": _written(0)})[0].upsert_criteria(
        SOURCE, criteria, grant=GRANT, projected_at=AT
    )


async def test_a_naive_time_is_refused_and_nothing_is_sent() -> None:
    repository, tx = _repository()
    with pytest.raises(ValidationFailed):
        await repository.upsert_capacity(
            SOURCE, sample_capacity_projection(), grant=GRANT, projected_at=datetime(2026, 1, 1)
        )
    assert tx.calls == []


async def test_a_write_is_refused_in_a_tenant_scope_and_on_a_read_only_unit() -> None:
    tenant_repository, tenant_tx = _repository(scope=ScopeId.tenant("a1"))
    with pytest.raises(ScopeKindMismatch):
        await tenant_repository.upsert_capacity(
            SOURCE, sample_capacity_projection(), grant=GRANT, projected_at=AT
        )
    read_only, read_tx = _repository(read_only=True)
    with pytest.raises(ReadOnlyUnitWrite):
        await read_only.upsert_capacity(
            SOURCE, sample_capacity_projection(), grant=GRANT, projected_at=AT
        )
    with pytest.raises(ReadOnlyUnitWrite):
        await read_only.mark_ended(
            SOURCE, GrantScope.CAPACITY, at=LEFT, reason=ProjectionEndReason.LEFT
        )
    assert tenant_tx.calls == [] and read_tx.calls == []


# History


@pytest.mark.parametrize(
    ("kind", "ids"),
    [
        (
            GrantScope.DIRECTORY,
            ["Q-PROJ-MARK-SERVICE", "Q-PROJ-MARK-LOCATION", "Q-PROJ-MARK-HOUR"],
        ),
        (GrantScope.CAPACITY, ["Q-PROJ-MARK-CAPACITY"]),
        (GrantScope.CRITERIA, ["Q-PROJ-MARK-CRITERIA"]),
    ],
)
async def test_marking_a_kind_as_ended_runs_the_statements_of_that_kind_and_sums_them(
    kind: GrantScope, ids: list[str]
) -> None:
    repository, tx = _repository({i: [{"marked": 2}] for i in ids})
    assert await repository.mark_ended(
        SOURCE, kind, at=LEFT, reason=ProjectionEndReason.LEFT
    ) == 2 * len(ids)
    assert _ids(tx) == ids
    for _, params in tx.calls:
        assert params == {
            "tenant": "net-pilot",
            "sourceTenant": SOURCE,
            "endedAt": LEFT,
            "endReason": "left",
        }


# The reads


def _stamped(row_params: dict[str, Any], **extra: Any) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for key, value in row_params.items():
        if value is None:
            continue
        if isinstance(value, datetime):
            value = DateTime.from_native(value)
        elif isinstance(value, time):
            value = Neo4jTime.from_native(value)
        elif isinstance(value, date):
            value = Date.from_native(value)
        props[key] = value
    props.update(
        {
            "tenantId": "net-pilot",
            "sourceTenantId": SOURCE,
            "projectedAt": DateTime.from_native(AT),
            "grantId": "grant-x-1",
            "grantVersion": 3,
        }
    )
    props.update(extra)
    return props


async def test_a_service_comes_back_from_its_nodes_equal_with_its_marks() -> None:
    service = sample_service_projection()
    rows = to_rows(service)
    service_row = rows[0].params
    location = next(r.params for r in rows if r.label == "ProjectedLocation")
    hours = [r.params for r in rows if r.label == "ProjectedOpeningHour"]
    repository, tx = _repository(
        {
            "Q-NETVIEW-SERVICES": [
                {
                    "service": _stamped(service_row),
                    "location": _stamped(location),
                    "hours": [_stamped(h) for h in hours],
                }
            ]
        }
    )
    [stored] = await repository.services()
    assert stored.projection == service
    assert (stored.source_tenant_id, stored.grant_id, stored.projected_at) == (
        SOURCE,
        "grant-x-1",
        AT,
    )
    assert stored.ended_at is None and stored.end_reason is None
    assert tx.calls[0][1] == {"tenant": "net-pilot", "liveOnly": True}
    await repository.services(live_only=False)
    assert tx.calls[1][1]["liveOnly"] is False


async def test_a_service_with_no_location_comes_back_without_one_and_with_its_end_marks() -> None:
    service = replace(
        sample_service_projection(),
        location=None,
        opening_hours=sample_service_projection().opening_hours[:1],
    )
    hour = to_rows(service)[-1]
    repository, _ = _repository(
        {
            "Q-NETVIEW-SERVICES": [
                {
                    "service": _stamped(
                        to_rows(service)[0].params,
                        endedAt=DateTime.from_native(LEFT),
                        endReason="left",
                    ),
                    "location": None,
                    "hours": [_stamped(hour.params)],
                }
            ]
        }
    )
    [stored] = await repository.services(live_only=False)
    assert stored.projection == service
    assert (stored.ended_at, stored.end_reason) == (LEFT, ProjectionEndReason.LEFT)


async def test_capacity_and_criteria_come_back_equal() -> None:
    capacity, criteria = sample_capacity_projection(), sample_criteria_projection()
    repository, _ = _repository(
        {
            "Q-NETVIEW-CAPACITIES": [{"capacity": _stamped(to_rows(capacity)[0].params)}],
            "Q-NETVIEW-CRITERIA": [{"criteria": _stamped(to_rows(criteria)[0].params)}],
        }
    )
    assert [r.projection for r in await repository.capacities()] == [capacity]
    assert [r.projection for r in await repository.criteria()] == [criteria]


@pytest.mark.parametrize(
    "damage",
    [
        {"serviceName": None},
        {"serviceName": 7},
        {"categoryCode": "no-such-category"},
        {"sourceVersion": "2"},
        {"projectedAt": "2026-10-29T09:30:00Z"},
        {"serviceName": "Ms Jane Smith"},
        {"endReason": "no-such-reason", "endedAt": DateTime.from_native(LEFT)},
    ],
)
async def test_a_node_the_dto_refuses_is_a_fixed_message_error(damage: dict[str, Any]) -> None:
    props = _stamped(to_rows(sample_service_projection())[0].params)
    props.update(damage)
    props = {k: v for k, v in props.items() if v is not None}
    repository, _ = _repository(
        {"Q-NETVIEW-SERVICES": [{"service": props, "location": None, "hours": []}]}
    )
    with pytest.raises(ProjectionRecordInvalid) as error:
        await repository.services()
    assert "Ms Jane" not in str(error.value)
    assert "Sample" not in str(error.value)


async def test_hours_come_back_in_position_order_whatever_order_the_server_gave() -> None:
    service = sample_service_projection()
    rows = to_rows(service)
    hours = [r.params for r in rows if r.label == "ProjectedOpeningHour"]
    assert len(hours) >= 2
    repository, _ = _repository(
        {
            "Q-NETVIEW-SERVICES": [
                {
                    "service": _stamped(rows[0].params),
                    "location": None,
                    "hours": [_stamped(h) for h in reversed(hours)],
                }
            ]
        }
    )
    [stored] = await repository.services()
    assert [h.position for h in stored.projection.opening_hours] == sorted(
        h["position"] for h in hours
    )
    assert isinstance(stored.projection.opening_hours[0], OpeningHourProjection)
