"""Scores and the case version (H-85, KI-247, KI-815, H-192, KI-400), against the real Neo4j.

A Pathways Dx code must be on the list; a recorded score changes only as a counted correction with
a reason that the audit keeps with the original; a write over a newer version of a case is refused
and writes nothing; a case opened with details is opened and filled in one unit. Two tenants: a
correction and a version in one tenant touch nothing of the other. Sample values only.
"""

import asyncio
import dataclasses
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.open_case import (
    OpenCaseCommand,
    UpdateCase,
    UpdateCaseCommand,
)
from diucs.domain.codes import ReferrerType
from diucs.domain.errors import NotFound, StaleVersion, ValidationFailed
from diucs.domain.model.scores import (
    ClinicalFrailty,
    News2,
    PathwaysDx,
    ScoreCorrectionReason,
)
from tests.integration.application.test_open_case import (
    ADVISOR,
    FILL,
    LATER,
    LISTED_DX,
    ScriptedRng,
    _audit,
    _clock,
    _idempotency,
    _open,
    _opener,
    _read,
    _update,
    fresh_graph,
)
from tests.support.neo4j import count_nodes
from tests.support.tenancy import as_tenant

__all__ = ["fresh_graph"]

pytestmark = pytest.mark.asyncio(loop_scope="session")

TYPING_ERROR = ScoreCorrectionReason.TYPING_ERROR


async def _version(factory: UnitOfWorkFactory, case_id: str) -> int:
    async with factory() as uow:
        found = await uow.cases.get_versioned(case_id)
    assert found is not None
    return found[1]


async def _filled(factory: UnitOfWorkFactory, tenant: str, *, key: str = "open-1") -> str:
    opened = await _open(factory, tenant, key=key)
    await _update(factory, opened.case_id, key=f"fill-{key}", **FILL)
    return opened.case_id


# H-85: the Pathways Dx code must be on the list.


