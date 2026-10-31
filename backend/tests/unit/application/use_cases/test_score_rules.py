"""The score rules of UpdateCase: a Pathways Dx code must be on the list (H-85, KI-247), and a
recorded score changes only as a correction with a reason that the audit keeps (Q7, KI-815).

Pure rules. The unit of work, the audit chain and the replay are in the integration tests
(tests/integration/application/test_open_case_scores.py). Sample values only.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.testing.fixed_terminology import FixedTerminology
from diucs.application.actor import Actor
from diucs.application.use_cases.open_case import (
    UpdateCaseCommand,
    apply_update,
    check_pathways_listed,
    new_open_case,
    score_correction_snapshot,
    update_fingerprint,
)
from diucs.domain.codes import AgeBand, ReferrerType, Role
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.scores import (
    ClinicalFrailty,
    ManchesterTriage,
    News2,
    PathwaysDx,
    ScoreCorrectionReason,
)
from tests.support.actors import ACTOR_TENANT

OPENED = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
LIST = FixedTerminology({}, {}, [("Dx02", "Sample (not a real code)"), ("DxA1", "Sample two")])


def case_with(*scores: Any) -> Case:
    opened = new_open_case("case-1", "4821", ReferrerType.AMBULANCE_CREW, OPENED)
    return replace(opened, scores=tuple(scores))


def update(**changes: Any) -> UpdateCaseCommand:
    return UpdateCaseCommand("update-1", ADVISOR, "case-1", **changes)


# H-85: a Pathways Dx code must be on the list.


async def test_a_listed_code_is_accepted() -> None:
    await check_pathways_listed(LIST, (PathwaysDx("Dx02"),), ())


async def test_a_code_that_is_not_on_the_list_is_refused_without_echoing_it() -> None:
    with pytest.raises(ValidationFailed) as refused:
        await check_pathways_listed(LIST, (News2(2), PathwaysDx("Dx99")), ())

    assert refused.value.field == "scores"
    assert "Dx99" not in str(refused.value)


async def test_a_code_in_the_wrong_case_is_not_on_the_list() -> None:
    with pytest.raises(ValidationFailed):
        await check_pathways_listed(LIST, (PathwaysDx("dx02"),), ())


async def test_a_code_already_recorded_is_not_checked_again_so_a_changed_list_blocks_no_edit() -> (
    None
):
    await check_pathways_listed(LIST, (PathwaysDx("Dx77"),), (PathwaysDx("Dx77"),))


async def test_a_corrected_code_is_checked_against_the_list() -> None:
    with pytest.raises(ValidationFailed):
        await check_pathways_listed(LIST, (PathwaysDx("Dx99"),), (PathwaysDx("Dx02"),))


async def test_a_write_with_no_scores_checks_nothing() -> None:
    await check_pathways_listed(LIST, None, ())
    await check_pathways_listed(LIST, (News2(1),), ())


async def test_an_empty_list_refuses_every_code_so_a_missing_list_fails_closed() -> None:
    with pytest.raises(ValidationFailed):
        await check_pathways_listed(FixedTerminology({}, {}), (PathwaysDx("Dx02"),), ())


# Q7: a recorded score is corrected by a new recorded score with a reason.


def test_changing_a_recorded_score_without_a_reason_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        apply_update(case_with(News2(2)), update(scores=(News2(5),)))

    assert refused.value.field == "score_correction_reason"
    assert "5" not in refused.value.message


def test_changing_a_recorded_score_with_a_reason_records_the_new_score_and_counts_it() -> None:
    reason = ScoreCorrectionReason.TYPING_ERROR

    updated = apply_update(
        case_with(News2(2), ClinicalFrailty(6)),
        update(scores=(News2(5),), score_correction_reason=reason),
    )

    assert updated.scores == (News2(5), ClinicalFrailty(6))
    assert updated.score_corrections == 1


def test_a_second_correction_counts_again() -> None:
    first = apply_update(
        case_with(News2(2)),
        update(scores=(News2(5),), score_correction_reason=ScoreCorrectionReason.RESCORED),
    )

    second = apply_update(
        first,
        update(scores=(News2(7),), score_correction_reason=ScoreCorrectionReason.TYPING_ERROR),
    )

    assert second.scores == (News2(7),)
    assert second.score_corrections == 2


def test_adding_a_score_of_a_new_method_needs_no_reason_and_is_not_a_correction() -> None:
    updated = apply_update(case_with(News2(2)), update(scores=(News2(2), ClinicalFrailty(4))))

    assert updated.scores == (News2(2), ClinicalFrailty(4))
    assert updated.score_corrections == 0


def test_a_first_recording_needs_no_reason() -> None:
    updated = apply_update(case_with(), update(scores=(News2(2),)))

    assert updated.scores == (News2(2),)
    assert updated.score_corrections == 0


def test_repeating_the_recorded_scores_is_not_a_correction_even_with_a_reason() -> None:
    updated = apply_update(
        case_with(News2(2)),
        update(scores=(News2(2),), score_correction_reason=ScoreCorrectionReason.TYPING_ERROR),
    )

    assert updated.score_corrections == 0


def test_a_reason_with_nothing_recorded_to_correct_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        apply_update(
            case_with(),
            update(scores=(News2(2),), score_correction_reason=ScoreCorrectionReason.RESCORED),
        )

    assert refused.value.field == "score_correction_reason"


def test_a_reason_that_is_not_a_listed_reason_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        apply_update(
            case_with(News2(2)),
            update(scores=(News2(5),), score_correction_reason="because"),
        )

    assert refused.value.field == "score_correction_reason"


def test_a_reason_given_with_no_scores_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        apply_update(
            case_with(News2(2)),
            update(
                age_band=AgeBand.A80_PLUS, score_correction_reason=ScoreCorrectionReason.RESCORED
            ),
        )


def test_a_closed_case_cannot_be_corrected() -> None:
    closed = replace(case_with(News2(2)), closed_at=OPENED)

    with pytest.raises(Conflict):
        apply_update(
            closed,
            update(scores=(News2(5),), score_correction_reason=ScoreCorrectionReason.TYPING_ERROR),
        )


def test_a_refused_correction_changes_nothing() -> None:
    recorded = case_with(News2(2))

    with pytest.raises(ValidationFailed):
        apply_update(recorded, update(scores=(News2(5),), age_band=AgeBand.A80_PLUS))

    assert recorded.scores == (News2(2),)
    assert recorded.age_band is None


def test_the_reason_is_part_of_the_command_fingerprint() -> None:
    plain = update(scores=(News2(5),))
    reasoned = update(scores=(News2(5),), score_correction_reason=ScoreCorrectionReason.RESCORED)
    other = update(scores=(News2(5),), score_correction_reason=ScoreCorrectionReason.TYPING_ERROR)

    assert (
        len({update_fingerprint(plain), update_fingerprint(reasoned), update_fingerprint(other)})
        == 3
    )


def test_the_audit_snapshot_of_a_correction_keeps_the_original_the_new_score_and_the_reason() -> (
    None
):
    snapshot = score_correction_snapshot(
        (News2(2), ManchesterTriage("urgent")),
        (News2(5), ManchesterTriage("urgent")),
        ScoreCorrectionReason.TYPING_ERROR,
    )

    assert snapshot == {
        "reason": "typing-error",
        "corrected": [
            {
                "was": {"method": "news2", "value": 2},
                "now": {"method": "news2", "value": 5},
            }
        ],
    }
