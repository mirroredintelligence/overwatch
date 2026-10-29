"""The pure parts of link access (L01, DEC-167): the CSRF token, the shape of an answer, the reply
policy's view of a link, and the judgement that keeps a Y from making an old figure current (H-31,
H-32). Everything that reads or writes is in tests/integration/application/test_link_access.py.
All values are synthetic: no patient data.
"""

import hashlib
import hmac
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.link_access import (
    ACTIONS,
    BAD_ATTEMPT_WINDOW,
    BAD_ATTEMPTS_PER_ADDRESS,
    CAPACITY_PURPOSE,
    LINK_CSRF_SECRET,
    LINK_PROMPT_MESSAGES,
    MAX_TOKEN_LENGTH,
    RENEW_WINDOW,
    RENEWALS_PER_WINDOW,
    REQUEST_WINDOW,
    REQUESTS_PER_WINDOW,
    LinkAction,
    LinkGone,
    LinkOutOfRange,
    LinkRequest,
    SendTheNumber,
    _token_hash,
    check_action,
    command_key,
    csrf_token,
    figure_of,
    iso_utc,
    judge,
    prompt_state,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportFlagReason,
    ReportSource,
    ReportType,
    ServiceCategory,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.reply_policy import (
    AskRecheck,
    NeedNumber,
    RecordConfirm,
    RecordNumber,
    RejectConfirmLimit,
    RejectLate,
)
from diucs.domain.rules.tokens import LinkTokenRecord

NOW = datetime(2026, 10, 23, 9, 5, tzinfo=UTC)
PROMPT_AT = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
REPLY_BY = PROMPT_AT + timedelta(minutes=30)
HASH_A = "a" * 64
HASH_B = "b" * 64
SECRET = b"link-csrf-secret-for-the-unit-tests"
TENANT_A = ScopeId.tenant("tenant-a")
TENANT_B = ScopeId.tenant("tenant-b")


def _profile(usual: tuple[int, int] = (0, 8)) -> ServiceProfile:
    return ServiceProfile(
        id="ucr-west",
        name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals in the next 2 hrs",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=usual,
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


def _report(
    at: datetime, value: int = 3, kind: ReportType = ReportType.NUMBER, ident: str = "r-1"
) -> CapacityReport:
    return CapacityReport(
        id=ident,
        service_id="ucr-west",
        value=value,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=at,
        source=ReportSource.TEXT,
        report_type=kind,
        derived_from=None if kind is ReportType.NUMBER else "r-0",
    )


def _record(token_hash: str = HASH_A) -> LinkTokenRecord:
    return LinkTokenRecord(
        token_hash=token_hash,
        purpose=CAPACITY_PURPOSE,
        about_id="c-1",
        phone_hash="ab" * 32,
        expires_at=REPLY_BY,
        used_at=None,
    )


def _link(record: LinkTokenRecord | None = None, scope: ScopeId = TENANT_A) -> LinkRequest:
    return LinkRequest(record=record or _record(), token="T" * 23, scope=scope, now=NOW)


# -- the names and numbers the page and the tests rely on ---------------------------------------


def test_the_csrf_secret_is_named_link_csrf() -> None:
    assert LINK_CSRF_SECRET == "link-csrf"


def test_the_capacity_purpose_is_the_one_a_prompt_issues() -> None:
    assert CAPACITY_PURPOSE == "capacity-reply"


def test_the_prompts_that_carry_a_link_are_c1_c2_and_c8() -> None:
    assert frozenset({"C1", "C2", "C8"}) == LINK_PROMPT_MESSAGES


def test_the_answers_a_link_takes_are_confirm_number_and_closed() -> None:
    assert frozenset({"confirm", "number", "closed"}) == ACTIONS


def test_the_rate_limits_are_pinned_by_their_values() -> None:
    assert (60, timedelta(minutes=1)) == (REQUESTS_PER_WINDOW, REQUEST_WINDOW)
    assert (20, timedelta(minutes=10)) == (BAD_ATTEMPTS_PER_ADDRESS, BAD_ATTEMPT_WINDOW)
    assert (20, timedelta(minutes=10)) == (RENEWALS_PER_WINDOW, RENEW_WINDOW)
    assert MAX_TOKEN_LENGTH == 64


# -- the CSRF token -------------------------------------------------------------------------------


def test_the_csrf_token_is_hmac_sha256_of_the_token_hash() -> None:
    expected = hmac.new(SECRET, HASH_A.encode("ascii"), hashlib.sha256).hexdigest()

    assert csrf_token(HASH_A, SECRET) == expected
    assert len(expected) == 64


def test_the_csrf_token_changes_with_the_link_and_with_the_secret() -> None:
    assert csrf_token(HASH_A, SECRET) != csrf_token(HASH_B, SECRET)
    assert csrf_token(HASH_A, SECRET) != csrf_token(HASH_A, SECRET + b"x")


@given(st.text(alphabet="0123456789abcdef", min_size=64, max_size=64), st.binary(min_size=1))
@settings(max_examples=200)
def test_the_csrf_token_is_stable_and_always_sixty_four_hex_digits(
    token_hash: str, secret: bytes
) -> None:
    first = csrf_token(token_hash, secret)

    assert first == csrf_token(token_hash, secret)
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")


# -- the replay key -------------------------------------------------------------------------------


def test_the_command_key_names_the_tenant_and_the_link() -> None:
    assert command_key(TENANT_A, _record(HASH_A)) == f"link:tenant-a:{HASH_A}"


def test_two_tenants_never_share_a_command_key_for_one_hash() -> None:
    assert command_key(TENANT_A, _record(HASH_A)) != command_key(TENANT_B, _record(HASH_A))
    assert command_key(TENANT_A, _record(HASH_A)) != command_key(TENANT_A, _record(HASH_B))


# -- the time of a page ----------------------------------------------------------------------------


def test_a_time_is_iso_8601_utc_with_a_z_and_whole_seconds() -> None:
    assert iso_utc(datetime(2026, 10, 23, 7, 15, 30, 999999, tzinfo=UTC)) == "2026-10-23T07:15:30Z"


def test_a_time_in_another_zone_is_written_in_utc() -> None:
    summer = timezone(timedelta(hours=1))

    assert iso_utc(datetime(2026, 10, 23, 8, 15, tzinfo=summer)) == "2026-10-23T07:15:00Z"


def test_no_time_is_none() -> None:
    assert iso_utc(None) is None


# -- the shape of an answer ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        LinkAction("confirm"),
        LinkAction("number", 0),
        LinkAction("number", 999),
        LinkAction("number", 40, confirm_out_of_range=True),
        LinkAction("closed"),
        LinkAction("closed", confirm_out_of_range=True),
    ],
)
def test_a_well_formed_answer_is_accepted(action: LinkAction) -> None:
    check_action(action)


