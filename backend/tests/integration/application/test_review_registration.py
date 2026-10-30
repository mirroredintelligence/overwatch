"""Integration tests for reviewing a registration (U28), against the real Neo4j the harness starts.
A submitted registration is seeded in Neo4j; each assertion reads back through a fresh unit of work
or the harness helpers. The numbers are sample values: there is no patient data and no real phone
number.

NOT RUN in the build wave (no Neo4j in the builder's environment, build-wave rules): the batch
verification run proves them.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
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
    PractitionerRoleCode,
    RegistrationStatus,
    Role,
    ScopeFlag,
    ServiceCategory,
)
from diucs.domain.errors import InvalidTransition, ValidationFailed
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Answer, CallBackResult, Registration, ScopeEntry
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, read_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
SERVICE_ID = "svc-ucr-west"
APPLICANT_ROLE = "role-applicant"
REGISTER_NUMBER = "01305 123456"
INVITED_MOBILE = "07700 900123"
SECRETS = FixedSecretStore({PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab"})
HASHER = HmacPhoneHasher(SECRETS)
AREA = districts_in_ranges(("DT", 1, 11), ("BH", 1, 31))
LEAD = Actor(Role.LEAD, "prac-lead", None, "web", frozenset(), tenant_id=ACTOR_TENANT)
GOOD = Lookups(True, True, "COMMUNITY RESPONSE LTD", "PILOT-SAMPLE", True, "DT4", NOW)
STEPS: dict[str, Any] = {
    "organisation": OrganisationStep(
        name="Community Response Ltd",
        ods_code="RXX01",
        org_type="nhs-trust",
        contact_name="Sam Patel",
        contact_email="sam.patel@example.org",
    ),
    "location": LocationStep(
        fixed_site=True,
        postcode="DT4 8XX",
        address="1 Sample Road, Weymouth",
        site_name="Sample Ward",
        site_type="ward",
        open_24h=True,
    ),
    "service": ServiceStep(
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
    ),
    "reporting": ReportingStep(
        measure="referrals-acceptable",
        usual_low=0,
        usual_high=8,
        cadence="every-2-hrs",
        channel="text",
        holder_name="Duty coordinator",
    ),
    "api": ApiStep(wanted=False),
}


class Rig:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self.uow_factory = uow_factory
        clock = FixedClock(NOW)
        kwargs: dict[str, Any] = {"area_districts_for": lambda scope: AREA}
        self.start = StartReview(uow_factory, HASHER, clock, **kwargs)
        self.explain = ExplainCheck(uow_factory, HASHER, clock, **kwargs)
        self.callback = RecordCallBack(
            uow_factory, HASHER, SECRETS, SequentialIds("cb"), clock, **kwargs
        )
        self.scope = RecordScopeDecision(uow_factory, HASHER, clock, **kwargs)
        self.status = GetReviewStatus(uow_factory, HASHER, clock, **kwargs)

    async def reg(self) -> Registration:
        async with self.uow_factory() as uow:
            found = await uow.registrations.get("reg-1")
        assert found is not None
        return found


async def _seed(uow_factory: UnitOfWorkFactory, owner_email: str = "owner@example.org") -> Rig:
    steps = dict(STEPS)
    steps["service"] = replace(STEPS["service"], owner_email=owner_email)
    draft = {key: encode_step(step) for key, step in steps.items()}
    draft[LOOKUPS_STEP] = encode_lookups(GOOD)
    async with uow_factory() as uow:
        await uow.scope.save_entry(
            ScopeEntry(
                service_id=SERVICE_ID,
                name="UCR West",
                category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                flag=ScopeFlag.IN_PILOT,
                date=date(2026, 10, 29),
            )
        )
        for practitioner_id, phone_hash in (
            ("prac-applicant", HASHER.hash(INVITED_MOBILE)),
            ("prac-lead", None),
        ):
            await uow.people.save_practitioner(
                Practitioner(
                    id=practitioner_id, active=True, display_name="Sample", phone_hash=phone_hash
                )
            )
        await uow.people.save_role(
            PractitionerRole(
                id=APPLICANT_ROLE,
                practitioner_id="prac-applicant",
                service_id=SERVICE_ID,
                code=PractitionerRoleCode.DUTY_MANAGER,
                active=True,
                channel=None,
                period_start=NOW,
            )
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-lead",
                practitioner_id="prac-lead",
                service_id=None,
                code=PractitionerRoleCode.SHIFT_LEAD,
                active=True,
                channel=None,
                period_start=NOW,
            )
        )
        await uow.contacts.put_phone(APPLICANT_ROLE, "+447700900123")
        await uow.registrations.add(
            Registration(
                id="reg-1",
                service_id=SERVICE_ID,
                status=RegistrationStatus.SUBMITTED,
                requester_role_id=APPLICANT_ROLE,
                owner_role_id=None,
                created_at=NOW,
                last_modified=NOW,
                submitted_at=NOW,
                draft=draft,
            )
        )
        await uow.commit()
    return Rig(uow_factory)


@pytest.fixture(autouse=True)
async def _graph(neo4j_driver: AsyncDriver, clean_graph: None) -> None:
    await ensure_audit_head(neo4j_driver)


async def test_starting_a_review_stores_in_review_and_a_second_start_is_an_invalid_transition(
    uow_factory: UnitOfWorkFactory,
) -> None:
    rig = await _seed(uow_factory)

    await rig.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))

    stored = await rig.reg()
    assert stored.status is RegistrationStatus.IN_REVIEW
    assert stored.owner_role_id == "role-lead"
    with pytest.raises(InvalidTransition):
        await rig.start.execute(StartReviewCommand("start-2", LEAD, "reg-1"))


async def test_an_owner_email_at_a_free_mail_domain_fails_and_an_explanation_makes_it_ok(
    uow_factory: UnitOfWorkFactory,
) -> None:
    rig = await _seed(uow_factory, owner_email="owner@gmail.com")
    await rig.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))

    before = await rig.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))
    email = next(check for check in before.checks if check.name == CHECK_EMAIL)
    assert email.passed is False
    assert email.message == "Criteria owner email is not an organisation address"
    assert before.automatic_ok is False

    await rig.explain.execute(
        ExplainCheckCommand("ex-1", LEAD, "reg-1", CHECK_EMAIL, "Shared trust mailbox")
    )

    after = await rig.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))
    assert after.automatic_ok is True
    assert (await rig.reg()).checks.automatic_ok is True


async def _provenance(driver: AsyncDriver) -> list[dict[str, Any]]:
    async def work(tx: Any) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (p:Provenance {tenantId: $tenant})-[:TARGET]->(t:AuditRef {tenantId: $tenant}) "
            "RETURN p.activity AS activity, t.id AS target, properties(p) AS props"
        )
        return await result.data()

    return await read_tx(driver, work)


async def test_a_confirmed_call_back_is_a_provenance_with_a_target_and_without_the_number(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    rig = await _seed(uow_factory)
    await rig.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))

    await rig.callback.execute(
        RecordCallBackCommand(
            "cb-1", LEAD, "reg-1", REGISTER_NUMBER, "Duty manager", CallBackResult.CONFIRMED
        )
    )

    found = [row for row in await _provenance(neo4j_driver) if row["activity"] == "call-back"]
    assert [row["target"] for row in found] == ["reg-1"]
    props = found[0]["props"]
    assert props["roleSpokenTo"] == "Duty manager"
    assert props["result"] == "confirmed"
    assert all("01305" not in str(value) for value in props.values())
    status = await rig.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))
    assert "Call-back done" not in status.missing


async def test_a_call_back_without_a_role_is_refused_and_adds_no_provenance(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    rig = await _seed(uow_factory)
    await rig.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))
    before = await count_nodes(neo4j_driver, "Provenance")

    with pytest.raises(ValidationFailed):
        await rig.callback.execute(
            RecordCallBackCommand(
                "cb-1", LEAD, "reg-1", REGISTER_NUMBER, "", CallBackResult.CONFIRMED
            )
        )

    assert await count_nodes(neo4j_driver, "Provenance") == before


async def test_a_scope_of_later_needs_a_reason_and_in_pilot_is_stored(
    uow_factory: UnitOfWorkFactory,
) -> None:
    rig = await _seed(uow_factory)
    await rig.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))
    answers = ScopeAnswers(Answer.YES, Answer.YES, Answer.YES, Answer.YES)

    with pytest.raises(ValidationFailed):
        await rig.scope.execute(
            RecordScopeDecisionCommand("sc-1", LEAD, "reg-1", answers, ScopeFlag.LATER, "")
        )
    await rig.scope.execute(
        RecordScopeDecisionCommand("sc-2", LEAD, "reg-1", answers, ScopeFlag.IN_PILOT, "")
    )

    assert (await rig.reg()).checks.scope is ScopeFlag.IN_PILOT


async def test_the_criteria_second_approval_is_missing_until_the_criteria_are_approved(
    uow_factory: UnitOfWorkFactory,
) -> None:
    rig = await _seed(uow_factory)
    await rig.start.execute(StartReviewCommand("start-1", LEAD, "reg-1"))

    status = await rig.status.execute(GetReviewStatusQuery(LEAD, "reg-1"))

    assert "Criteria second approval" in status.missing
