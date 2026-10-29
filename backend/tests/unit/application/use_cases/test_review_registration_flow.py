"""StartReview, ExplainCheck, RecordCallBack, RecordScopeDecision and GetReviewStatus against
recording stand-ins for their ports (U28): the order of the calls, what is written and what is not,
and that the number called never reaches the graph's records. What is really stored, read back from
Neo4j, is in tests/integration/application/test_review_registration.py. Sample values only."""

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.use_cases.registration_draft import (
    ApiStep,
    LocationStep,
    OrganisationStep,
    ReportingStep,
    ServiceStep,
    encode_step,
)
from diucs.application.use_cases.registration_submit import LOOKUPS_STEP, Lookups, encode_lookups
from diucs.application.use_cases.review_registration import (
    CHECK_EMAIL,
    NOTES_STEP,
    ExplainCheck,
    ExplainCheckCommand,
    GetReviewStatus,
    GetReviewStatusQuery,
    RecordCallBack,
    RecordCallBackCommand,
    RecordScopeDecision,
    RecordScopeDecisionCommand,
    ScopeAnswers,
    StartReview,
    StartReviewCommand,
    districts_in_ranges,
)
from diucs.domain.codes import (
    CriteriaStatus,
    PractitionerRoleCode,
    RegistrationStatus,
    Role,
    ScopeFlag,
)
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Answer, CallBackResult, Registration
from tests.support.actors import ACTOR_TENANT
from tests.support.registration_rig import StubUnits

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
SERVICE_ID = "svc-ucr-west"
APPLICANT_ROLE = "role-applicant"
REGISTER_NUMBER = "01305 123456"
SECRETS = FixedSecretStore({PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab"})
HASHER = HmacPhoneHasher(SECRETS)
INVITED_MOBILE = "07700 900123"
AREA = districts_in_ranges(("DT", 1, 11), ("BH", 1, 31))
LEAD = Actor(Role.LEAD, "prac-lead", None, "web", frozenset(), tenant_id=ACTOR_TENANT)
ADVISOR = replace(LEAD, role=Role.ADVISOR)
ORG = OrganisationStep(
    name="Community Response Ltd",
    ods_code="RXX01",
    org_type="nhs-trust",
    contact_name="Sam Patel",
    contact_email="sam.patel@example.org",
    contact_phone="01305 000111",
)
SITE = LocationStep(
    fixed_site=True,
    postcode="DT4 8XX",
    address="1 Sample Road, Weymouth",
    site_name="Sample Ward",
    site_type="ward",
    open_24h=True,
)
SERVICE = ServiceStep(
    service_name="UCR West",
    category="urgent-community-response",
    referral_methods="phone",
    spoa_phone="01305 123400",
    accepting_days="mon,tue",
    accepting_start="08:00",
    accepting_end="20:00",
    needs="frailty",
    age_min=18,
    no_age_limit=True,
    no_exclusions=True,
    owner_role="Clinical lead, UCR",
    owner_email="owner@example.org",
    review_by=date(2027, 1, 1),
    districts="DT4",
)
REPORTING = ReportingStep(
    measure="referrals-acceptable",
    usual_low=0,
    usual_high=8,
    cadence="every-2-hrs",
    channel="text",
    holder_name="Duty coordinator",
)
GOOD = Lookups(True, True, "COMMUNITY RESPONSE LTD", "PILOT-SAMPLE", True, "DT4", NOW)
ANSWERS = ScopeAnswers(Answer.YES, Answer.YES, Answer.YES, Answer.YES)


class World:
    def __init__(
        self,
        status: RegistrationStatus = RegistrationStatus.SUBMITTED,
        *,
        owner_email: str = "owner@example.org",
    ) -> None:
        self.units = StubUnits()
        self.clock = FixedClock(NOW)
        self.ids = SequentialIds("id")
        steps = {
            "organisation": ORG,
            "location": SITE,
            "service": replace(SERVICE, owner_email=owner_email),
            "reporting": REPORTING,
            "api": ApiStep(wanted=False),
        }
        draft: dict[str, dict[str, Any]] = {k: encode_step(v) for k, v in steps.items()}
        draft[LOOKUPS_STEP] = encode_lookups(GOOD)
        self.units.registrations.held["reg-1"] = Registration(
            id="reg-1",
            service_id=SERVICE_ID,
            status=status,
            requester_role_id=APPLICANT_ROLE,
            owner_role_id=None,
            created_at=NOW,
            last_modified=NOW,
            submitted_at=NOW,
            draft=draft,
        )
        self.units.people.practitioners["prac-applicant"] = Practitioner(
            id="prac-applicant",
            active=True,
            display_name="Applicant",
            phone_hash=HASHER.hash(INVITED_MOBILE),
        )
        self.units.people.roles[APPLICANT_ROLE] = PractitionerRole(
            id=APPLICANT_ROLE,
            practitioner_id="prac-applicant",
            service_id=SERVICE_ID,
            code=PractitionerRoleCode.DUTY_MANAGER,
            active=True,
            channel=None,
            period_start=NOW,
        )
        self.units.people.roles["role-lead"] = PractitionerRole(
            id="role-lead",
            practitioner_id="prac-lead",
            service_id=None,
            code=PractitionerRoleCode.SHIFT_LEAD,
            active=True,
            channel=None,
            period_start=NOW,
        )
        self.units.contacts.phones[APPLICANT_ROLE] = "+447700900123"
        kwargs: dict[str, Any] = {"area_districts_for": lambda scope: AREA}
        self.start = StartReview(self.units, HASHER, self.clock, **kwargs)
        self.explain = ExplainCheck(self.units, HASHER, self.clock, **kwargs)
        self.callback = RecordCallBack(self.units, HASHER, SECRETS, self.ids, self.clock, **kwargs)
        self.scope = RecordScopeDecision(self.units, HASHER, self.clock, **kwargs)
        self.status = GetReviewStatus(self.units, HASHER, self.clock, **kwargs)

    def registration(self) -> Registration:
        return self.units.registrations.held["reg-1"]

    async def started(self) -> None:
        await self.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))

    def call(self, **changes: Any) -> RecordCallBackCommand:
        values: dict[str, Any] = {
            "idempotency_key": "cb-1",
            "actor": LEAD,
            "registration_id": "reg-1",
            "number_called": REGISTER_NUMBER,
            "role_spoken_to": "Duty manager",
            "result": CallBackResult.CONFIRMED,
        }
        values.update(changes)
        return RecordCallBackCommand(**values)

    def decide(self, **changes: Any) -> RecordScopeDecisionCommand:
        values: dict[str, Any] = {
            "idempotency_key": "sc-1",
            "actor": LEAD,
            "registration_id": "reg-1",
            "answers": ANSWERS,
            "decision": ScopeFlag.IN_PILOT,
            "reason": "",
        }
        values.update(changes)
        return RecordScopeDecisionCommand(**values)


