"""Tenant lifecycle state machine, activation blockers, quarantine and purge rules (TEN-006).

Rules: docs/delivery/tenancy-audit/F-lifecycle-flows.md 2.4, DEC-136 item 10, DEC-155. Safety
critical (`domain/rules/`): table-driven, property-tested, mutation-checked.
"""

import dataclasses
import itertools
from datetime import datetime, timedelta
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.domain.errors import DomainError, InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    NumberStatus,
    RetentionClass,
    SuspendMode,
    SuspendReason,
    Tenant,
    TenantStatus,
)
from diucs.domain.rules.tenant_lifecycle import (
    NUMBER_QUARANTINE,
    OFFBOARDING_NOTICE,
    PURGE_OPERATORS_REQUIRED,
    ActivationFacts,
    activate_tenant,
    activation_blockers,
    complete_offboarding,
    number_assignable,
    number_quarantine_until,
    offboarding_may_complete_at,
    purge_blockers,
    purge_tenant,
    reopen_tenant,
    resume_tenant,
    start_offboarding,
    suspend_tenant,
    transition_config,
    transition_tenant,
)
from tests.support.tenant_samples import SAMPLE_ID, T0, make_tenant, passing_facts

S = TenantStatus
C = ConfigStatus
CANARY = "canary-tenant-ref"
DAY = timedelta(days=1)
MICROSECOND = timedelta(microseconds=1)

# audit F 2.4 and the prompt, rule 8: the only legal moves. A tuple, so test ids are stable.
LEGAL: tuple[tuple[TenantStatus, TenantStatus], ...] = (
    (S.PROVISIONING, S.ACTIVE),
    (S.ACTIVE, S.SUSPENDED),
    (S.SUSPENDED, S.ACTIVE),
    (S.ACTIVE, S.OFFBOARDING),
    (S.SUSPENDED, S.OFFBOARDING),
    (S.OFFBOARDING, S.OFFBOARDED),
    (S.OFFBOARDING, S.ACTIVE),
    (S.OFFBOARDED, S.ACTIVE),
    (S.OFFBOARDED, S.PURGED),
)
ALL_PAIRS = tuple(itertools.product(S, S))
ILLEGAL = tuple(pair for pair in ALL_PAIRS if pair not in LEGAL)


def test_the_constants_are_as_decided() -> None:
    assert timedelta(days=30) == OFFBOARDING_NOTICE
    assert timedelta(days=90) == NUMBER_QUARANTINE
    assert PURGE_OPERATORS_REQUIRED == 2


# ---------------------------------------------------------------- 16. the state machine


def test_the_table_has_nine_legal_moves_of_thirty_six_pairs() -> None:
    assert len(LEGAL) == 9
    assert len(ILLEGAL) == 36 - 9


@pytest.mark.parametrize(("current", "target"), LEGAL, ids=lambda s: s.value)
def test_every_legal_move_is_accepted(current: TenantStatus, target: TenantStatus) -> None:
    result = transition_tenant(current, target)
    assert result is target


@pytest.mark.parametrize(("current", "target"), ILLEGAL, ids=lambda s: s.value)
def test_every_other_pair_is_refused(current: TenantStatus, target: TenantStatus) -> None:
    with pytest.raises(InvalidTransition) as refused:
        transition_tenant(current, target)
    assert current.value in str(refused.value)
    assert target.value in str(refused.value)


def test_purged_is_terminal_and_provisioning_cannot_be_suspended() -> None:
    for target in S:
        with pytest.raises(InvalidTransition):
            transition_tenant(S.PURGED, target)
    with pytest.raises(InvalidTransition):
        transition_tenant(S.PROVISIONING, S.SUSPENDED)
    for status in S:
        with pytest.raises(InvalidTransition):
            transition_tenant(status, status)


@pytest.mark.parametrize("bad", ["active", NumberStatus.ACTIVE, ConfigStatus.DRAFT, None, 1])
def test_a_status_that_is_not_exactly_a_tenant_status_is_refused(bad: Any) -> None:
    # "active" == TenantStatus.ACTIVE and NumberStatus.ACTIVE == TenantStatus.ACTIVE (lesson L3).
    with pytest.raises(ValidationFailed) as refused:
        transition_tenant(bad, S.ACTIVE)
    assert refused.value.field == "current"
    with pytest.raises(ValidationFailed) as refused:
        transition_tenant(S.PROVISIONING, bad)
    assert refused.value.field == "target"


def _graph() -> dict[TenantStatus, set[TenantStatus]]:
    """The machine as the code answers it, built by asking about every pair."""
    graph: dict[TenantStatus, set[TenantStatus]] = {status: set() for status in S}
    for current, target in ALL_PAIRS:
        try:
            transition_tenant(current, target)
        except InvalidTransition:
            continue
        graph[current].add(target)
    return graph


def test_the_machine_follows_the_table_exactly() -> None:
    graph = _graph()
    assert {(a, b) for a, targets in graph.items() for b in targets} == set(LEGAL)


def test_every_state_is_reachable_and_only_purged_is_a_dead_end() -> None:
    graph = _graph()
    reached = {S.PROVISIONING}
    frontier = [S.PROVISIONING]
    while frontier:
        for target in graph[frontier.pop()]:
            if target not in reached:
                reached.add(target)
                frontier.append(target)
    assert reached == set(S)
    assert [status for status, targets in graph.items() if not targets] == [S.PURGED]
    # Nothing leads back into provisioning: a tenant is created there and only there.
    assert not any(S.PROVISIONING in targets for targets in graph.values())


