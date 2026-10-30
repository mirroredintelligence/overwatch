"""Integration tests for OpenCase and UpdateCase (U11), against the real Neo4j the harness starts.

Every assertion reads back through a fresh unit of work or a harness helper, so it checks what was
really stored (DEC-004). Values are the sample values of the prompt. The only full postcode in this
module is the sample DT4 8XX, and it must never reach storage, the audit log or any other node.

The module runs on a private contracted container (DEC-159): the two tenants share need-category
Concepts, which the shared schema's single-property key refuses until TEN-032.
"""

import dataclasses
import random
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditRecord
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, TenantNotBound, bind_scope
from diucs.application.use_cases.open_case import (
    OpenCase,
    OpenCaseCommand,
    OpenCaseResult,
    UpdateCase,
    UpdateCaseCommand,
    UpdateCaseResult,
)
from diucs.domain.codes import AgeBand, NeedCategory, Outcome, ReferrerType, Role, Urgency
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.scores import ClinicalFrailty, News2
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, node_props, read_tx
from tests.support.tenancy import as_tenant
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(minutes=40)
CLOSED_AT = NOW + timedelta(hours=1)
REFERENCE = re.compile(r"[1-9][0-9]{3}")

ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
CLINICAL = dataclasses.replace(ADVISOR, role=Role.CLINICAL, practitioner_id="prac-clinical-1")
REFUSED_ROLES = (
    Role.REPORTER,
    Role.LEAD,
    Role.OWNER,
    Role.EXEC,
    Role.WALL,
    Role.ANONYMOUS_LINK,
    Role.SUPPORT,
    Role.AUDIT,
)


class ScriptedRng(random.Random):
    """Serves the numbers given to feed() from randint, then a seeded random source. It stands in
    for the reference's random source (production passes secrets.SystemRandom())."""

    def __init__(self) -> None:
        super().__init__(0)
        self._queue: list[int] = []
        self._fallback = random.Random(7)

    def feed(self, *values: int) -> None:
        self._queue.extend(values)

    def randint(self, low: int, high: int) -> int:
        if self._queue:
            return self._queue.pop(0)
        return self._fallback.randint(low, high)


_DRIVER: AsyncDriver | None = None
"""The driver of this module's private container, set by fresh_graph, for the constructor helpers
below (the replay store is the process's driver store, DEC-012)."""


def _idempotency() -> DriverIdempotencyStore:
    assert _DRIVER is not None, "fresh_graph has not run"
    return DriverIdempotencyStore(_DRIVER)


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def fresh_graph(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str, clean_graph: None
) -> AsyncIterator[None]:
    """An empty graph with the audit chain head of each tenant, before and after every test. The
    heads are made per tenant, bound in turn, so a test with no tenant bound still has them."""
    global _DRIVER
    _DRIVER = neo4j_driver
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    yield


def _clock(at: datetime = NOW) -> FixedClock:
    return FixedClock(at)


def _opener(factory: UnitOfWorkFactory, tenant: str, rng: ScriptedRng) -> OpenCase:
    return OpenCase(factory, _clock(), SequentialIds.scoped(tenant), _idempotency(), rng)


async def _read(factory: UnitOfWorkFactory, case_id: str) -> Case | None:
    async with factory() as uow:
        return await uow.cases.get(case_id)


async def _audit(factory: UnitOfWorkFactory) -> list[AuditRecord]:
    async with factory() as uow:
        return await uow.audit.records()


async def _every_property_text(driver: AsyncDriver) -> list[str]:
    """The text of every property of every node in the graph."""

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run("MATCH (n) RETURN properties(n) AS props")).data()

    rows = await read_tx(driver, work)
    return [str(value) for row in rows for value in row["props"].values()]


async def _open(
    factory: UnitOfWorkFactory,
    tenant: str,
    *,
    key: str = "open-1",
    actor: Actor = ADVISOR,
    referrer: ReferrerType = ReferrerType.AMBULANCE_CREW,
    rng: ScriptedRng | None = None,
) -> OpenCaseResult:
    return await _opener(factory, tenant, rng or ScriptedRng()).execute(
        OpenCaseCommand(key, actor, referrer)
    )


async def _update(
    factory: UnitOfWorkFactory, case_id: str, *, key: str = "update-1", **changes: Any
) -> UpdateCaseResult:
    return await UpdateCase(factory, _clock(LATER), _idempotency()).execute(
        UpdateCaseCommand(key, ADVISOR, case_id, **changes)
    )


