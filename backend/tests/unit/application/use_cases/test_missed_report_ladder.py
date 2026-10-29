"""The parts of MissedReportLadder (U06) that need no database: its constants, the due time a step
belongs to, the rule that a report answers a prompt, and the tenant refusal.

No Neo4j: the tenant cases hand the use case a unit of work that fails the test if it is touched.
"""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.tenancy import ScopeId, TenantNotBound
from diucs.application.use_cases import missed_report_ladder as ladder
from diucs.application.use_cases.missed_report_ladder import (
    LADDER_KINDS,
    REMINDER_REPLY_WINDOW,
    LadderStepCommand,
    LadderStepResult,
    MissedReportLadder,
    ladder_due,
    prompt_answered,
)
from diucs.application.work import SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.schedule import (
    ESCALATE_AFTER,
    PHONE_TASK_AFTER,
    REMINDER_AFTER,
    LadderStep,
    ladder_times,
)

DUE = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)
ACTOR = Actor(
    role=Role.OWNER, practitioner_id=None, device_id=None, channel="worker", service_ids=frozenset()
)
STEP_OF_KIND = {
    WorkKind.REMINDER: LadderStep.REMINDER,
    WorkKind.PHONE_TASK: LadderStep.PHONE_TASK,
    WorkKind.ESCALATE_TO_LEAD: LadderStep.ESCALATE,
}


def _work(kind: WorkKind, due_at: datetime) -> ScheduledWork:
    return ScheduledWork(
        id="work-1",
        kind=kind,
        due_at=due_at,
        about_id="comm-1",
        sequence_number=None,
        status=SCHEDULED,
    )


def test_the_actions_are_the_words_the_prompt_names() -> None:
    assert (
        ladder.REMINDED,
        ladder.PHONE_TASK_RAISED,
        ladder.ESCALATED,
        ladder.STOPPED,
        ladder.IGNORED,
    ) == ("reminded", "phone-task", "escalated", "stopped", "ignored")


def test_the_ladder_is_the_reminder_the_phone_task_and_the_escalation() -> None:
    assert LADDER_KINDS == (WorkKind.REMINDER, WorkKind.PHONE_TASK, WorkKind.ESCALATE_TO_LEAD)


def test_the_new_reply_window_is_thirty_minutes() -> None:
    assert timedelta(minutes=30) == REMINDER_REPLY_WINDOW


def test_the_command_names_no_tenant_and_the_result_names_no_person() -> None:
    # The tenant is bound once at the edge and read from the unit of work (DEC-130 item 3).
    assert {f.name for f in dataclasses.fields(LadderStepCommand)} == {
        "idempotency_key",
        "actor",
        "work_id",
    }
    assert {f.name for f in dataclasses.fields(LadderStepResult)} == {
        "action",
        "communication_id",
        "replayed",
    }


@pytest.mark.parametrize(
    ("kind", "offset"),
    [
        (WorkKind.REMINDER, timedelta(minutes=30)),
        (WorkKind.PHONE_TASK, timedelta(minutes=60)),
        (WorkKind.ESCALATE_TO_LEAD, timedelta(minutes=90)),
    ],
)
def test_a_step_belongs_to_the_prompt_due_its_offset_earlier(
    kind: WorkKind, offset: timedelta
) -> None:
    assert ladder_due(_work(kind, DUE + offset)) == DUE


def test_the_offsets_are_the_ones_the_schedule_rules_define() -> None:
    assert ladder_due(_work(WorkKind.REMINDER, DUE + REMINDER_AFTER)) == DUE
    assert ladder_due(_work(WorkKind.PHONE_TASK, DUE + PHONE_TASK_AFTER)) == DUE
    assert ladder_due(_work(WorkKind.ESCALATE_TO_LEAD, DUE + ESCALATE_AFTER)) == DUE


@pytest.mark.parametrize(
    "kind",
    [WorkKind.PROMPT_DUE, WorkKind.BOOKING_EXPIRE, WorkKind.ALERT_ESCALATE, WorkKind.REVERIFY],
)
def test_work_that_is_not_a_ladder_step_has_no_prompt_due(kind: WorkKind) -> None:
    with pytest.raises(ValidationFailed) as refused:
        ladder_due(_work(kind, DUE))
    assert refused.value.field == "kind"


def test_ladder_due_reads_the_instant_not_the_wall_clock() -> None:
    from zoneinfo import ZoneInfo

    # 01:30 BST on 2026-10-25 is 00:30 UTC; the step 30 minutes later is 01:00 UTC, which is 01:00
    # GMT in London. A London-zoned input must give the real instant, not a wall-clock difference.
    london = ZoneInfo("Europe/London")
    due = datetime(2026, 10, 25, 1, 30, tzinfo=london)
    step_at = (due.astimezone(UTC) + REMINDER_AFTER).astimezone(london)
    assert ladder_due(_work(WorkKind.REMINDER, step_at)) == due.astimezone(UTC)


@given(
    due=st.datetimes(
        min_value=datetime(2026, 1, 1), max_value=datetime(2030, 1, 1), timezones=st.just(UTC)
    ),
    kind=st.sampled_from(LADDER_KINDS),
)
def test_every_step_the_schedule_makes_is_found_again_by_its_due(
    due: datetime, kind: WorkKind
) -> None:
    times = ladder_times(due)
    assert ladder_due(_work(kind, times[STEP_OF_KIND[kind]])) == due


@given(
    due=st.datetimes(
        min_value=datetime(2026, 1, 1), max_value=datetime(2030, 1, 1), timezones=st.just(UTC)
    ),
    delta=st.integers(min_value=-10_000_000, max_value=10_000_000),
)
def test_a_report_answers_a_prompt_exactly_when_it_is_timed_at_or_after_the_due_time(
    due: datetime, delta: int
) -> None:
    effective = due + timedelta(seconds=delta)
    assert prompt_answered(effective, due) is (delta >= 0)


def test_a_report_a_microsecond_before_the_due_time_does_not_answer_it() -> None:
    assert prompt_answered(DUE - timedelta(microseconds=1), DUE) is False
    assert prompt_answered(DUE, DUE) is True


class _Untouched:
    """A unit of work that fails the test if the use case reads or writes anything."""

    def __init__(self, scope: ScopeId | None) -> None:
        self.unit_scope = scope

    async def __aenter__(self) -> _Untouched:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the unit of work was touched: {name}")


def _use_case(scope: ScopeId | None) -> MissedReportLadder:
    return MissedReportLadder(
        lambda: _Untouched(scope),  # type: ignore[arg-type, return-value]
        FixedClock(DUE),
        SequentialIds(),
        lambda repo: None,  # type: ignore[arg-type, return-value]
        "diucs.example",
        None,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "scope", [None, ScopeId.network("net-aaaa")], ids=["nothing-bound", "network-scope"]
)
async def test_a_step_with_no_tenant_bound_is_refused_before_anything_is_read(
    scope: ScopeId | None,
) -> None:
    with pytest.raises(TenantNotBound):
        await _use_case(scope).execute(
            LadderStepCommand(idempotency_key="k", actor=ACTOR, work_id="work-1")
        )