@settings(max_examples=200, deadline=None)
@given(st.sampled_from(list(S)), st.sampled_from(list(S)))
def test_property_a_move_follows_the_table_or_is_refused_and_is_deterministic(
    current: TenantStatus, target: TenantStatus
) -> None:
    outcomes = []
    for _ in range(2):
        try:
            outcomes.append(transition_tenant(current, target))
        except InvalidTransition as refusal:
            outcomes.append(str(refusal))
    assert outcomes[0] == outcomes[1]
    assert (outcomes[0] is target) == ((current, target) in LEGAL)


# ---------------------------------------------------------------- 17. suspend and resume


def test_suspend_sets_mode_reason_and_time_and_counts_the_epoch() -> None:
    tenant = make_tenant(S.ACTIVE)
    now = T0 + timedelta(days=3)
    suspended = suspend_tenant(tenant, SuspendMode.BLOCKED, SuspendReason.SECURITY_INCIDENT, now)
    assert isinstance(suspended, Tenant)
    assert suspended.status is S.SUSPENDED
    assert suspended.suspend_mode is SuspendMode.BLOCKED
    assert suspended.suspend_reason is SuspendReason.SECURITY_INCIDENT
    assert suspended.suspended_at == now
    assert suspended.epoch == tenant.epoch + 1
    assert suspended.id == tenant.id and suspended.activated_at == tenant.activated_at


def test_the_original_tenant_is_unchanged_by_every_move() -> None:
    tenant = make_tenant(S.ACTIVE)
    before = dataclasses.replace(tenant)
    now = T0 + timedelta(days=3)
    suspend_tenant(tenant, SuspendMode.READ_ONLY, SuspendReason.CONTRACT, now)
    start_offboarding(tenant, now)
    assert tenant == before
    assert tenant.status is S.ACTIVE and tenant.epoch == 1


def test_resume_clears_the_three_suspend_fields_and_counts_the_epoch_again() -> None:
    tenant = make_tenant(S.ACTIVE)
    suspended = suspend_tenant(
        tenant, SuspendMode.READ_ONLY, SuspendReason.CLINICAL_SAFETY, T0 + 3 * DAY
    )
    resumed = resume_tenant(suspended, T0 + 4 * DAY)
    assert resumed.status is S.ACTIVE
    assert (resumed.suspend_mode, resumed.suspend_reason, resumed.suspended_at) == (None,) * 3
    assert resumed.epoch == tenant.epoch + 2
    assert suspended.status is S.SUSPENDED and suspended.suspend_mode is SuspendMode.READ_ONLY


@pytest.mark.parametrize(
    "status", [S.PROVISIONING, S.SUSPENDED, S.OFFBOARDING, S.OFFBOARDED, S.PURGED]
)
def test_only_an_active_tenant_can_be_suspended(status: TenantStatus) -> None:
    with pytest.raises(InvalidTransition):
        suspend_tenant(
            make_tenant(status), SuspendMode.BLOCKED, SuspendReason.CONTRACT, T0 + 90 * DAY
        )


@pytest.mark.parametrize(
    "status", [S.PROVISIONING, S.ACTIVE, S.OFFBOARDING, S.OFFBOARDED, S.PURGED]
)
def test_only_a_suspended_tenant_can_be_resumed(status: TenantStatus) -> None:
    # OFFBOARDING and OFFBOARDED may move to active (reopen), but that is `reopen_tenant`, not this.
    with pytest.raises(InvalidTransition):
        resume_tenant(make_tenant(status), T0 + 90 * DAY)


def test_suspend_refuses_a_mode_or_reason_that_is_not_exactly_its_enum() -> None:
    tenant = make_tenant(S.ACTIVE)
    now = T0 + 3 * DAY
    for mode in ("read-only", None, SuspendReason.CONTRACT):
        with pytest.raises(ValidationFailed):
            suspend_tenant(tenant, mode, SuspendReason.CONTRACT, now)  # type: ignore[arg-type]
    for reason in ("contract", None, SuspendMode.BLOCKED):
        with pytest.raises(ValidationFailed):
            suspend_tenant(tenant, SuspendMode.BLOCKED, reason, now)  # type: ignore[arg-type]


def test_a_suspend_time_before_activation_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        suspend_tenant(make_tenant(S.ACTIVE), SuspendMode.BLOCKED, SuspendReason.CONTRACT, T0)


@pytest.mark.parametrize("now", [datetime(2026, 2, 1), "2026-02-01", None, 5])
def test_every_function_that_takes_now_refuses_a_naive_or_missing_instant(now: Any) -> None:
    active, suspended = make_tenant(S.ACTIVE), make_tenant(S.SUSPENDED)
    offboarding, offboarded = make_tenant(S.OFFBOARDING), make_tenant(S.OFFBOARDED)
    calls: list[Any] = [
        lambda: suspend_tenant(active, SuspendMode.BLOCKED, SuspendReason.CONTRACT, now),
        lambda: resume_tenant(suspended, now),
        lambda: start_offboarding(active, now),
        lambda: complete_offboarding(offboarding, now),
        lambda: purge_tenant(offboarded, now),
        lambda: activate_tenant(make_tenant(S.PROVISIONING), passing_facts(), now),
        lambda: purge_blockers(offboarded, now, ["a", "b"], SAMPLE_ID),
        lambda: number_assignable(NumberStatus.RETIRED, T0, now),
        lambda: number_quarantine_until(now),
    ]
    for call in calls:
        with pytest.raises(ValueError):
            call()


