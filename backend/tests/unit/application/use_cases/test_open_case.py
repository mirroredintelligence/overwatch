"""The pure rules of OpenCase and UpdateCase (U11): the role, the tenant scope, the postcode
district, the reference retry, the open and update rules, completeness, the audit snapshot and the
replay keys and fingerprints.

The storage behaviour (the case repository, the audit chain, replay in Neo4j) is in
tests/integration/application/test_open_case.py, which runs against a real Neo4j (DEC-004). No
in-memory case store is written here. Values are the sample values of the prompt.
"""

import random
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.application.actor import Actor
from diucs.application.tenancy import ScopeId, TenantNotBound
from diucs.application.use_cases.open_case import (
    OpenCaseCommand,
    UpdateCaseCommand,
    apply_update,
    check_role,
    district_for,
    free_reference,
    missing_fields,
    new_open_case,
    open_fingerprint,
    replay_key,
    snapshot_of,
    tenant_scope,
    update_fingerprint,
)
from diucs.domain.codes import AgeBand, NeedCategory, Outcome, ReferrerType, Role, Urgency
from diucs.domain.errors import Conflict, NotAllowed, ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.scores import (
    AmbulanceCategory,
    ClinicalFrailty,
    ManchesterTriage,
    News2,
    PathwaysDx,
)
from diucs.domain.rules.booking_rules import REFERENCE_ATTEMPTS
from tests.support.actors import ACTOR_TENANT

OPENED = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
LATER = datetime(2026, 10, 29, 10, 10, tzinfo=UTC)
CLOSED_AT = datetime(2026, 10, 29, 11, 0, tzinfo=UTC)
REFERENCE = re.compile(r"[1-9][0-9]{3}")

ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
ALLOWED_ROLES = (Role.ADVISOR, Role.CLINICAL)
REFUSED_ROLES = tuple(role for role in Role if role not in ALLOWED_ROLES)

