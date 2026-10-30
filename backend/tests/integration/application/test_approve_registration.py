"""Integration tests for the approval steps of a registration (U29), against the real Neo4j.

The registration is the sample one of the U28 review tests (SERVICE_ID, the applicant's role and
phone, the lead). It is started for review by StartReview. Where a test needs an approved
registration, the approved status is stored directly (the repository stores what it is given), since
approval itself needs a criteria version that these tests do not seed. Sample values only.
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.approve_registration import (
    ApproveRegistration,
    GetRegistrationRecord,
    NotApproveRegistration,
    NoteCommand,
    RecordTestAnswer,
    RecordTestAnswerCommand,
    RegistrationDecisionCommand,
    ReopenRegistration,
    SendBackRegistration,
    SetServiceLive,
)
from diucs.application.use_cases.review_registration import StartReview, StartReviewCommand
from diucs.application.work import SCHEDULED, WorkKind
from diucs.domain.codes import RegistrationStatus, Role
from diucs.domain.errors import NotAllowed, ValidationFailed
from tests.integration.application.test_review_registration import (
    AREA,
    HASHER,
    LEAD,
    NOW,
    SERVICE_ID,
    _seed,
)
from tests.support.actors import ACTOR_TENANT
from tests.support.booking_rig import sealer
from tests.support.link_rig import ucr_west

pytestmark = pytest.mark.asyncio(loop_scope="session")

REG = "reg-1"
APPLICANT_PHONE = "+447700900123"
REPORTER = Actor(Role.REPORTER, None, None, "text", frozenset({SERVICE_ID}), tenant_id=ACTOR_TENANT)
STRANGER_PHONE_HASH = HASHER.hash("+447700999999")
PHONE_HASH = HASHER.hash(APPLICANT_PHONE)


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 29, hour, minute, tzinfo=UTC)


def approve(uow_factory: UnitOfWorkFactory, when: datetime) -> ApproveRegistration:
    return ApproveRegistration(
        uow_factory,
        FixedClock(when),
        SequentialIds("ap"),
        sealer(),
        phone_hasher=HASHER,
        area_districts_for=lambda scope: AREA,
    )


async def start_review(uow_factory: UnitOfWorkFactory) -> None:
    await StartReview(
        uow_factory,
        HASHER,
        FixedClock(NOW),
        area_districts_for=lambda scope: AREA,
    ).execute(StartReviewCommand(idempotency_key="start-1", actor=LEAD, registration_id=REG))


async def registration_status(uow_factory: UnitOfWorkFactory) -> RegistrationStatus:
    async with uow_factory() as uow:
        stored = await uow.registrations.get(REG)
    assert stored is not None
    return stored.status


async def seed_approved(
    uow_factory: UnitOfWorkFactory, extra: dict[str, str] | None = None
) -> None:
    """The registration stored as approved, with the service it registers."""
    async with uow_factory() as uow:
        stored = await uow.registrations.get(REG)
        assert stored is not None
        record = dict(stored.draft.get("record", {}))
        record.update(extra or {})
        await uow.registrations.save(
            replace(
                stored,
                status=RegistrationStatus.APPROVED,
                draft={**stored.draft, "record": record},
            )
        )
        await uow.services.save(ucr_west(SERVICE_ID, active=False))
        await uow.commit()


async def test_approving_with_the_call_back_missing_is_refused_naming_it_and_changes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await ensure_audit_head(neo4j_driver)
    await _seed(uow_factory)
    await start_review(uow_factory)
    with pytest.raises(NotAllowed, match="Call-back done"):
        await approve(uow_factory, at(14, 30)).execute(RegistrationDecisionCommand(REG, LEAD))
    assert await registration_status(uow_factory) is RegistrationStatus.IN_REVIEW


async def test_the_requester_cannot_approve_their_own_registration(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await ensure_audit_head(neo4j_driver)
    await _seed(uow_factory)
    await start_review(uow_factory)
    applicant_as_lead = Actor(
        Role.LEAD, "prac-applicant", None, "web", frozenset(), tenant_id=ACTOR_TENANT
    )
    with pytest.raises(NotAllowed, match="differ"):
        await approve(uow_factory, at(14, 30)).execute(
            RegistrationDecisionCommand(REG, applicant_as_lead)
        )
    assert await registration_status(uow_factory) is RegistrationStatus.IN_REVIEW


async def test_a_test_answer_from_another_phone_is_ignored_and_the_registered_phone_records_it(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await ensure_audit_head(neo4j_driver)
    await _seed(uow_factory)
    await start_review(uow_factory)
    await seed_approved(uow_factory)
    answer = RecordTestAnswer(uow_factory, FixedClock(at(14, 35)), phone_hasher=HASHER)
    ignored = await answer.execute(
        RecordTestAnswerCommand(REG, REPORTER, phone_hash=STRANGER_PHONE_HASH)
    )
    assert ignored.recorded is False
    async with uow_factory() as uow:
        stored = await uow.registrations.get(REG)
    assert stored is not None and "test_answered_at" not in stored.draft.get("record", {})

    recorded = await answer.execute(RecordTestAnswerCommand(REG, REPORTER, phone_hash=PHONE_HASH))
    assert recorded.recorded is True
    async with uow_factory() as uow:
        stored = await uow.registrations.get(REG)
    assert stored is not None
    assert stored.draft["record"]["test_answered_at"] == at(14, 35).isoformat()


async def test_setting_live_before_the_test_answer_is_refused_and_after_it_activates_the_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await ensure_audit_head(neo4j_driver)
    await _seed(uow_factory)
    await start_review(uow_factory)
    await seed_approved(uow_factory)
    live = SetServiceLive(uow_factory, FixedClock(at(14, 40)), SequentialIds("live"))
    with pytest.raises(NotAllowed):
        await live.execute(RegistrationDecisionCommand(REG, LEAD))
    assert await registration_status(uow_factory) is RegistrationStatus.APPROVED

    await RecordTestAnswer(uow_factory, FixedClock(at(14, 41)), phone_hasher=HASHER).execute(
        RecordTestAnswerCommand(REG, REPORTER, phone_hash=PHONE_HASH)
    )
    await live.execute(RegistrationDecisionCommand(REG, LEAD))
    assert await registration_status(uow_factory) is RegistrationStatus.LIVE
    async with uow_factory() as uow:
        service = await uow.services.get(SERVICE_ID)
        works = await uow.scheduled_work.for_about(SERVICE_ID, WorkKind.PROMPT_DUE)
        events = [m.event_type for m in await uow.outbox.pending(200)]
    assert service is not None and service.active is True
    assert [w.status for w in works] == [SCHEDULED]
    assert "RegistrationApproved" in events


async def test_send_back_needs_a_note_and_with_one_stores_needs_changes(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await ensure_audit_head(neo4j_driver)
    await _seed(uow_factory)
    await start_review(uow_factory)
    send_back = SendBackRegistration(uow_factory, FixedClock(at(14, 20)))
    with pytest.raises(ValidationFailed):
        await send_back.execute(NoteCommand(REG, LEAD, note="   "))
    assert await registration_status(uow_factory) is RegistrationStatus.IN_REVIEW
    result = await send_back.execute(
        NoteCommand(REG, LEAD, note="Please add the call-back number.")
    )
    assert result.status is RegistrationStatus.NEEDS_CHANGES
    async with uow_factory() as uow:
        stored = await uow.registrations.get(REG)
    assert stored is not None and stored.note == "Please add the call-back number."


async def test_not_approve_then_reopen_returns_the_registration_to_review(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await ensure_audit_head(neo4j_driver)
    await _seed(uow_factory)
    await start_review(uow_factory)
    refused = await NotApproveRegistration(uow_factory, FixedClock(at(14, 22))).execute(
        NoteCommand(REG, LEAD, note="Outside the pilot area.")
    )
    assert refused.status is RegistrationStatus.NOT_APPROVED
    reopened = await ReopenRegistration(uow_factory, FixedClock(at(14, 25))).execute(
        RegistrationDecisionCommand(REG, LEAD)
    )
    assert reopened.status is RegistrationStatus.IN_REVIEW


async def test_the_record_lists_the_timed_steps_in_time_order_with_who_and_when(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await ensure_audit_head(neo4j_driver)
    await _seed(uow_factory)
    await start_review(uow_factory)
    await seed_approved(
        uow_factory, {"approved_at": at(11, 0).isoformat(), "approved_by": "prac-lead"}
    )
    await RecordTestAnswer(uow_factory, FixedClock(at(15, 5)), phone_hasher=HASHER).execute(
        RecordTestAnswerCommand(REG, REPORTER, phone_hash=PHONE_HASH)
    )
    await SetServiceLive(uow_factory, FixedClock(at(15, 10)), SequentialIds("rec")).execute(
        RegistrationDecisionCommand(REG, LEAD)
    )
    steps = await GetRegistrationRecord(uow_factory).execute(RegistrationDecisionCommand(REG, LEAD))
    timed = [(s.step, s.at) for s in steps if s.at is not None]
    assert [name for name, _ in timed] == ["submitted", "approved", "test-answered", "set-live"]
    assert timed == sorted(timed, key=lambda item: item[1])
    assert [s.step for s in steps if s.at is None] == ["call-back", "scope", "criteria"]