def test_a_function_that_takes_a_tenant_refuses_anything_else() -> None:
    now = T0 + 90 * DAY
    for bad in (None, {"status": "active"}, "example-icb", S.ACTIVE):
        for call in (
            lambda b=bad: suspend_tenant(b, SuspendMode.BLOCKED, SuspendReason.CONTRACT, now),
            lambda b=bad: resume_tenant(b, now),
            lambda b=bad: start_offboarding(b, now),
            lambda b=bad: complete_offboarding(b, now),
            lambda b=bad: purge_tenant(b, now),
            lambda b=bad: reopen_tenant(b),
            lambda b=bad: activate_tenant(b, passing_facts(), now),
            lambda b=bad: offboarding_may_complete_at(b),
            lambda b=bad: purge_blockers(b, now, ["a", "b"], SAMPLE_ID),
        ):
            with pytest.raises(TypeError, match="a Tenant is required"):
                call()


# ---------------------------------------------------------------- 18. offboarding and purge


def test_start_offboarding_from_active_or_suspended() -> None:
    now = T0 + 20 * DAY
    started = start_offboarding(make_tenant(S.ACTIVE), now)
    assert started.status is S.OFFBOARDING and started.offboarding_started_at == now
    suspended = suspend_tenant(
        make_tenant(S.ACTIVE), SuspendMode.BLOCKED, SuspendReason.CONTRACT, T0 + 3 * DAY
    )
    started = start_offboarding(suspended, now)
    assert started.status is S.OFFBOARDING
    assert (started.suspend_mode, started.suspend_reason, started.suspended_at) == (None,) * 3
    assert started.epoch == suspended.epoch


@pytest.mark.parametrize("status", [S.PROVISIONING, S.OFFBOARDING, S.OFFBOARDED, S.PURGED])
def test_offboarding_starts_only_from_active_or_suspended(status: TenantStatus) -> None:
    with pytest.raises(InvalidTransition):
        start_offboarding(make_tenant(status), T0 + 90 * DAY)


def test_the_notice_ends_thirty_days_after_it_started() -> None:
    tenant = make_tenant(S.OFFBOARDING)
    assert tenant.offboarding_started_at is not None
    assert offboarding_may_complete_at(tenant) == tenant.offboarding_started_at + timedelta(days=30)


def test_the_notice_has_no_end_before_offboarding_has_started() -> None:
    with pytest.raises(NotAllowed):
        offboarding_may_complete_at(make_tenant(S.ACTIVE))


def test_complete_offboarding_is_refused_one_microsecond_before_thirty_days() -> None:
    tenant = make_tenant(S.OFFBOARDING)
    assert tenant.offboarding_started_at is not None
    end = tenant.offboarding_started_at + timedelta(days=30)
    with pytest.raises(NotAllowed):
        complete_offboarding(tenant, end - MICROSECOND)


def test_complete_offboarding_passes_at_exactly_thirty_days_and_after() -> None:
    tenant = make_tenant(S.OFFBOARDING)
    assert tenant.offboarding_started_at is not None
    end = tenant.offboarding_started_at + timedelta(days=30)
    done = complete_offboarding(tenant, end)
    assert done.status is S.OFFBOARDED and done.offboarded_at == end
    assert complete_offboarding(tenant, end + MICROSECOND).offboarded_at == end + MICROSECOND
    assert tenant.status is S.OFFBOARDING


def test_a_waiver_lets_offboarding_complete_early_and_only_a_real_true_does() -> None:
    tenant = make_tenant(S.OFFBOARDING)
    assert tenant.offboarding_started_at is not None
    early = tenant.offboarding_started_at + DAY
    assert complete_offboarding(tenant, early, waived=True).status is S.OFFBOARDED
    for not_a_waiver in (False, 1, "yes", "true", [1], None):
        with pytest.raises(NotAllowed):
            complete_offboarding(tenant, early, waived=not_a_waiver)  # type: ignore[arg-type]


@pytest.mark.parametrize("status", [S.PROVISIONING, S.ACTIVE, S.SUSPENDED, S.OFFBOARDED, S.PURGED])
def test_offboarding_completes_only_from_offboarding(status: TenantStatus) -> None:
    with pytest.raises(InvalidTransition):
        complete_offboarding(make_tenant(status), T0 + 900 * DAY, waived=True)


def test_purge_marks_the_tenant_purged_at_the_time_given() -> None:
    tenant = make_tenant(S.OFFBOARDED)
    now = T0 + 100 * DAY
    purged = purge_tenant(tenant, now)
    assert purged.status is S.PURGED and purged.purged_at == now
    assert tenant.status is S.OFFBOARDED


def test_purge_is_refused_while_the_retention_hold_is_in_the_future() -> None:
    hold = T0 + 100 * DAY
    tenant = make_tenant(S.OFFBOARDED, retention_hold_until=hold)
    with pytest.raises(NotAllowed):
        purge_tenant(tenant, hold - MICROSECOND)
    with pytest.raises(NotAllowed):
        purge_tenant(tenant, T0 + 50 * DAY)