# Start review


async def test_starting_a_review_moves_the_registration_to_in_review_under_the_lead() -> None:
    world = World()

    result = await world.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))

    assert result.status is RegistrationStatus.IN_REVIEW
    assert result.reviewer_role_id == "role-lead"
    stored = world.registration()
    assert stored.status is RegistrationStatus.IN_REVIEW
    assert stored.owner_role_id == "role-lead"
    assert stored.last_modified == NOW
    assert world.units.commits == 1
    assert len(world.units.audit.entries) == 1
    assert world.units.audit.entries[0].use_case == "StartReview"


async def test_a_second_start_is_an_invalid_transition_and_writes_nothing() -> None:
    world = World()
    await world.started()
    writes = list(world.units.writes.names)

    with pytest.raises(InvalidTransition):
        await world.start.execute(StartReviewCommand("start-2", LEAD, "reg-1"))

    assert world.units.writes.names == writes


@pytest.mark.parametrize(
    "status", [RegistrationStatus.INVITED, RegistrationStatus.DRAFT, RegistrationStatus.APPROVED]
)
async def test_a_registration_that_is_not_submitted_cannot_be_started(
    status: RegistrationStatus,
) -> None:
    world = World(status)

    with pytest.raises(InvalidTransition):
        await world.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))

    assert world.units.writes.names == []


