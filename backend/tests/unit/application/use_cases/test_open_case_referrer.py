"""A case opens with no referrer, and the referrer is set by an update (W7A-A2, A3).

The advisor's call screen opens an empty case before anything is known (W10), so the referrer type
is optional at open. It is required before the case is complete: `missing_fields` names it, and
FilterOptions refuses a case without one. The storage behaviour is in
tests/integration/adapters/inbound/fhir_rest/test_routes_cases_w7a.py.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.application.actor import Actor
from diucs.application.use_cases.open_case import (
    OpenCaseCommand,
    UpdateCaseCommand,
    apply_update,
    missing_fields,
    new_open_case,
    open_fingerprint,
    snapshot_of,
    update_fingerprint,
)
from diucs.domain.codes import AgeBand, NeedCategory, Outcome, ReferrerType, Role, Urgency
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.case import Case, audit_summary
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
FILL: dict[str, Any] = {
    "age_band": AgeBand.A80_PLUS,
    "postcode": "DT4 8XX",
    "needs": (NeedCategory.FRAILTY,),
    "urgency": Urgency.TODAY,
}


def empty_case() -> Case:
    return new_open_case("case-1", "4821", None, OPENED)


def test_an_empty_case_has_no_referrer() -> None:
    assert empty_case().referrer_type is None


def test_the_open_command_needs_no_referrer() -> None:
    command = OpenCaseCommand("key-1", ADVISOR)

    assert command.referrer_type is None
    assert open_fingerprint(command) != open_fingerprint(
        OpenCaseCommand("key-1", ADVISOR, ReferrerType.GP)
    )


def test_an_update_sets_the_referrer() -> None:
    updated = apply_update(
        empty_case(), UpdateCaseCommand("u-1", ADVISOR, "case-1", referrer_type=ReferrerType.GP)
    )

    assert updated.referrer_type is ReferrerType.GP


def test_an_update_that_leaves_the_referrer_out_keeps_it() -> None:
    with_referrer = apply_update(
        empty_case(), UpdateCaseCommand("u-1", ADVISOR, "case-1", referrer_type=ReferrerType.GP)
    )

    again = apply_update(with_referrer, UpdateCaseCommand("u-2", ADVISOR, "case-1", **FILL))

    assert again.referrer_type is ReferrerType.GP


def test_a_referrer_that_is_not_a_referrer_type_is_refused() -> None:
    command = UpdateCaseCommand(
        "u-1",
        ADVISOR,
        "case-1",
        referrer_type="gp",  # type: ignore[arg-type]
    )

    with pytest.raises(ValidationFailed) as refused:
        apply_update(empty_case(), command)

    assert refused.value.field == "referrer_type"


def test_the_referrer_is_part_of_the_update_fingerprint() -> None:
    first = UpdateCaseCommand("u-1", ADVISOR, "case-1", referrer_type=ReferrerType.GP)
    second = replace(first, referrer_type=ReferrerType.CARE_HOME)

    assert update_fingerprint(first) != update_fingerprint(second)


def test_a_case_with_no_referrer_is_missing_it_last() -> None:
    assert missing_fields(empty_case()) == (
        "age_band",
        "postcode",
        "needs",
        "urgency",
        "referrer_type",
    )


def test_a_case_with_every_field_and_a_referrer_is_complete() -> None:
    case = apply_update(
        empty_case(),
        UpdateCaseCommand("u-1", ADVISOR, "case-1", referrer_type=ReferrerType.GP, **FILL),
    )

    assert missing_fields(case) == ()


def test_the_audit_snapshot_of_a_case_with_no_referrer_holds_none() -> None:
    assert snapshot_of(empty_case())["referrer_type"] is None


def test_the_close_summary_of_a_case_with_no_referrer_holds_none() -> None:
    summary = audit_summary(empty_case(), Outcome.DECLINED, OPENED)

    assert summary.referrer_type is None