def test_purge_passes_at_the_hold_instant_and_after() -> None:
    hold = T0 + 100 * DAY
    tenant = make_tenant(S.OFFBOARDED, retention_hold_until=hold)
    assert purge_tenant(tenant, hold).purged_at == hold
    assert purge_tenant(tenant, hold + MICROSECOND).status is S.PURGED


@pytest.mark.parametrize("status", [S.PROVISIONING, S.ACTIVE, S.SUSPENDED, S.OFFBOARDING, S.PURGED])
def test_purge_applies_only_to_an_offboarded_tenant(status: TenantStatus) -> None:
    with pytest.raises(InvalidTransition):
        purge_tenant(make_tenant(status), T0 + 900 * DAY)


@pytest.mark.parametrize("status", [S.OFFBOARDING, S.OFFBOARDED])
def test_reopening_before_purge_makes_the_tenant_active_again(status: TenantStatus) -> None:
    tenant = make_tenant(status)
    now = T0 + 100 * DAY
    reopened = reopen_tenant(tenant)
    assert reopened.status is S.ACTIVE
    assert reopened.offboarding_started_at is None and reopened.offboarded_at is None
    assert reopened.activated_at == tenant.activated_at
    assert reopened.epoch == tenant.epoch + 1


@pytest.mark.parametrize("status", [S.PROVISIONING, S.ACTIVE, S.SUSPENDED, S.PURGED])
def test_only_an_offboarding_or_offboarded_tenant_is_reopened(status: TenantStatus) -> None:
    with pytest.raises(InvalidTransition):
        reopen_tenant(make_tenant(status))


def test_a_reopened_tenant_starts_a_new_notice_period_when_it_offboards_again() -> None:
    reopened = reopen_tenant(make_tenant(S.OFFBOARDING))
    again = start_offboarding(reopened, T0 + 200 * DAY)
    assert offboarding_may_complete_at(again) == T0 + 230 * DAY


# ---------------------------------------------------------------- activation


def test_a_provisioning_tenant_activates_when_every_fact_passes() -> None:
    tenant = make_tenant(S.PROVISIONING)
    now = T0 + 2 * DAY
    active = activate_tenant(tenant, passing_facts(), now)
    assert active.status is S.ACTIVE and active.activated_at == now
    assert tenant.status is S.PROVISIONING and tenant.activated_at is None


def test_activation_is_refused_with_the_blockers_named_in_order() -> None:
    tenant = make_tenant(S.PROVISIONING)
    facts = passing_facts(config_approved=False, wording_complete=False)
    with pytest.raises(NotAllowed) as refused:
        activate_tenant(tenant, facts, T0 + DAY)
    text = str(refused.value)
    assert text.startswith("Activation is unavailable until: ")
    assert text.index("Configuration version approved") < text.index("System, referral system")


@pytest.mark.parametrize("bad", [None, {"config_approved": True}, "facts", 5])
def test_activation_needs_activation_facts_and_nothing_else(bad: Any) -> None:
    with pytest.raises(TypeError, match="ActivationFacts are required"):
        activate_tenant(make_tenant(S.PROVISIONING), bad, T0 + DAY)


def test_the_state_is_checked_before_the_facts() -> None:
    with pytest.raises(InvalidTransition):
        activate_tenant(make_tenant(S.ACTIVE), passing_facts(config_approved=False), T0 + DAY)


# ---------------------------------------------------------------- 19. number quarantine


def test_a_number_is_quarantined_for_ninety_days_from_retirement() -> None:
    assert number_quarantine_until(T0) == T0 + timedelta(days=90)
    assert number_quarantine_until(T0 + MICROSECOND) == T0 + timedelta(days=90) + MICROSECOND


def test_a_retired_number_is_assignable_only_from_day_ninety() -> None:
    until = number_quarantine_until(T0)
    assert not number_assignable(NumberStatus.RETIRED, until, T0 + timedelta(days=89))
    assert not number_assignable(NumberStatus.RETIRED, until, until - MICROSECOND)
    assert number_assignable(NumberStatus.RETIRED, until, until)
    assert number_assignable(NumberStatus.RETIRED, until, until + MICROSECOND)
    assert not number_assignable(NumberStatus.QUARANTINED, until, until - MICROSECOND)
    assert number_assignable(NumberStatus.QUARANTINED, until, until)


def test_a_number_that_was_never_assigned_is_assignable() -> None:
    assert number_assignable(None, None, T0)


def test_a_number_with_no_quarantine_end_is_not_assignable_unless_never_assigned() -> None:
    assert not number_assignable(NumberStatus.QUARANTINED, None, T0 + 900 * DAY)
    assert not number_assignable(NumberStatus.RETIRED, None, T0 + 900 * DAY)


def test_an_active_number_is_not_assignable_whatever_its_dates() -> None:
    assert not number_assignable(NumberStatus.ACTIVE, None, T0)
    assert not number_assignable(NumberStatus.ACTIVE, T0, T0 + 900 * DAY)


@pytest.mark.parametrize("bad", ["retired", S.ACTIVE, 1])
def test_a_number_status_is_checked_by_type(bad: Any) -> None:
    with pytest.raises(ValidationFailed):
        number_assignable(bad, T0, T0)


def test_a_naive_quarantine_end_is_refused() -> None:
    with pytest.raises(ValueError):
        number_assignable(NumberStatus.RETIRED, datetime(2026, 1, 5), T0)


