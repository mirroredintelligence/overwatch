"""Integration tests for clinical advice requests (U40), against the real Neo4j the harness starts.

Each test seeds committed units of work and reads back through a fresh one (DEC-004). Clock:
Friday 23 October 2026 (BST is UTC+1): 14:12 London is 13:12 UTC. Synthetic values only; the
postcode DT4 8XX never reaches storage, and the advice note is text the protected store holds.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.clinical_advice import (
    AvailableClinicians,
    GiveClinicalAdvice,
    GiveClinicalAdviceCommand,
    ListClinicalQueue,
    RequestClinicalAdvice,
    RequestClinicalAdviceCommand,
    ReturnIdleRequest,
    SetPresence,
    SetPresenceCommand,
    TakeClinicalRequest,
    TakeClinicalRequestCommand,
    presence_key,
)
from diucs.application.work import WorkKind
from diucs.domain.codes import (
    AgeBand,
    NeedCategory,
    PractitionerRoleCode,
    ReferrerType,
    Role,
    Urgency,
)
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.rules.clinical_queue import Presence
from tests.support.actors import ACTOR_TENANT
from tests.support.booking_rig import SECRETS
from tests.support.neo4j import count_nodes, read_tx, wipe
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

REQUESTED_AT = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)  # 14:12 BST
TAKEN_AT = datetime(2026, 10, 23, 13, 14, tzinfo=UTC)  # 14:14 BST
ADVISED_AT = datetime(2026, 10, 23, 13, 20, tzinfo=UTC)  # 14:20 BST
RETURN_DUE = datetime(2026, 10, 23, 13, 24, tzinfo=UTC)  # 14:24 BST
CASE_ID = "case-4821"
CLIN_1 = "prac-clin-1"
CLIN_2 = "prac-clin-2"
ROLE_1 = "role-clin-1"
ROLE_2 = "role-clin-2"
NOTE_120 = "x" * 120
NOTE_300 = "y" * 300
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
CLINICIAN_1 = Actor(
    role=Role.CLINICAL,
    practitioner_id=CLIN_1,
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
CLINICIAN_2 = Actor(
    role=Role.CLINICAL,
    practitioner_id=CLIN_2,
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
SEALER = AesGcmContentSealer(SECRETS)


def _case() -> Case:
    return Case(
        id=CASE_ID,
        reference="4821",
        referrer_type=ReferrerType.AMBULANCE_CREW,
        age_band=AgeBand.A80_PLUS,
        postcode="DT4",
        needs=(NeedCategory.FRAILTY,),
        urgency=Urgency.WITHIN_2_HRS,
        scores=(),
        opened_at=datetime(2026, 10, 23, 13, 10, tzinfo=UTC),
    )


async def _seed(factory: UnitOfWorkFactory, driver: AsyncDriver, tenant: str) -> None:
    """Two clinical leads with active roles, and a case."""
    await ensure_audit_heads(driver, tenant)
    async with factory() as uow:
        for practitioner_id, role_id in ((CLIN_1, ROLE_1), (CLIN_2, ROLE_2)):
            await uow.people.save_practitioner(
                Practitioner(
                    id=practitioner_id,
                    active=True,
                    display_name="Sample Clinician",
                    phone_hash=None,
                )
            )
            await uow.people.save_role(
                PractitionerRole(
                    id=role_id,
                    practitioner_id=practitioner_id,
                    service_id=None,
                    code=PractitionerRoleCode.CLINICAL_LEAD,
                    active=True,
                    channel=None,
                    period_start=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
        await uow.cases.add(_case())
        await uow.commit()


def _request(
    factory: UnitOfWorkFactory, cache: InMemoryCache, at: datetime
) -> RequestClinicalAdvice:
    return RequestClinicalAdvice(factory, SequentialIds(), FixedClock(at), cache, SEALER)


async def _queue(factory: UnitOfWorkFactory, at: datetime) -> list[Any]:
    return await ListClinicalQueue(factory, FixedClock(at)).execute(CLINICIAN_1)


async def _open_request_id(factory: UnitOfWorkFactory) -> str:
    async with factory() as uow:
        records = await uow.clinical_requests.open_requests()
    assert len(records) == 1
    return records[0].request.id


async def _take(
    factory: UnitOfWorkFactory, request_id: str, at: datetime, who: Actor = CLINICIAN_1
) -> None:
    await TakeClinicalRequest(factory, SequentialIds(), FixedClock(at)).execute(
        TakeClinicalRequestCommand(who, request_id)
    )


async def _set_available(cache: InMemoryCache, *practitioners: str) -> None:
    for practitioner_id in practitioners:
        await cache.set(presence_key(practitioner_id), Presence.AVAILABLE.value)


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)


async def test_a_request_is_stored_waiting_and_two_available_clinicians_are_notified(
    seeded: None, uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    cache = InMemoryCache(FixedClock(REQUESTED_AT))
    await _set_available(cache, CLIN_1, CLIN_2)
    before = await count_nodes(neo4j_driver, "OutboxMessage")
    result = await _request(uow_factory, cache, REQUESTED_AT).execute(
        RequestClinicalAdviceCommand(ADVISOR, CASE_ID, "now", "borderline-criteria")
    )
    assert result.notified == 2
    assert await count_nodes(neo4j_driver, "OutboxMessage") == before + 2
    queue = await _queue(uow_factory, REQUESTED_AT)
    assert [r.request.id for r in queue] == [result.request_id]
    assert queue[0].request.taken_by is None


async def test_a_take_locks_the_request_and_a_second_take_conflicts(
    seeded: None, uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    cache = InMemoryCache(FixedClock(REQUESTED_AT))
    await _set_available(cache, CLIN_1, CLIN_2)
    await _request(uow_factory, cache, REQUESTED_AT).execute(
        RequestClinicalAdviceCommand(ADVISOR, CASE_ID, "now", "other")
    )
    request_id = await _open_request_id(uow_factory)
    await _take(uow_factory, request_id, TAKEN_AT)
    async with uow_factory() as uow:
        record = await uow.clinical_requests.get(request_id)
        works = await uow.scheduled_work.for_about(request_id, WorkKind.CLINICAL_RETURN)
    assert record is not None
    assert record.request.taken_by == CLIN_1
    assert record.request.taken_at == TAKEN_AT
    assert [w.due_at for w in works] == [RETURN_DUE]
    with pytest.raises(Conflict):
        await _take(uow_factory, request_id, TAKEN_AT, CLINICIAN_2)


async def test_an_unadvised_lock_returns_to_the_queue_at_ten_minutes(
    seeded: None, uow_factory: UnitOfWorkFactory
) -> None:
    cache = InMemoryCache(FixedClock(REQUESTED_AT))
    await _set_available(cache, CLIN_1)
    await _request(uow_factory, cache, REQUESTED_AT).execute(
        RequestClinicalAdviceCommand(ADVISOR, CASE_ID, "now", "other")
    )
    request_id = await _open_request_id(uow_factory)
    await _take(uow_factory, request_id, TAKEN_AT)
    await ReturnIdleRequest(uow_factory, FixedClock(RETURN_DUE)).execute(request_id)
    queue = await _queue(uow_factory, RETURN_DUE)
    assert [r.request.id for r in queue] == [request_id]
    assert queue[0].request.taken_by is None


async def test_advice_before_the_return_cancels_the_return_work(
    seeded: None, uow_factory: UnitOfWorkFactory
) -> None:
    cache = InMemoryCache(FixedClock(REQUESTED_AT))
    await _set_available(cache, CLIN_1)
    await _request(uow_factory, cache, REQUESTED_AT).execute(
        RequestClinicalAdviceCommand(ADVISOR, CASE_ID, "now", "other")
    )
    request_id = await _open_request_id(uow_factory)
    await _take(uow_factory, request_id, TAKEN_AT)
    await GiveClinicalAdvice(uow_factory, SequentialIds(), FixedClock(ADVISED_AT)).execute(
        GiveClinicalAdviceCommand(CLINICIAN_1, request_id, "go-ahead")
    )
    async with uow_factory() as uow:
        works = await uow.scheduled_work.for_about(request_id, WorkKind.CLINICAL_RETURN)
    assert works and all(w.status != "scheduled" for w in works)


async def test_a_note_of_300_characters_is_refused_and_one_of_120_is_held_by_handle(
    seeded: None, uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    cache = InMemoryCache(FixedClock(REQUESTED_AT))
    await _set_available(cache, CLIN_1)
    await _request(uow_factory, cache, REQUESTED_AT).execute(
        RequestClinicalAdviceCommand(ADVISOR, CASE_ID, "now", "other")
    )
    request_id = await _open_request_id(uow_factory)
    await _take(uow_factory, request_id, TAKEN_AT)
    give = GiveClinicalAdvice(uow_factory, SequentialIds(), FixedClock(ADVISED_AT))
    with pytest.raises(ValidationFailed):
        await give.execute(
            GiveClinicalAdviceCommand(CLINICIAN_1, request_id, "go-ahead", note=NOTE_300)
        )
    await give.execute(
        GiveClinicalAdviceCommand(
            CLINICIAN_1, request_id, "go-ahead", "within-criteria-on-judgement", NOTE_120
        )
    )
    async with uow_factory() as uow:
        record = await uow.clinical_requests.get(request_id)
        assert record is not None and record.advice is not None
        handle = record.advice.note_handle
        assert handle is not None
        assert await uow.protected_text.get(handle) == NOTE_120
    rows = await _rows(
        neo4j_driver,
        "MATCH (e:AuditEvent) WHERE e.entryJson CONTAINS $note RETURN count(e) AS n",
        note=NOTE_120,
    )
    assert rows[0]["n"] == 0


async def test_going_away_returns_the_taken_requests(
    seeded: None, uow_factory: UnitOfWorkFactory
) -> None:
    cache = InMemoryCache(FixedClock(REQUESTED_AT))
    await _set_available(cache, CLIN_1)
    await _request(uow_factory, cache, REQUESTED_AT).execute(
        RequestClinicalAdviceCommand(ADVISOR, CASE_ID, "now", "other")
    )
    request_id = await _open_request_id(uow_factory)
    await _take(uow_factory, request_id, TAKEN_AT)
    await SetPresence(uow_factory, cache, FixedClock(TAKEN_AT)).execute(
        SetPresenceCommand(CLINICIAN_1, Presence.AWAY)
    )
    queue = await _queue(uow_factory, TAKEN_AT)
    assert [r.request.id for r in queue] == [request_id]
    assert queue[0].request.taken_by is None


async def test_available_clinicians_is_a_count_never_a_name(
    seeded: None, uow_factory: UnitOfWorkFactory
) -> None:
    cache = InMemoryCache(FixedClock(REQUESTED_AT))
    await cache.set(presence_key(CLIN_1), Presence.AVAILABLE.value)
    await cache.set(presence_key(CLIN_2), Presence.BUSY.value)
    count = await AvailableClinicians(uow_factory, cache, FixedClock(REQUESTED_AT)).execute()
    assert count == 1 and isinstance(count, int)


async def test_an_advisor_cannot_give_advice_and_a_clinician_cannot_request_it(
    seeded: None, uow_factory: UnitOfWorkFactory
) -> None:
    cache = InMemoryCache(FixedClock(REQUESTED_AT))
    with pytest.raises(NotAllowed):
        await _request(uow_factory, cache, REQUESTED_AT).execute(
            RequestClinicalAdviceCommand(CLINICIAN_1, CASE_ID, "now", "other")
        )
    with pytest.raises(NotFound):
        await _take(uow_factory, "no-such-request", TAKEN_AT)


async def _rows(driver: AsyncDriver, query: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(query, **params)
        return [record.data() async for record in result]

    return await read_tx(driver, work)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    """A private Neo4j with the superseded single-property keys dropped (DEC-159)."""
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    """Overrides the session driver for this module."""
    return two_tenant_driver


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def fresh_graph(neo4j_driver: AsyncDriver) -> None:
    await wipe(neo4j_driver)


async def test_tenant_b_request_id_is_not_found_to_tenant_a(
    two_tenant_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """A request of tenant B, given to tenant A's take, answers not found (DEC-130)."""
    factory_b = tenant_uow_factory(two_tenant_driver, other_tenant_id)
    factory_a = tenant_uow_factory(two_tenant_driver, tenant_id)
    await _seed(factory_b, two_tenant_driver, other_tenant_id)
    cache = InMemoryCache(FixedClock(REQUESTED_AT))
    await cache.set(presence_key(CLIN_1), Presence.AVAILABLE.value)
    await RequestClinicalAdvice(
        factory_b, SequentialIds(), FixedClock(REQUESTED_AT), cache, SEALER
    ).execute(RequestClinicalAdviceCommand(ADVISOR, CASE_ID, "now", "other"))
    async with factory_b() as uow:
        b_records = await uow.clinical_requests.open_requests()
    b_request = b_records[0].request.id
    with pytest.raises(NotFound):
        await TakeClinicalRequest(factory_a, SequentialIds(), FixedClock(TAKEN_AT)).execute(
            TakeClinicalRequestCommand(CLINICIAN_1, b_request)
        )
    async with factory_a() as uow:
        assert await uow.clinical_requests.open_requests() == []
