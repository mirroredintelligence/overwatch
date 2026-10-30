"""Integration tests for the ScheduledWork records (P08).

They run against the throwaway Neo4j that the harness starts for the pytest session (DEC-008). Each
write is one committed transaction and each read is a new session, so the assertions are on what
was really stored. Values are synthetic.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.scheduled_work_repository import (
    Neo4jScheduledWorkRepository,
)
from diucs.application.tenancy import bind_tenant
from diucs.application.work import ScheduledWork, WorkKind
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

LONDON = ZoneInfo("Europe/London")
BOOKING = "booking-1"


def _work(
    id_: str,
    kind: WorkKind,
    *,
    due: datetime = datetime(2026, 10, 24, 14, 21, tzinfo=UTC),
    about: str = BOOKING,
    status: str = "scheduled",
    sequence: int | None = 4,
) -> ScheduledWork:
    return ScheduledWork(
        id=id_,
        kind=kind,
        due_at=due,
        about_id=about,
        sequence_number=sequence,
        status=status,
    )


async def _add(driver: AsyncDriver, *works: ScheduledWork) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = Neo4jScheduledWorkRepository(tx)
        for item in works:
            await repo.add(item)

    await write_tx(driver, work)


async def _get(driver: AsyncDriver, id_: str) -> ScheduledWork:
    async def work(tx: AsyncManagedTransaction) -> ScheduledWork:
        return await Neo4jScheduledWorkRepository(tx).get(id_)

    return await read_tx(driver, work)


async def _for_about(
    driver: AsyncDriver, about: str, kind: WorkKind | None = None
) -> list[ScheduledWork]:
    async def work(tx: AsyncManagedTransaction) -> list[ScheduledWork]:
        return await Neo4jScheduledWorkRepository(tx).for_about(about, kind)

    return await read_tx(driver, work)


async def test_for_about_returns_only_the_asked_kind_and_the_cancelled_status_persists(
    neo4j_driver: AsyncDriver,
) -> None:
    expire = _work("work-expire", WorkKind.BOOKING_EXPIRE)
    prompt = _work("work-prompt", WorkKind.BOOKING_PHONE_PROMPT, sequence=5)
    timer = _work("work-timer", WorkKind.BOOKING_EXPIRE, sequence=6)
    await _add(neo4j_driver, expire, prompt, timer)

    async def cancel(tx: AsyncManagedTransaction) -> None:
        repo = Neo4jScheduledWorkRepository(tx)
        cancelled = _work("work-timer", WorkKind.BOOKING_EXPIRE, status="cancelled", sequence=6)
        await repo.save(cancelled)

    await write_tx(neo4j_driver, cancel)

    found = await _for_about(neo4j_driver, BOOKING, WorkKind.BOOKING_EXPIRE)
    assert [w.id for w in found] == ["work-expire", "work-timer"]
    assert {w.id: w.status for w in found} == {
        "work-expire": "scheduled",
        "work-timer": "cancelled",
    }
    assert len(await _for_about(neo4j_driver, BOOKING)) == 3


async def test_a_work_record_round_trips_through_a_fresh_session(neo4j_driver: AsyncDriver) -> None:
    saved = _work("work-rt", WorkKind.NOT_UPDATED_CHECK, sequence=9)

    async def save(tx: AsyncManagedTransaction) -> None:
        await Neo4jScheduledWorkRepository(tx).add(saved)

    async def load(tx: AsyncManagedTransaction) -> ScheduledWork:
        return await Neo4jScheduledWorkRepository(tx).get("work-rt")

    await assert_round_trip(neo4j_driver, save, load, saved)


async def test_a_london_due_time_is_stored_and_read_back_as_the_same_instant(
    neo4j_driver: AsyncDriver,
) -> None:
    # 2026-10-25 01:30 GMT (fold 1) is 01:30 UTC. The record must keep the instant.
    gmt_0130 = datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=1).astimezone(UTC)
    await _add(neo4j_driver, _work("work-london", WorkKind.REVERIFY, due=gmt_0130))

    loaded = await _get(neo4j_driver, "work-london")
    assert loaded.due_at == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    assert loaded.due_at.utcoffset() == timedelta(0)


async def test_the_stored_node_has_its_labels_keys_and_a_single_about_link(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _work("work-props", WorkKind.REMINDER, sequence=12))

    props = await node_props(neo4j_driver, "ScheduledWork", id="work-props")
    assert props["kind"] == "reminder"
    assert props["status"] == "scheduled"
    assert props["sequenceNumber"] == 12


async def test_a_subject_is_created_once_when_absent_and_reused_after(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _work("work-a", WorkKind.BOOKING_EXPIRE, sequence=1))
    await _add(neo4j_driver, _work("work-b", WorkKind.BOOKING_PHONE_PROMPT, sequence=2))

    assert await count_nodes(neo4j_driver, "Resource") == 1
    props = await node_props(neo4j_driver, "Resource", key=BOOKING)
    assert props["placeholder"] is True


async def test_adding_the_same_record_twice_is_safe_to_retry(neo4j_driver: AsyncDriver) -> None:
    work = _work("work-retry", WorkKind.ESCALATE_TO_LEAD, sequence=3)
    await _add(neo4j_driver, work)
    await _add(neo4j_driver, work)

    assert await count_nodes(neo4j_driver, "ScheduledWork") == 1


async def test_adding_a_different_record_under_an_existing_id_is_a_conflict(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _work("work-clash", WorkKind.ESCALATE_TO_LEAD, sequence=3))

    with pytest.raises(Conflict):
        await _add(neo4j_driver, _work("work-clash", WorkKind.REMINDER, sequence=3))
    assert (await _get(neo4j_driver, "work-clash")).kind is WorkKind.ESCALATE_TO_LEAD


async def test_getting_an_unknown_record_is_not_found(neo4j_driver: AsyncDriver) -> None:
    with pytest.raises(NotFound):
        await _get(neo4j_driver, "work-missing")


async def test_saving_an_unknown_record_is_not_found(neo4j_driver: AsyncDriver) -> None:
    async def save(tx: AsyncManagedTransaction) -> None:
        await Neo4jScheduledWorkRepository(tx).save(_work("work-missing", WorkKind.REVERIFY))

    with pytest.raises(NotFound):
        await write_tx(neo4j_driver, save)


async def _count_subjects(driver: AsyncDriver, key: str) -> int:
    """How many subject Resource nodes carry this key (a placeholder subject is one of them)."""

    async def work(tx: AsyncManagedTransaction) -> int:
        record = await (
            await tx.run(
                "MATCH (s:Resource {key: $key, tenantId: $tenant}) RETURN count(s) AS total",
                key=key,
            )
        ).single()
        assert record is not None
        return int(record["total"])

    return await read_tx(driver, work)


async def test_a_refused_add_for_a_new_subject_leaves_no_subject_node_after_commit(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _work("work-held", WorkKind.ESCALATE_TO_LEAD, sequence=3))

    async def refused_then_commit(tx: AsyncManagedTransaction) -> None:
        # The caller swallows the refusal and the unit of work still commits (DEC-053 item 16).
        with pytest.raises(Conflict):
            await Neo4jScheduledWorkRepository(tx).add(
                _work("work-held", WorkKind.REMINDER, about="booking-2", sequence=3)
            )

    await write_tx(neo4j_driver, refused_then_commit)

    assert await count_nodes(neo4j_driver, "ScheduledWork") == 1
    assert await _count_subjects(neo4j_driver, "booking-2") == 0
    assert (await _get(neo4j_driver, "work-held")).about_id == BOOKING


async def test_a_refused_save_of_an_unknown_record_leaves_no_node_after_commit(
    neo4j_driver: AsyncDriver,
) -> None:
    async def refused_then_commit(tx: AsyncManagedTransaction) -> None:
        with pytest.raises(NotFound):
            await Neo4jScheduledWorkRepository(tx).save(
                _work("work-ghost", WorkKind.REVERIFY, about="booking-3")
            )

    await write_tx(neo4j_driver, refused_then_commit)

    assert await count_nodes(neo4j_driver, "ScheduledWork") == 0
    assert await _count_subjects(neo4j_driver, "booking-3") == 0


async def test_a_naive_due_time_is_refused_before_anything_is_written(
    neo4j_driver: AsyncDriver,
) -> None:
    # Restored from the first round, where the test built the record outside pytest.raises and was
    # then deleted. The refusal is at construction, so no node is written (DEC-053 item 16).
    with pytest.raises(ValidationFailed):
        await _add(
            neo4j_driver, _work("work-naive", WorkKind.REVERIFY, due=datetime(2026, 10, 24, 14, 21))
        )

    assert await count_nodes(neo4j_driver, "ScheduledWork") == 0


async def test_work_is_found_only_for_its_exact_subject_key(neo4j_driver: AsyncDriver) -> None:
    # A prefix match on the subject key would return the svc-10 record for svc-1 (and the reverse
    # for a longer query). Both directions are stored, so each query must return only its own.
    await _add(
        neo4j_driver,
        _work("work-svc-10", WorkKind.PROMPT_DUE, about="HealthcareService/svc-10", sequence=5),
        _work("work-svc-1", WorkKind.PROMPT_DUE, about="HealthcareService/svc-1", sequence=6),
    )

    async def find(tx: AsyncManagedTransaction, about: str) -> list[ScheduledWork]:
        return await Neo4jScheduledWorkRepository(tx).for_about(about)

    async def ids_for(about: str) -> list[str]:
        return [work.id for work in await read_tx(neo4j_driver, lambda tx: find(tx, about))]

    assert await ids_for("HealthcareService/svc-1") == ["work-svc-1"]
    assert await ids_for("HealthcareService/svc-10") == ["work-svc-10"]
    for variant in ("HealthcareService/svc", "HealthcareService/svc-1 ", "healthcareservice/svc-1"):
        assert await ids_for(variant) == [], variant


# --- two tenants (TEN-015): a scheduled work item and its subject belong to one tenant -----------
#
# Both tenants use the same work id and the same booking key. The contracted container holds the
# composite keys only (TEN-005, TEN-032), so the two tenants can share them.


@pytest_asyncio.fixture(loop_scope="session")
async def two(neo4j_driver: AsyncDriver, clean_graph: None) -> AsyncIterator[AsyncDriver]:
    yield neo4j_driver


async def test_another_tenants_work_reads_as_not_found_and_cannot_be_saved(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    with bind_tenant(other_tenant_id):
        await _add(two, _work("work-1", WorkKind.REMINDER))

    async def as_a_read(tx: AsyncManagedTransaction) -> list[ScheduledWork]:
        repo = Neo4jScheduledWorkRepository(tx)
        with pytest.raises(NotFound):
            await repo.get("work-1")
        return await repo.for_about(BOOKING)

    async def as_a_save(tx: AsyncManagedTransaction) -> None:
        with pytest.raises(NotFound):
            await Neo4jScheduledWorkRepository(tx).save(
                _work("work-1", WorkKind.REMINDER, status="cancelled")
            )

    with bind_tenant(tenant_id):
        assert await read_tx(two, as_a_read) == []
        await write_tx(two, as_a_save)

    with bind_tenant(other_tenant_id):
        assert (await _get(two, "work-1")).status == "scheduled"


async def test_the_same_work_id_in_two_tenants_is_two_records(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    with bind_tenant(tenant_id):
        await _add(two, _work("work-1", WorkKind.REMINDER, sequence=1))
    with bind_tenant(other_tenant_id):
        await _add(two, _work("work-1", WorkKind.PHONE_TASK, sequence=2))

    with bind_tenant(tenant_id):
        assert (await _get(two, "work-1")).kind is WorkKind.REMINDER
        assert [w.kind for w in await _for_about(two, BOOKING)] == [WorkKind.REMINDER]
    with bind_tenant(other_tenant_id):
        assert (await _get(two, "work-1")).kind is WorkKind.PHONE_TASK

    async def subjects(tx: AsyncManagedTransaction) -> list[tuple[str, int]]:
        result = await tx.run(
            "MATCH (s:Resource {key: $key}) RETURN s.tenantId AS tenant, count(s) AS n "
            "ORDER BY tenant",
            key=BOOKING,
        )
        return [(record["tenant"], int(record["n"])) async for record in result]

    assert sorted(await read_tx(two, subjects)) == sorted([(tenant_id, 1), (other_tenant_id, 1)])