@settings(max_examples=300, deadline=None)
@given(
    st.sampled_from([None, *NumberStatus]),
    st.one_of(st.none(), st.integers(0, 400)),
    st.integers(0, 400),
    st.integers(0, 400),
)
def test_property_assignability_never_goes_back_to_false_as_time_passes(
    status: NumberStatus | None, until_days: int | None, now_days: int, later_days: int
) -> None:
    until = None if until_days is None else T0 + timedelta(days=until_days)
    now = T0 + timedelta(days=now_days)
    later = now + timedelta(days=later_days)
    if number_assignable(status, until, now):
        assert number_assignable(status, until, later)
    # and it is deterministic
    assert number_assignable(status, until, now) == number_assignable(status, until, now)


@settings(max_examples=200, deadline=None)
@given(st.integers(0, 1000))
def test_property_a_retired_number_is_assignable_exactly_from_ninety_days(days: int) -> None:
    now = T0 + timedelta(days=days)
    assert number_assignable(NumberStatus.RETIRED, number_quarantine_until(T0), now) == (days >= 90)


# ---------------------------------------------------------------- 20. purge blockers

NOT_OFFBOARDED = "Tenant is offboarded"
HOLD = "Retention hold has not passed"
OPERATORS = "Two different operators are needed"
TYPED = "The tenant id was not typed correctly"


def test_purge_blockers_lists_the_four_in_order_for_an_active_tenant() -> None:
    tenant = make_tenant(S.ACTIVE, retention_hold_until=T0 + 100 * DAY)
    assert purge_blockers(tenant, T0 + 10 * DAY, ["op-1"], "wrong-id") == [
        NOT_OFFBOARDED,
        HOLD,
        OPERATORS,
        TYPED,
    ]


def test_purge_blockers_is_empty_for_an_offboarded_tenant_past_its_hold() -> None:
    tenant = make_tenant(S.OFFBOARDED, retention_hold_until=T0 + 100 * DAY)
    assert purge_blockers(tenant, T0 + 100 * DAY, ["op-1", "op-2"], SAMPLE_ID) == []
    assert (
        purge_blockers(make_tenant(S.OFFBOARDED), T0 + 90 * DAY, ("op-1", "op-2"), SAMPLE_ID) == []
    )


def test_each_purge_blocker_is_listed_alone() -> None:
    offboarded = make_tenant(S.OFFBOARDED, retention_hold_until=T0 + 100 * DAY)
    past = T0 + 100 * DAY
    two = ["op-1", "op-2"]
    assert purge_blockers(make_tenant(S.OFFBOARDING), past, two, SAMPLE_ID) == [NOT_OFFBOARDED]
    assert purge_blockers(offboarded, past - MICROSECOND, two, SAMPLE_ID) == [HOLD]
    assert purge_blockers(offboarded, past, ["op-1"], SAMPLE_ID) == [OPERATORS]
    assert purge_blockers(offboarded, past, two, "example-icb2") == [TYPED]
    assert purge_blockers(offboarded, past, two, "Example-icb") == [TYPED]
    assert purge_blockers(offboarded, past, two, "") == [TYPED]


@pytest.mark.parametrize(
    "operators",
    [[], ["op-1"], ["op-1", "op-1"], ["op-1", ""], ["op-1", " "], ["op-1", None], "op-1op-2", None],
    ids=["none", "one", "equal", "empty", "blank", "none-ref", "bare-string", "not-a-list"],
)
def test_fewer_than_two_distinct_named_operators_block_the_purge(operators: Any) -> None:
    tenant = make_tenant(S.OFFBOARDED)
    assert purge_blockers(tenant, T0 + 90 * DAY, operators, SAMPLE_ID) == [OPERATORS]


def test_the_typed_id_must_be_exactly_text_and_equal() -> None:
    class Text(str):
        pass

    tenant = make_tenant(S.OFFBOARDED)
    for typed in (None, 5, b"example-icb", Text(SAMPLE_ID)):
        assert purge_blockers(tenant, T0 + 90 * DAY, ["a", "b"], typed) == [TYPED]  # type: ignore[arg-type]


def test_a_purged_tenant_is_not_offboarded() -> None:
    assert NOT_OFFBOARDED in purge_blockers(
        make_tenant(S.PURGED), T0 + 90 * DAY, ["a", "b"], SAMPLE_ID
    )


# ---------------------------------------------------------------- 21. activation blockers

CONFIG = "Configuration version approved"
ZONE = "Time zone set"
NUMBER = "At least one sender number active with a test text delivered"
EMAIL = "Email sender verified"
ADMIN = "First tenant administrator invited"
ENTRA = "Sign-in directory bound and verified"
ROLE = "At least one role mapping"
CONTACTS = "Support contacts set: coordination phone and clinical safety officer"
RETENTION = "Retention set for every data class"
REFERENCES = "Data sharing, data protection and clinical safety references recorded"
WORDING = "System, referral system and coordination team names set"
DISTRICTS = "Area districts set"
AGREEMENT = "Network agreement accepted"
ALL_SENTENCES = [
    CONFIG,
    ZONE,
    NUMBER,
    EMAIL,
    ADMIN,
    ENTRA,
    ROLE,
    CONTACTS,
    RETENTION,
    REFERENCES,
    WORDING,
    DISTRICTS,
    AGREEMENT,
]
PHONE, CSO = ContactKind.COORDINATION_PHONE, ContactKind.CLINICAL_SAFETY_OFFICER
ALL_RETENTION = frozenset(RetentionClass)