async def test_only_the_lead_may_start_and_an_unknown_registration_is_not_found() -> None:
    world = World()

    with pytest.raises(NotAllowed):
        await world.start.execute(StartReviewCommand("start-1", ADVISOR, "reg-1"))
    with pytest.raises(NotFound):
        await world.start.execute(StartReviewCommand("start-1", LEAD, "reg-unknown"))

    assert world.units.writes.names == []


async def test_a_lead_with_no_shift_lead_post_cannot_start() -> None:
    world = World()
    del world.units.people.roles["role-lead"]

    with pytest.raises(NotAllowed):
        await world.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))

    assert world.units.writes.names == []


async def test_starting_stores_whether_the_automatic_checks_are_ok() -> None:
    good = World()
    await good.started()
    assert good.registration().checks.automatic_ok is True

    free_mail = World(owner_email="owner@gmail.com")
    await free_mail.started()
    assert free_mail.registration().checks.automatic_ok is False


async def test_the_same_start_key_twice_is_one_start() -> None:
    world = World()

    first = await world.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))
    second = await world.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))

    assert second == first
    assert len(world.units.audit.entries) == 1


# Explain a check


async def test_explaining_the_failed_email_check_makes_the_automatic_checks_ok() -> None:
    world = World(owner_email="owner@gmail.com")
    await world.started()
    assert world.registration().checks.automatic_ok is False

    result = await world.explain.execute(
        ExplainCheckCommand("ex-1", LEAD, "reg-1", CHECK_EMAIL, "Shared trust mailbox")
    )

    assert result.automatic_ok is True
    assert world.registration().checks.automatic_ok is True
    assert world.registration().draft[NOTES_STEP] == {CHECK_EMAIL: "Shared trust mailbox"}
    status = await world.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))
    assert status.automatic_ok is True
    email = next(check for check in status.checks if check.name == CHECK_EMAIL)
    assert (email.passed, email.ok, email.explained_note) == (False, True, "Shared trust mailbox")


async def test_a_check_that_passed_or_does_not_exist_cannot_be_explained() -> None:
    world = World()
    await world.started()
    writes = list(world.units.writes.names)

    with pytest.raises(Conflict):
        await world.explain.execute(
            ExplainCheckCommand("ex-1", LEAD, "reg-1", CHECK_EMAIL, "Not needed")
        )
    with pytest.raises(ValidationFailed) as raised:
        await world.explain.execute(
            ExplainCheckCommand("ex-2", LEAD, "reg-1", "no-such-check", "Note")
        )

    assert raised.value.field == "check_name"
    assert world.units.writes.names == writes


@pytest.mark.parametrize("note", ["", "   ", "x" * 501, "Ring DT4 8XX about it"])
async def test_a_note_must_be_present_short_and_free_of_patient_data(note: str) -> None:
    world = World(owner_email="owner@gmail.com")
    await world.started()
    writes = list(world.units.writes.names)

    with pytest.raises(ValidationFailed) as raised:
        await world.explain.execute(ExplainCheckCommand("ex-1", LEAD, "reg-1", CHECK_EMAIL, note))

    assert raised.value.field == "note"
    assert world.units.writes.names == writes


async def test_a_check_can_be_explained_only_while_the_registration_is_in_review() -> None:
    world = World(RegistrationStatus.SUBMITTED, owner_email="owner@gmail.com")

    with pytest.raises(InvalidTransition):
        await world.explain.execute(
            ExplainCheckCommand("ex-1", LEAD, "reg-1", CHECK_EMAIL, "Shared mailbox")
        )

    assert world.units.writes.names == []


# Call-back