FILL: dict[str, Any] = {
    "age_band": AgeBand.A80_PLUS,
    "postcode": " dt4 8xx ",
    "needs": (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
    "urgency": Urgency.WITHIN_2_HRS,
    "scores": (News2(2), ClinicalFrailty(6)),
}


class ScriptedRandom(random.Random):
    """randint returns the given numbers in order, then the last one again. It stands in for the
    reference's random source, which production gives a secrets-backed generator."""

    def __init__(self, *values: int) -> None:
        super().__init__(0)
        self._values = list(values)

    def randint(self, low: int, high: int) -> int:
        if len(self._values) > 1:
            return self._values.pop(0)
        return self._values[0]


def opened_case(reference: str = "4821") -> Case:
    return new_open_case("case-1", reference, ReferrerType.AMBULANCE_CREW, OPENED)


def update(**changes: Any) -> UpdateCaseCommand:
    return UpdateCaseCommand("update-1", ADVISOR, "case-1", **changes)


def complete_case() -> Case:
    return apply_update(opened_case(), update(**FILL))


# The role.


@pytest.mark.parametrize("role", ALLOWED_ROLES)
def test_an_advisor_or_a_clinician_may_open_and_update_a_case(role: Role) -> None:
    check_role(replace(ADVISOR, role=role))


@pytest.mark.parametrize("role", REFUSED_ROLES)
def test_any_other_role_may_not_open_or_update_a_case(role: Role) -> None:
    with pytest.raises(NotAllowed):
        check_role(replace(ADVISOR, role=role))


# The tenant scope: the tenant comes from the unit of work, never from a parameter.


def test_a_tenant_scope_is_returned_as_bound() -> None:
    scope = ScopeId.tenant("tenant-a")

    assert tenant_scope(scope) == scope


def test_no_bound_scope_is_refused_as_tenant_not_bound() -> None:
    with pytest.raises(TenantNotBound):
        tenant_scope(None)


def test_a_network_scope_is_refused_as_tenant_not_bound() -> None:
    with pytest.raises(TenantNotBound):
        tenant_scope(ScopeId.network("net-test-1"))


# The postcode: only the district is kept (DEC-067 item 1).


@pytest.mark.parametrize(
    ("text", "district"),
    [
        (" dt4 8xx ", "DT4"),
        ("DT4 8XX", "DT4"),
        ("dt48xx", "DT4"),
        ("dt4 8xx", "DT4"),
        ("DT4 8XX", "DT4"),
    ],
)
def test_a_full_postcode_is_kept_as_its_district(text: str, district: str) -> None:
    assert district_for(text) == district


@pytest.mark.parametrize("text", ["DT4 8X", "DT48", "ＤＴ４ ８ＸＸ", "", "DT4 8XX 9"])
def test_a_text_that_is_not_a_full_postcode_is_refused_and_does_not_echo_it(text: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        district_for(text)

    assert refused.value.field == "postcode"
    if text.strip():
        assert text.strip() not in str(refused.value)


def test_a_postcode_that_is_not_text_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        district_for(2048)

    assert refused.value.field == "postcode"


# The reference: four digits without a leading zero, retried while held (DEC-067 item 7).


@pytest.mark.asyncio
async def test_a_held_reference_is_retried_and_the_next_one_is_returned() -> None:
    held = {"4821"}

    async def is_held(candidate: str) -> bool:
        return candidate in held

    reference = await free_reference(ScriptedRandom(4821, 4822), is_held)

    assert reference == "4822"


@pytest.mark.asyncio
async def test_a_reference_is_four_digits_with_no_leading_zero() -> None:
    async def never_held(candidate: str) -> bool:
        return False

    rng = random.Random(7)
    references = [await free_reference(rng, never_held) for _ in range(40)]

    assert all(REFERENCE.fullmatch(reference) for reference in references)


@pytest.mark.asyncio
async def test_a_reference_held_on_every_attempt_is_a_conflict() -> None:
    async def always_held(candidate: str) -> bool:
        return True

    with pytest.raises(Conflict):
        await free_reference(ScriptedRandom(4821), always_held)


@pytest.mark.asyncio
async def test_the_retry_stops_after_the_attempts_the_booking_rules_allow() -> None:
    attempts: list[str] = []

    async def record_and_hold(candidate: str) -> bool:
        attempts.append(candidate)
        return True

    with pytest.raises(Conflict):
        await free_reference(random.Random(3), record_and_hold)

    assert len(attempts) <= REFERENCE_ATTEMPTS


# A new case: empty, with the referrer, the reference and the open time.


def test_a_new_case_holds_only_its_identity_referrer_and_open_time() -> None:
    assert opened_case() == Case(
        id="case-1",
        reference="4821",
        referrer_type=ReferrerType.AMBULANCE_CREW,
        age_band=None,
        postcode=None,
        needs=(),
        urgency=None,
        scores=(),
        opened_at=OPENED,
    )


# The update rules.


def test_the_fields_are_stored_as_given_and_the_postcode_as_its_district() -> None:
    updated = apply_update(opened_case(), update(**FILL))

    assert updated == Case(
        id="case-1",
        reference="4821",
        referrer_type=ReferrerType.AMBULANCE_CREW,
        age_band=AgeBand.A80_PLUS,
        postcode="DT4",
        needs=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
        urgency=Urgency.WITHIN_2_HRS,
        scores=(News2(2), ClinicalFrailty(6)),
        opened_at=OPENED,
    )


# A district chosen from the chips (W50, W9H DEC-1045): the one way a district alone is kept.


@pytest.mark.parametrize(("text", "district"), [("DT4", "DT4"), (" dt4 ", "DT4"), ("BH21", "BH21")])
def test_a_chosen_district_is_kept_as_the_cases_district(text: str, district: str) -> None:
    updated = apply_update(complete_case(), update(district=text))

    assert updated.postcode == district
    assert replace(updated, postcode="DT4") == complete_case()


@pytest.mark.parametrize("text", ["DT4 8XX", "DT48X9", "", "ＤＴ４", "DT 4", "4DT", "DT4,BH1"])
def test_a_district_that_is_not_one_is_refused_and_does_not_echo_it(text: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        apply_update(complete_case(), update(district=text))

    assert refused.value.field == "district"
    if text.strip():
        assert text.strip() not in str(refused.value)


def test_a_district_and_a_full_postcode_together_are_refused_and_nothing_changes() -> None:
    case = complete_case()

    with pytest.raises(ValidationFailed) as refused:
        apply_update(case, update(district="BH1", postcode="DT4 8XX"))

    assert refused.value.field == "district"
    assert case.postcode == "DT4"


def test_a_district_cannot_change_a_closed_case() -> None:
    with pytest.raises(Conflict):
        apply_update(replace(complete_case(), closed_at=CLOSED_AT), update(district="BH1"))


def test_a_district_is_part_of_what_a_command_says() -> None:
    assert update_fingerprint(update(district="BH1")) != update_fingerprint(update(district="DT4"))
    assert update_fingerprint(update(district="DT4")) != update_fingerprint(update())


def test_a_district_alone_is_not_a_full_postcode_for_the_postcode_field() -> None:
    # The needs form still needs the whole postcode: only the explicit district field takes one.
    with pytest.raises(ValidationFailed) as refused:
        apply_update(opened_case(), update(postcode="DT4"))

    assert refused.value.field == "postcode"


def test_a_field_left_out_of_the_update_is_unchanged() -> None:
    first = apply_update(opened_case(), update(age_band=AgeBand.A16_64))

    second = apply_update(first, update(urgency=Urgency.TODAY))

    assert second.age_band is AgeBand.A16_64
    assert second.urgency is Urgency.TODAY


@pytest.mark.parametrize(
    "score",
    [
        News2(20),
        ClinicalFrailty(1),
        AmbulanceCategory(4),
        ManchesterTriage("urgent"),
        PathwaysDx("ABC12"),
    ],
)
def test_every_kind_of_score_is_recorded_as_given(score: Any) -> None:
    updated = apply_update(opened_case(), update(scores=(score,)))

    assert updated.scores == (score,)


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"age_band": "80+"}, "age_band"),
        ({"urgency": "today"}, "urgency"),
        ({"needs": ("frailty",)}, "needs"),
        ({"needs": ()}, "needs"),
        ({"needs": (NeedCategory.FRAILTY, NeedCategory.FRAILTY)}, "needs"),
        ({"scores": (2,)}, "scores"),
        ({"scores": (News2(2), News2(3))}, "scores"),
        ({"postcode": "DT4 8X"}, "postcode"),
        ({"postcode": "ＤＴ４ ８ＸＸ"}, "postcode"),
    ],
)
def test_a_value_of_the_wrong_kind_or_a_repeated_score_is_refused(
    changes: dict[str, Any], field: str
) -> None:
    before = opened_case()

    with pytest.raises(ValidationFailed) as refused:
        apply_update(before, update(**changes))

    assert refused.value.field == field
    assert before == opened_case()