SINGLE_FAILURES: list[tuple[str, dict[str, Any], str]] = [
    ("config not approved", {"config_approved": False}, CONFIG),
    ("config approved is the integer 1", {"config_approved": 1}, CONFIG),
    ("config approved is the text true", {"config_approved": "true"}, CONFIG),
    ("config approved is None", {"config_approved": None}, CONFIG),
    ("no time zone", {"time_zone": None}, ZONE),
    ("time zone off the list", {"time_zone": "UTC"}, ZONE),
    ("time zone not text", {"time_zone": 5}, ZONE),
    ("no active tested number", {"active_numbers_tested": 0}, NUMBER),
    ("number count is a flag", {"active_numbers_tested": True}, NUMBER),
    ("number count is text", {"active_numbers_tested": "1"}, NUMBER),
    ("number count is negative", {"active_numbers_tested": -1}, NUMBER),
    ("email sender not verified", {"email_sender_verified": False}, EMAIL),
    ("email verified is 1", {"email_sender_verified": 1}, EMAIL),
    (
        "email in use is 0 (not exactly False)",
        {"email_in_use": 0, "email_sender_verified": False},
        EMAIL,
    ),
    ("email in use is None", {"email_in_use": None, "email_sender_verified": False}, EMAIL),
    ("no first admin", {"first_admin_invited": False}, ADMIN),
    ("first admin is 1", {"first_admin_invited": 1}, ADMIN),
    ("no sign-in directory", {"entra_binding_verified": False}, ENTRA),
    ("sign-in directory is 1", {"entra_binding_verified": 1}, ENTRA),
    ("no role mapping", {"role_mappings": 0}, ROLE),
    ("role mappings is a flag", {"role_mappings": True}, ROLE),
    ("role mappings is text", {"role_mappings": "2"}, ROLE),
    ("no clinical safety officer", {"contact_kinds": frozenset({PHONE})}, CONTACTS),
    ("no coordination phone", {"contact_kinds": frozenset({CSO})}, CONTACTS),
    ("only other contacts", {"contact_kinds": frozenset({ContactKind.SUPPORT_EMAIL})}, CONTACTS),
    ("no contacts", {"contact_kinds": frozenset()}, CONTACTS),
    (
        "contacts as plain text",
        {"contact_kinds": frozenset({"coordination-phone", "clinical-safety-officer"})},
        CONTACTS,
    ),
    ("contacts not a set", {"contact_kinds": None}, CONTACTS),
    (
        "one retention class short",
        {"retention_classes_set": ALL_RETENTION - {RetentionClass.AUDIT_CHAIN}},
        RETENTION,
    ),
    ("no retention classes", {"retention_classes_set": frozenset()}, RETENTION),
    (
        "retention as plain text",
        {"retention_classes_set": frozenset(c.value for c in RetentionClass)},
        RETENTION,
    ),
    ("retention not a set", {"retention_classes_set": None}, RETENTION),
    ("no dsa", {"references_recorded": frozenset({"dpia", "dcb0160"})}, REFERENCES),
    ("no dpia", {"references_recorded": frozenset({"dsa", "dcb0160"})}, REFERENCES),
    ("no dcb0160", {"references_recorded": frozenset({"dsa", "dpia"})}, REFERENCES),
    ("no references", {"references_recorded": frozenset()}, REFERENCES),
    ("references not a set", {"references_recorded": "dsa dpia dcb0160"}, REFERENCES),
    ("wording incomplete", {"wording_complete": False}, WORDING),
    ("wording complete is 1", {"wording_complete": 1}, WORDING),
    ("services without districts", {"area_districts_set": False}, DISTRICTS),
    ("districts is 1", {"area_districts_set": 1}, DISTRICTS),
    ("registers services is 0", {"registers_services": 0, "area_districts_set": False}, DISTRICTS),
    ("member without agreement", {"agreement_accepted": False}, AGREEMENT),
    ("agreement is 1", {"agreement_accepted": 1}, AGREEMENT),
    ("network member is None", {"network_member": None, "agreement_accepted": False}, AGREEMENT),
]


def test_all_passing_facts_list_nothing() -> None:
    assert activation_blockers(passing_facts()) == []


@pytest.mark.parametrize(
    ("overrides", "sentence"),
    [case[1:] for case in SINGLE_FAILURES],
    ids=[case[0] for case in SINGLE_FAILURES],
)
def test_one_failing_check_lists_exactly_its_sentence(
    overrides: dict[str, Any], sentence: str
) -> None:
    assert activation_blockers(passing_facts(**overrides)) == [sentence]


def test_every_sentence_has_a_failing_case() -> None:
    assert {case[2] for case in SINGLE_FAILURES} == set(ALL_SENTENCES)


def test_a_service_registrar_without_districts_is_blocked_but_not_otherwise() -> None:
    assert (
        activation_blockers(passing_facts(registers_services=False, area_districts_set=False)) == []
    )
    assert activation_blockers(
        passing_facts(registers_services=True, area_districts_set=False)
    ) == [DISTRICTS]


def test_email_is_checked_only_when_in_use() -> None:
    assert activation_blockers(passing_facts(email_in_use=False, email_sender_verified=False)) == []
    assert activation_blockers(passing_facts(email_in_use=True, email_sender_verified=False)) == [
        EMAIL
    ]