async def test_a_confirmed_call_back_records_a_provenance_and_confirms_the_check() -> None:
    world = World()
    await world.started()

    result = await world.callback.execute(world.call())

    assert result.callback_confirmed is True
    assert world.registration().checks.callback_confirmed is True
    assert len(world.units.audit.provenance) == 1
    record = world.units.audit.provenance[0]
    assert record["activity"] == "call-back"
    assert record["target_type"] == "Task"
    assert record["target_id"] == "reg-1"
    assert record["agent_id"] == "prac-lead"
    assert record["agent_role"] is Role.LEAD
    assert record["extra"]["roleSpokenTo"] == "Duty manager"
    assert record["extra"]["result"] == "confirmed"
    status = await world.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))
    assert "Call-back done" not in status.missing


async def test_the_number_called_is_kept_only_in_the_contact_store() -> None:
    world = World()
    await world.started()

    await world.callback.execute(world.call())

    record = world.units.audit.provenance[0]
    callback_id = record["extra"]["callbackId"]
    assert world.units.contacts.phones[f"callback-{callback_id}"] == REGISTER_NUMBER
    everything = repr((record, world.units.audit.entries, world.registration()))
    for form in ("01305 123456", "01305123456", "+441305123456"):
        assert form not in everything
    assert len(record["extra"]["numberHash"]) == 64


async def test_a_call_back_without_a_role_is_refused_and_no_provenance_is_added() -> None:
    world = World()
    await world.started()

    for role in ("", "   "):
        with pytest.raises(ValidationFailed) as raised:
            await world.callback.execute(world.call(role_spoken_to=role))
        assert raised.value.field == "role_spoken_to"

    assert world.units.audit.provenance == []


async def test_a_no_answer_needs_no_role_and_does_not_confirm() -> None:
    world = World()
    await world.started()

    result = await world.callback.execute(
        world.call(result=CallBackResult.NO_ANSWER, role_spoken_to="")
    )

    assert result.callback_confirmed is False
    assert world.registration().checks.callback_confirmed is False
    assert "roleSpokenTo" not in world.units.audit.provenance[0]["extra"]


async def test_a_later_not_confirmed_call_back_withdraws_the_confirmation() -> None:
    world = World()
    await world.started()
    await world.callback.execute(world.call())

    await world.callback.execute(
        world.call(idempotency_key="cb-2", result=CallBackResult.NOT_CONFIRMED)
    )

    assert world.registration().checks.callback_confirmed is False
    assert len(world.units.audit.provenance) == 2


@pytest.mark.parametrize("applicants_number", ["07700 900123", "01305 000111", "01305 123400"])
async def test_the_applicants_own_numbers_cannot_be_the_number_called(
    applicants_number: str,
) -> None:
    world = World()
    await world.started()

    with pytest.raises(ValidationFailed) as raised:
        await world.callback.execute(world.call(number_called=applicants_number))

    assert raised.value.field == "number_called"
    assert world.units.audit.provenance == []


async def test_a_call_back_is_recorded_only_while_in_review_and_only_by_the_lead() -> None:
    world = World()
    with pytest.raises(InvalidTransition):
        await world.callback.execute(world.call())
    await world.started()
    with pytest.raises(NotAllowed):
        await world.callback.execute(world.call(actor=ADVISOR))

    assert world.units.audit.provenance == []


async def test_the_same_call_back_key_twice_records_one_provenance() -> None:
    world = World()
    await world.started()

    first = await world.callback.execute(world.call())
    second = await world.callback.execute(world.call())

    assert second == first
    assert len(world.units.audit.provenance) == 1
    with pytest.raises(Conflict):
        await world.callback.execute(world.call(role_spoken_to="Someone else"))


# Scope decision