async def test_a_dx_code_not_on_the_list_is_refused_and_nothing_is_recorded(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _open(uow_factory, tenant_id)

    with pytest.raises(ValidationFailed) as refused:
        await _update(uow_factory, opened.case_id, scores=(PathwaysDx("DxSAMPLE99"),))

    assert refused.value.field == "scores"
    assert "DxSAMPLE99" not in str(refused.value)
    case = await _read(uow_factory, opened.case_id)
    assert case is not None and case.scores == ()


async def test_a_dx_code_on_the_list_is_recorded(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _open(uow_factory, tenant_id)

    await _update(uow_factory, opened.case_id, scores=(PathwaysDx("DxSAMPLE01"),))

    case = await _read(uow_factory, opened.case_id)
    assert case is not None and case.scores == (PathwaysDx("DxSAMPLE01"),)


async def test_a_dx_code_refused_in_one_score_leaves_the_other_scores_of_the_write_unrecorded(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _open(uow_factory, tenant_id)

    with pytest.raises(ValidationFailed):
        await _update(uow_factory, opened.case_id, scores=(News2(2), PathwaysDx("DxSAMPLE99")))

    case = await _read(uow_factory, opened.case_id)
    assert case is not None and case.scores == ()


# Q7: a correction is a new recorded score with a reason; the original stays in the audit.


async def test_a_recorded_score_is_corrected_and_the_audit_keeps_the_original_and_the_reason(
    uow_factory: UnitOfWorkFactory, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    case_id = await _filled(uow_factory, tenant_id)

    await _update(
        uow_factory,
        case_id,
        key="correct-1",
        scores=(News2(5),),
        score_correction_reason=TYPING_ERROR,
    )

    case = await _read(uow_factory, case_id)
    assert case is not None
    assert case.scores == (News2(5), ClinicalFrailty(6))
    assert case.score_corrections == 1
    entries = [record.entry for record in await _audit(uow_factory)]
    corrections = [
        e for e in entries if e.use_case == "UpdateCase" and "score_correction" in e.snapshot
    ]
    assert len(corrections) == 1
    assert corrections[0].snapshot["score_correction"] == {
        "reason": "typing-error",
        "corrected": [
            {"was": {"method": "news2", "value": 2}, "now": {"method": "news2", "value": 5}}
        ],
    }
    # The first Observations are still in the graph, no longer listed by the request.
    assert await count_nodes(neo4j_driver, "Observation") == 4


async def test_changing_a_recorded_score_without_a_reason_is_refused_and_nothing_changes(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    case_id = await _filled(uow_factory, tenant_id)
    before = await _read(uow_factory, case_id)
    version = await _version(uow_factory, case_id)

    with pytest.raises(ValidationFailed) as refused:
        await _update(uow_factory, case_id, key="no-reason", scores=(News2(5),))

    assert refused.value.field == "score_correction_reason"
    assert await _read(uow_factory, case_id) == before
    assert await _version(uow_factory, case_id) == version


async def test_a_second_correction_is_counted_and_the_case_reads_back_the_latest_scores(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    case_id = await _filled(uow_factory, tenant_id)
    await _update(
        uow_factory, case_id, key="c1", scores=(News2(5),), score_correction_reason=TYPING_ERROR
    )

    await _update(
        uow_factory,
        case_id,
        key="c2",
        scores=(News2(7),),
        score_correction_reason=ScoreCorrectionReason.RESCORED,
    )

    case = await _read(uow_factory, case_id)
    assert case is not None
    assert case.scores == (News2(7), ClinicalFrailty(6))
    assert case.score_corrections == 2


async def test_a_score_of_a_new_method_is_added_without_a_reason(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _open(uow_factory, tenant_id)
    await _update(uow_factory, opened.case_id, key="u1", scores=(News2(2),))

    await _update(uow_factory, opened.case_id, key="u2", scores=(News2(2), ClinicalFrailty(4)))

    case = await _read(uow_factory, opened.case_id)
    assert case is not None
    assert case.scores == (News2(2), ClinicalFrailty(4))
    assert case.score_corrections == 0


async def test_replaying_a_correction_with_the_same_key_does_not_correct_twice(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    case_id = await _filled(uow_factory, tenant_id)
    for _ in range(2):
        await _update(
            uow_factory,
            case_id,
            key="c-same",
            scores=(News2(5),),
            score_correction_reason=TYPING_ERROR,
        )

    case = await _read(uow_factory, case_id)
    assert case is not None and case.score_corrections == 1


async def test_a_correction_in_one_tenant_touches_nothing_of_the_other(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    with as_tenant(other_tenant_id):
        b_case = await _filled(uow_factory_b, other_tenant_id, key="open-b")
    b_before = await _read(uow_factory_b, b_case)
    with as_tenant(tenant_id):
        a_case = await _filled(uow_factory_a, tenant_id, key="open-a")
        await _update(
            uow_factory_a,
            a_case,
            key="c-a",
            scores=(News2(5),),
            score_correction_reason=TYPING_ERROR,
        )
        with pytest.raises(NotFound):
            await _update(
                uow_factory_a,
                b_case,
                key="c-foreign",
                scores=(News2(9),),
                score_correction_reason=TYPING_ERROR,
            )

    assert await _read(uow_factory_b, b_case) == b_before
    assert await count_nodes(neo4j_driver, "Observation", tenant=other_tenant_id) == 2


# H-192: the case version.


async def test_a_save_changes_the_version_and_a_read_returns_it(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    case_id = await _filled(uow_factory, tenant_id)
    first = await _version(uow_factory, case_id)

    await _update(uow_factory, case_id, key="u-2", urgency=None, age_band=None)

    assert await _version(uow_factory, case_id) == first + 1


async def test_an_update_naming_an_older_version_is_refused_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    case_id = await _filled(uow_factory, tenant_id)
    read = await _version(uow_factory, case_id)
    await _update(uow_factory, case_id, key="u-other", expected_version=read)
    before = await _read(uow_factory, case_id)
    version = await _version(uow_factory, case_id)

    with pytest.raises(StaleVersion):
        await _update(
            uow_factory,
            case_id,
            key="u-stale",
            expected_version=read,
            postcode="BH1 1AA",
        )

    assert await _read(uow_factory, case_id) == before
    assert await _version(uow_factory, case_id) == version


async def test_an_update_naming_the_current_version_is_applied(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    case_id = await _filled(uow_factory, tenant_id)
    read = await _version(uow_factory, case_id)

    await _update(uow_factory, case_id, key="u-ok", expected_version=read, postcode="BH1 1AA")

    case = await _read(uow_factory, case_id)
    assert case is not None and case.postcode == "BH1"


async def test_two_updates_that_read_the_same_version_cannot_both_be_applied(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    case_id = await _filled(uow_factory, tenant_id)
    read = await _version(uow_factory, case_id)

    async def attempt(key: str, postcode: str) -> str:
        try:
            await _update(uow_factory, case_id, key=key, expected_version=read, postcode=postcode)
        except StaleVersion:
            return "stale"
        return "applied"

    answers = await asyncio.gather(attempt("race-a", "BH1 1AA"), attempt("race-b", "BH2 2BB"))

    assert sorted(answers) == ["applied", "stale"]
    assert await _version(uow_factory, case_id) == read + 1


async def test_a_closed_case_is_a_conflict_before_the_version_is_looked_at(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    from diucs.domain.codes import Outcome
    from diucs.domain.errors import Conflict

    case_id = await _filled(uow_factory, tenant_id)
    async with uow_factory() as uow:
        case = await uow.cases.get(case_id)
        assert case is not None
        await uow.cases.save(case.close(Outcome.DECLINED, LATER))
        await uow.commit()

    with pytest.raises(Conflict):
        await _update(uow_factory, case_id, key="late", expected_version=1, postcode="BH1 1AA")


# KI-400: a case opened with details is opened and filled in one unit.


def _details(**changes: Any) -> UpdateCaseCommand:
    return UpdateCaseCommand("", ADVISOR, "", **{**FILL, **changes})


async def test_a_case_opened_with_details_holds_them_and_wrote_one_audit_entry(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _opener(uow_factory, tenant_id, ScriptedRng()).execute(
        OpenCaseCommand("open-d", ADVISOR, ReferrerType.GP, _details())
    )

    case = await _read(uow_factory, opened.case_id)
    assert case is not None
    assert case.postcode == "DT4"
    assert case.scores == (News2(2), ClinicalFrailty(6))
    entries = [r.entry for r in await _audit(uow_factory) if opened.case_id in r.entry.entity_ids]
    assert [e.use_case for e in entries] == ["OpenCase"]


async def test_details_that_are_refused_leave_no_case_behind(
    uow_factory: UnitOfWorkFactory, tenant_id: str, neo4j_driver: AsyncDriver
) -> None:
    with pytest.raises(ValidationFailed):
        await _opener(uow_factory, tenant_id, ScriptedRng()).execute(
            OpenCaseCommand("open-bad", ADVISOR, ReferrerType.GP, _details(postcode="not one"))
        )
    with pytest.raises(ValidationFailed):
        await _opener(uow_factory, tenant_id, ScriptedRng()).execute(
            OpenCaseCommand(
                "open-dx", ADVISOR, ReferrerType.GP, _details(scores=(PathwaysDx("DxNOPE99"),))
            )
        )

    assert await count_nodes(neo4j_driver, "ServiceRequest") == 0
    assert await count_nodes(neo4j_driver, "Patient") == 0
    assert await _audit(uow_factory) == []


async def test_the_same_key_with_other_details_is_a_conflict(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    from diucs.domain.errors import Conflict

    opener = _opener(uow_factory, tenant_id, ScriptedRng())
    await opener.execute(OpenCaseCommand("open-k", ADVISOR, ReferrerType.GP, _details()))

    with pytest.raises(Conflict):
        await opener.execute(
            OpenCaseCommand("open-k", ADVISOR, ReferrerType.GP, _details(postcode="BH1 1AA"))
        )


async def test_an_update_command_without_a_version_still_applies(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    opened = await _open(uow_factory, tenant_id)
    result = await UpdateCase(uow_factory, _clock(LATER), _idempotency(), LISTED_DX).execute(
        dataclasses.replace(UpdateCaseCommand("k", ADVISOR, opened.case_id), **FILL)
    )

    assert result.complete is True