def test_the_agreement_is_checked_only_for_a_network_member() -> None:
    assert activation_blockers(passing_facts(network_member=False, agreement_accepted=False)) == []
    assert activation_blockers(passing_facts(network_member=True, agreement_accepted=False)) == [
        AGREEMENT
    ]


def test_a_tenant_with_nothing_done_lists_every_sentence_in_order() -> None:
    nothing = ActivationFacts(
        config_approved=False,
        time_zone=None,
        active_numbers_tested=0,
        email_in_use=True,
        email_sender_verified=False,
        first_admin_invited=False,
        entra_binding_verified=False,
        role_mappings=0,
        contact_kinds=frozenset(),
        retention_classes_set=frozenset(),
        references_recorded=frozenset(),
        wording_complete=False,
        registers_services=True,
        area_districts_set=False,
        network_member=True,
        agreement_accepted=False,
    )
    assert activation_blockers(nothing) == ALL_SENTENCES


def test_the_sentences_never_claim_an_approval_or_a_certification() -> None:
    for sentence in ALL_SENTENCES:
        lowered = sentence.lower()
        assert "approved" not in lowered.replace("configuration version approved", "")
        assert "certified" not in lowered


def test_activation_facts_have_no_defaults_and_are_frozen() -> None:
    assert all(
        f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        for f in dataclasses.fields(ActivationFacts)
    )
    assert len(dataclasses.fields(ActivationFacts)) == 16
    with pytest.raises(dataclasses.FrozenInstanceError):
        passing_facts().config_approved = False  # type: ignore[misc]


def test_the_facts_are_listed_in_the_decided_order() -> None:
    assert [f.name for f in dataclasses.fields(ActivationFacts)] == [
        "config_approved",
        "time_zone",
        "active_numbers_tested",
        "email_in_use",
        "email_sender_verified",
        "first_admin_invited",
        "entra_binding_verified",
        "role_mappings",
        "contact_kinds",
        "retention_classes_set",
        "references_recorded",
        "wording_complete",
        "registers_services",
        "area_districts_set",
        "network_member",
        "agreement_accepted",
    ]


FACT_VALUES = st.fixed_dictionaries(
    {
        "config_approved": st.one_of(st.booleans(), st.integers(0, 2), st.none()),
        "time_zone": st.sampled_from([None, "Europe/London", "UTC", 5]),
        "active_numbers_tested": st.one_of(st.integers(-1, 3), st.booleans(), st.text(max_size=2)),
        "email_in_use": st.one_of(st.booleans(), st.none(), st.integers(0, 1)),
        "email_sender_verified": st.one_of(st.booleans(), st.integers(0, 1)),
        "first_admin_invited": st.one_of(st.booleans(), st.integers(0, 1)),
        "entra_binding_verified": st.one_of(st.booleans(), st.integers(0, 1)),
        "role_mappings": st.one_of(st.integers(-1, 3), st.booleans()),
        "contact_kinds": st.frozensets(st.sampled_from([*ContactKind, "coordination-phone"])),
        "retention_classes_set": st.frozensets(st.sampled_from([*RetentionClass, "bookings"])),
        "references_recorded": st.frozensets(st.sampled_from(["dsa", "dpia", "dcb0160", "x"])),
        "wording_complete": st.one_of(st.booleans(), st.integers(0, 1)),
        "registers_services": st.one_of(st.booleans(), st.none()),
        "area_districts_set": st.one_of(st.booleans(), st.integers(0, 1)),
        "network_member": st.one_of(st.booleans(), st.none()),
        "agreement_accepted": st.one_of(st.booleans(), st.integers(0, 1)),
    }
)


@settings(max_examples=400, deadline=None)
@given(FACT_VALUES)
def test_property_blockers_are_a_deterministic_ordered_subset_and_empty_only_when_all_pass(
    values: dict[str, Any],
) -> None:
    facts = passing_facts(**values)
    blockers = activation_blockers(facts)
    assert blockers == activation_blockers(facts)
    assert [b for b in ALL_SENTENCES if b in blockers] == blockers
    exact = (
        values["config_approved"] is True
        and values["time_zone"] == "Europe/London"
        and type(values["active_numbers_tested"]) is int
        and values["active_numbers_tested"] >= 1
        and (values["email_in_use"] is False or values["email_sender_verified"] is True)
        and values["first_admin_invited"] is True
        and values["entra_binding_verified"] is True
        and type(values["role_mappings"]) is int
        and values["role_mappings"] >= 1
        and {k for k in values["contact_kinds"] if type(k) is ContactKind} >= {PHONE, CSO}
        and {k for k in values["retention_classes_set"] if type(k) is RetentionClass}
        == ALL_RETENTION
        and values["references_recorded"] >= {"dsa", "dpia", "dcb0160"}
        and values["wording_complete"] is True
        and (values["registers_services"] is False or values["area_districts_set"] is True)
        and (values["network_member"] is False or values["agreement_accepted"] is True)
    )
    assert (blockers == []) == exact


# ---------------------------------------------------------------- 22. configuration versions

CONFIG_LEGAL = (
    (C.DRAFT, C.PENDING_APPROVAL),
    (C.PENDING_APPROVAL, C.DRAFT),
    (C.PENDING_APPROVAL, C.CURRENT),
    (C.CURRENT, C.SUPERSEDED),
)
CONFIG_ILLEGAL = tuple(p for p in itertools.product(C, C) if p not in CONFIG_LEGAL)