def test_recorded_scores_can_be_repeated_unchanged() -> None:
    recorded = apply_update(opened_case(), update(scores=(News2(2),)))

    again = apply_update(recorded, update(scores=(News2(2),)))

    assert again.scores == (News2(2),)


def test_recorded_scores_cannot_be_changed_without_a_reason() -> None:
    # A change is a correction with a reason (Q7, DEC-1171): tests/unit/.../test_score_rules.py.
    recorded = apply_update(opened_case(), update(scores=(News2(2),)))

    with pytest.raises(ValidationFailed) as refused:
        apply_update(recorded, update(scores=(News2(3),)))

    assert refused.value.field == "score_correction_reason"


def test_recorded_scores_cannot_be_cleared() -> None:
    recorded = apply_update(opened_case(), update(scores=(News2(2),)))

    with pytest.raises(ValidationFailed) as refused:
        apply_update(recorded, update(scores=()))

    assert refused.value.field == "scores"


@pytest.mark.parametrize("outcome", [Outcome.DECLINED, Outcome.NO_SERVICE_FITS])
def test_a_closed_case_cannot_be_updated_and_is_a_conflict(outcome: Outcome) -> None:
    closed = complete_case().close(outcome, CLOSED_AT)

    with pytest.raises(Conflict):
        apply_update(closed, update(**FILL))

    assert closed.closed_at == CLOSED_AT


# Completeness: age band, postcode, at least one need, urgency (the prompt's rule).


def test_an_empty_case_is_missing_every_field_in_order() -> None:
    assert missing_fields(opened_case()) == ("age_band", "postcode", "needs", "urgency")


def test_only_the_age_band_leaves_three_things_missing() -> None:
    case = apply_update(opened_case(), update(age_band=AgeBand.A80_PLUS))

    assert missing_fields(case) == ("postcode", "needs", "urgency")


def test_a_case_with_everything_but_a_need_is_missing_the_need() -> None:
    without_needs = replace(complete_case(), needs=())

    assert missing_fields(without_needs) == ("needs",)


def test_a_case_with_the_four_required_fields_is_complete() -> None:
    assert missing_fields(complete_case()) == ()


# The audit snapshot: reference, referrer, age band, needs, urgency. Never the postcode.


def test_the_snapshot_holds_the_five_audit_fields_and_no_postcode() -> None:
    snapshot = snapshot_of(complete_case())

    assert set(snapshot) == {"reference", "referrer_type", "age_band", "needs", "urgency"}
    assert snapshot["reference"] == "4821"
    assert "DT4" not in snapshot.values()


# Replay keys and fingerprints (the same key in another tenant is another command).


def test_a_replay_key_is_named_by_the_use_case_and_the_tenant() -> None:
    tenant_a = ScopeId.tenant("tenant-a")
    tenant_b = ScopeId.tenant("tenant-b")

    keys = {
        replay_key("OpenCase", tenant_a, "k-1"),
        replay_key("OpenCase", tenant_b, "k-1"),
        replay_key("UpdateCase", tenant_a, "k-1"),
    }

    assert len(keys) == 3


def test_an_open_fingerprint_is_stable_for_the_same_command_and_changes_with_the_referrer() -> None:
    same = OpenCaseCommand("open-1", ADVISOR, ReferrerType.GP)

    assert open_fingerprint(same) == open_fingerprint(replace(same))
    assert open_fingerprint(same) != open_fingerprint(
        OpenCaseCommand("open-1", ADVISOR, ReferrerType.NHS_111)
    )
    assert open_fingerprint(same) != open_fingerprint(
        OpenCaseCommand("open-1", replace(ADVISOR, role=Role.CLINICAL), ReferrerType.GP)
    )


def test_an_update_fingerprint_is_stable_for_the_same_body_and_changes_with_any_field() -> None:
    same = update(age_band=AgeBand.A80_PLUS)

    assert update_fingerprint(same) == update_fingerprint(replace(same))
    assert update_fingerprint(same) != update_fingerprint(update(age_band=AgeBand.A16_64))
    assert update_fingerprint(same) != update_fingerprint(
        update(age_band=AgeBand.A80_PLUS, postcode="DT4 8XX")
    )
