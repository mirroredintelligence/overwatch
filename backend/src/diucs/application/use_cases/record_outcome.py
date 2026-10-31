"""RecordOutcome: the advisor records how a case ended, and the case closes (U14).

Closing clears the postcode and the needs from the stored case (Case.close, D18). The case
repository removes the postcode property and the need relationships (DEC-066). The audit entry is
written in the same unit of work and keeps what audit needs: the need categories, the age band, the
urgency, the scores, the destination, the outcome and the times. Needs are captured before they are
cleared. The postcode is never in the snapshot (DEC-067).

The read-only SystmOne summary (build_summary) is built only while the case is open, from the values
the advisor has entered. The stored case holds the postcode district only, so the summary's Postcode
row is the district (DEC-294).

Decisions: DEC-294 (destination rule, summary wording, the Postcode row) and DEC-295 (close, audit).
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import current_scope_or_none
from diucs.application.use_cases.filter_options import need_phrase
from diucs.application.use_cases.open_case import check_role, replay_key, tenant_scope
from diucs.domain.codes import BestFitNotUsedReason, Outcome, display
from diucs.domain.errors import Conflict, NotFound, StaleVersion, ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.scores import (
    AmbulanceCategory,
    ClinicalFrailty,
    ManchesterTriage,
    News2,
    PathwaysDx,
    Score,
    score_record,
)

RECORD_OUTCOME: Final = "RecordOutcome"
CLOSE_ACTION: Final = "U"
DESTINATION_OUTCOMES: Final = frozenset({Outcome.ACCEPTED_AND_BOOKED, Outcome.REDIRECTED})
SUMMARY_ROWS: Final = (
    "Referrer",
    "Age band",
    "Postcode",
    "Needs",
    "Urgency",
    "Scores",
    "Destination",
    "Booked",
    "Data age",
)


@dataclass(frozen=True, slots=True)
class RecordOutcomeCommand:
    idempotency_key: str
    actor: Actor
    case_id: str
    outcome: Outcome
    destination_service_id: str | None = None
    best_fit_not_used: BestFitNotUsedReason | None = None
    expected_version: int | None = None
    """The version of the case the caller read, when it says (H-192, DEC-1172): a case at another
    version raises StaleVersion. A close that names none closes whatever is stored."""


@dataclass(frozen=True, slots=True)
class RecordOutcomeResult:
    case_id: str
    reference: str
    closed_at: datetime


@dataclass(frozen=True, slots=True)
class _StoredOutcome:
    """What the idempotency store keeps for a close: the command's fingerprint and its result."""

    fingerprint: str
    result: RecordOutcomeResult


def check_destination(outcome: Outcome, destination_service_id: str | None) -> None:
    """An accepted-and-booked or redirected outcome names the service it went to. Every other
    outcome names none. Checked before the case is read, so a refusal writes nothing."""
    if outcome in DESTINATION_OUTCOMES:
        if destination_service_id is None or not destination_service_id.strip():
            raise ValidationFailed(
                "destination_service_id", "this outcome needs the destination service"
            )
        return
    if destination_service_id is not None:
        raise ValidationFailed(
            "destination_service_id", "this outcome takes no destination service"
        )


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def needs_text(case: Case) -> str:
    if not case.needs:
        return ""
    return _sentence(", ".join(need_phrase(need) for need in case.needs))


def score_text(score: Score) -> str:
    match score:
        case News2():
            return f"NEWS2 {score.value}"
        case ClinicalFrailty():
            return f"Frailty scale {score.value}"
        case AmbulanceCategory():
            return f"Ambulance category {score.value}"
        case ManchesterTriage():
            return f"Manchester {score.level.replace('-', ' ')}"
        case PathwaysDx():
            return f"Pathways Dx {score.code}"
    raise ValidationFailed("scores", "not a known score")