FILL: dict[str, Any] = {
    "age_band": AgeBand.A80_PLUS,
    "postcode": " dt4 8xx ",
    "needs": (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
    "urgency": Urgency.WITHIN_2_HRS,
    "scores": (News2(2), ClinicalFrailty(6)),
}


async def test_an_advisor_opens_an_empty_case_with_a_four_digit_reference(
    uow_factory: UnitOfWorkFactory, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    result = await _open(uow_factory, tenant_id)

    assert REFERENCE.fullmatch(result.reference)
    assert await _read(uow_factory, result.case_id) == Case(
        id=result.case_id,
        reference=result.reference,
        referrer_type=ReferrerType.AMBULANCE_CREW,
        age_band=None,
        postcode=None,
        needs=(),
        urgency=None,
        scores=(),
        opened_at=NOW,
    )
    stub = await node_props(neo4j_driver, "Patient", id=f"pt-{result.case_id}")
    assert "name" not in stub
    assert "birthDate" not in stub
    assert "identifier" not in stub


async def test_the_update_stores_the_district_and_the_fields_and_completes_the_case(
    uow_factory: UnitOfWorkFactory, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    opened = await _open(uow_factory, tenant_id)

    result = await _update(uow_factory, opened.case_id, **FILL)

    assert result == UpdateCaseResult(opened.case_id, complete=True, missing=())
    case = await _read(uow_factory, opened.case_id)
    assert case is not None
    # Only the district is stored (DEC-067 item 1; it overrides the prompt's DT4 8XX read-back).
    assert case.postcode == "DT4"
    assert case.age_band is AgeBand.A80_PLUS
    assert case.needs == (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY)
    assert case.urgency is Urgency.WITHIN_2_HRS
    assert case.scores == (News2(2), ClinicalFrailty(6))
    stub = await node_props(neo4j_driver, "Patient", id=f"pt-{opened.case_id}")
    assert stub["postalCode"] == "DT4"
    assert "name" not in stub
    assert "birthDate" not in stub
    assert "identifier" not in stub


async def test_only_the_age_band_leaves_three_things_missing(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _open(uow_factory, tenant_id)

    result = await _update(uow_factory, opened.case_id, age_band=AgeBand.A80_PLUS)

    assert result == UpdateCaseResult(
        opened.case_id, complete=False, missing=("postcode", "needs", "urgency")
    )


async def test_the_missing_names_follow_the_order_age_band_postcode_needs_urgency(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _open(uow_factory, tenant_id)

    result = await _update(uow_factory, opened.case_id)

    assert result.missing == ("age_band", "postcode", "needs", "urgency")
    assert result.complete is False


@pytest.mark.parametrize("postcode", ["DT4 8X", "DT48", "ＤＴ４ ８ＸＸ"])
async def test_a_postcode_that_is_not_a_full_postcode_is_refused_and_nothing_changes(
    uow_factory: UnitOfWorkFactory, tenant_id: str, postcode: str
) -> None:
    opened = await _open(uow_factory, tenant_id)
    before = await _read(uow_factory, opened.case_id)

    with pytest.raises(ValidationFailed) as refused:
        await _update(uow_factory, opened.case_id, age_band=AgeBand.A80_PLUS, postcode=postcode)

    assert refused.value.field == "postcode"
    assert await _read(uow_factory, opened.case_id) == before
    assert [r.entry.use_case for r in await _audit(uow_factory)] == ["OpenCase"]


async def test_a_score_out_of_range_and_a_frailty_of_zero_are_refused_before_any_write(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _open(uow_factory, tenant_id)
    before = await _read(uow_factory, opened.case_id)

    with pytest.raises(ValidationFailed) as news2:
        News2(21)
    with pytest.raises(ValidationFailed) as frailty:
        ClinicalFrailty(0)

    assert news2.value.field == "news2"
    assert frailty.value.field == "clinical_frailty"
    assert await _read(uow_factory, opened.case_id) == before


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"age_band": "80+"}, "age_band"),
        ({"urgency": "today"}, "urgency"),
        ({"needs": ("frailty",)}, "needs"),
        ({"needs": (NeedCategory.FRAILTY, NeedCategory.FRAILTY)}, "needs"),
        ({"scores": (2,)}, "scores"),
        ({"scores": (News2(2), News2(3))}, "scores"),
    ],
)
async def test_a_value_of_the_wrong_kind_or_a_repeated_score_is_refused_and_nothing_changes(
    uow_factory: UnitOfWorkFactory, tenant_id: str, changes: dict[str, Any], field: str
) -> None:
    opened = await _open(uow_factory, tenant_id)
    before = await _read(uow_factory, opened.case_id)

    with pytest.raises(ValidationFailed) as refused:
        await _update(uow_factory, opened.case_id, **changes)

    assert refused.value.field == field
    assert await _read(uow_factory, opened.case_id) == before


async def test_recorded_scores_can_be_recorded_once_and_cannot_change(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _open(uow_factory, tenant_id)
    await _update(uow_factory, opened.case_id, scores=(News2(2),))
    before = await _read(uow_factory, opened.case_id)

    with pytest.raises(ValidationFailed) as refused:
        await _update(uow_factory, opened.case_id, key="update-2", scores=(News2(3),))

    assert refused.value.field == "scores"
    assert await _read(uow_factory, opened.case_id) == before


@pytest.mark.parametrize("role", REFUSED_ROLES)
async def test_a_role_other_than_advisor_or_clinical_may_not_open_or_update_a_case(
    uow_factory: UnitOfWorkFactory, tenant_id: str, role: Role, neo4j_driver: AsyncDriver
) -> None:
    other = dataclasses.replace(ADVISOR, role=role)
    with pytest.raises(NotAllowed):
        await _opener(uow_factory, tenant_id, ScriptedRng()).execute(
            OpenCaseCommand("open-x", other, ReferrerType.GP)
        )
    opened = await _open(uow_factory, tenant_id)

    with pytest.raises(NotAllowed):
        await UpdateCase(uow_factory, _clock(LATER), _idempotency()).execute(
            UpdateCaseCommand("update-x", other, opened.case_id, **FILL)
        )
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 1


async def test_a_clinical_advisor_may_open_and_update_a_case(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _opener(uow_factory, tenant_id, ScriptedRng()).execute(
        OpenCaseCommand("open-c", CLINICAL, ReferrerType.GP)
    )

    result = await UpdateCase(uow_factory, _clock(LATER), _idempotency()).execute(
        UpdateCaseCommand("update-c", CLINICAL, opened.case_id, **FILL)
    )

    assert result.complete is True


async def test_a_reference_already_held_is_retried_and_the_two_references_differ(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    rng = ScriptedRng()
    opener = _opener(uow_factory, tenant_id, rng)
    rng.feed(4821)
    first = await opener.execute(OpenCaseCommand("open-1", ADVISOR, ReferrerType.GP))
    rng.feed(4821, 4822)

    second = await opener.execute(OpenCaseCommand("open-2", ADVISOR, ReferrerType.GP))

    assert first.reference == "4821"
    assert second.reference == "4822"
    assert (await _read(uow_factory, second.case_id)).reference == "4822"  # type: ignore[union-attr]


async def test_updating_a_closed_case_is_a_conflict_and_the_closed_case_is_unchanged(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _open(uow_factory, tenant_id)
    async with uow_factory() as uow:
        case = await uow.cases.get(opened.case_id)
        assert case is not None
        await uow.cases.save(case.close(Outcome.DECLINED, CLOSED_AT))
        await uow.commit()
    closed = await _read(uow_factory, opened.case_id)

    with pytest.raises(Conflict):
        await _update(uow_factory, opened.case_id, **FILL)

    assert await _read(uow_factory, opened.case_id) == closed
    assert closed is not None
    assert closed.closed_at == CLOSED_AT


async def test_an_update_of_a_case_that_does_not_exist_is_not_found(
    uow_factory: UnitOfWorkFactory,
) -> None:
    with pytest.raises(NotFound):
        await _update(uow_factory, "no-such-case", age_band=AgeBand.A80_PLUS)


async def test_a_repeat_open_with_the_same_key_returns_the_first_case(
    uow_factory: UnitOfWorkFactory, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    opener = _opener(uow_factory, tenant_id, ScriptedRng())
    first = await opener.execute(OpenCaseCommand("open-1", ADVISOR, ReferrerType.GP))

    second = await opener.execute(OpenCaseCommand("open-1", ADVISOR, ReferrerType.GP))

    assert second == first
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 1
    assert [r.entry.use_case for r in await _audit(uow_factory)] == ["OpenCase"]


async def test_a_repeat_open_with_the_same_key_and_another_referrer_is_a_conflict(
    uow_factory: UnitOfWorkFactory, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    opener = _opener(uow_factory, tenant_id, ScriptedRng())
    await opener.execute(OpenCaseCommand("open-1", ADVISOR, ReferrerType.GP))

    with pytest.raises(Conflict):
        await opener.execute(OpenCaseCommand("open-1", ADVISOR, ReferrerType.NHS_111))
    with pytest.raises(Conflict):
        await opener.execute(OpenCaseCommand("open-1", CLINICAL, ReferrerType.GP))

    assert await count_nodes(neo4j_driver, "ServiceRequest") == 1


async def test_a_repeat_update_with_the_same_key_replays_and_another_body_is_a_conflict(
    uow_factory: UnitOfWorkFactory, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    opened = await _open(uow_factory, tenant_id)
    first = await _update(uow_factory, opened.case_id, key="u-1", age_band=AgeBand.A80_PLUS)
    stored = await _read(uow_factory, opened.case_id)

    again = await _update(uow_factory, opened.case_id, key="u-1", age_band=AgeBand.A80_PLUS)

    assert again == first
    assert await _read(uow_factory, opened.case_id) == stored
    with pytest.raises(Conflict):
        await _update(uow_factory, opened.case_id, key="u-1", age_band=AgeBand.A16_64)
    assert await _read(uow_factory, opened.case_id) == stored


async def test_the_audit_holds_the_snapshots_and_no_postcode_anywhere(
    uow_factory: UnitOfWorkFactory, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    opened = await _open(uow_factory, tenant_id)
    await _update(uow_factory, opened.case_id, **FILL)

    records = await _audit(uow_factory)
    assert [r.entry.action for r in records] == ["C", "U"]
    assert [r.entry.use_case for r in records] == ["OpenCase", "UpdateCase"]
    assert all(r.entry.entity_ids == (opened.case_id,) for r in records)
    assert set(records[1].entry.snapshot or {}) == {
        "reference",
        "referrer_type",
        "age_band",
        "needs",
        "urgency",
    }
    assert (records[1].entry.snapshot or {})["reference"] == opened.reference
    texts = await _every_property_text(neo4j_driver)
    assert not [text for text in texts if "8XX" in text or "DT4 8" in text]


async def test_the_same_key_in_two_tenants_is_two_commands(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    # Each call runs with its own tenant bound, as the edge binds it: the use case reads the
    # replay record under the bound tenant before it opens a unit of work, and a unit of work
    # from `uow_factory_b` binds B only while it is entered.
    with as_tenant(tenant_id):
        a = await _open(uow_factory_a, tenant_id, key="shared")
    with as_tenant(other_tenant_id):
        b = await _open(uow_factory_b, other_tenant_id, key="shared")

    assert a.case_id != b.case_id
    assert await _read(uow_factory_a, b.case_id) is None
    assert await _read(uow_factory_b, a.case_id) is None


async def test_tenant_b_cannot_read_or_change_a_case_it_names_by_id(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
) -> None:
    a = await _open(uow_factory_a, tenant_id)
    before = await _read(uow_factory_a, a.case_id)

    with pytest.raises(NotFound):
        await _update(uow_factory_b, a.case_id, **FILL)

    assert await _read(uow_factory_b, a.case_id) is None
    assert await _read(uow_factory_a, a.case_id) == before


async def test_the_same_reference_in_two_tenants_does_not_collide(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    rng_a = ScriptedRng()
    rng_a.feed(4821)
    rng_b = ScriptedRng()
    rng_b.feed(4821, 4822)
    with as_tenant(tenant_id):
        a = await _opener(uow_factory_a, tenant_id, rng_a).execute(
            OpenCaseCommand("open-a", ADVISOR, ReferrerType.GP)
        )
    with as_tenant(other_tenant_id):
        b = await _opener(uow_factory_b, other_tenant_id, rng_b).execute(
            OpenCaseCommand("open-b", ADVISOR, ReferrerType.GP)
        )

    assert a.reference == "4821"
    assert b.reference == "4821"


@pytest.mark.no_tenant
async def test_with_no_tenant_bound_nothing_is_opened_or_updated(
    uow_factory: UnitOfWorkFactory, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    with pytest.raises(TenantNotBound):
        await _open(uow_factory, tenant_id)
    with pytest.raises(TenantNotBound):
        await _update(uow_factory, "case-1", **FILL)
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 0


async def test_a_unit_of_work_bound_to_a_network_scope_opens_nothing(
    uow_factory: UnitOfWorkFactory, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    with bind_scope(ScopeId.network("net-test-1")), pytest.raises(TenantNotBound):
        await _open(uow_factory, tenant_id)
    assert await count_nodes(neo4j_driver, "ServiceRequest") == 0