@pytest.mark.parametrize(
    ("action", "field"),
    [
        (LinkAction("approve"), "action"),
        (LinkAction(""), "action"),
        (LinkAction("Confirm"), "action"),
        (LinkAction("number"), "value"),
        (LinkAction("number", -1), "value"),
        (LinkAction("number", 1000), "value"),
        (LinkAction("number", True), "value"),
        (LinkAction("number", 3.5), "value"),  # type: ignore[arg-type]
        (LinkAction("number", "3"), "value"),  # type: ignore[arg-type]
        (LinkAction("confirm", 3), "value"),
        (LinkAction("closed", 0), "value"),
        (LinkAction("number", 4, confirm_out_of_range="yes"), "confirmOutOfRange"),  # type: ignore[arg-type]
        (LinkAction("confirm", confirm_out_of_range=True), "confirmOutOfRange"),
    ],
)
def test_a_malformed_answer_is_refused_by_field_name(action: LinkAction, field: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_action(action)

    assert refused.value.field == field


@given(
    action=st.one_of(st.none(), st.integers(), st.text(), st.sampled_from(sorted(ACTIONS))),
    value=st.one_of(st.none(), st.integers(), st.floats(), st.text(), st.booleans()),
    out_of_range=st.one_of(st.booleans(), st.none(), st.integers(), st.text()),
)
@settings(max_examples=300)
def test_an_answer_is_accepted_or_refused_by_field_and_never_raises_anything_else(
    action: object, value: object, out_of_range: object
) -> None:
    answer = LinkAction(action, value, out_of_range)  # type: ignore[arg-type]
    try:
        check_action(answer)
    except ValidationFailed as refused:
        assert refused.field in {"action", "value", "confirmOutOfRange"}
        assert "token" not in refused.message
        return
    assert answer.action in ACTIONS
    if answer.action == "number":
        assert type(answer.value) is int and 0 <= answer.value <= 999
    else:
        assert answer.value is None
    assert type(answer.confirm_out_of_range) is bool


def test_a_closed_answer_sends_the_figure_zero_and_a_number_its_own() -> None:
    assert figure_of(LinkAction("closed")) == 0
    assert figure_of(LinkAction("number", 7)) == 7
    assert figure_of(LinkAction("number", 0)) == 0


# -- the reply policy's view of a link ------------------------------------------------------------


def test_a_link_is_a_prompt_that_closes_when_the_link_expires() -> None:
    latest = _report(datetime(2026, 10, 23, 7, 15, tzinfo=UTC), value=3)

    state = prompt_state(_link(), _profile((1, 6)), latest, 1, LinkAction("confirm"))

    assert state.service_id == "ucr-west"
    assert state.reply_by == REPLY_BY
    assert state.recorded_value == 3
    assert state.consecutive_confirms == 1
    assert state.last_accepted_at == latest.effective_at
    assert state.last_accepted_value == 3
    assert state.usual_range == (1, 6)
    assert state.letter is None


def test_a_link_with_no_figure_on_record_has_nothing_to_confirm() -> None:
    state = prompt_state(_link(), _profile(), None, 0, LinkAction("confirm"))

    assert state.recorded_value is None
    assert state.last_accepted_at is None
    assert state.last_accepted_value is None


@pytest.mark.parametrize(
    ("action", "pending"),
    [
        (LinkAction("number", 40), None),
        (LinkAction("number", 40, confirm_out_of_range=True), 40),
        (LinkAction("closed"), None),
        (LinkAction("closed", confirm_out_of_range=True), 0),
        (LinkAction("confirm"), None),
    ],
)
def test_a_figure_sent_with_confirm_out_of_range_is_the_second_sending_of_it(
    action: LinkAction, pending: int | None
) -> None:
    assert prompt_state(_link(), _profile(), None, 0, action).pending_out_of_range == pending


# -- what the policy and the hazards allow ------------------------------------------------------


def _figure(hours_before_prompt: float) -> CapacityReport:
    return _report(PROMPT_AT - timedelta(hours=hours_before_prompt))


def test_a_figure_inside_its_window_can_be_confirmed() -> None:
    decision = RecordConfirm()

    assert judge(decision, _profile(), _figure(1.75), PROMPT_AT, False) is decision


def test_a_figure_exactly_two_hours_old_at_the_prompt_can_be_confirmed() -> None:
    decision = RecordConfirm()

    assert judge(decision, _profile(), _figure(2), PROMPT_AT, False) is decision


def test_a_figure_older_than_two_hours_at_the_prompt_cannot_be_confirmed_h31() -> None:
    older = _report(PROMPT_AT - timedelta(hours=2, seconds=1))

    with pytest.raises(SendTheNumber) as refused:
        judge(RecordConfirm(), _profile(), older, PROMPT_AT, False)

    assert refused.value.reason == "stale"


def test_a_number_reported_since_the_prompt_cannot_be_confirmed_h32() -> None:
    with pytest.raises(SendTheNumber) as refused:
        judge(RecordConfirm(), _profile(), _figure(1), PROMPT_AT, True)

    assert refused.value.reason == "stale"


def test_a_confirmation_with_no_figure_on_record_is_never_recorded() -> None:
    with pytest.raises(SendTheNumber) as refused:
        judge(RecordConfirm(), _profile(), None, PROMPT_AT, False)

    assert refused.value.reason == "stale"


def test_the_policy_asking_for_the_number_is_passed_on() -> None:
    with pytest.raises(SendTheNumber) as refused:
        judge(NeedNumber(), _profile(), None, PROMPT_AT, False)

    assert refused.value.reason == "no-figure"


def test_a_third_y_in_a_row_is_refused_with_the_limit() -> None:
    with pytest.raises(SendTheNumber) as refused:
        judge(RejectConfirmLimit(), _profile(), _figure(1), PROMPT_AT, False)

    assert refused.value.reason == "limit"


def test_a_figure_outside_the_usual_range_is_refused_with_the_range() -> None:
    with pytest.raises(LinkOutOfRange) as refused:
        judge(AskRecheck(40), _profile((2, 9)), _figure(1), PROMPT_AT, False)

    assert (refused.value.usual_min, refused.value.usual_max) == (2, 9)


def test_a_late_answer_is_an_expired_link() -> None:
    with pytest.raises(LinkGone) as refused:
        judge(RejectLate(NOW), _profile(), _figure(1), PROMPT_AT, False)

    assert refused.value.state == "expired"


def test_a_number_is_recorded_whatever_the_age_of_the_figure() -> None:
    decision = RecordNumber(5, False, None)

    assert judge(decision, _profile(), _figure(9), PROMPT_AT, True) is decision
    assert judge(decision, _profile(), None, PROMPT_AT, False) is decision


def test_a_number_confirmed_out_of_range_keeps_its_flag() -> None:
    decision = RecordNumber(40, False, ReportFlagReason.OUT_OF_RANGE_TWICE)

    assert judge(decision, _profile(), _figure(1), PROMPT_AT, False).flag is decision.flag


@given(
    age=st.integers(min_value=-3 * 3600, max_value=6 * 3600),
    number_since=st.booleans(),
)
@settings(max_examples=300)
def test_a_y_is_recorded_only_for_a_figure_no_older_than_two_hours_with_no_number_since(
    age: int, number_since: bool
) -> None:
    """H-31 and H-32 as a property: whatever the age of the figure at the prompt and whatever was
    reported since, a Y is recorded exactly when the figure is no older than two hours and no
    number has been written after the prompt."""
    decision = RecordConfirm()
    latest = _report(PROMPT_AT - timedelta(seconds=age))
    allowed = age <= 2 * 3600 and not number_since

    try:
        outcome = judge(decision, _profile(), latest, PROMPT_AT, number_since)
    except SendTheNumber as refused:
        assert not allowed
        assert refused.reason == "stale"
    else:
        assert allowed
        assert outcome is decision


def test_a_link_request_holds_what_it_was_found_with() -> None:
    link = _link()

    assert replace(link, now=NOW + timedelta(seconds=1)).now > link.now
    assert link.scope == TENANT_A


# -- the token hash -------------------------------------------------------------------------


def test_a_secret_that_cannot_hash_a_token_is_a_fault_and_not_an_unknown_link() -> None:
    """Text that cannot be a token is an unknown link; a store with no usable secret is a
    configuration fault, which must not look like one."""
    broken = FixedSecretStore({"link-token": b""})

    with pytest.raises(ValidationFailed) as fault:
        _token_hash("A" * 23, broken)

    assert fault.value.field == "secret"


@pytest.mark.parametrize("token", ["", "not a token", "a" * 65, "é" * 23, "a/b"])
def test_text_that_cannot_be_a_token_has_no_hash(token: str) -> None:
    assert _token_hash(token, FixedSecretStore({"link-token": SECRET})) is None


def test_a_token_has_the_keyed_hash_of_the_tokens_module() -> None:
    expected = hmac.new(SECRET, b"A" * 23, hashlib.sha256).hexdigest()

    assert _token_hash("A" * 23, FixedSecretStore({"link-token": SECRET})) == expected