async def test_an_in_pilot_decision_is_stored_with_its_answers_in_a_provenance() -> None:
    world = World()
    await world.started()

    result = await world.scope.execute(world.decide())

    assert result.decision is ScopeFlag.IN_PILOT
    assert world.registration().checks.scope is ScopeFlag.IN_PILOT
    record = world.units.audit.provenance[0]
    assert record["activity"] == "scope-decision"
    assert record["target_id"] == "reg-1"
    assert record["extra"]["decision"] == "in-pilot"
    assert record["extra"]["onDorsetPathway"] == "yes"
    assert record["extra"]["takesSpoaReferrals"] == "yes"
    assert record["extra"]["canReport"] == "yes"
    assert record["extra"]["categoryOnPilotList"] == "yes"
    status = await world.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))
    assert "Scope decided: in pilot" not in status.missing


@pytest.mark.parametrize("decision", [ScopeFlag.LATER, ScopeFlag.OUT_OF_SCOPE])
async def test_a_decision_other_than_in_pilot_needs_a_reason(decision: ScopeFlag) -> None:
    world = World()
    await world.started()

    for reason in ("", "   "):
        with pytest.raises(ValidationFailed) as raised:
            await world.scope.execute(world.decide(decision=decision, reason=reason))
        assert raised.value.field == "reason"
    assert world.units.audit.provenance == []

    result = await world.scope.execute(world.decide(decision=decision, reason="Not ready yet"))

    assert result.decision is decision
    assert world.registration().checks.scope is decision
    assert world.units.audit.provenance[0]["extra"]["reason"] == "Not ready yet"
    status = await world.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))
    assert "Scope decided: in pilot" in status.missing


async def test_a_reason_with_patient_data_is_refused_and_a_decision_needs_review_and_the_lead() -> (
    None
):
    world = World()
    with pytest.raises(InvalidTransition):
        await world.scope.execute(world.decide())
    await world.started()
    with pytest.raises(ValidationFailed):
        await world.scope.execute(
            world.decide(decision=ScopeFlag.LATER, reason="Patient at DT4 8XX")
        )
    with pytest.raises(NotAllowed):
        await world.scope.execute(world.decide(actor=ADVISOR))

    assert world.units.audit.provenance == []


# Status


async def test_the_status_lists_what_is_missing_until_each_part_is_done() -> None:
    world = World()
    await world.started()

    status = await world.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))

    assert status.missing == (
        "Call-back done",
        "Scope decided: in pilot",
        "Criteria second approval",
    )
    assert status.automatic_ok is True
    assert [check.passed for check in status.checks] == [True] * 5
    assert status.status is RegistrationStatus.IN_REVIEW


async def test_the_criteria_approval_is_missing_until_the_service_has_a_current_version() -> None:
    world = World()
    await world.started()
    await world.callback.execute(world.call())
    await world.scope.execute(world.decide())
    before = await world.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))
    assert before.missing == ("Criteria second approval",)

    world.units.criteria.current[SERVICE_ID] = ServiceCriteria(
        id="crit-1",
        service_id=SERVICE_ID,
        version=1,
        status=CriteriaStatus.CURRENT,
        age_min=18,
        age_max=None,
        districts=frozenset({"DT4"}),
        accepts=frozenset(),
        excludes=frozenset(),
        review_by=date(2027, 1, 1),
        owner_role_id="role-owner",
    )
    after = await world.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))

    assert after.missing == ()
    assert after.criteria_approved is True


async def test_the_status_re_runs_the_checks_so_a_changed_number_is_seen() -> None:
    world = World()
    await world.started()
    world.units.contacts.phones[APPLICANT_ROLE] = "07700 900999"

    status = await world.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))

    assert status.automatic_ok is False
    assert "Automatic checks passed or explained" in status.missing


async def test_the_status_is_read_only_and_for_the_lead() -> None:
    world = World()
    await world.started()
    writes = list(world.units.writes.names)

    await world.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))
    with pytest.raises(NotAllowed):
        await world.status.execute(GetReviewStatusQuery(ADVISOR, "reg-1"))
    with pytest.raises(NotFound):
        await world.status.execute(GetReviewStatusQuery(LEAD, "reg-unknown"))

    assert world.units.writes.names == writes
