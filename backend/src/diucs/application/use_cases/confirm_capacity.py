"""ConfirmCapacity: a Y that says the figure on record is still right (U02).

A confirmation is a new CapacityReport of type confirmed, with the value of the latest report and
derived_from set to that report. At most MAX_CONSECUTIVE_CONFIRMS may follow one number report; a
further one is refused and nothing is written.

The unit of work takes the service's write lock first, then reads the latest report and the count,
then takes the effective time and writes (DEC-112 items 8 and 10, DEC-139; lessons L73, L99). Two confirmations for one service therefore
run one after the other. The write itself goes through record_report (U01), which also writes the
echo, status events, audit entry and idempotency record in the same unit of work.
"""

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.report_capacity import check_may_report, record_report
from diucs.domain.codes import ReportSource, ReportType, Status
from diucs.domain.errors import ConfirmLimitReached, Conflict, NotFound, NothingToConfirm
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.rules.reply_policy import MAX_CONSECUTIVE_CONFIRMS

USE_CASE = "ConfirmCapacity"


@dataclass(frozen=True, slots=True)
class ConfirmCapacityCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    source: ReportSource
    performer_role_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmCapacityResult:
    report_id: str
    status: Status
    status_changed: bool
    next_due: datetime | None
    confirmed_value: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class _StoredConfirm:
    """The result kept for a command key, with the fingerprint of the command that made it."""

    fingerprint: str
    result: ConfirmCapacityResult


def _fingerprint(command: ConfirmCapacityCommand) -> str:
    body = repr(
        (
            USE_CASE,
            command.service_id,
            command.source.value,
            command.performer_role_id,
            command.actor.role.value,
            command.actor.practitioner_id,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _replay(stored: object, fingerprint: str) -> ConfirmCapacityResult:
    """A stored result for this key replays only for the same command by the same actor. Any other
    stored value, including a key that ReportCapacity stored, is a Conflict (DEC-112 item 6)."""
    if not isinstance(stored, _StoredConfirm) or stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different command")
    return replace(stored.result, replayed=True)


class ConfirmCapacity:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency

    async def execute(self, command: ConfirmCapacityCommand) -> ConfirmCapacityResult:
        fingerprint = _fingerprint(command)
        # An early read outside the unit of work. The authoritative check is inside it.
        early = await self._idempotency.get(command.idempotency_key)
        if early is not None:
            return _replay(early, fingerprint)

        async with self._uow_factory() as uow:
            # The service lock comes before every read that decides the count, and before the
            # effective time is taken (DEC-139): a confirmation that waits behind a report is timed
            # after it.
            await uow.capacity.lock_service(command.service_id)
            now = self._clock.now()
            stored = await uow.idempotency.get(command.idempotency_key)
            if stored is not None:
                return _replay(stored, fingerprint)

            profile = await uow.services.get(command.service_id)
            if profile is None or not profile.active:
                raise NotFound("no active service with this id")
            check_may_report(command.actor, command.source, profile.id)

            latest = await uow.capacity.latest(profile.id)
            if latest is None:
                raise NothingToConfirm("this service has no report to confirm")
            trailing = await uow.capacity.trailing_confirmations(profile.id)
            if trailing >= MAX_CONSECUTIVE_CONFIRMS:
                raise ConfirmLimitReached("confirmed twice in a row: give the figure again")

            report = CapacityReport(
                id=self._ids.new_id(),
                service_id=profile.id,
                value=latest.value,
                measure=profile.measure,
                effective_at=now,
                source=command.source,
                report_type=ReportType.CONFIRMED,
                performer_role_id=command.performer_role_id,
                derived_from=latest.id,
            )
            send_echo = command.performer_role_id if command.source is ReportSource.TEXT else None
            recorded = await record_report(
                uow,
                profile=profile,
                report=report,
                actor=command.actor,
                now=now,
                ids=self._ids,
                send_echo=send_echo,
                replaced_value=None,
                use_case=USE_CASE,
                audit_snapshot={
                    "value": report.value,
                    "derived_from": latest.id,
                    "consecutive": trailing + 1,
                },
            )
            result = ConfirmCapacityResult(
                report_id=recorded.report_id,
                status=recorded.status,
                status_changed=recorded.status_changed,
                next_due=recorded.next_due,
                confirmed_value=report.value,
            )
            await uow.idempotency.put(command.idempotency_key, _StoredConfirm(fingerprint, result))
            await uow.commit()
        return result