def build_summary(
    case: Case,
    *,
    destination_name: str | None,
    booking_line: str | None,
    data_age_line: str | None,
) -> list[tuple[str, str]]:
    """The SystmOne summary rows, in the order of SUMMARY_ROWS. A row with an empty value is left
    out. Built only while the case is open."""
    if case.closed_at is not None:
        raise Conflict("the summary is built only while the case is open")
    values: dict[str, str | None] = {
        "Referrer": None if case.referrer_type is None else display(case.referrer_type),
        "Age band": None if case.age_band is None else display(case.age_band),
        "Postcode": case.postcode,
        "Needs": needs_text(case),
        "Urgency": None if case.urgency is None else display(case.urgency),
        "Scores": " · ".join(score_text(score) for score in case.scores),
        "Destination": destination_name,
        "Booked": booking_line,
        "Data age": data_age_line,
    }
    return [
        (label, value)
        for label in SUMMARY_ROWS
        if (value := values[label]) is not None and value.strip()
    ]


def score_snapshot(score: Score) -> dict[str, Any]:
    return score_record(score)


def close_snapshot(
    case: Case,
    outcome: Outcome,
    destination_service_id: str | None,
    best_fit_not_used: BestFitNotUsedReason | None,
    closed_at: datetime,
) -> dict[str, Any]:
    """The audit snapshot of a close. Taken from the case before it is cleared, and never holding
    the postcode."""
    return {
        "reference": case.reference,
        "age_band": None if case.age_band is None else case.age_band.value,
        "needs": [need.value for need in case.needs],
        "urgency": None if case.urgency is None else case.urgency.value,
        "scores": [score_snapshot(score) for score in case.scores],
        "destination_service_id": destination_service_id,
        "outcome": outcome.value,
        "best_fit_not_used": None if best_fit_not_used is None else best_fit_not_used.value,
        "opened_at": case.opened_at,
        "closed_at": closed_at,
    }


def _fingerprint(command: RecordOutcomeCommand) -> str:
    body = repr(
        (
            command.case_id,
            command.outcome.value,
            command.destination_service_id,
            None if command.best_fit_not_used is None else command.best_fit_not_used.value,
            command.actor.role.value,
            command.actor.practitioner_id,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _same_command(stored: str, fingerprint: str) -> None:
    if stored != fingerprint:
        raise Conflict("this command key was used for a different outcome")


class RecordOutcome:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        idempotency: IdempotencyStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._idempotency = idempotency

    async def execute(self, command: RecordOutcomeCommand) -> RecordOutcomeResult:
        check_role(command.actor)
        scope = tenant_scope(current_scope_or_none())
        fingerprint = _fingerprint(command)
        early = await self._idempotency.get(
            replay_key(RECORD_OUTCOME, scope, command.idempotency_key)
        )
        if isinstance(early, _StoredOutcome):
            _same_command(early.fingerprint, fingerprint)
            return early.result
        check_destination(command.outcome, command.destination_service_id)

        async with self._uow_factory() as uow:
            key = replay_key(RECORD_OUTCOME, tenant_scope(uow.unit_scope), command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _StoredOutcome):
                _same_command(stored.fingerprint, fingerprint)
                return stored.result

            found = await uow.cases.get_versioned(command.case_id)
            if found is None:
                raise NotFound("no case with this id")
            case, version = found
            if case.closed_at is not None:
                raise Conflict("the case is already closed")
            if command.expected_version is not None and command.expected_version != version:
                raise StaleVersion
            destination = command.destination_service_id
            if destination is not None:
                # A service of another tenant is not found, as an unknown one is (DEC-131).
                profile = await uow.services.get(destination)
                if profile is None or not profile.active:
                    raise NotFound("no active service with this id")

            now = self._clock.now()
            snapshot = close_snapshot(
                case, command.outcome, destination, command.best_fit_not_used, now
            )
            closed = case.close(
                command.outcome,
                now,
                destination_service_id=destination,
                best_fit_not_used=command.best_fit_not_used,
            )
            await uow.cases.save(closed, expected_version=command.expected_version)
            entities = (case.id,) if destination is None else (case.id, destination)
            await uow.audit.append(
                AuditEntry(
                    action=CLOSE_ACTION,
                    use_case=RECORD_OUTCOME,
                    actor=command.actor,
                    entity_ids=entities,
                    snapshot=snapshot,
                    at=now,
                )
            )
            result = RecordOutcomeResult(case_id=case.id, reference=case.reference, closed_at=now)
            await uow.idempotency.put(key, _StoredOutcome(fingerprint, result))
            await uow.commit()
        return result