@pytest.mark.parametrize(("current", "target"), CONFIG_LEGAL, ids=lambda s: s.value)
def test_a_legal_configuration_move_is_accepted(
    current: ConfigStatus, target: ConfigStatus
) -> None:
    assert transition_config(current, target) is target


@pytest.mark.parametrize(("current", "target"), CONFIG_ILLEGAL, ids=lambda s: s.value)
def test_every_other_configuration_move_is_refused(
    current: ConfigStatus, target: ConfigStatus
) -> None:
    with pytest.raises(InvalidTransition) as refused:
        transition_config(current, target)
    assert current.value in str(refused.value) and target.value in str(refused.value)


def test_a_current_version_cannot_go_back_to_draft_and_a_superseded_one_is_final() -> None:
    with pytest.raises(InvalidTransition):
        transition_config(C.CURRENT, C.DRAFT)
    for target in C:
        with pytest.raises(InvalidTransition):
            transition_config(C.SUPERSEDED, target)


@pytest.mark.parametrize("bad", ["draft", S.ACTIVE, None])
def test_a_configuration_status_is_checked_by_type(bad: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        transition_config(bad, C.CURRENT)
    assert refused.value.field == "current"
    with pytest.raises(ValidationFailed) as refused:
        transition_config(C.DRAFT, bad)
    assert refused.value.field == "target"


# ---------------------------------------------------------------- state machine as a whole

OPERATIONS = ("activate", "suspend", "resume", "start", "complete", "waived", "purge", "reopen")


def _apply(tenant: Tenant, op: str, now: datetime) -> Tenant:
    if op == "activate":
        return activate_tenant(tenant, passing_facts(), now)
    if op == "suspend":
        return suspend_tenant(tenant, SuspendMode.READ_ONLY, SuspendReason.OPERATOR_REQUEST, now)
    if op == "resume":
        return resume_tenant(tenant, now)
    if op == "start":
        return start_offboarding(tenant, now)
    if op == "complete":
        return complete_offboarding(tenant, now)
    if op == "waived":
        return complete_offboarding(tenant, now, waived=True)
    if op == "purge":
        return purge_tenant(tenant, now)
    return reopen_tenant(tenant)


@settings(max_examples=300, deadline=None)
@given(st.lists(st.tuples(st.sampled_from(OPERATIONS), st.integers(0, 40 * 24 * 60)), max_size=25))
def test_property_a_run_of_operations_only_follows_the_table_and_keeps_every_invariant(
    steps: list[tuple[str, int]],
) -> None:
    tenant = make_tenant(S.PROVISIONING)
    clock = T0 + DAY
    for op, minutes in steps:
        clock += timedelta(minutes=minutes)
        before = dataclasses.replace(tenant)
        try:
            after = _apply(tenant, op, clock)
        except DomainError:
            assert tenant == before  # a refusal changes nothing
            continue
        assert tenant == before  # the input is never changed
        assert (before.status, after.status) in LEGAL
        assert after == _apply(tenant, op, clock)  # deterministic
        assert after.epoch >= before.epoch
        assert after.id == before.id and after.created_at == before.created_at
        suspended = after.status is S.SUSPENDED
        assert (after.suspend_mode is not None) == suspended
        assert (after.suspend_reason is not None) == suspended
        assert (after.suspended_at is not None) == suspended
        assert (after.purged_at is not None) == (after.status is S.PURGED)
        tenant = after
    if tenant.status is S.PURGED:
        for op in OPERATIONS:
            with pytest.raises(DomainError):
                _apply(tenant, op, clock + 400 * DAY)


# ---------------------------------------------------------------- 23. nothing is echoed


def test_no_refusal_in_this_module_echoes_the_value_that_caused_it() -> None:
    offboarded = make_tenant(S.OFFBOARDED)
    probes: list[Any] = [
        lambda: transition_tenant(CANARY, S.ACTIVE),
        lambda: transition_tenant(S.ACTIVE, CANARY),
        lambda: transition_config(CANARY, C.CURRENT),
        lambda: suspend_tenant(make_tenant(S.ACTIVE), CANARY, SuspendReason.CONTRACT, T0 + 3 * DAY),
        lambda: number_assignable(CANARY, T0, T0),
        lambda: purge_tenant(
            make_tenant(S.OFFBOARDED, retention_hold_until=T0 + 900 * DAY), T0 + DAY * 70
        ),
        lambda: complete_offboarding(make_tenant(S.OFFBOARDING), T0 + 11 * DAY),
        lambda: activate_tenant(
            make_tenant(S.PROVISIONING), passing_facts(time_zone=CANARY), T0 + DAY
        ),
        lambda: offboarding_may_complete_at(make_tenant(S.ACTIVE, display_name=CANARY)),
        lambda: resume_tenant(make_tenant(S.ACTIVE, display_name=CANARY), T0 + 9 * DAY),
    ]
    for probe in probes:
        with pytest.raises(Exception) as refused:  # noqa: B017
            probe()
        assert "canary" not in str(refused.value)
    for blockers in (
        purge_blockers(offboarded, T0 + 90 * DAY, [CANARY], CANARY),
        activation_blockers(passing_facts(time_zone=CANARY)),
    ):
        assert all("canary" not in sentence for sentence in blockers)
